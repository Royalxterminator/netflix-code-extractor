import hashlib
import secrets
import sqlite3
import threading
import time
import string
import random
import json
from datetime import datetime
from werkzeug.security import generate_password_hash

from email_bot.config import (
    DATA_DIR, ADMIN_ID, logger, SQLITE_DB_PATH, verify_data_directory,
    APPROVED_USERS, SUB_ADMIN_USERS, SUB_ADMIN_ASSIGNMENTS,
    USER_EMAIL_ASSIGNMENTS, ADMIN_CAN_EDIT_EXPIRY, RENEWAL_DECISIONS,
)


def _sqlite_connect():
    return sqlite3.connect(SQLITE_DB_PATH, timeout=30)


def _now():
    return datetime.utcnow().isoformat(timespec="seconds")


def get_app_setting(key, default=None):
    """Return a persisted application setting, or ``default`` if unset."""
    try:
        with _sqlite_connect() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        return row[0] if row else default
    except sqlite3.Error as exc:
        logger.error("Could not read app setting %s: %s", key, exc)
        return default


def set_app_setting(key, value):
    """Persist an application setting."""
    try:
        with _sqlite_connect() as conn:
            conn.execute(
                "INSERT INTO app_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
        return True
    except sqlite3.Error as exc:
        logger.error("Could not write app setting %s: %s", key, exc)
        return False


def format_web_user_id(web_user_id):
    """Return the stable, user-facing identifier for a web account."""
    try:
        return f"WEB-{int(web_user_id):06d}"
    except (TypeError, ValueError):
        return "WEB-UNKNOWN"


def list_telegram_user_ids():
    """Return all Telegram users known to SQLite, including pending users."""
    try:
        with _sqlite_connect() as conn:
            rows = conn.execute(
                "SELECT telegram_id FROM users WHERE telegram_id IS NOT NULL"
            ).fetchall()
        return [int(row[0]) for row in rows]
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.error("Could not list Telegram users: %s", exc)
        return []


def get_telegram_user(telegram_id):
    """Return a Telegram user's SQLite record, whether active or pending."""
    try:
        with _sqlite_connect() as conn:
            row = conn.execute(
                "SELECT telegram_id, full_name, approved_by, approved_at, api_token, active "
                "FROM users WHERE telegram_id = ?",
                (int(telegram_id),),
            ).fetchone()
        if not row:
            return None
        return {
            "telegram_id": row[0],
            "full_name": row[1],
            "approved_by": row[2],
            "approved_at": row[3],
            "api_token": row[4],
            "active": bool(row[5]),
        }
    except (sqlite3.Error, TypeError, ValueError) as exc:
        logger.error("Could not load Telegram user %s: %s", telegram_id, exc)
        return None


# Global for web user email assignments
WEB_USER_EMAIL_ASSIGNMENTS = {}


def init_sqlite_database():
    """Create the single SQLite database used by bot and web code."""
    global SQLITE_READY
    try:
        with _sqlite_connect() as conn:
            conn.executescript("""
                PRAGMA foreign_keys = ON;
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY, full_name TEXT, approved_by INTEGER,
                    approved_at TEXT NOT NULL, api_token TEXT UNIQUE, active INTEGER NOT NULL DEFAULT 1
                );
                CREATE TABLE IF NOT EXISTS user_permissions (
                    telegram_id INTEGER NOT NULL, permission TEXT NOT NULL,
                    PRIMARY KEY (telegram_id, permission),
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sub_admins (
                    telegram_id INTEGER PRIMARY KEY,
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS sub_admin_assignments (
                    sub_admin_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
                    PRIMARY KEY (sub_admin_id, user_id),
                    FOREIGN KEY (sub_admin_id) REFERENCES users(telegram_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS admin_expiry_permissions (
                    admin_id INTEGER PRIMARY KEY, can_edit_expiry INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS user_email_assignments (
                    user_id INTEGER NOT NULL, email TEXT NOT NULL,
                    expiry_date TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, email)
                );
                CREATE TABLE IF NOT EXISTS renewal_decisions (
                    decision_key TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    expiry_date TEXT NOT NULL, status TEXT NOT NULL,
                    emails TEXT, decided_by INTEGER, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS email_renewal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    email TEXT NOT NULL, old_expiry TEXT, new_expiry TEXT NOT NULL,
                    action TEXT NOT NULL, changed_by INTEGER, changed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS access_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                    category TEXT NOT NULL, email TEXT NOT NULL, fetch_time REAL NOT NULL,
                    message TEXT, created_at TEXT NOT NULL,
                    user_type TEXT, username TEXT, full_name TEXT, telegram_id INTEGER
                );
                CREATE TABLE IF NOT EXISTS web_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL, full_name TEXT, telegram_id INTEGER UNIQUE,
                    role TEXT DEFAULT 'user', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    approved INTEGER DEFAULT 0,
                    api_token TEXT UNIQUE,
                    permissions TEXT
                );
                CREATE TABLE IF NOT EXISTS web_email_assignments (
                    web_user_id INTEGER NOT NULL,
                    email TEXT NOT NULL,
                    expiry_date TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (web_user_id, email)
                );
                -- New table for named API keys
                CREATE TABLE IF NOT EXISTS api_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    user_type TEXT NOT NULL,  -- 'telegram' or 'web'
                    name TEXT NOT NULL,
                    key TEXT UNIQUE NOT NULL,
                    created_at TEXT NOT NULL,
                    last_used TEXT
                );
                CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                INSERT OR IGNORE INTO schema_meta(key, value) VALUES ('schema_version', '1');
                CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS unified_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    approved INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_identities (
                    account_id INTEGER NOT NULL,
                    identity_type TEXT NOT NULL,
                    identity_id TEXT NOT NULL,
                    username TEXT,
                    full_name TEXT,
                    verified INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (identity_type, identity_id),
                    FOREIGN KEY (account_id) REFERENCES unified_accounts(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_account_identities_account ON account_identities(account_id);
                CREATE TABLE IF NOT EXISTS account_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS account_link_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER NOT NULL,
                    code_hash TEXT UNIQUE NOT NULL,
                    expires_at TEXT NOT NULL,
                    used_at TEXT,
                    created_by TEXT,
                    FOREIGN KEY (account_id) REFERENCES unified_accounts(id) ON DELETE CASCADE
                );
            """)
            # Identity columns were added after the original audit table.  Keep
            # this migration idempotent for existing SQLite installations.
            columns = {row[1] for row in conn.execute("PRAGMA table_info(access_logs)").fetchall()}
            for column, definition in (
                ('user_type', 'TEXT'),
                ('username', 'TEXT'),
                ('full_name', 'TEXT'),
                ('telegram_id', 'INTEGER'),
            ):
                if column not in columns:
                    conn.execute(f"ALTER TABLE access_logs ADD COLUMN {column} {definition}")
        SQLITE_READY = True
        migrate_unified_accounts()
        logger.info(f"SQLite database ready at: {SQLITE_DB_PATH}")
        return True
    except Exception as e:
        SQLITE_READY = False
        logger.error(f"SQLite database initialization failed: {e}")
        return False


# ---------- Unified account identity layer ----------

def _identity_key(identity_type, identity_id):
    return str(identity_type).strip().lower(), str(identity_id).strip()


def _ensure_unified_account(conn, identity_type, identity_id, username=None, full_name=None, approved=False):
    identity_type, identity_id = _identity_key(identity_type, identity_id)
    row = conn.execute(
        "SELECT account_id FROM account_identities WHERE identity_type=? AND identity_id=?",
        (identity_type, identity_id),
    ).fetchone()
    now = _now()
    if row:
        account_id = row[0]
        conn.execute(
            "UPDATE account_identities SET username=COALESCE(?, username), full_name=COALESCE(?, full_name) WHERE identity_type=? AND identity_id=?",
            (username, full_name, identity_type, identity_id),
        )
        if approved:
            conn.execute("UPDATE unified_accounts SET approved=1, updated_at=? WHERE id=?", (now, account_id))
        return account_id
    conn.execute(
        "INSERT INTO unified_accounts(approved,created_at,updated_at) VALUES (?,?,?)",
        (int(bool(approved)), now, now),
    )
    account_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO account_identities(account_id,identity_type,identity_id,username,full_name,created_at) VALUES (?,?,?,?,?,?)",
        (account_id, identity_type, identity_id, username, full_name, now),
    )
    return account_id


def migrate_unified_accounts():
    """Idempotently backfill canonical accounts from legacy Telegram and Web data."""
    try:
        with _sqlite_connect() as conn:
            # Import all Telegram records, including inactive/pending users.
            # APPROVED_USERS only contains active users and therefore cannot be
            # the source for the web approval directory.
            for uid, full_name, active in conn.execute(
                "SELECT telegram_id, full_name, active FROM users WHERE telegram_id IS NOT NULL"
            ).fetchall():
                _ensure_unified_account(
                    conn,
                    "telegram",
                    int(uid),
                    full_name=full_name,
                    approved=bool(active),
                )
            for uid, data in APPROVED_USERS.items():
                data = data if isinstance(data, dict) else {}
                _ensure_unified_account(conn, "telegram", int(uid), full_name=data.get("name"), approved=True)
            for row in conn.execute("SELECT id, username, full_name, telegram_id, approved FROM web_users").fetchall():
                wid, username, full_name, telegram_id, approved = row
                if telegram_id is not None:
                    account_id = _ensure_unified_account(conn, "telegram", int(telegram_id), full_name=full_name, approved=bool(approved))
                    existing = conn.execute("SELECT account_id FROM account_identities WHERE identity_type='web' AND identity_id=?", (str(wid),)).fetchone()
                    if existing and existing[0] != account_id:
                        # Existing explicit links win; never silently merge accounts.
                        continue
                    if not existing:
                        conn.execute("INSERT INTO account_identities(account_id,identity_type,identity_id,username,full_name,created_at) VALUES (?,?,?,?,?,?)", (account_id, "web", str(wid), username, full_name, _now()))
                else:
                    _ensure_unified_account(conn, "web", wid, username=username, full_name=full_name, approved=bool(approved))
    except Exception as exc:
        logger.error("Unified account migration failed: %s", exc)


def sync_account_approval(identity_type, identity_id, approved, actor_type="system", actor_id=None):
    """Persist one approval decision across all linked legacy and canonical records.

    Web and Telegram accounts may be linked by telegram_id.  Approval changes
    must therefore be transactional and bidirectional; otherwise a rejected
    account can remain usable through the other interface.
    """
    identity_type, identity_id = _identity_key(identity_type, identity_id)
    approved_value = int(bool(approved))
    with _sqlite_connect() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        if identity_type == "web":
            web_row = conn.execute(
                "SELECT telegram_id FROM web_users WHERE id=?", (int(identity_id),)
            ).fetchone()
            if not web_row:
                return False
            telegram_id = web_row[0]
            conn.execute("UPDATE web_users SET approved=? WHERE id=?", (approved_value, int(identity_id)))
            if telegram_id is not None:
                conn.execute("UPDATE users SET active=? WHERE telegram_id=?", (approved_value, telegram_id))
                account_id = _ensure_unified_account(conn, "telegram", telegram_id)
            else:
                account_id = _ensure_unified_account(conn, "web", identity_id)
        elif identity_type == "telegram":
            telegram_id = int(identity_id)
            conn.execute("UPDATE users SET active=? WHERE telegram_id=?", (approved_value, telegram_id))
            conn.execute("UPDATE web_users SET approved=? WHERE telegram_id=?", (approved_value, telegram_id))
            account_id = _ensure_unified_account(conn, "telegram", telegram_id)
        else:
            raise ValueError("Unsupported account identity type")

        now = _now()
        conn.execute("UPDATE unified_accounts SET approved=?, updated_at=? WHERE id=?", (approved_value, now, account_id))
        conn.execute(
            "INSERT INTO account_audit_log(account_id,actor_type,actor_id,action,details,created_at) VALUES (?,?,?,?,?,?)",
            (account_id, actor_type, str(actor_id) if actor_id is not None else None,
             "approve_account" if approved_value else "reject_account", json.dumps({"approved": bool(approved_value)}), now),
        )
    if identity_type == "telegram":
        if approved_value:
            load_approved_users()
        else:
            APPROVED_USERS.pop(int(identity_id), None)
    elif telegram_id is not None:
        # Keep Telegram-side authorization in the same state immediately,
        # without waiting for the next process restart.
        if approved_value:
            load_approved_users()
        else:
            APPROVED_USERS.pop(int(telegram_id), None)
    return True


def list_unified_accounts(include_pending=True):
    """Return each canonical account once, including Telegram-only and Web-only users."""
    migrate_unified_accounts()
    with _sqlite_connect() as conn:
        rows = conn.execute("""
            SELECT a.id, a.approved, i.identity_type, i.identity_id, i.username, i.full_name
            FROM unified_accounts a JOIN account_identities i ON i.account_id=a.id
            ORDER BY a.id, i.identity_type
        """).fetchall()
    accounts = {}
    for aid, approved, kind, identity_id, username, full_name in rows:
        if not include_pending and not approved:
            continue
        item = accounts.setdefault(aid, {"id": aid, "approved": bool(approved), "telegram_id": None, "web_id": None, "username": None, "full_name": None, "identities": []})
        item["identities"].append({"type": kind, "id": identity_id, "username": username, "full_name": full_name})
        if kind == "telegram":
            item["telegram_id"] = int(identity_id)
        elif kind == "web":
            item["web_id"] = int(identity_id)
            item["username"] = username
        item["full_name"] = item["full_name"] or full_name
    return list(accounts.values())


def resolve_unified_account(target):
    """Resolve unified ID, Telegram ID, Web ID (WEB-000001), or username."""
    raw = str(target or "").strip()
    candidates = []
    if raw.upper().startswith("WEB-") and raw[4:].isdigit():
        candidates.append(("web", str(int(raw[4:]))))
    elif raw.isdigit():
        candidates.extend([("telegram", str(int(raw))), ("web", str(int(raw))), ("unified", str(int(raw)))])
    else:
        candidates.append(("username", raw.lstrip("@").lower()))
    migrate_unified_accounts()
    with _sqlite_connect() as conn:
        for kind, value in candidates:
            if kind == "unified":
                row = conn.execute("SELECT id FROM unified_accounts WHERE id=?", (value,)).fetchone()
            elif kind == "username":
                row = conn.execute("SELECT account_id FROM account_identities WHERE lower(username)=?", (value,)).fetchone()
            else:
                row = conn.execute("SELECT account_id FROM account_identities WHERE identity_type=? AND identity_id=?", (kind, value)).fetchone()
            if row:
                return int(row[0])
    return None


def record_account_audit(account_id, actor_type, actor_id, action, details=None):
    try:
        with _sqlite_connect() as conn:
            conn.execute("INSERT INTO account_audit_log(account_id,actor_type,actor_id,action,details,created_at) VALUES (?,?,?,?,?,?)", (account_id, actor_type, str(actor_id) if actor_id is not None else None, action, json.dumps(details or {}, sort_keys=True), _now()))
    except Exception as exc:
        logger.error("Could not record account audit event: %s", exc)


def create_account_link_code(account_id, created_by, ttl_seconds=600):
    """Create a one-time, expiring code. The raw code is returned only to the caller."""
    raw = secrets.token_urlsafe(24)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.utcnow().timestamp() + int(ttl_seconds)
    with _sqlite_connect() as conn:
        conn.execute("UPDATE account_link_codes SET used_at=? WHERE account_id=? AND used_at IS NULL", (_now(), account_id))
        conn.execute("INSERT INTO account_link_codes(account_id,code_hash,expires_at,created_by) VALUES (?,?,datetime(?,'unixepoch'),?)", (account_id, digest, expires, str(created_by)))
    return raw


def consume_account_link_code(raw_code, identity_type, identity_id, username=None, full_name=None):
    digest = hashlib.sha256(str(raw_code).encode()).hexdigest()
    with _sqlite_connect() as conn:
        row = conn.execute("SELECT id,account_id FROM account_link_codes WHERE code_hash=? AND used_at IS NULL AND expires_at > datetime('now')", (digest,)).fetchone()
        if not row:
            return None
        account_id = row[1]
        existing = conn.execute("SELECT account_id FROM account_identities WHERE identity_type=? AND identity_id=?", (identity_type, str(identity_id))).fetchone()
        if existing and existing[0] != account_id:
            return None
        if not existing:
            conn.execute("INSERT INTO account_identities(account_id,identity_type,identity_id,username,full_name,created_at) VALUES (?,?,?,?,?,?)", (account_id, identity_type, str(identity_id), username, full_name, _now()))
        conn.execute("UPDATE account_link_codes SET used_at=? WHERE id=?", (_now(), row[0]))
    record_account_audit(account_id, "system", identity_id, "link_identity", {"identity_type": identity_type})
    return account_id


def merge_unified_accounts(source_account_id, target_account_id, actor_id):
    """Merge identities into target; callers must enforce super-admin authorization."""
    source_account_id, target_account_id = int(source_account_id), int(target_account_id)
    if source_account_id == target_account_id:
        return False
    with _sqlite_connect() as conn:
        source = conn.execute("SELECT id FROM unified_accounts WHERE id=?", (source_account_id,)).fetchone()
        target = conn.execute("SELECT id FROM unified_accounts WHERE id=?", (target_account_id,)).fetchone()
        if not source or not target:
            return False
        conflicts = conn.execute("""
            SELECT s.identity_type, s.identity_id FROM account_identities s
            JOIN account_identities t ON t.identity_type=s.identity_type AND t.identity_id=s.identity_id
            WHERE s.account_id=? AND t.account_id=?
        """, (source_account_id, target_account_id)).fetchall()
        if conflicts:
            return False
        conn.execute("UPDATE account_identities SET account_id=? WHERE account_id=?", (target_account_id, source_account_id))
        conn.execute("UPDATE account_link_codes SET account_id=? WHERE account_id=? AND used_at IS NULL", (target_account_id, source_account_id))
        conn.execute("DELETE FROM unified_accounts WHERE id=?", (source_account_id,))
    record_account_audit(target_account_id, "telegram", actor_id, "merge_account", {"source_account_id": source_account_id})
    return True


# ---------- Existing load/save functions (unchanged from original) ----------

def save_approved_users():
    try:
        with _sqlite_connect() as conn:
            for user_id, raw_data in APPROVED_USERS.items():
                data = raw_data if isinstance(raw_data, dict) else {}
                conn.execute("""INSERT INTO users(telegram_id,full_name,approved_by,approved_at,api_token,active)
                    VALUES(?,?,?,?,?,1) ON CONFLICT(telegram_id) DO UPDATE SET full_name=excluded.full_name,
                    approved_by=excluded.approved_by, api_token=excluded.api_token, active=1""",
                    (int(user_id), data.get("name"), data.get("approved_by"), data.get("approved_at", _now()), data.get("api_token")))
                conn.execute("DELETE FROM user_permissions WHERE telegram_id=?", (int(user_id),))
                conn.executemany("INSERT OR IGNORE INTO user_permissions VALUES (?,?)", [(int(user_id), p) for p in dict.fromkeys(data.get("permissions", []))])
    except Exception as e:
        logger.error(f"Error saving approved users: {e}")


def load_approved_users():
    try:
        with _sqlite_connect() as conn:
            users = conn.execute("SELECT telegram_id,full_name,approved_by,approved_at,api_token FROM users WHERE active=1").fetchall()
            permission_rows = conn.execute("SELECT telegram_id,permission FROM user_permissions").fetchall()
        permissions = {}
        for user_id, permission in permission_rows:
            permissions.setdefault(user_id, []).append(permission)
        APPROVED_USERS.clear()
        APPROVED_USERS.update({uid: {"permissions": permissions.get(uid, []), "approved_by": by, "approved_at": approved_at, "name": name or f"User {uid}", **({"api_token": token} if token else {})} for uid, name, by, approved_at, token in users})
        if not APPROVED_USERS:
            APPROVED_USERS[ADMIN_ID] = {
                "permissions": ["Household", "Reset", "Login Code", "Verification Code", "Verification Code After Login", "Verify Email", "TV Login"],
                "approved_by": ADMIN_ID,
                "approved_at": _now(),
                "name": "Super Admin",
            }
            save_approved_users()
    except Exception as e:
        logger.error(f"Error loading approved users: {e}")


def save_sub_admin_users():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM sub_admins")
            conn.executemany("INSERT OR IGNORE INTO sub_admins VALUES (?)", [(int(uid),) for uid in SUB_ADMIN_USERS])
    except Exception as e:
        logger.error(f"Error saving sub admins: {e}")


def load_sub_admin_users():
    try:
        with _sqlite_connect() as conn:
            values = [row[0] for row in conn.execute("SELECT telegram_id FROM sub_admins")]
        SUB_ADMIN_USERS.clear(); SUB_ADMIN_USERS.update(values)
    except Exception as e:
        logger.error(f"Error loading sub admins: {e}")


def save_sub_admin_assignments():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM sub_admin_assignments")
            conn.executemany("INSERT OR IGNORE INTO sub_admin_assignments VALUES (?,?)", [(int(a), int(u)) for a, users in SUB_ADMIN_ASSIGNMENTS.items() for u in users])
    except Exception as e:
        logger.error(f"Error saving sub-admin assignments: {e}")


def load_sub_admin_assignments():
    try:
        with _sqlite_connect() as conn:
            loaded = {}
            for admin, user in conn.execute("SELECT sub_admin_id,user_id FROM sub_admin_assignments"):
                loaded.setdefault(admin, []).append(user)
        SUB_ADMIN_ASSIGNMENTS.clear(); SUB_ADMIN_ASSIGNMENTS.update(loaded)
    except Exception as e:
        logger.error(f"Error loading sub-admin assignments: {e}")


def save_user_email_assignments():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM user_email_assignments")
            rows = [(int(uid), str(email).strip().lower(), str(expiry), _now()) for uid, emails in USER_EMAIL_ASSIGNMENTS.items() if isinstance(emails, dict) for email, expiry in emails.items()]
            conn.executemany("INSERT INTO user_email_assignments VALUES (?,?,?,?)", rows)
    except Exception as e:
        logger.error(f"Error saving user email assignments: {e}")


def load_user_email_assignments():
    try:
        with _sqlite_connect() as conn:
            loaded = {}
            for uid, email, expiry in conn.execute("SELECT user_id,email,expiry_date FROM user_email_assignments"):
                loaded.setdefault(uid, {})[email] = expiry
        USER_EMAIL_ASSIGNMENTS.clear(); USER_EMAIL_ASSIGNMENTS.update(loaded)
    except Exception as e:
        logger.error(f"Error loading user email assignments: {e}")


def save_admin_expiry_permissions():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM admin_expiry_permissions")
            conn.executemany("INSERT INTO admin_expiry_permissions VALUES (?,?)", [(int(uid), int(bool(value))) for uid, value in ADMIN_CAN_EDIT_EXPIRY.items()])
    except Exception as e:
        logger.error(f"Error saving admin expiry permissions: {e}")


def load_admin_expiry_permissions():
    try:
        with _sqlite_connect() as conn:
            loaded = dict(conn.execute("SELECT admin_id,can_edit_expiry FROM admin_expiry_permissions"))
        ADMIN_CAN_EDIT_EXPIRY.clear(); ADMIN_CAN_EDIT_EXPIRY.update({uid: bool(value) for uid, value in loaded.items()})
    except Exception as e:
        logger.error(f"Error loading admin expiry permissions: {e}")


def save_renewal_decisions():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM renewal_decisions")
            conn.executemany("INSERT INTO renewal_decisions VALUES (?,?,?,?,?,?,?)", [(key, int(data.get("user_id", 0)), data.get("expiry_date", ""), data.get("status", ""), "\n".join(data.get("emails", [])), data.get("decided_by"), data.get("updated_at", _now())) for key, data in RENEWAL_DECISIONS.items()])
    except Exception as e:
        logger.error(f"Error saving renewal decisions: {e}")


def load_renewal_decisions():
    try:
        with _sqlite_connect() as conn:
            loaded = {key: {"user_id": uid, "expiry_date": date, "status": status, "emails": emails.split("\n") if emails else [], "decided_by": by, "updated_at": updated} for key, uid, date, status, emails, by, updated in conn.execute("SELECT * FROM renewal_decisions")}
        RENEWAL_DECISIONS.clear(); RENEWAL_DECISIONS.update(loaded)
    except Exception as e:
        logger.error(f"Error loading renewal decisions: {e}")


def record_email_renewal_history(user_id, email, old_expiry, new_expiry, action="update", changed_by=None):
    """Insert a single row into email_renewal_history."""
    try:
        with _sqlite_connect() as conn:
            conn.execute(
                "INSERT INTO email_renewal_history (user_id, email, old_expiry, new_expiry, action, changed_by, changed_at) VALUES (?,?,?,?,?,?,?)",
                (int(user_id), str(email).strip().lower(), old_expiry, new_expiry, action, int(changed_by) if changed_by is not None else None, _now())
            )
    except Exception as e:
        logger.error(f"Error recording email renewal history: {e}")


def record_email_renewal_history_bulk(entries, action="update", changed_by=None):
    """Insert multiple rows into email_renewal_history in a single transaction.

    ``entries`` is an iterable of ``(user_id, email, old_expiry, new_expiry)`` tuples.
    """
    rows = []
    for entry in entries or []:
        try:
            uid, email, old_expiry, new_expiry = entry
        except (TypeError, ValueError):
            continue
        rows.append((int(uid), str(email).strip().lower(), old_expiry, new_expiry, action, int(changed_by) if changed_by is not None else None, _now()))
    if not rows:
        return
    try:
        with _sqlite_connect() as conn:
            conn.executemany(
                "INSERT INTO email_renewal_history (user_id, email, old_expiry, new_expiry, action, changed_by, changed_at) VALUES (?,?,?,?,?,?,?)",
                rows
            )
    except Exception as e:
        logger.error(f"Error recording bulk email renewal history: {e}")


# ---------- Telegram user functions (existing) ----------

def get_user_assigned_emails_with_expired(user_id):
    from email_bot.expiry import get_user_assigned_emails_with_expired
    return get_user_assigned_emails_with_expired(user_id)


def get_user_email_expiry(user_id, email):
    from email_bot.expiry import get_user_email_expiry
    return get_user_email_expiry(user_id, email)


def is_user_email_expired(user_id, email):
    from email_bot.expiry import is_user_email_expired
    return is_user_email_expired(user_id, email)


def get_user_assigned_emails_count(user_id):
    from email_bot.expiry import get_user_assigned_emails_count
    return get_user_assigned_emails_count(user_id)


def get_user_assigned_emails(user_id):
    from email_bot.messages import get_user_assigned_emails
    return get_user_assigned_emails(user_id)


def generate_api_token(user_id):
    if user_id not in APPROVED_USERS:
        return None
    token = secrets.token_urlsafe(32)
    APPROVED_USERS[user_id].setdefault("permissions", [])
    APPROVED_USERS[user_id]["api_token"] = token
    save_approved_users()
    return token


def validate_legacy_token(token):
    for uid, data in APPROVED_USERS.items():
        if isinstance(data, dict) and data.get("api_token") == token:
            return uid, 'telegram'
    return None, None


# ---------- Web user email assignment functions ----------

def save_web_user_email_assignments():
    try:
        with _sqlite_connect() as conn:
            conn.execute("DELETE FROM web_email_assignments")
            rows = [(int(uid), str(email).strip().lower(), str(expiry), _now())
                    for uid, emails in WEB_USER_EMAIL_ASSIGNMENTS.items()
                    if isinstance(emails, dict)
                    for email, expiry in emails.items()]
            conn.executemany("INSERT INTO web_email_assignments VALUES (?,?,?,?)", rows)
    except Exception as e:
        logger.error(f"Error saving web user email assignments: {e}")


def load_web_user_email_assignments():
    try:
        with _sqlite_connect() as conn:
            loaded = {}
            for uid, email, expiry in conn.execute("SELECT web_user_id, email, expiry_date FROM web_email_assignments"):
                loaded.setdefault(uid, {})[email] = expiry
        WEB_USER_EMAIL_ASSIGNMENTS.clear()
        WEB_USER_EMAIL_ASSIGNMENTS.update(loaded)
    except Exception as e:
        logger.error(f"Error loading web user email assignments: {e}")


def get_web_user_assigned_emails(web_user_id):
    from email_bot.expiry import today_ist, parse_expiry_date
    email_map = WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id, {})
    today = today_ist()
    active = []
    for email, expiry_str in email_map.items():
        try:
            expiry_date = parse_expiry_date(expiry_str)
            if expiry_date >= today:
                active.append(email)
        except:
            pass
    return active


def get_web_user_assigned_emails_with_expired(web_user_id):
    return list(WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id, {}).keys())


def get_web_user_email_expiry(web_user_id, email):
    return WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id, {}).get(email.lower())


def set_web_user_email_expiry(web_user_id, email, expiry_date):
    from email_bot.expiry import normalize_expiry_date
    email = email.lower()
    expiry_date = normalize_expiry_date(expiry_date)
    if not expiry_date:
        return False
    map = WEB_USER_EMAIL_ASSIGNMENTS.setdefault(web_user_id, {})
    if email not in map:
        return False
    map[email] = expiry_date
    save_web_user_email_assignments()
    return True


def remove_web_user_email(web_user_id, email):
    email = email.lower()
    map = WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id)
    if map and email in map:
        del map[email]
        if not map:
            del WEB_USER_EMAIL_ASSIGNMENTS[web_user_id]
        save_web_user_email_assignments()
        return True
    return False


def assign_web_user_emails_bulk(web_user_id, assignments):
    from email_bot.expiry import normalize_expiry_date
    added = []
    already = []
    invalid = []
    email_map = WEB_USER_EMAIL_ASSIGNMENTS.setdefault(web_user_id, {})
    for email, expiry in assignments:
        email = email.lower()
        expiry = normalize_expiry_date(expiry)
        if not expiry:
            invalid.append(email)
            continue
        if email in email_map:
            already.append(email)
        else:
            email_map[email] = expiry
            added.append((email, expiry))
    if added:
        save_web_user_email_assignments()
    return added, already, invalid


# ---------- Web user permissions ----------

def get_web_user_permissions(web_user_id):
    try:
        with _sqlite_connect() as conn:
            row = conn.execute("SELECT permissions FROM web_users WHERE id=?", (web_user_id,)).fetchone()
            if row and row[0]:
                try:
                    permissions = json.loads(row[0])
                except (TypeError, ValueError, json.JSONDecodeError):
                    logger.warning("Malformed permissions JSON for web user %s", web_user_id)
                    return []
                return permissions if isinstance(permissions, list) else []
            return []
    except Exception:
        return []


def get_web_user_identity(web_user_id):
    """Return identity fields used by API/audit logging for a web account."""
    try:
        with _sqlite_connect() as conn:
            row = conn.execute(
                "SELECT id, username, full_name, telegram_id FROM web_users WHERE id = ?",
                (web_user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            'id': row[0],
            'type': 'web',
            'username': row[1],
            'full_name': row[2],
            'telegram_id': row[3],
        }
    except Exception as e:
        logger.error("Error loading web user identity %s: %s", web_user_id, e)
        return None


def set_web_user_permissions(web_user_id, permissions_list):
    try:
        with _sqlite_connect() as conn:
            conn.execute("UPDATE web_users SET permissions=? WHERE id=?", (json.dumps(permissions_list), web_user_id))
        return True
    except Exception as e:
        logger.error(f"Error setting web user permissions: {e}")
        return False


# ---------- API Key Management ----------

def create_api_key(user_id, user_type, name):
    """Generate a new API key for a user. Returns the key string or None."""
    key = secrets.token_urlsafe(32)
    try:
        with _sqlite_connect() as conn:
            conn.execute(
                "INSERT INTO api_keys (user_id, user_type, name, key, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, user_type, name, key, _now())
            )
        return key
    except sqlite3.IntegrityError:
        # Key collision – retry once
        key = secrets.token_hex(32)
        try:
            with _sqlite_connect() as conn:
                conn.execute(
                    "INSERT INTO api_keys (user_id, user_type, name, key, created_at) VALUES (?, ?, ?, ?, ?)",
                    (user_id, user_type, name, key, _now())
                )
            return key
        except Exception as e:
            logger.error(f"Failed to create API key: {e}")
            return None
    except Exception as e:
        logger.error(f"Failed to create API key: {e}")
        return None


def validate_api_key(key):
    """Return (user_id, user_type) if key is valid, else None."""
    try:
        with _sqlite_connect() as conn:
            row = conn.execute(
                "SELECT user_id, user_type FROM api_keys WHERE key = ?",
                (key,)
            ).fetchone()
            if row:
                # Update last_used
                conn.execute(
                    "UPDATE api_keys SET last_used = ? WHERE key = ?",
                    (_now(), key)
                )
                return row[0], row[1]
    except Exception as e:
        logger.error(f"Error validating API key: {e}")
    return None


def list_api_keys(user_id, user_type):
    """Return list of API keys for a user with metadata."""
    try:
        with _sqlite_connect() as conn:
            rows = conn.execute(
                "SELECT id, name, key, created_at, last_used FROM api_keys WHERE user_id = ? AND user_type = ?",
                (user_id, user_type)
            ).fetchall()
            return [{
                'id': r[0],
                'name': r[1],
                'key': r[2],
                'created_at': r[3],
                'last_used': r[4]
            } for r in rows]
    except Exception as e:
        logger.error(f"Error listing API keys: {e}")
        return []


def revoke_api_key(key_id, user_id, user_type):
    """Delete an API key if it belongs to the user."""
    try:
        with _sqlite_connect() as conn:
            conn.execute(
                "DELETE FROM api_keys WHERE id = ? AND user_id = ? AND user_type = ?",
                (key_id, user_id, user_type)
            )
            return conn.total_changes > 0
    except Exception as e:
        logger.error(f"Error revoking API key: {e}")
        return False


# ---------- Unified token/key validation ----------

def validate_any_token(token):
    """Try new API keys first, then legacy tokens."""
    # 1. New API keys
    result = validate_api_key(token)
    if result:
        user_id, user_type = result
        return {'type': user_type, 'id': user_id}
    # 2. Legacy token (only for Telegram)
    uid, utype = validate_legacy_token(token)
    if uid is not None:
        return {'type': utype, 'id': uid}
    return None


# ---------- Data health check ----------

def data_health_check():
    def check_loop():
        while True:
            time.sleep(3600)
            verify_data_directory()
    threading.Thread(target=check_loop, daemon=True).start()


# ---------- Web account creation ----------

def create_web_account_for_user(user_id, user_name=None, regenerate=False):
    chars = string.ascii_letters + string.digits + "!@#$%"
    password = secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase) + secrets.choice(string.digits) + secrets.choice("!@#$%") + ''.join(secrets.choice(chars) for _ in range(4))
    password_chars = list(password); random.shuffle(password_chars); password = ''.join(password_chars)
    username = f"user_{secrets.token_hex(4)}"
    try:
        with _sqlite_connect() as conn:
            existing = conn.execute("SELECT id, username FROM web_users WHERE telegram_id=?", (int(user_id),)).fetchone()
            if existing:
                if not regenerate:
                    conn.execute("UPDATE web_users SET approved=1 WHERE id=?", (existing[0],))
                    return {"success": True, "username": existing[1], "web_id": format_web_user_id(existing[0]), "password": None, "message": "Web account already exists"}
                username = existing[1]
                conn.execute(
                    "UPDATE web_users SET password_hash=?, full_name=?, telegram_id=?, approved=1 WHERE id=?",
                    (generate_password_hash(password), user_name or f"User {user_id}", int(user_id), existing[0]),
                )
                message = "Web account credentials regenerated successfully (new password)"
            else:
                conn.execute(
                    "INSERT INTO web_users(username,password_hash,full_name,telegram_id,role,approved) VALUES (?,?,?,?,?,?)",
                    (username, generate_password_hash(password), user_name or f"User {user_id}", int(user_id), "user", 1)
                )
                message = "Web account created successfully"
        with _sqlite_connect() as conn:
            web_user_id = conn.execute("SELECT id FROM web_users WHERE username=?", (username,)).fetchone()[0]
        return {"success": True, "username": username, "web_id": format_web_user_id(web_user_id), "password": password, "message": message}
    except Exception as e:
        logger.error(f"Error creating web account: {e}")
        return {"success": False, "username": username, "password": None, "message": str(e)}


def get_web_user_by_id(web_user_id):
    """Return web user record as dict."""
    try:
        with _sqlite_connect() as conn:
            row = conn.execute("SELECT id, username, password_hash, full_name, telegram_id, role, approved, api_token, permissions FROM web_users WHERE id=?", (web_user_id,)).fetchone()
            if row:
                try:
                    parsed_permissions = json.loads(row[8]) if row[8] else []
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed_permissions = []
                return {
                    "id": row[0],
                    "web_id": format_web_user_id(row[0]),
                    "username": row[1],
                    "password_hash": row[2],
                    "full_name": row[3],
                    "telegram_id": row[4],
                    "role": row[5],
                    "approved": bool(row[6]),
                    "api_token": row[7],
                    "permissions": parsed_permissions if isinstance(parsed_permissions, list) else []
                }
    except Exception as e:
        logger.error("Error loading web user %s: %s", web_user_id, e)
    return None