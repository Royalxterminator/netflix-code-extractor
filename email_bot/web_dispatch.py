"""
Unified dispatch over Telegram and Web users for admin operations.

All functions accept (user_type, uid) where user_type is 'telegram' or 'web'
and uid is an integer. This lets the Telegram admin handlers support web users
without duplicating logic.
"""
from datetime import timedelta
from email_bot.config import ADMIN_ID, DATE_FORMAT, DEFAULT_EXPIRY_DAYS, logger, SQLITE_DB_PATH
from email_bot import storage, expiry
from email_bot.permissions import (
    get_user_display_name as _tg_display_name,
    get_user_permissions as _tg_perms,
    API_ACCESS_PERMISSION,
)


# ─── Identifier parsing ───────────────────────────────────────────────────────

def parse_user_identifier(user_input):
    """Parse a user identifier string.

    '123'   -> ('telegram', 123)
    'web_4' -> ('web', 4)
    'web4'  -> ('web', 4)
    'bad'   -> None
    """
    if user_input is None:
        return None
    low = str(user_input).strip().lower()
    if low.startswith('web_'):
        num = low[4:]
        return ('web', int(num)) if num.isdigit() else None
    if low.startswith('web'):
        num = low[3:]
        return ('web', int(num)) if num.isdigit() else None
    if low.isdigit():
        return ('telegram', int(low))
    return None


def parse_target_id(token):
    """Parse a target id token from callback data (handles suffixes)."""
    if not token:
        return None
    token = str(token).strip().lower()
    if token.startswith('web_'):
        first = token[4:].split('_')[0]
        return ('web', int(first)) if first.isdigit() else None
    if token.startswith('web'):
        first = token[3:].split('_')[0]
        return ('web', int(first)) if first.isdigit() else None
    first = token.split('_')[0]
    return ('telegram', int(first)) if first.isdigit() else None


def user_label(user_type, uid):
    return f"web_{uid}" if user_type == 'web' else str(uid)


# ─── Display ──────────────────────────────────────────────────────────────────

def get_display_name(user_type, uid):
    if user_type == 'telegram':
        return _tg_display_name(uid)
    wu = storage.get_web_user_by_id(uid)
    if wu:
        return wu.get('username') or f'web_{uid}'
    return f'web_{uid}'


def get_web_user_display(uid):
    wu = storage.get_web_user_by_id(uid)
    if wu:
        return wu.get('full_name') or wu.get('username') or f'web_{uid}'
    return f'web_{uid}'


# ─── Email accessors ──────────────────────────────────────────────────────────

def get_emails_with_expired(user_type, uid):
    if user_type == 'telegram':
        return expiry.get_user_assigned_emails_with_expired(uid)
    return expiry.web_get_user_assigned_emails_with_expired(uid)


def get_email_expiry(user_type, uid, email):
    if user_type == 'telegram':
        return expiry.get_user_email_expiry(uid, email)
    return expiry.web_get_user_email_expiry(uid, email)


def is_email_expired(user_type, uid, email):
    return expiry.is_expiry_date_expired(get_email_expiry(user_type, uid, email))


def get_expired_emails(user_type, uid):
    if user_type == 'telegram':
        from email_bot.permissions import get_user_expired_emails
        return get_user_expired_emails(uid)
    return [e for e in get_emails_with_expired(user_type, uid) if is_email_expired(user_type, uid, e)]


def get_emails_for_expiry_date(user_type, uid, target_date_str):
    target_norm = expiry.normalize_expiry_date(target_date_str)
    return [e for e in get_emails_with_expired(user_type, uid)
            if expiry.normalize_expiry_date(get_email_expiry(user_type, uid, e)) == target_norm]


def get_expiring_tomorrow_emails(user_type, uid):
    tomorrow_str = (expiry.today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    return get_emails_for_expiry_date(user_type, uid, tomorrow_str)


def get_expiring_tomorrow_count(user_type, uid):
    return len(get_expiring_tomorrow_emails(user_type, uid))


def get_expiring_next7(user_type, uid):
    today = expiry.today_ist()
    end = today + timedelta(days=7)
    result = []
    for email in get_emails_with_expired(user_type, uid):
        try:
            exp_obj = expiry.parse_expiry_date(get_email_expiry(user_type, uid, email))
            if today <= exp_obj <= end:
                result.append(email)
        except Exception:
            pass
    return result


def get_email_count(user_type, uid):
    return len(get_emails_with_expired(user_type, uid))


def get_email_counts(user_type, uid):
    all_emails = get_emails_with_expired(user_type, uid)
    expired = [e for e in all_emails if is_email_expired(user_type, uid, e)]
    return {
        'all': len(all_emails),
        'active': len(all_emails) - len(expired),
        'expired': len(expired),
        'tomorrow': get_expiring_tomorrow_count(user_type, uid),
        'next7': len(get_expiring_next7(user_type, uid)),
    }


def filter_emails(user_type, uid, filter_key="all", search_query=None):
    tomorrow_str = (expiry.today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    today = expiry.today_ist()
    end7 = today + timedelta(days=7)
    result = []
    for email in get_emails_with_expired(user_type, uid):
        exp_norm = expiry.normalize_expiry_date(get_email_expiry(user_type, uid, email))
        inc = True
        if filter_key == 'active':
            inc = not is_email_expired(user_type, uid, email)
        elif filter_key == 'expired':
            inc = is_email_expired(user_type, uid, email)
        elif filter_key == 'tomorrow':
            inc = (exp_norm == tomorrow_str)
        elif filter_key == 'next7':
            inc = False
            if exp_norm:
                try:
                    inc = today <= expiry.parse_expiry_date(exp_norm) <= end7
                except Exception:
                    inc = False
        if inc and search_query and search_query.lower() not in email.lower():
            inc = False
        if inc:
            result.append(email)
    return result


# ─── Email mutations ──────────────────────────────────────────────────────────

def assign_bulk(user_type, uid, assignments):
    """Assign emails in bulk. assignments = list of (email, expiry_date_str).
    Returns (added_pairs, already_target, invalid)."""
    if user_type == 'telegram':
        return expiry.assign_emails_to_user_bulk(uid, assignments)
    added, already, invalid = [], [], []
    for email, expiry_date in assignments:
        email_norm = str(email).strip().lower()
        exp_norm = expiry.normalize_expiry_date(expiry_date)
        if not email_norm or not exp_norm:
            invalid.append(email)
            continue
        existing = storage.get_web_user_email_expiry(uid, email_norm)
        if existing == exp_norm:
            already.append((email_norm, exp_norm))
        else:
            storage.set_web_user_email_expiry(uid, email_norm, exp_norm)
            added.append((email_norm, exp_norm))
    return added, already, invalid


def remove_email(user_type, uid, email):
    if user_type == 'telegram':
        return expiry.remove_email_from_user(uid, email)
    return storage.remove_web_user_email(uid, str(email).strip().lower())


def set_expiry(user_type, uid, email, expiry_date):
    if user_type == 'telegram':
        return expiry.set_user_email_expiry(uid, email, expiry_date)
    return storage.set_web_user_email_expiry(uid, str(email).strip().lower(), expiry_date)


def replace_email(user_type, uid, old_email, new_email):
    if user_type == 'telegram':
        return expiry.replace_user_email(uid, old_email, new_email)
    old_norm = str(old_email).strip().lower()
    new_norm = str(new_email).strip().lower()
    exp = storage.get_web_user_email_expiry(uid, old_norm)
    if exp is None:
        return False, 'Old email not found'
    storage.set_web_user_email_expiry(uid, new_norm, exp)
    storage.remove_web_user_email(uid, old_norm)
    return True, ''


# ─── Renewal ──────────────────────────────────────────────────────────────────

def renew_for_date(user_type, uid, expiry_date_text, admin_user_id=None):
    """Renew all emails matching a specific expiry date. Returns (renewed_lines, skipped_lines)."""
    if user_type == 'telegram':
        from email_bot.utils import renew_emails_for_user_on_date
        return renew_emails_for_user_on_date(uid, expiry_date_text, admin_user_id=admin_user_id)
    exp_norm = expiry.normalize_expiry_date(expiry_date_text)
    if not exp_norm:
        return [], ['Invalid expiry date']
    emails = get_emails_for_expiry_date(user_type, uid, exp_norm)
    renewed_lines, skipped_lines = [], []
    for email in emails:
        current = get_email_expiry(user_type, uid, email)
        if not current or not expiry.is_valid_expiry_date(current):
            skipped_lines.append(f'  {email}: invalid/missing expiry')
            continue
        new_exp = expiry.add_exact_subscription_days(current, DEFAULT_EXPIRY_DAYS)
        if set_expiry(user_type, uid, email, new_exp):
            renewed_lines.append(f'  {email}: {current}   {new_exp}')
        else:
            skipped_lines.append(f'  {email}: could not update')
    return renewed_lines, skipped_lines


def renew_selected(user_type, uid, emails, days=DEFAULT_EXPIRY_DAYS, admin_user_id=None, action="bulk_renew"):
    """Renew specific emails by extending from their current expiry."""
    renewed, skipped = [], []
    for email in emails:
        email_norm = str(email).strip().lower()
        current = get_email_expiry(user_type, uid, email_norm)
        if not current or not expiry.is_valid_expiry_date(current):
            skipped.append(f"▫️ `{email_norm}`: invalid/missing expiry")
            continue
        try:
            current_date = expiry.parse_expiry_date(current)
            new_expiry = (current_date + timedelta(days=days)).strftime(DATE_FORMAT)
        except Exception:
            skipped.append(f"▫️ `{email_norm}`: invalid date")
            continue
        if set_expiry(user_type, uid, email_norm, new_expiry):
            if user_type == 'telegram':
                from email_bot.storage import record_email_renewal_history
                record_email_renewal_history(uid, email_norm, current, new_expiry, action=action, changed_by=admin_user_id)
            renewed.append((email_norm, current, new_expiry))
        else:
            skipped.append(f"▫️ `{email_norm}`: could not update")
    return renewed, skipped


# ─── Permissions ──────────────────────────────────────────────────────────────

def get_permissions(user_type, uid):
    if user_type == 'telegram':
        return _tg_perms(uid)
    return storage.get_web_user_permissions(uid)


def set_permissions(user_type, uid, perms):
    if user_type == 'telegram':
        uid_int = int(uid)
        if uid_int in storage.APPROVED_USERS:
            storage.APPROVED_USERS[uid_int]['permissions'] = perms
            storage.save_approved_users()
        return True
    return storage.set_web_user_permissions(uid, perms)


def add_permission(user_type, uid, cat):
    perms = get_permissions(user_type, uid)
    if cat not in perms:
        perms.append(cat)
        set_permissions(user_type, uid, perms)
        return True
    return False


def remove_permission(user_type, uid, cat):
    perms = get_permissions(user_type, uid)
    if cat in perms:
        perms.remove(cat)
        set_permissions(user_type, uid, perms)
        return True
    return False


# ─── User lifecycle ───────────────────────────────────────────────────────────

def user_exists(user_type, uid):
    if user_type == 'telegram':
        return int(uid) in storage.APPROVED_USERS
    return storage.get_web_user_by_id(uid) is not None


def is_sub_admin(user_type, uid):
    if user_type == 'telegram':
        from email_bot.permissions import is_sub_admin as _is_sub
        return _is_sub(int(uid))
    return False


def can_manage_user(admin_tg_id, user_type, uid):
    """Check if a Telegram admin can manage a given user (of either type)."""
    if user_type == 'telegram':
        from email_bot.permissions import get_manageable_users
        return int(uid) in get_manageable_users(admin_tg_id, include_self=True)
    from email_bot.permissions import is_super_admin
    return is_super_admin(admin_tg_id)


def set_approved(user_type, uid, approved):
    """Approve / disapprove a user."""
    if user_type == 'telegram':
        return storage.sync_account_approval('telegram', uid, approved, 'telegram_web_dispatch', ADMIN_ID)
    try:
        return storage.sync_account_approval('web', uid, approved, 'telegram_web_dispatch', ADMIN_ID)
    except Exception as e:
        logger.error(f"Error setting web user {uid} approved: {e}")
        return False


def remove_user(user_type, uid):
    """Remove a user completely (disapprove + remove emails)."""
    import sqlite3
    if user_type == 'telegram':
        uid_int = int(uid)
        storage.APPROVED_USERS.pop(uid_int, None)
        storage.save_approved_users()
        if uid_int in storage.USER_EMAIL_ASSIGNMENTS:
            del storage.USER_EMAIL_ASSIGNMENTS[uid_int]
            storage.save_user_email_assignments()
        return True
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30)
        conn.execute("DELETE FROM web_users WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error removing web user {uid}: {e}")
    if uid in storage.WEB_USER_EMAIL_ASSIGNMENTS:
        del storage.WEB_USER_EMAIL_ASSIGNMENTS[uid]
        storage.save_web_user_email_assignments()
    return True


# ─── Search / duplicate helpers ───────────────────────────────────────────────

def web_find_duplicates(uid, emails):
    """Find emails already assigned to other web users."""
    email_set = {str(e).strip().lower() for e in (emails or [])}
    duplicates = {}
    for other_uid, email_map in storage.WEB_USER_EMAIL_ASSIGNMENTS.items():
        if other_uid == uid or not isinstance(email_map, dict):
            continue
        for email in email_set:
            if email in email_map:
                duplicates.setdefault(email, []).append(other_uid)
    return duplicates


def web_expiry_summary(uid):
    """Compact expiry summary for a web user."""
    emails = storage.WEB_USER_EMAIL_ASSIGNMENTS.get(uid, {})
    if not emails:
        return "No emails assigned."
    lines = ["📧 **Your assigned emails:**", "━━━━━━━━━━━━━━━━━━━━"]
    for email, exp in sorted(emails.items(), key=lambda x: expiry.normalize_expiry_date(x[1]) or '9999'):
        status = '❌' if expiry.is_expiry_date_expired(exp) else '✅'
        lines.append(f"{status} `{email}` → `{exp or 'N/A'}`")
    return '\n'.join(lines)