import os
import sqlite3
import hashlib
import secrets
import re
import json
from functools import wraps
from datetime import datetime, timedelta

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.exceptions import HTTPException as StarletteHTTPException
from werkzeug.security import generate_password_hash, check_password_hash

# Import shared modules
from email_bot import storage, expiry, permissions, email_fetcher, utils, extractors
from email_bot.config import DATA_DIR, logger, IST, DATE_FORMAT, ADMIN_ID, SQLITE_DB_PATH
from email_bot.api import api_router, init_api
from email_bot.utils import log_user_access

# Expose the Flask-style `request.endpoint` attribute for Jinja templates.
if not hasattr(StarletteRequest, 'endpoint'):
    def _request_endpoint(self):
        route = self.scope.get('route')
        return getattr(route, 'name', None)
    StarletteRequest.endpoint = property(_request_endpoint)

# ---------------------- FastAPI Setup ----------------------
class CSRFError(Exception):
    pass

async def csrf_protect(request: Request):
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and (not request.url.path.startswith('/api/') or request.url.path == '/api/search'):
        form = await request.form()
        supplied = form.get('_csrf_token') or request.headers.get('X-CSRF-Token')
        if not supplied or not secrets.compare_digest(supplied, request.session.get('_csrf_token', '')):
            raise CSRFError()
    return None

app = FastAPI(title="Netflix Access Bot", dependencies=[Depends(csrf_protect)])

app.secret_key = os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
if not os.environ.get('FLASK_SECRET_KEY'):
    logger.warning('FLASK_SECRET_KEY is not configured; sessions will reset on restart.')

templates = Jinja2Templates(directory='templates')

# ---------------------- Register API Router ----------------------
runtime_ctx = {
    'get_user_assigned_emails_with_expired': storage.get_user_assigned_emails_with_expired,
    'get_user_email_expiry': storage.get_user_email_expiry,
    'is_user_email_expired': expiry.is_user_email_expired,
    'get_user_permissions': permissions.get_user_permissions,
    'can_user_access_email': permissions.can_user_access_email,
    'fetch_emails_concurrently': email_fetcher.fetch_emails_concurrently,
    'validate_api_token': storage.validate_any_token,
    'log_user_access': log_user_access,
    'get_web_user_permissions': storage.get_web_user_permissions,
    'user_email_assignments': storage.USER_EMAIL_ASSIGNMENTS,
}
init_api(runtime_ctx)
app.include_router(api_router)

# ---------------------- Web Users DB ----------------------
WEB_DB_PATH = SQLITE_DB_PATH

def normalize_telegram_id(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None

def init_web_db():
    storage.init_sqlite_database()
    conn = sqlite3.connect(WEB_DB_PATH)
    c = conn.cursor()
    c.execute("PRAGMA table_info(web_users)")
    columns = [col[1] for col in c.fetchall()]
    if 'approved' not in columns:
        c.execute("ALTER TABLE web_users ADD COLUMN approved INTEGER DEFAULT 0")
    if 'api_token' not in columns:
        c.execute("ALTER TABLE web_users ADD COLUMN api_token TEXT")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_web_users_api_token ON web_users(api_token)")
    if 'permissions' not in columns:
        c.execute("ALTER TABLE web_users ADD COLUMN permissions TEXT")

    default_username = os.environ.get('WEB_ADMIN_USERNAME', 'admin')
    default_password = os.environ.get('WEB_ADMIN_PASSWORD')
    default_telegram_id = normalize_telegram_id(os.environ.get('WEB_ADMIN_TELEGRAM_ID'))

    c.execute('SELECT id FROM web_users WHERE role = "super_admin"')
    row = c.fetchone()
    if row and default_password:
        pwd_hash = generate_password_hash(default_password)
        c.execute('''
            UPDATE web_users
            SET username = ?, password_hash = ?, full_name = ?, telegram_id = ?, approved = 1
            WHERE role = "super_admin"
        ''', (default_username, pwd_hash, 'Super Admin', default_telegram_id))
        logger.info("Updated super admin credentials from environment.")
    elif not row:
        if not default_password:
            default_password = secrets.token_urlsafe(24)
            logger.warning(
                "WEB_ADMIN_PASSWORD is not set. A temporary administrator password was generated: %s",
                default_password,
            )
        pwd_hash = generate_password_hash(default_password)
        c.execute('''
            INSERT INTO web_users (username, password_hash, full_name, telegram_id, role, approved)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (default_username, pwd_hash, 'Super Admin', default_telegram_id, 'super_admin', 1))
        logger.info(f"Created super admin user '{default_username}' with password from environment.")
    conn.commit()
    conn.close()

init_web_db()

storage.load_approved_users()
storage.load_sub_admin_users()
storage.load_sub_admin_assignments()
storage.load_user_email_assignments()
storage.load_web_user_email_assignments()
storage.load_renewal_decisions()
storage.load_admin_expiry_permissions()

def sync_telegram_users_to_web():
    """Keep linked web accounts approved when their Telegram account is approved."""
    try:
        with sqlite3.connect(WEB_DB_PATH) as conn:
            rows = conn.execute('SELECT telegram_id, active FROM users WHERE telegram_id IS NOT NULL').fetchall()
            for telegram_id, active in rows:
                telegram_id = normalize_telegram_id(telegram_id)
                if telegram_id is not None:
                    conn.execute(
                        'UPDATE web_users SET approved = ? WHERE telegram_id = ?',
                        (1 if active else 0, telegram_id),
                    )
                    conn.execute(
                        "UPDATE unified_accounts SET approved = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id IN (SELECT account_id FROM account_identities "
                        "WHERE identity_type = 'telegram' AND identity_id = ?)",
                        (1 if active else 0, str(telegram_id)),
                    )
    except sqlite3.Error as exc:
        logger.error('Could not synchronize Telegram approvals to web users: %s', exc)

sync_telegram_users_to_web()

def get_user_display_identity(telegram_id):
    telegram_id = normalize_telegram_id(telegram_id)
    with sqlite3.connect(WEB_DB_PATH) as conn:
        row = conn.execute(
            'SELECT username, full_name FROM web_users WHERE telegram_id = ?',
            (telegram_id,)
        ).fetchone()
    approved = storage.APPROVED_USERS.get(telegram_id, {})
    bot_name = approved.get('name') if isinstance(approved, dict) else None
    return {
        'username': row[0] if row else f'user_{telegram_id}',
        'full_name': (row[1] if row and row[1] else None) or bot_name or f'User {telegram_id}',
    }

def _web_user_from_row(row):
    if not row:
        return None
    try:
        permissions_value = json.loads(row[8]) if row[8] else []
        permissions_value = permissions_value if isinstance(permissions_value, list) else []
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning('Ignoring malformed permissions JSON for web user %s', row[0])
        permissions_value = []
    return {
        'id': row[0],
        'web_id': storage.format_web_user_id(row[0]),
        'username': row[1],
        'password_hash': row[2],
        'full_name': row[3],
        'telegram_id': normalize_telegram_id(row[4]),
        'role': row[5],
        'approved': bool(row[6]),
        'api_token': row[7],
        'permissions': permissions_value
    }

def _check_user_password(user, password):
    if not user or not isinstance(password, str):
        return False
    stored = user.get('password_hash') or ''
    try:
        valid = check_password_hash(stored, password)
    except (ValueError, TypeError):
        valid = secrets.compare_digest(hashlib.sha256(password.encode()).hexdigest(), stored)
    if valid and not stored.startswith(('scrypt:', 'pbkdf2:')):
        with sqlite3.connect(WEB_DB_PATH) as conn:
            conn.execute('UPDATE web_users SET password_hash = ? WHERE id = ?',
                         (generate_password_hash(password), user['id']))
    return valid

def get_web_user(username):
    username = username.strip() if isinstance(username, str) else ''
    conn = sqlite3.connect(WEB_DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash, full_name, telegram_id, role, approved, api_token, permissions FROM web_users WHERE lower(username) = lower(?)', (username,))
    row = c.fetchone()
    conn.close()
    return _web_user_from_row(row)

def get_web_user_by_id(user_id):
    conn = sqlite3.connect(WEB_DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, password_hash, full_name, telegram_id, role, approved, api_token, permissions FROM web_users WHERE id = ?', (user_id,))
    row = c.fetchone()
    conn.close()
    return _web_user_from_row(row)

WEB_PERMISSION_KEYS = ['Household', 'Reset', 'Login Code', 'Verification Code', 'Verification Code After Login', 'Verify Email', 'TV Login', 'API Access']

def get_current_telegram_id(request: Request):
    user = get_web_user_by_id(request.session.get('user_id')) if 'user_id' in request.session else None
    return normalize_telegram_id(user.get('telegram_id')) if user else None

def get_current_admin_permissions(request: Request):
    user = get_web_user_by_id(request.session.get('user_id')) if 'user_id' in request.session else None
    if not user:
        return []
    if user['role'] == 'super_admin':
        return WEB_PERMISSION_KEYS[:]
    return [p for p in user.get('permissions', []) if p in WEB_PERMISSION_KEYS]


def _web_user_approved_by(web_id, approver_id):
    """Return whether the web account's current approval was made by approver_id."""
    try:
        with sqlite3.connect(WEB_DB_PATH) as conn:
            row = conn.execute(
                """SELECT l.actor_type, l.actor_id
                   FROM account_audit_log l
                   JOIN account_identities i ON i.account_id = l.account_id
                   WHERE i.identity_type = 'web' AND i.identity_id = ?
                     AND l.action = 'approve_account'
                   ORDER BY l.id DESC LIMIT 1""",
                (str(web_id),),
            ).fetchone()
        return bool(row and row[0] == 'web' and str(row[1]) == str(approver_id))
    except sqlite3.Error:
        return False


def _manageable_scope(request: Request):
    """Return (Telegram IDs, web IDs) visible/manageable by the current admin."""
    current_user = get_web_user_by_id(request.session.get('user_id')) if 'user_id' in request.session else None
    if not current_user:
        return set(), set()
    if current_user['role'] == 'super_admin':
        return set(storage.list_telegram_user_ids()) | set(storage.APPROVED_USERS.keys()), set(
            storage.WEB_USER_EMAIL_ASSIGNMENTS.keys()
        ) | {u['id'] for u in _get_dashboard_web_users()}

    tg_id = get_current_telegram_id(request)
    telegram_ids = set(permissions.get_manageable_users(tg_id, include_self=True) if tg_id else [])
    web_ids = {current_user['id']}
    with sqlite3.connect(WEB_DB_PATH) as conn:
        rows = conn.execute('SELECT id, telegram_id, approved FROM web_users').fetchall()
    for web_id, linked_tg, approved in rows:
        if not approved:
            continue
        if linked_tg is not None and normalize_telegram_id(linked_tg) in telegram_ids:
            web_ids.add(web_id)
        elif _web_user_approved_by(web_id, current_user['id']):
            web_ids.add(web_id)
    return telegram_ids, web_ids


def create_web_user(username, password, full_name, role='user', telegram_id=None):
    pwd_hash = generate_password_hash(password)
    telegram_id = normalize_telegram_id(telegram_id)
    conn = sqlite3.connect(WEB_DB_PATH)
    c = conn.cursor()
    try:
        c.execute('INSERT INTO web_users (username, password_hash, full_name, telegram_id, role, approved) VALUES (?, ?, ?, ?, ?, ?)',
                  (username, pwd_hash, full_name, telegram_id, role, 0))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def is_strong_password(password):
    if not isinstance(password, str):
        return False
    if len(password) < 8:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{};:"\\|,.<>/?]', password):
        return False
    return True

# ---------------------- Session / Flash / CSRF helpers ----------------------
def _flash(request: Request, message, category='info'):
    request.session.setdefault('_flashes', []).append((category, message))

def _pop_flashes(request: Request, with_categories=False):
    flashes = request.session.pop('_flashes', [])
    if with_categories:
        return flashes
    return [message for _category, message in flashes]

def _get_csrf_token(request: Request):
    token = request.session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        request.session['_csrf_token'] = token
    return token

def _make_url_for(request: Request):
    from urllib.parse import urlencode

    def url_for(name, **kwargs):
        if name == 'static':
            if 'filename' in kwargs:
                kwargs['path'] = kwargs.pop('filename')
            url = request.url_for(name, **kwargs)
            return url.path + (f'?{url.query}' if url.query else '')

        path_params = {}
        query_params = {}
        matched = False
        router = request.scope.get('router')
        if router is not None:
            for route in getattr(router, 'routes', []):
                if getattr(route, 'name', None) == name:
                    convertors = getattr(route, 'param_convertors', {}) or {}
                    for key, value in kwargs.items():
                        if key in convertors:
                            path_params[key] = value
                        else:
                            query_params[key] = value
                    matched = True
                    break
        if not matched:
            path_params = kwargs
        url_obj = request.url_for(name, **path_params)
        url = url_obj.path + (f'?{url_obj.query}' if url_obj.query else '')
        if query_params:
            url += ('&' if '?' in url else '?') + urlencode(query_params)
        return url

    return url_for

def _redirect(request: Request, endpoint, **params):
    return RedirectResponse(_make_url_for(request)(endpoint, **params), status_code=302)

# ---------------------- Template Context Processor ----------------------
def _context_processor(request: Request):
    user = get_web_user_by_id(request.session.get('user_id')) if 'user_id' in request.session else None
    api_base_url = os.environ.get('PUBLIC_API_URL', str(request.base_url).rstrip('/'))
    is_admin = bool(user and user['role'] in ('admin', 'super_admin'))
    is_super = bool(user and user['role'] == 'super_admin')
    return {
        'app_name': 'Netflix Access Bot',
        'current_user': user,
        'is_admin_user': is_admin,
        'is_super_admin_user': is_super,
        'today': datetime.now(IST).strftime(DATE_FORMAT),
        'api_base_url': api_base_url,
        'csrf_token': _get_csrf_token(request),
        'url_for': _make_url_for(request),
        'get_flashed_messages': lambda with_categories=False: _pop_flashes(request, with_categories),
    }

templates.context_processors = [_context_processor]

# ---------------------- Auth Dependencies ----------------------
class AuthRedirect(Exception):
    """Raised by auth dependencies to redirect the browser after flashing."""
    def __init__(self, endpoint, message=None, category='warning', clear=False):
        self.endpoint = endpoint
        self.message = message
        self.category = category
        self.clear = clear

async def login_required(request: Request):
    if 'user_id' not in request.session:
        if request.url.path.startswith('/api/'):
            raise HTTPException(status_code=401, detail='Please log in again.')
        raise AuthRedirect('login', 'Please log in first.', 'warning')
    return None

async def admin_required(request: Request):
    if 'user_id' not in request.session:
        raise AuthRedirect('login', 'Please log in first.', 'warning')
    user = get_web_user_by_id(request.session['user_id'])
    if not user or not user['approved'] or user['role'] not in ('admin', 'super_admin'):
        request.session.clear()
        raise AuthRedirect('search_page', 'Admin access required.', 'danger')
    return None

# ---------------------- Web Routes ----------------------
@app.get('/api-guide', dependencies=[Depends(login_required)])
async def api_guide(request: Request):
    return templates.TemplateResponse(request, 'api_guide.html', {})

@app.get('/')
async def splash(request: Request):
    return _redirect(request, 'search_page')

@app.get('/home')
async def home(request: Request):
    return templates.TemplateResponse(request, 'home.html', {})

@app.get('/login')
@app.post('/login')
async def login(request: Request):
    if request.method == 'POST':
        form = await request.form()
        username = form.get('username')
        password = form.get('password')
        remember = form.get('remember') == 'on'
        user = get_web_user(username)
        valid_password = False
        if user and isinstance(password, str):
            valid_password = _check_user_password(user, password)
        if user and valid_password:
            if user['role'] not in ('admin', 'super_admin'):
                _flash(request, 'Only admins can sign in.', 'danger')
                logger.warning(f"Non-admin login attempt for username '{username}'")
                return templates.TemplateResponse(request, 'login.html', {})
            if user['role'] == 'super_admin':
                user['approved'] = True
            if not user['approved']:
                _flash(request, f"Your account is pending admin approval. Web ID: {user['web_id']}. Give this ID or your username to a super-admin for approval.", 'warning')
                return templates.TemplateResponse(request, 'login.html', {})
            request.session.clear()
            request.session['user_id'] = user['id']
            request.session['telegram_id'] = user.get('telegram_id')
            if remember:
                request.session['_permanent'] = True
            _flash(request, 'Logged in successfully.', 'success')
            logger.info(f"Admin '{username}' logged in successfully.")
            return _redirect(request, 'dashboard')
        _flash(request, 'Invalid credentials.', 'danger')
        logger.warning(f"Failed login attempt for username '{username}'")
    return templates.TemplateResponse(request, 'login.html', {})

@app.get('/profile', dependencies=[Depends(login_required)])
@app.post('/profile', dependencies=[Depends(login_required)])
async def profile(request: Request):
    user = get_web_user_by_id(request.session['user_id'])
    if request.method == 'POST':
        form = await request.form()
        if form.get('action') == 'link_telegram':
            telegram_id = normalize_telegram_id(form.get('telegram_id'))
            link_password = form.get('link_password', '')
            if not telegram_id:
                _flash(request, 'Enter a valid numeric Telegram ID.', 'danger')
                return templates.TemplateResponse(request, 'profile.html', {'user': user})
            if not _check_user_password(user, link_password):
                _flash(request, 'Password is incorrect.', 'danger')
                return templates.TemplateResponse(request, 'profile.html', {'user': user})
            if telegram_id not in storage.APPROVED_USERS:
                _flash(request, 'That Telegram user is not approved yet.', 'danger')
                return templates.TemplateResponse(request, 'profile.html', {'user': user})
            if telegram_id != ADMIN_ID and not storage.USER_EMAIL_ASSIGNMENTS.get(telegram_id):
                _flash(request, 'That Telegram user has no email assignments.', 'danger')
                return templates.TemplateResponse(request, 'profile.html', {'user': user})
            conn = sqlite3.connect(WEB_DB_PATH)
            c = conn.cursor()
            c.execute('SELECT id FROM web_users WHERE telegram_id = ? AND id != ?', (telegram_id, user['id']))
            if c.fetchone():
                conn.close()
                _flash(request, 'That Telegram ID is already linked to another web account.', 'danger')
                return templates.TemplateResponse(request, 'profile.html', {'user': user})
            c.execute('UPDATE web_users SET telegram_id = ? WHERE id = ?', (telegram_id, user['id']))
            conn.commit()
            conn.close()
            _flash(request, 'Telegram account linked successfully.', 'success')
            return _redirect(request, 'profile')
        # Change password
        current = form.get('current_password')
        new_pwd = form.get('new_password')
        confirm = form.get('confirm_password')
        if not _check_user_password(user, current):
            _flash(request, 'Current password is incorrect.', 'danger')
            return templates.TemplateResponse(request, 'profile.html', {'user': user})
        if new_pwd != confirm:
            _flash(request, 'New passwords do not match.', 'danger')
            return templates.TemplateResponse(request, 'profile.html', {'user': user})
        if not is_strong_password(new_pwd):
            _flash(request, 'Password must be at least 8 characters, include uppercase, lowercase, digit, and special character.', 'danger')
            return templates.TemplateResponse(request, 'profile.html', {'user': user})
        new_hash = generate_password_hash(new_pwd)
        conn = sqlite3.connect(WEB_DB_PATH)
        c = conn.cursor()
        c.execute('UPDATE web_users SET password_hash = ? WHERE id = ?', (new_hash, user['id']))
        conn.commit()
        conn.close()
        _flash(request, 'Password updated successfully.', 'success')
        return _redirect(request, 'profile')
    api_keys = storage.list_api_keys(user['id'], 'web')
    return templates.TemplateResponse(request, 'profile.html', {'user': user, 'api_keys': api_keys})

@app.post('/profile/create-api-key', dependencies=[Depends(login_required)])
async def create_api_key(request: Request):
    user = get_web_user_by_id(request.session['user_id'])
    form = await request.form()
    name = (form.get('key_name') or '').strip()
    if not name:
        _flash(request, 'Please enter a name for the API key.', 'danger')
        return _redirect(request, 'profile')
    try:
        key = storage.create_api_key(user['id'], 'web', name)
    except Exception as e:
        logger.exception('Failed to create API key')
        key = None
    if key:
        _flash(request, f'API key created: {key}', 'success')
    else:
        _flash(request, 'Failed to create API key.', 'danger')
    return _redirect(request, 'profile')

@app.post('/profile/delete-api-key/{key_id}', dependencies=[Depends(login_required)])
async def delete_api_key(request: Request, key_id: int):
    user = get_web_user_by_id(request.session['user_id'])
    try:
        ok = storage.revoke_api_key(key_id, user['id'], 'web')
    except Exception:
        logger.exception('Failed to revoke API key')
        ok = False
    if ok:
        _flash(request, 'API key revoked.', 'success')
    else:
        _flash(request, 'API key not found or not yours.', 'danger')
    return _redirect(request, 'profile')

@app.get('/logout')
async def logout(request: Request):
    request.session.clear()
    _flash(request, 'Logged out.', 'info')
    return _redirect(request, 'login')

# ---------------------- Dashboard (Admin only) ----------------------
def _get_dashboard_web_users():
    """Return all web users as a list of dicts (id, username, full_name, role, approved, telegram_id)."""
    conn = sqlite3.connect(WEB_DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, username, full_name, role, approved, telegram_id FROM web_users')
    rows = c.fetchall()
    conn.close()
    return [
        {
            'id': r[0], 'username': r[1], 'full_name': r[2],
            'web_id': storage.format_web_user_id(r[0]),
            'role': r[3], 'approved': bool(r[4]), 'telegram_id': r[5],
        }
        for r in rows
    ]


@app.get('/dashboard', dependencies=[Depends(admin_required)])
async def dashboard(request: Request):
    stats = _build_dashboard_stats(request)
    return templates.TemplateResponse(request, 'dashboard.html', {'stats': stats})


def _build_dashboard_stats(request: Request):
    current_user = get_web_user_by_id(request.session['user_id'])
    web_users = _get_dashboard_web_users()
    total_users = sum(1 for w in web_users if w['approved'] and w['role'] != 'super_admin')
    pending_users = sum(1 for w in web_users if not w['approved']) if current_user['role'] == 'super_admin' else 0

    with sqlite3.connect(WEB_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''
            SELECT user_id, category, email, fetch_time, message, created_at,
                   user_type, username, full_name
            FROM access_logs ORDER BY id DESC LIMIT 20
        ''').fetchall()
        searches_today = conn.execute(
            "SELECT COUNT(*) FROM access_logs WHERE created_at >= ?",
            (datetime.utcnow().date().isoformat(),),
        ).fetchone()[0]
        total_searches = conn.execute(
            "SELECT COUNT(*) FROM access_logs"
        ).fetchone()[0]

    recent_searches = []
    recent_events = []
    for row in rows:
        item = dict(row)
        item['status'] = 'success' if not str(item.get('message') or '').startswith('Error:') else 'error'
        recent_searches.append(item)
        display_name = item.get('full_name') or item.get('username') or f"ID {item.get('user_id')}"
        recent_events.append({
            'created_at': item.get('created_at') or '',
            'message': f"{display_name} searched {item.get('email')} ({item.get('category')})",
        })

    stats = {
        'total_users': total_users,
        'pending_users': pending_users,
        'searches_today': searches_today,
        'total_searches': total_searches,
        'imap_ready': bool((storage.get_app_setting('imap_email') and storage.get_app_setting('imap_pass')) or (os.getenv('EMAIL_USER') and os.getenv('EMAIL_PASS'))),
        'recent_events': recent_events,
        'recent_searches': recent_searches,
    }
    return stats


@app.get('/api/dashboard/stats', dependencies=[Depends(admin_required)])
async def dashboard_stats(request: Request):
    return JSONResponse(_build_dashboard_stats(request))

# ---------------------- Users Management ----------------------
@app.get('/users', dependencies=[Depends(admin_required)])
async def users_page(request: Request):
    query = request.query_params.get('q', '')
    status_filter = request.query_params.get('status', 'all')
    current_user = get_web_user_by_id(request.session['user_id'])
    grantable_permissions = get_current_admin_permissions(request)
    manageable_telegram_users = set(storage.list_telegram_user_ids()) if current_user['role'] == 'super_admin' else set(
        permissions.get_manageable_users(get_current_telegram_id(request), include_self=True) if get_current_telegram_id(request) else []
    )
    user_list = []
    for account in storage.list_unified_accounts(include_pending=True):
        tg_id = account['telegram_id']
        web_id = account['web_id']
        is_current_web_account = web_id == current_user['id']
        if current_user['role'] != 'super_admin' and not is_current_web_account:
            if (not tg_id or tg_id not in manageable_telegram_users) and web_id not in _manageable_scope(request)[1]:
                continue
        if tg_id == ADMIN_ID and current_user['role'] != 'super_admin' and not is_current_web_account:
            continue
        username = account['username'] or (f'user_{tg_id}' if tg_id else f'web_{web_id}')
        name = account['full_name'] or username
        role = 'super_admin' if tg_id == ADMIN_ID else 'user'
        if web_id:
            web = storage.get_web_user_by_id(web_id)
            role = (web or {}).get('role', role)
        status = 'approved' if account['approved'] else 'pending'
        searchable = f"{account['id']} {tg_id or ''} {web_id or ''} {username} {name}".lower()
        if query.lower() not in searchable or (status_filter != 'all' and status_filter != status):
            continue
        user_list.append({'id': str(tg_id) if tg_id else f'web_{web_id}', 'full_name': name,
                          'username': username, 'web_id': storage.format_web_user_id(web_id) if web_id else None,
                          'telegram_id': tg_id, 'role': role, 'status': status,
                          'created_at': 'N/A', 'unified_id': account['id']})

    return templates.TemplateResponse(request, 'users.html', {'users': user_list, 'query': query, 'status': status_filter, 'grantable_permissions': grantable_permissions})

@app.post('/users/approve-by-username', dependencies=[Depends(admin_required)])
async def approve_user_by_username(request: Request):
    form = await request.form()
    lookup = (form.get('username') or form.get('web_id') or '').strip()
    if not lookup:
        _flash(request, 'Enter a username or Web ID to approve.', 'danger')
        return _redirect(request, 'users_page')

    current_user = get_web_user_by_id(request.session['user_id'])
    normalized_id = lookup.upper().replace('-', '')
    query = 'SELECT id, username, approved FROM web_users WHERE lower(username) = lower(?) OR (id = ? AND ? LIKE ?)'
    params = [lookup.lstrip('@'), None, normalized_id, 'WEB%']
    if normalized_id.startswith('WEB') and normalized_id[3:].isdigit():
        params[1] = int(normalized_id[3:])

    permission_keys = ['Household', 'Reset', 'Login Code', 'Verification Code', 'Verification Code After Login', 'Verify Email', 'TV Login', 'API Access']
    requested_permissions = list(dict.fromkeys(form.getlist('permissions')))
    if current_user['role'] == 'super_admin':
        granted_permissions = [p for p in requested_permissions if p in permission_keys]
    else:
        own_permissions = get_current_admin_permissions(request)
        if any(p not in own_permissions for p in requested_permissions):
            _flash(request, 'You can only provide permissions assigned to you.', 'danger')
            return _redirect(request, 'users_page')
        granted_permissions = requested_permissions

    with sqlite3.connect(WEB_DB_PATH) as conn:
        row = conn.execute(query, params).fetchone()
        if not row:
            _flash(request, 'No web account was found with that username or Web ID.', 'danger')
            return _redirect(request, 'users_page')
        if row[2]:
            _flash(request, 'That user is already approved.', 'info')
            return _redirect(request, 'users_page')
        conn.execute('UPDATE web_users SET permissions = ? WHERE id = ?', (json.dumps(granted_permissions), row[0]))

    if not storage.sync_account_approval('web', row[0], True, 'web', request.session.get('user_id')):
        _flash(request, 'The account could not be approved.', 'danger')
        return _redirect(request, 'users_page')

    _flash(request, f'User @{row[1]} ({storage.format_web_user_id(row[0])}) approved successfully.', 'success')
    return _redirect(request, 'users_page')

def _permissions_for_template(perm_dict):
    keys = ['Household', 'Reset', 'Login Code', 'Verification Code', 'Verification Code After Login', 'Verify Email', 'TV Login', 'API Access']
    return {key: {'label': key, 'enabled': key in perm_dict} for key in keys}

@app.get('/users/{user_id}', dependencies=[Depends(admin_required)])
async def user_detail(request: Request, user_id: str):
    if _is_web_user_id(user_id):
        web_id = _get_web_user_id(user_id)
        if not _is_manageable_user(request, user_id):
            _flash(request, 'You do not have permission to view this user.', 'danger')
            return _redirect(request, 'users_page')
        conn = sqlite3.connect(WEB_DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, username, full_name, role, approved, telegram_id, permissions FROM web_users WHERE id = ?', (web_id,))
        row = c.fetchone()
        conn.close()
        if not row:
            _flash(request, 'User not found.', 'danger')
            return _redirect(request, 'users_page')
        target = {
            'id': f"web_{row[0]}",
            'username': row[1],
            'full_name': row[2],
            'role': row[3],
            'status': 'approved' if row[4] else 'pending',
            'telegram_id': row[5],
            'permissions': _safe_permissions(row[6])
        }
        perms_for_template = _permissions_for_template({p: True for p in target['permissions']})
        return templates.TemplateResponse(request, 'user_detail.html', {
            'target': target,
            'perms': perms_for_template,
            'searches': []
        })
    else:
        try:
            uid = int(user_id)
        except ValueError:
            _flash(request, 'Invalid user ID.', 'danger')
            return _redirect(request, 'users_page')
        current_user = get_web_user_by_id(request.session['user_id'])
        if current_user['role'] == 'super_admin':
            manageable = storage.list_telegram_user_ids()
        else:
            tg_id = get_current_telegram_id(request)
            manageable = permissions.get_manageable_users(tg_id, include_self=True) if tg_id else []
        if uid not in manageable:
            _flash(request, 'You do not have permission to view this user.', 'danger')
            return _redirect(request, 'users_page')

        target = {'id': uid}
        telegram_user = storage.get_telegram_user(uid)
        if telegram_user:
            identity = get_user_display_identity(uid)
            target['full_name'] = identity['full_name']
            target['username'] = identity['username']
            target['role'] = 'super_admin' if uid == ADMIN_ID else ('admin' if uid in storage.SUB_ADMIN_USERS else 'user')
            target['status'] = 'active' if telegram_user['active'] else 'pending'
        else:
            _flash(request, 'User not found.', 'danger')
            return _redirect(request, 'users_page')

        perms_for_template = _permissions_for_template({p: True for p in permissions.get_user_permissions(uid)})
        return templates.TemplateResponse(request, 'user_detail.html', {
            'target': target,
            'perms': perms_for_template,
            'searches': []
        })

@app.post('/users/{user_id}/reset-password', dependencies=[Depends(admin_required)])
async def reset_web_user_password(request: Request, user_id: str):
    if not _is_web_user_id(user_id) or not _is_manageable_user(request, user_id):
        _flash(request, 'You do not have permission to reset this user password.', 'danger')
        return _redirect(request, 'users_page')

    web_id = _get_web_user_id(user_id)
    form = await request.form()
    new_password = form.get('new_password', '')
    confirm_password = form.get('confirm_password', '')
    if not is_strong_password(new_password):
        _flash(request, 'Password must be at least 8 characters and include uppercase, lowercase, a digit, and a special character.', 'danger')
        return _redirect(request, 'user_detail', user_id=user_id)
    if new_password != confirm_password:
        _flash(request, 'The new passwords do not match.', 'danger')
        return _redirect(request, 'user_detail', user_id=user_id)

    with sqlite3.connect(WEB_DB_PATH) as conn:
        updated = conn.execute(
            'UPDATE web_users SET password_hash = ? WHERE id = ?',
            (generate_password_hash(new_password), web_id),
        ).rowcount
    if not updated:
        _flash(request, 'User not found.', 'danger')
    else:
        _flash(request, 'Web user password reset successfully. The username and account data were preserved.', 'success')
    return _redirect(request, 'user_detail', user_id=user_id)

def _is_manageable_user(request: Request, user_id):
    current_user = get_web_user_by_id(request.session.get('user_id')) if 'user_id' in request.session else None
    if not current_user:
        return False
    if current_user['role'] == 'super_admin':
        if isinstance(user_id, int) or str(user_id).isdigit():
            return storage.get_telegram_user(int(user_id)) is not None
        web_id = _get_web_user_id(user_id)
        return web_id is not None and get_web_user_by_id(web_id) is not None
    telegram_ids, web_ids = _manageable_scope(request)
    web_id = _get_web_user_id(user_id)
    if web_id is not None:
        return web_id in web_ids
    try:
        return int(user_id) in telegram_ids
    except (TypeError, ValueError):
        return False

def _is_web_user_id(user_id_str):
    return _get_web_user_id(user_id_str) is not None

def _get_web_user_id(user_id_str):
    parts = str(user_id_str).split('_')
    if len(parts) == 2 and parts[0] == 'web' and parts[1].isdigit() and int(parts[1]) > 0:
        return int(parts[1])
    return None

def _safe_permissions(value):
    try:
        parsed = json.loads(value) if value else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []

@app.post('/users/{user_id}/status', dependencies=[Depends(admin_required)])
async def update_user_status(request: Request, user_id: str):
    form = await request.form()
    if _is_web_user_id(user_id):
        web_id = _get_web_user_id(user_id)
        if web_id is None or not _is_manageable_user(request, user_id):
            _flash(request, 'You do not have permission to update this user.', 'danger')
            return _redirect(request, 'users_page')
        status = form.get('status', 'pending')
        approved = 1 if status == 'approved' else 0
        if not storage.sync_account_approval('web', web_id, approved, 'web', request.session.get('user_id')):
            _flash(request, 'Web user not found.', 'danger')
            return _redirect(request, 'users_page')
        _flash(request, f'Web user status updated to {status}.', 'success')
        return _redirect(request, 'user_detail', user_id=user_id)
    else:
        try:
            uid = int(user_id)
        except ValueError:
            _flash(request, 'Invalid user ID.', 'danger')
            return _redirect(request, 'users_page')
        if not _is_manageable_user(request, uid) or uid == ADMIN_ID:
            _flash(request, 'You do not have permission to update this user.', 'danger')
            return _redirect(request, 'users_page')
        status = form.get('status', 'active')
        if status not in ('active', 'pending', 'blocked', 'rejected'):
            _flash(request, 'Invalid user status.', 'danger')
            return _redirect(request, 'user_detail', user_id=user_id)
        if not storage.sync_account_approval('telegram', uid, status == 'active', 'web', request.session.get('user_id')):
            _flash(request, 'Telegram user not found.', 'danger')
            return _redirect(request, 'users_page')
        _flash(request, f'User status updated to {status}.', 'success')
        return _redirect(request, 'user_detail', user_id=user_id)

@app.post('/users/{user_id}/role', dependencies=[Depends(admin_required)])
async def update_user_role(request: Request, user_id: str):
    if get_current_telegram_id(request) != ADMIN_ID:
        _flash(request, 'Only the super admin can update roles.', 'danger')
        return _redirect(request, 'user_detail', user_id=user_id)
    form = await request.form()
    if _is_web_user_id(user_id):
        web_id = _get_web_user_id(user_id)
        role = form.get('role', 'user')
        if role not in ('user', 'admin'):
            _flash(request, 'Only user and admin roles can be assigned here.', 'danger')
            return _redirect(request, 'user_detail', user_id=user_id)
        with sqlite3.connect(WEB_DB_PATH) as conn:
            updated = conn.execute(
                'UPDATE web_users SET role = ? WHERE id = ? AND role != "super_admin"',
                (role, web_id),
            ).rowcount
        if not updated:
            _flash(request, 'Web user not found or cannot be modified.', 'danger')
        else:
            linked_user = get_web_user_by_id(web_id)
            telegram_id = normalize_telegram_id(linked_user.get('telegram_id')) if linked_user else None
            if telegram_id is not None:
                if role == 'admin':
                    storage.SUB_ADMIN_USERS.add(telegram_id)
                else:
                    storage.SUB_ADMIN_USERS.discard(telegram_id)
                storage.save_sub_admin_users()
                permissions.update_user_commands(telegram_id)
            _flash(request, f'Web user role updated to {role}.', 'success')
        return _redirect(request, 'user_detail', user_id=user_id)
    try:
        uid = int(user_id)
    except ValueError:
        _flash(request, 'Invalid user ID.', 'danger')
        return _redirect(request, 'users_page')
    role = form.get('role', 'user')
    if role not in ('user', 'admin'):
        _flash(request, 'Invalid role.', 'danger')
        return _redirect(request, 'user_detail', user_id=user_id)
    with sqlite3.connect(WEB_DB_PATH) as conn:
        conn.execute('UPDATE web_users SET role = ? WHERE telegram_id = ?', (role, uid))
    if role == 'admin':
        storage.SUB_ADMIN_USERS.add(uid)
    else:
        storage.SUB_ADMIN_USERS.discard(uid)
    storage.save_sub_admin_users()
    _flash(request, 'User role updated.', 'success')
    return _redirect(request, 'user_detail', user_id=user_id)

@app.post('/users/{user_id}/permission', dependencies=[Depends(admin_required)])
async def update_user_permission(request: Request, user_id: str):
    form = await request.form()
    permission = form.get('permission_key', '').strip()
    allowed = {'Household', 'Reset', 'Login Code', 'Verification Code', 'Verification Code After Login', 'Verify Email', 'TV Login', 'API Access'}
    if permission not in allowed:
        return JSONResponse({'ok': False, 'error': 'Invalid permission'}, status_code=400)

    if _is_web_user_id(user_id):
        web_id = _get_web_user_id(user_id)
        if web_id is None or not _is_manageable_user(request, user_id):
            return JSONResponse({'ok': False, 'error': 'Permission denied'}, status_code=403)
        current_user = get_web_user_by_id(request.session['user_id'])
        if current_user['role'] != 'super_admin':
            if permission not in get_current_admin_permissions(request):
                return JSONResponse({'ok': False, 'error': 'You can only grant permissions assigned to you.'}, status_code=403)
        conn = sqlite3.connect(WEB_DB_PATH)
        c = conn.cursor()
        c.execute('SELECT permissions FROM web_users WHERE id = ?', (web_id,))
        row = c.fetchone()
        try:
            perms = json.loads(row[0]) if row and row[0] else []
            perms = perms if isinstance(perms, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            perms = []
        if permission in perms:
            perms.remove(permission)
            enabled = False
        else:
            perms.append(permission)
            enabled = True
        c.execute('UPDATE web_users SET permissions = ? WHERE id = ?', (json.dumps(perms), web_id))
        conn.commit()
        conn.close()
        return JSONResponse({'ok': True, 'enabled': enabled})
    else:
        try:
            uid = int(user_id)
        except ValueError:
            return JSONResponse({'ok': False, 'error': 'Invalid user ID'}, status_code=400)
        if not _is_manageable_user(request, uid):
            return JSONResponse({'ok': False, 'error': 'Permission denied'}, status_code=403)
        data = storage.APPROVED_USERS.get(uid)
        if not isinstance(data, dict):
            return JSONResponse({'ok': False, 'error': 'User not found'}, status_code=404)
        perms = data.setdefault('permissions', [])
        if permission in perms:
            perms.remove(permission)
            enabled = False
        else:
            perms.append(permission)
            enabled = True
        storage.save_approved_users()
        return JSONResponse({'ok': True, 'enabled': enabled})

# ---------------------- Search ----------------------
SEARCH_CATEGORY_KEYS = ['login_code', 'reset', 'household', 'verify_email', 'tv_login', 'verification_code', 'verification_code_after_login']
SEARCH_CATEGORY_LABELS = {
    'login_code': {'label': 'Login Code', 'icon': '🔑'},
    'reset': {'label': 'Reset Link', 'icon': '🔒'},
    'household': {'label': 'Household', 'icon': '🏠'},
    'verify_email': {'label': 'Verify Email', 'icon': '✉️'},
    'tv_login': {'label': 'TV Login', 'icon': '📺'},
    'verification_code': {'label': 'Verification Code', 'icon': '🔢'},
    'verification_code_after_login': {'label': 'Verification Code After Login', 'icon': '🔐'},
}

def get_category_locks():
    raw = storage.get_app_setting('category_locks') or '{}'
    try:
        locks = json.loads(raw)
        return locks if isinstance(locks, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

def set_category_locks(locks):
    storage.set_app_setting('category_locks', json.dumps(locks))

@app.get('/search')
async def search_page(request: Request):
    locks = get_category_locks()
    categories = {}
    for key in SEARCH_CATEGORY_KEYS:
        info = dict(SEARCH_CATEGORY_LABELS[key])
        info['locked'] = bool((locks.get(key) or {}).get('enabled'))
        categories[key] = info
    return templates.TemplateResponse(request, 'search.html', {'categories': categories})

@app.post('/api/search')
async def api_search(request: Request):
    data = await request.json()
    category_key = data.get('category')
    emails_text = (data.get('emails') or '').strip()
    if not emails_text:
        return JSONResponse({'ok': False, 'error': 'No emails provided'}, status_code=400)
    email_list = utils.parse_emails(emails_text)
    if not email_list:
        return JSONResponse({'ok': False, 'error': 'No valid emails found'}, status_code=400)

    cat_map = {
        'login_code': 'Login Code',
        'reset': 'Reset',
        'household': 'Household',
        'verify_email': 'Verify Email',
        'tv_login': 'TV Login',
        'verification_code': 'Verification Code',
        'verification_code_after_login': 'Verification Code After Login'
    }
    category = cat_map.get(category_key)
    if not category:
        return JSONResponse({'ok': False, 'error': 'Invalid category'}, status_code=400)

    lock = get_category_locks().get(category_key) or {}
    if lock.get('enabled'):
        supplied = data.get('password') or ''
        if not supplied:
            return JSONResponse({'ok': False, 'error': 'Category password required.'}, status_code=403)
        if not secrets.compare_digest(supplied, lock.get('password') or ''):
            return JSONResponse({'ok': False, 'error': 'Incorrect password for this category.'}, status_code=403)

    imap_user = storage.get_app_setting('imap_email') or os.environ.get('EMAIL_USER')
    imap_pass = storage.get_app_setting('imap_pass') or os.environ.get('EMAIL_PASS')

    logged_in_user = get_web_user_by_id(request.session.get('user_id')) if request.session.get('user_id') else None

    class SearchAccessUser:
        def __init__(self, user):
            self.id = user['id'] if user else 0
            self.identity = {
                'id': self.id,
                'type': 'web' if user else 'public',
                'username': user.get('username') if user else 'public',
                'full_name': user.get('full_name') if user else 'Public Search',
                'telegram_id': user.get('telegram_id') if user else None,
            }

    access_user = SearchAccessUser(logged_in_user)

    results = []
    for email in email_list:
        content, fetch_time = email_fetcher.fetch_email_for_account(email, category, imap_user, imap_pass)
        status = 'error' if str(content).startswith('Error:') else (
            'found' if 'No new' not in content and 'No relevant' not in content else 'not_found'
        )

        try:
            log_user_access(access_user, category, email, fetch_time, content)
        except Exception as exc:
            logger.warning('Could not write search activity for %s: %s', email, exc)

        items = []
        if status == 'found':
            if 'Login Code' in category:
                code = extractors.extract_login_code(content)
                if code != "No 4-digit code found.":
                    items.append(code)
            elif category == 'Verification Code':
                code = extractors.extract_verification_code(content)
                if code != "No 6-digit verification code found.":
                    items.append(code)
            elif category == 'Verification Code After Login':
                code = extractors.extract_verification_code_after_login('', content)
                if code:
                    items.append(code)
            elif 'Reset' in category:
                link = extractors.extract_reset_link(content)
                if link != "No reset link found.":
                    items.append(link)
            elif 'Household' in category:
                links = extractors.extract_household_links(content)
                if links != "No household links found.":
                    items = links.split('\n')
            elif 'Verify Email' in category:
                link = extractors.extract_verify_email_link(content)
                if link != "No verification link found.":
                    items.append(link)
            elif 'TV Login' in category:
                link = extractors.extract_tv_login_link(content)
                if link != "No TV login link found.":
                    items.append(link)

        results.append({
            'email': email,
            'status': status,
            'result': content,
            'fetch_time': fetch_time,
            'items': items
        })

    return JSONResponse({'ok': True, 'results': results})

# ---------------------- Admin Actions ----------------------
@app.get('/logs', dependencies=[Depends(admin_required)])
async def logs_page(request: Request):
    with sqlite3.connect(WEB_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute('''
            SELECT id, user_id, category, email, fetch_time, message, created_at,
                   user_type, username, full_name, telegram_id
            FROM access_logs ORDER BY id DESC LIMIT 500
        ''').fetchall()
    searches = []
    events = []
    for row in rows:
        item = dict(row)
        item['user_type'] = item.get('user_type') or 'telegram'
        item['username'] = item.get('username') or ''
        item['full_name'] = item.get('full_name') or ''
        item['telegram_id'] = item.get('telegram_id')
        if not item['full_name'] and item['user_type'] == 'telegram':
            identity = get_user_display_identity(item['user_id'])
            item['full_name'] = identity['full_name']
            item['username'] = identity['username']
        item['display_name'] = item['full_name'] or item['username'] or f"ID {item['user_id']}"
        item['status'] = 'success'
        searches.append(item)
        events.append({
            'created_at': item['created_at'],
            'message': f"{item['display_name']} ({item['user_type']} ID: {item['user_id']}) accessed {item['email']}",
            'event_type': item['category'],
        })
    return templates.TemplateResponse(request, 'logs.html', {'events': events, 'searches': searches})

@app.get('/settings', dependencies=[Depends(admin_required)])
@app.post('/settings', dependencies=[Depends(admin_required)])
async def settings_page(request: Request):
    if request.method == 'POST':
        form = await request.form()
        imap_email = (form.get('imap_email') or '').strip()
        imap_pass = form.get('imap_pass') or ''
        if imap_email:
            storage.set_app_setting('imap_email', imap_email)
        if imap_pass:
            storage.set_app_setting('imap_pass', imap_pass)

        enabled_keys = set(form.getlist('lock_enabled'))
        locks = {}
        for key in SEARCH_CATEGORY_KEYS:
            locks[key] = {
                'enabled': key in enabled_keys,
                'password': form.get(f'lock_password_{key}', '') or '',
            }
        set_category_locks(locks)

        _flash(request, 'Settings saved.', 'success')
        return _redirect(request, 'settings_page')

    imap_email = storage.get_app_setting('imap_email') or ''
    imap_pass = storage.get_app_setting('imap_pass') or ''
    locks = get_category_locks()
    lock_entries = {}
    for key in SEARCH_CATEGORY_KEYS:
        entry = locks.get(key) or {}
        lock_entries[key] = {'enabled': bool(entry.get('enabled')), 'password': entry.get('password') or ''}
    return templates.TemplateResponse(request, 'settings.html', {
        'imap_email': imap_email,
        'imap_pass': imap_pass,
        'category_keys': SEARCH_CATEGORY_KEYS,
        'labels': SEARCH_CATEGORY_LABELS,
        'locks': lock_entries,
    })

@app.get('/download-data', dependencies=[Depends(admin_required)])
async def download_data(request: Request):
    import io
    import zipfile

    in_memory = io.BytesIO()
    with zipfile.ZipFile(in_memory, 'w', zipfile.ZIP_DEFLATED) as zf:
        path = SQLITE_DB_PATH
        if os.path.exists(path):
            with open(path, 'rb') as fh:
                zf.writestr(os.path.basename(path), fh.read())
    in_memory.seek(0)
    return Response(
        content=in_memory.getvalue(),
        media_type='application/zip',
        headers={'Content-Disposition': 'attachment; filename="dashboard_data.zip"'}
    )

# ---------------------- API Token management routes ----------------------
@app.post('/profile/generate-api-token', dependencies=[Depends(login_required)])
async def generate_api_token(request: Request):
    user = get_web_user_by_id(request.session['user_id'])
    token = storage.generate_web_api_token(user['id'])
    if token:
        _flash(request, 'API token generated.', 'success')
    else:
        _flash(request, 'Failed to generate token.', 'danger')
    return _redirect(request, 'profile')

@app.post('/profile/regenerate-api-token', dependencies=[Depends(login_required)])
async def regenerate_api_token(request: Request):
    user = get_web_user_by_id(request.session['user_id'])
    token = storage.generate_web_api_token(user['id'])
    if token:
        _flash(request, 'API token regenerated.', 'success')
    else:
        _flash(request, 'Failed to regenerate token.', 'danger')
    return _redirect(request, 'profile')

# ---------------------- Error Handlers ----------------------
@app.exception_handler(CSRFError)
async def csrf_error_handler(request: Request, exc):
    return JSONResponse({'ok': False, 'error': 'Invalid or missing CSRF token.'}, status_code=400)

@app.exception_handler(AuthRedirect)
async def auth_redirect_handler(request: Request, exc: AuthRedirect):
    if exc.message:
        _flash(request, exc.message, exc.category)
    return RedirectResponse(request.url_for(exc.endpoint), status_code=302)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc):
    if request.url.path.startswith('/api/'):
        return JSONResponse({'ok': False, 'error': str(exc.detail)}, status_code=exc.status_code)
    if exc.status_code == 404:
        return templates.TemplateResponse(request, 'error.html', {
            'code': 404, 'title': 'Page Not Found', 'message': 'The requested page does not exist.'
        }, status_code=404)
    return templates.TemplateResponse(request, 'error.html', {
        'code': exc.status_code, 'title': 'Error', 'message': str(exc.detail)
    }, status_code=exc.status_code)

@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc):
    logger.exception('Unhandled server error')
    return templates.TemplateResponse(request, 'error.html', {
        'code': 500, 'title': 'Server Error', 'message': 'An internal error occurred.'
    }, status_code=500)

# ---------------------- Static / Session Middleware ----------------------
app.mount('/static', StaticFiles(directory='static'), name='static')

secure_cookie = os.environ.get('SESSION_COOKIE_SECURE', '').strip().lower() in {'1', 'true', 'yes', 'on'}
app.add_middleware(
    SessionMiddleware,
    secret_key=app.secret_key,
    session_cookie='session',
    max_age=30 * 24 * 60 * 60,
    same_site='lax',
    https_only=secure_cookie,
)

if __name__ == '__main__':
    import uvicorn
    storage.init_sqlite_database()
    storage.load_approved_users()
    storage.load_sub_admin_users()
    storage.load_sub_admin_assignments()
    storage.load_user_email_assignments()
    storage.load_web_user_email_assignments()
    storage.load_renewal_decisions()
    storage.load_admin_expiry_permissions()
    # Railway supplies PORT; prefer it over the legacy local FLASK_PORT value.
    port = int(os.environ.get('PORT') or os.environ.get('FLASK_PORT') or 5000)
    uvicorn.run(app, host='0.0.0.0', port=port)
