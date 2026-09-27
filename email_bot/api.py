# email_bot/api.py
from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
import os
import logging
from email_bot import storage, expiry, email_fetcher, extractors
from email_bot.permissions import get_user_permissions
from email_bot.utils import log_user_access

# Runtime context from main app
_runtime = {}

def init_api(runtime_ctx):
    global _runtime
    _runtime = runtime_ctx

api_router = APIRouter(prefix='/api')

async def _get_api_key(request: Request):
    """Extract API key from X-Api-Key header or Authorization bearer."""
    key = request.headers.get('X-Api-Key')
    if not key:
        auth = request.headers.get('Authorization')
        if auth and auth.startswith('Bearer '):
            key = auth.split(' ', 1)[1]
    # Also check JSON body for 'api_key' (legacy)
    if not key:
        try:
            data = await request.json()
        except Exception:
            data = {}
        key = (data or {}).get('api_key') or (data or {}).get('token')
    return key

async def require_auth(request: Request):
    key = await _get_api_key(request)
    if not key:
        return JSONResponse({'error': 'Missing API key'}, status_code=401)
    auth_info = storage.validate_any_token(key)
    if auth_info is None:
        return JSONResponse({'error': 'Invalid API key'}, status_code=401)
    return auth_info

def get_user_permissions_for_auth(auth_info):
    if auth_info['type'] == 'telegram':
        return get_user_permissions(auth_info['id'])
    else:
        return storage.get_web_user_permissions(auth_info['id'])

def can_user_access_email_for_auth(auth_info, email):
    if auth_info['type'] == 'telegram':
        can_access = _runtime.get('can_user_access_email')
        if can_access:
            return can_access(auth_info['id'], email)
        return False
    else:
        web_id = auth_info['id']
        email_map = storage.WEB_USER_EMAIL_ASSIGNMENTS.get(web_id, {})
        normalized_email = str(email).strip().lower()
        expiry_date = email_map.get(normalized_email)
        return bool(expiry_date) and not expiry.is_expiry_date_expired(expiry_date)

@api_router.get('/')
async def index():
    base_url = os.environ.get('PUBLIC_API_URL', '').rstrip('/')
    return {
        "status": "ok",
        "message": "Email Bot API is running",
        "endpoints": {
            "/api/health": "GET - Health check",
            "/api/emails": "GET - List user's assigned emails",
            "/api/permissions": "GET - List user's permissions",
            "/api/fetch": "POST - Fetch email content (send JSON with 'email' or 'emails' and 'choice')"
        },
        "auth": "Use X-Api-Key: <your-key> header or Authorization: Bearer <token>",
        "base_url": base_url or None
    }

@api_router.get('/health')
async def health():
    return {'status': 'ok'}

@api_router.get('/emails')
async def get_emails(request: Request, auth_info=Depends(require_auth)):
    if isinstance(auth_info, JSONResponse):
        return auth_info
    if auth_info['type'] == 'telegram':
        emails = storage.get_user_assigned_emails_with_expired(auth_info['id'])
        result = []
        for email in emails:
            expiry_date = storage.get_user_email_expiry(auth_info['id'], email)
            active = not expiry.is_expiry_date_expired(expiry_date)
            result.append({'email': email, 'expiry': expiry_date, 'active': active})
    else:
        web_id = auth_info['id']
        email_map = storage.WEB_USER_EMAIL_ASSIGNMENTS.get(web_id, {})
        result = []
        for email, expiry_date in email_map.items():
            active = not expiry.is_expiry_date_expired(expiry_date)
            result.append({'email': email, 'expiry': expiry_date, 'active': active})
    return {'user_id': auth_info['id'], 'emails': result}

@api_router.get('/permissions')
async def get_permissions(request: Request, auth_info=Depends(require_auth)):
    if isinstance(auth_info, JSONResponse):
        return auth_info
    perms = get_user_permissions_for_auth(auth_info)
    return {'user_id': auth_info['id'], 'permissions': perms}

class APIUser:
    def __init__(self, user_id, user_type='telegram'):
        self.id = user_id
        if user_type == 'web':
            self.identity = storage.get_web_user_identity(user_id) or {
                'id': user_id, 'type': 'web', 'username': None,
                'full_name': None, 'telegram_id': None,
            }

@api_router.post('/fetch')
async def fetch_emails(request: Request, auth_info=Depends(require_auth)):
    if isinstance(auth_info, JSONResponse):
        return auth_info
    try:
        data = await request.json()
    except Exception:
        data = {}
    email_input = data.get('email') or data.get('emails')
    if not email_input:
        return JSONResponse({'error': 'Provide "email" (string) or "emails" (list)'}, status_code=400)
    if isinstance(email_input, str):
        emails = [email_input]
    elif isinstance(email_input, list):
        emails = email_input
    else:
        return JSONResponse({'error': '"email" must be a string or "emails" a list'}, status_code=400)

    emails = list(dict.fromkeys(str(email).strip().lower() for email in emails if isinstance(email, str) and str(email).strip()))
    if not emails or len(emails) > 50:
        return JSONResponse({'error': 'Provide between 1 and 50 valid emails'}, status_code=400)

    category_key = data.get('choice') or data.get('category')
    if not category_key:
        return JSONResponse({'error': 'Missing "choice" (e.g., "household", "2FA", "reset", etc.)'}, status_code=400)

    cat_map = {
        '2FA': 'Login Code',
        'login_code': 'Login Code',
        'reset': 'Reset',
        'household': 'Household',
        'verify_email': 'Verify Email',
        'verification': 'Verification Code',
        'verification_after_login': 'Verification Code After Login',
        'verification_code_after_login': 'Verification Code After Login',
        'tv_login': 'TV Login',
        'tv': 'TV Login',
    }
    category = cat_map.get(str(category_key).lower())
    if not category:
        return JSONResponse({'error': f'Invalid choice. Allowed: {list(cat_map.keys())}'}, status_code=400)

    perms = get_user_permissions_for_auth(auth_info)
    if category not in perms:
        return JSONResponse({'error': f'Not authorized for category "{category}"'}, status_code=403)

    invalid_emails = []
    for email in emails:
        if not can_user_access_email_for_auth(auth_info, email):
            invalid_emails.append(email)
    if invalid_emails:
        return JSONResponse({
            'error': 'Some emails are not assigned or expired',
            'invalid_emails': invalid_emails
        }, status_code=403)

    fetch_func = _runtime.get('fetch_emails_concurrently')
    if not fetch_func:
        return JSONResponse({'error': 'Fetch function not available'}, status_code=500)

    results = fetch_func(emails, category)
    response = {}
    log_func = _runtime.get('log_user_access')
    for email, (content, fetch_time) in results.items():
        is_found = content and not str(content).startswith("Error:") and "No new" not in content and "No relevant" not in content
        code = None
        link = None
        country = None
        if is_found:
            if category == 'Login Code':
                code = extractors.extract_login_code(content)
                if code == "No 4-digit code found.":
                    code = None
            elif category == 'Verification Code':
                code = extractors.extract_verification_code(content)
                if code == "No 6-digit verification code found.":
                    code = None
            elif category == 'Verification Code After Login':
                code = extractors.extract_verification_code_after_login('', content)
            elif category == 'Reset':
                link = extractors.extract_reset_link(content)
                if link == "No reset link found.":
                    link = None
            elif category == 'Household':
                links = extractors.extract_household_links(content)
                if links != "No household links found.":
                    link = links
            elif category == 'Verify Email':
                link = extractors.extract_verify_email_link(content)
                if link == "No verification link found.":
                    link = None
            elif category == 'TV Login':
                link = extractors.extract_tv_login_link(content)
                if link == "No TV login link found.":
                    link = None
            country = extractors.extract_account_region(content)
        response[email] = {
            'found': is_found,
            'content': content if not is_found else None,
            'code': code,
            'link': link,
            'country': country,
            'fetch_time_seconds': fetch_time
        }
        if is_found and log_func:
            try:
                api_user = APIUser(auth_info['id'], auth_info['type'])
                log_func(api_user, f"{category} [API]", email, fetch_time, content)
            except Exception as e:
                logging.error(f"Failed to log API access for {email}: {e}")

    return {'user_id': auth_info['id'], 'category': category, 'results': response}
