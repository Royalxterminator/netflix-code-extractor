"""Expiry-date parsing, email assignment management, sorting, counts, replacement, and access checks.

Loaded by email_bot.main into one shared runtime context.
"""

from email_bot.config import (
    logger, ADMIN_ID, DATE_FORMAT, IST, DEFAULT_EXPIRY_DAYS, STATE_LOCK,
    USER_EMAIL_ASSIGNMENTS
)
from email_bot.storage import (
    save_user_email_assignments,
    record_email_renewal_history,
    record_email_renewal_history_bulk,
    save_renewal_decisions,
    # web assignment functions
    WEB_USER_EMAIL_ASSIGNMENTS,
    get_web_user_email_expiry,
    set_web_user_email_expiry,
    remove_web_user_email,
    assign_web_user_emails_bulk,
    get_web_user_assigned_emails_with_expired,
    get_web_user_assigned_emails,
    save_web_user_email_assignments,
)
import re
from datetime import datetime, timedelta

# =============================
# EMAIL ASSIGNMENT MANAGEMENT WITH EXPIRY
# =============================

def today_ist():
    """Return today's date in Asia/Kolkata timezone."""
    return datetime.now(IST).date()


def default_expiry_str(days=DEFAULT_EXPIRY_DAYS):
    """Default subscription expiry: today + exact number of days in IST."""
    return (today_ist() + timedelta(days=days)).strftime(DATE_FORMAT)


def add_exact_subscription_days(expiry_date_text, days=DEFAULT_EXPIRY_DAYS):
    """
    Extend an expiry by an exact day count, not by calendar month.
    Example: 2026-05-25 + 30 days = 2026-06-24.
    """
    return (parse_expiry_date(expiry_date_text) + timedelta(days=days)).strftime(DATE_FORMAT)


def parse_expiry_date(date_text):
    """
    Parse supported expiry date formats into a date object.

    Accepted admin input formats:
        - YYYY-MM-DD  e.g. 2026-06-11
        - DD-MM-YYYY  e.g. 11-06-2026
        - YYYY/MM/DD  e.g. 2026/06/11
        - DD/MM/YYYY  e.g. 11/06/2026

    Internal storage always remains YYYY-MM-DD.
    """
    raw = str(date_text).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid expiry date format: {date_text}")


def normalize_expiry_date(date_text):
    """Return expiry date as YYYY-MM-DD, or None if invalid."""
    try:
        return parse_expiry_date(date_text).strftime(DATE_FORMAT)
    except Exception:
        return None


def is_valid_expiry_date(date_text):
    return normalize_expiry_date(date_text) is not None


def renew_emails_for_user_on_date(user_id, expiry_date_text, admin_user_id=None):
    """Compatibility wrapper for the renewal helper defined in utils.py."""
    from email_bot.utils import renew_emails_for_user_on_date as _renew_emails
    return _renew_emails(user_id, expiry_date_text, admin_user_id=admin_user_id)


def parse_bulk_expiry_updates(input_text):
    """
    Parse pasted bulk expiry data like:
        email@example.com 11-06-2026
        email2@example.com 2026-06-12

    Returns:
        updates: [(email_lower, normalized_yyyy_mm_dd), ...]
        invalid_lines: [line, ...]
    """
    updates = []
    invalid_lines = []

    email_pattern = r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'
    date_pattern = r'\b(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})\b'

    for raw_line in str(input_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        email_match = re.search(email_pattern, line)
        date_match = re.search(date_pattern, line)

        if not email_match and not date_match:
            continue

        if not email_match or not date_match:
            invalid_lines.append(line)
            continue

        expiry = normalize_expiry_date(date_match.group(0))
        if not expiry:
            invalid_lines.append(line)
            continue

        updates.append((email_match.group(0).lower(), expiry))

    return updates, invalid_lines


def parse_email_replacement_pairs(input_text):
    """
    Parse bulk replacement lines like:
        old@example.com new@example.com
        old2@example.com -> new2@example.com
        old3@example.com, new3@example.com

    Returns:
        replacements: [(old_email_lower, new_email_lower), ...]
        invalid_lines: [line, ...]
    """
    replacements = []
    invalid_lines = []
    email_pattern = r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'

    for raw_line in str(input_text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        emails = re.findall(email_pattern, line)

        if not emails:
            continue

        if len(emails) < 2:
            invalid_lines.append(line)
            continue

        replacements.append((emails[0].lower(), emails[1].lower()))

    return replacements, invalid_lines


def _user_key(user_id):
    try:
        return int(user_id)
    except Exception:
        return str(user_id)


def _get_user_email_map(user_id, create=False):
    """
    Return the user's email map as a dict: {email: expiry_date}.

    Always ensures the returned value is a dict, converting old list format
    if necessary. If create=True, creates an empty dict if the user doesn't exist.
    """
    key = _user_key(user_id)
    current = USER_EMAIL_ASSIGNMENTS.get(key)

    # If no entry exists
    if current is None:
        if create:
            USER_EMAIL_ASSIGNMENTS[key] = {}
            return USER_EMAIL_ASSIGNMENTS[key]
        return {}

    # If it's a list (old format), convert to dict with default expiry
    if isinstance(current, list):
        new_map = {
            str(email).strip().lower(): default_expiry_str()
            for email in current
            if str(email).strip()
        }
        USER_EMAIL_ASSIGNMENTS[key] = new_map
        save_user_email_assignments()
        return new_map

    # If it's already a dict, return it
    if isinstance(current, dict):
        return current

    # If it's something else (invalid), reset to empty dict
    logger.warning(f"Invalid email assignment format for user {key}, resetting to empty dict.")
    USER_EMAIL_ASSIGNMENTS[key] = {}
    save_user_email_assignments()
    return {}


def _email_expiry_sort_key(user_id, email):
    """Sort emails by expiry date first, then email address. Invalid/missing dates go last."""
    email_lower = str(email).strip().lower()
    expiry = _get_user_email_map(user_id).get(email_lower)
    normalized_expiry = normalize_expiry_date(expiry)

    if normalized_expiry:
        try:
            expiry_sort_value = parse_expiry_date(normalized_expiry)
        except Exception:
            expiry_sort_value = datetime.max.date()
    else:
        expiry_sort_value = datetime.max.date()

    return (expiry_sort_value, email_lower)


def sort_user_emails_by_expiry(user_id, emails):
    """Return emails in clean expiry-date order: oldest/expired first, newest later."""
    return sorted(list(emails or []), key=lambda email: _email_expiry_sort_key(user_id, email))


def get_user_assigned_emails_with_expired(user_id):
    """Get all emails assigned to a user, including expired ones."""
    return sort_user_emails_by_expiry(user_id, _get_user_email_map(user_id).keys())


def get_user_email_expiry(user_id, email):
    email_lower = str(email).strip().lower()
    return _get_user_email_map(user_id).get(email_lower)


def set_user_email_expiry(user_id, email, expiry_date):
    email_lower = str(email).strip().lower()
    expiry_date = normalize_expiry_date(expiry_date)
    if not expiry_date:
        return False

    if not expiry_date:
        return False

    email_map = _get_user_email_map(user_id)

    if email_lower not in email_map:
        return False

    old_expiry = email_map.get(email_lower)
    email_map[email_lower] = expiry_date
    save_user_email_assignments()
    if old_expiry != expiry_date:
        record_email_renewal_history(user_id, email_lower, old_expiry, expiry_date, action="expiry_update")
    return True


def is_expiry_date_expired(expiry_date_text):
    """Single source of truth for expiry status.

    An email is *expired* only when its expiry date is **strictly before**
    today (IST). An email whose expiry date is today (or in the future) is
    still considered *active*.

    Returns ``True`` if the (raw) expiry date string represents an expired
    email, ``False`` otherwise. Unparseable/empty values are treated as
    expired (safe default: hide from "active" listings).
    """
    raw = expiry_date_text
    if not raw or not str(raw).strip():
        return True
    try:
        return parse_expiry_date(raw) < today_ist()
    except Exception:
        return True


def is_user_email_expired(user_id, email):
    expiry = get_user_email_expiry(user_id, email)
    return is_expiry_date_expired(expiry)


def assign_emails_to_user_bulk(user_id, assignments):
    """Assign many emails and persist once instead of rewriting storage per email.

    ``assignments`` accepts ``(email, expiry_date)`` pairs. Invalid entries are
    returned separately and existing assignments are left unchanged.
    """
    normalized = []
    invalid = []
    seen = set()

    for item in assignments or []:
        try:
            raw_email, raw_expiry = item
        except (TypeError, ValueError):
            invalid.append(str(item))
            continue

        email_lower = str(raw_email).strip().lower()
        expiry = normalize_expiry_date(raw_expiry) if raw_expiry is not None else default_expiry_str()
        if not email_lower or not expiry:
            invalid.append(email_lower or str(raw_email))
            continue
        if email_lower in seen:
            continue
        seen.add(email_lower)
        normalized.append((email_lower, expiry))

    if not normalized:
        return [], [], invalid

    added = []
    already_assigned = []
    with STATE_LOCK:
        email_map = _get_user_email_map(user_id, create=True)
        for email_lower, expiry in normalized:
            if email_lower in email_map:
                already_assigned.append(email_lower)
                continue
            email_map[email_lower] = expiry
            added.append((email_lower, expiry))

        if added:
            save_user_email_assignments()

    if added:
        record_email_renewal_history_bulk(
            [(user_id, email, None, expiry) for email, expiry in added],
            action="assign",
        )

    return added, already_assigned, invalid


def assign_email_to_user(user_id, email, expiry_date=None):
    """Assign one email to a user; retained for compatibility."""
    expiry_date = expiry_date or default_expiry_str()
    added, _already, _invalid = assign_emails_to_user_bulk(user_id, [(email, expiry_date)])
    return bool(added)


def remove_email_from_user(user_id, email):
    """Remove an email from a user."""
    email_lower = str(email).strip().lower()
    email_map = _get_user_email_map(user_id)

    if email_lower in email_map:
        del email_map[email_lower]

        if not email_map:
            USER_EMAIL_ASSIGNMENTS.pop(_user_key(user_id), None)

        save_user_email_assignments()
        return True

    return False


def get_user_assigned_emails_count(user_id):
    """Get count of all emails assigned to user, including expired ones."""
    return len(_get_user_email_map(user_id))


def get_emails_for_expiry_date(user_id, target_date_str):
    """Return emails for a user that expire on the given date string (YYYY-MM-DD)."""
    target = str(target_date_str).strip()
    matched = []
    for email, expiry in _get_user_email_map(user_id).items():
        normalized = normalize_expiry_date(expiry)
        if normalized == target:
            matched.append(email)
    return matched


def get_user_expiring_tomorrow_emails(user_id):
    """Return this user's emails that expire tomorrow in IST."""
    tomorrow_str = (today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    return get_emails_for_expiry_date(user_id, tomorrow_str)


def get_user_expiring_tomorrow_count(user_id):
    """Get count of emails expiring tomorrow for a user."""
    return len(get_user_expiring_tomorrow_emails(user_id))


def format_user_email_expiry_summary(user_id):
    """Build a compact expiry summary for user/admin assignment messages."""
    from email_bot.messages import get_user_assigned_emails
    tomorrow_str = (today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    total_assigned = get_user_assigned_emails_count(user_id)
    active_count = len(get_user_assigned_emails(user_id))
    expired_count = max(total_assigned - active_count, 0)
    expiring_tomorrow_count = get_user_expiring_tomorrow_count(user_id)

    return (
        "📊 **Email Summary**\n"
        f"• Total Assigned: `{total_assigned}`\n"
        f"• Active: `{active_count}`\n"
        f"• Expired: `{expired_count}`\n"
        f"• Expiring Tomorrow ({tomorrow_str}): `{expiring_tomorrow_count}`"
    )


def replace_user_email(user_id, old_email, new_email):
    """
    Deletes old_email and inserts new_email with the exact same expiration date.
    """
    old_email = str(old_email).strip().lower()
    new_email = str(new_email).strip().lower()

    if not old_email or not new_email:
        return False

    email_map = _get_user_email_map(user_id)

    if old_email not in email_map:
        return False

    old_expiry = email_map[old_email]

    if old_email != new_email:
        del email_map[old_email]

    email_map[new_email] = old_expiry
    save_user_email_assignments()
    return True


# ==============================================================================
# WEB USER EMAIL ASSIGNMENT WRAPPERS (delegates to storage)
# ==============================================================================

def web_assign_emails_to_user_bulk(web_user_id, assignments):
    """Assign multiple emails to a web user. Delegates to storage."""
    return assign_web_user_emails_bulk(web_user_id, assignments)


def web_remove_email_from_user(web_user_id, email):
    """Remove an email from a web user."""
    return remove_web_user_email(web_user_id, email)


def web_set_user_email_expiry(web_user_id, email, expiry_date):
    """Set expiry date for a web user's email."""
    return set_web_user_email_expiry(web_user_id, email, expiry_date)


def web_get_user_assigned_emails_with_expired(web_user_id):
    """Get all emails (including expired) for a web user."""
    return get_web_user_assigned_emails_with_expired(web_user_id)


def web_get_user_email_expiry(web_user_id, email):
    """Get expiry date for a web user's email."""
    return get_web_user_email_expiry(web_user_id, email)


def web_get_user_assigned_emails(web_user_id):
    """Get non‑expired emails for a web user."""
    return get_web_user_assigned_emails(web_user_id)


def web_get_user_assigned_emails_count(web_user_id):
    """Count all emails assigned to a web user (including expired)."""
    return len(WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id, {}))


def web_format_user_email_expiry_summary(web_user_id):
    """Build expiry summary for a web user."""
    from email_bot.messages import get_user_assigned_emails  # only works for telegram, so we need custom
    total_assigned = web_get_user_assigned_emails_count(web_user_id)
    active = web_get_user_assigned_emails(web_user_id)
    active_count = len(active)
    expired_count = total_assigned - active_count
    # Tomorrow expiring
    tomorrow_str = (today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    expiring_tomorrow = [
        email for email, expiry in WEB_USER_EMAIL_ASSIGNMENTS.get(web_user_id, {}).items()
        if normalize_expiry_date(expiry) == tomorrow_str
    ]
    return (
        "📊 **Email Summary**\n"
        f"• Total Assigned: `{total_assigned}`\n"
        f"• Active: `{active_count}`\n"
        f"• Expired: `{expired_count}`\n"
        f"• Expiring Tomorrow ({tomorrow_str}): `{len(expiring_tomorrow)}`"
    )
