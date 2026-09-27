"""Permissions, display helpers, and email query/filter utilities.

Loaded by app.py into one shared runtime context.
"""

from email_bot.config import ADMIN_ID, logger, DATE_FORMAT, APPROVED_USERS, SUB_ADMIN_USERS, SUB_ADMIN_ASSIGNMENTS
from email_bot.storage import save_approved_users
from datetime import timedelta

# ==============================================================================
# HELPER & UTILITY FUNCTIONS
# ==============================================================================

# ===== NEW =====
API_ACCESS_PERMISSION = "API Access"
# ==============

# Simple in-memory cache for display names (key: user_id, value: name)
_name_cache = {}

def is_super_admin(user_id):
    return user_id == ADMIN_ID

def is_sub_admin(user_id):
    return user_id in SUB_ADMIN_USERS

def is_admin(user_id):
    return is_super_admin(user_id) or is_sub_admin(user_id)

def get_user_display_name(user_id):
    """
    Checks local memory/approved-user data for a display name.
    """
    # 1. Check cache first
    if user_id in _name_cache:
        return _name_cache[user_id]

    # 2. Try to get from APPROVED_USERS (RAM)
    if user_id in APPROVED_USERS and isinstance(APPROVED_USERS[user_id], dict):
        if 'name' in APPROVED_USERS[user_id] and APPROVED_USERS[user_id]['name']:
            _name_cache[user_id] = APPROVED_USERS[user_id]['name']
            return _name_cache[user_id]

    # 3. Fallback
    fallback = f"ID: {user_id}"
    _name_cache[user_id] = fallback
    return fallback

def get_user_permissions(user_id):
    user_data = APPROVED_USERS.get(user_id, {})
    if isinstance(user_data, dict):
        return user_data.get('permissions', [])
    return []

def can_user_access_email(user_id, email):
    from email_bot.expiry import _get_user_email_map, is_user_email_expired

    if is_super_admin(user_id):
        return True

    email_lower = str(email).strip().lower()
    email_map = _get_user_email_map(user_id)

    if email_lower not in email_map:
        return False

    return not is_user_email_expired(user_id, email_lower)

def get_manageable_users(admin_id, include_self=False):
    if is_super_admin(admin_id):
        return list(APPROVED_USERS.keys())
    elif is_sub_admin(admin_id):
        manageable = SUB_ADMIN_ASSIGNMENTS.get(admin_id, [])
        if include_self and admin_id not in manageable:
            return [admin_id] + manageable
        return manageable[:]
    else:
        return []

def update_user_commands(user_id):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return None

# ... rest of the file unchanged (email query functions etc.)

# ==============================================================================
# EMAIL QUERY & FILTER FUNCTIONS
# ==============================================================================

def get_user_expired_emails(user_id):
    """Return this user's expired emails in expiry-date order."""
    from email_bot.expiry import _get_user_email_map, is_user_email_expired, sort_user_emails_by_expiry
    return sort_user_emails_by_expiry(
        user_id,
        [email for email in _get_user_email_map(user_id).keys() if is_user_email_expired(user_id, email)]
    )


def get_user_expiring_next_7_days_emails(user_id):
    """Return emails expiring from today through the next 7 days, sorted by expiry date."""
    from email_bot.expiry import _get_user_email_map, normalize_expiry_date, parse_expiry_date, today_ist, sort_user_emails_by_expiry
    today = today_ist()
    end_date = today + timedelta(days=7)
    matched = []
    for email, expiry in _get_user_email_map(user_id).items():
        normalized = normalize_expiry_date(expiry)
        if not normalized:
            continue
        try:
            expiry_obj = parse_expiry_date(normalized)
            if today <= expiry_obj <= end_date:
                matched.append(email)
        except Exception:
            continue
    return sort_user_emails_by_expiry(user_id, matched)


def filter_user_emails(user_id, emails=None, filter_key="all", search_query=None):
    """Filter a user's emails for management panels while preserving date-wise order."""
    from email_bot.expiry import _get_user_email_map, get_user_email_expiry, normalize_expiry_date, parse_expiry_date, today_ist, sort_user_emails_by_expiry, is_user_email_expired
    filter_key = str(filter_key or "all").lower()
    base_emails = sort_user_emails_by_expiry(user_id, emails if emails is not None else _get_user_email_map(user_id).keys())
    tomorrow_str = (today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    today = today_ist()
    end_date = today + timedelta(days=7)

    filtered = []
    for email in base_emails:
        expiry = get_user_email_expiry(user_id, email)
        expiry_norm = normalize_expiry_date(expiry)
        include = True

        if filter_key == "active":
            include = not is_user_email_expired(user_id, email)
        elif filter_key == "expired":
            include = is_user_email_expired(user_id, email)
        elif filter_key == "tomorrow":
            include = expiry_norm == tomorrow_str
        elif filter_key == "next7":
            include = False
            if expiry_norm:
                try:
                    expiry_obj = parse_expiry_date(expiry_norm)
                    include = today <= expiry_obj <= end_date
                except Exception:
                    include = False
        elif filter_key != "all":
            include = True

        if include:
            filtered.append(email)

    query = str(search_query or "").strip().lower()
    if query:
        filtered = [email for email in filtered if query in email.lower()]

    return sort_user_emails_by_expiry(user_id, filtered)


def get_user_email_counts(user_id):
    """Return useful counts for filter buttons and summaries."""
    from email_bot.expiry import get_user_assigned_emails_with_expired, get_user_expiring_tomorrow_emails, is_user_email_expired
    all_emails = get_user_assigned_emails_with_expired(user_id)
    return {
        "all": len(all_emails),
        "active": len([email for email in all_emails if not is_user_email_expired(user_id, email)]),
        "expired": len([email for email in all_emails if is_user_email_expired(user_id, email)]),
        "tomorrow": len(get_user_expiring_tomorrow_emails(user_id)),
        "next7": len(get_user_expiring_next_7_days_emails(user_id)),
    }


def find_duplicate_email_assignments(emails, exclude_user_id=None):
    """Find emails assigned to another Telegram or Web user.

    ``exclude_user_id`` may be a Telegram integer or a ``web_<id>`` target.
    The returned owner IDs retain that same display format so duplicate
    confirmation can identify both backends consistently.
    """
    from email_bot.expiry import _user_key, _get_user_email_map
    from email_bot.config import USER_EMAIL_ASSIGNMENTS
    from email_bot.storage import WEB_USER_EMAIL_ASSIGNMENTS
    exclude_key = str(exclude_user_id).strip().lower() if exclude_user_id is not None else None
    email_set = {str(email).strip().lower() for email in (emails or []) if str(email).strip()}
    duplicates = {}

    owners = [
        (str(_user_key(raw_user_id)), email_map)
        for raw_user_id, email_map in USER_EMAIL_ASSIGNMENTS.items()
    ]
    owners.extend(
        (f"web_{raw_user_id}", email_map)
        for raw_user_id, email_map in WEB_USER_EMAIL_ASSIGNMENTS.items()
    )

    for user_id, email_map in owners:
        if exclude_key is not None and user_id.lower() == exclude_key:
            continue
        if not isinstance(email_map, dict):
            continue
        for email in email_set:
            if email in email_map:
                duplicates.setdefault(email, []).append((user_id, email_map.get(email)))

    return duplicates


def format_duplicate_warning(duplicates, max_items=15):
    """Format duplicate assignment warning compactly."""
    if not duplicates:
        return ""
    lines = ["⚠️ **Duplicate Email Warning**", "These email(s) are already assigned somewhere else:"]
    shown = 0
    for email, owners in duplicates.items():
        if shown >= max_items:
            break
        owner_text = ", ".join([
            f"{get_user_display_name(uid) if not str(uid).startswith('web_') else uid} ({uid}) — {expiry}"
            for uid, expiry in owners[:3]
        ])
        lines.append(f"• `{email}` → {owner_text}")
        shown += 1
    extra = len(duplicates) - shown
    if extra > 0:
        lines.append(f"• ... and {extra} more duplicate email(s)")
    return "\n".join(lines)