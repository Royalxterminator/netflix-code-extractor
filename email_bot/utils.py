from email_bot.config import (
    ADMIN_ID, ADMIN_CHANNEL_ID, logger, DATA_DIR, DATE_FORMAT, IST,
    DEFAULT_EXPIRY_DAYS, MAX_EMAILS_PER_MESSAGE, MAX_ADMIN_EMAILS_PER_MESSAGE,
    MAX_INPUT_LENGTH, APPROVED_URLS,
    UTC, RENEWAL_DECISIONS, USER_EMAIL_ASSIGNMENTS, expiry_renewal_state,
    SQLITE_DB_PATH
)
from email_bot.storage import (
    save_renewal_decisions,
    SUB_ADMIN_USERS,
    SUB_ADMIN_ASSIGNMENTS,
    save_sub_admin_users,
    save_sub_admin_assignments,
    save_approved_users,
    save_user_email_assignments
)
from email_bot.permissions import get_user_display_name, is_admin, get_manageable_users
import re, os, time, json, sqlite3
from datetime import datetime, timedelta

def parse_emails(input_text, max_emails=None):
    """Parse, validate, de-duplicate, and normalize email addresses.
    ``max_emails`` keeps expensive normal-user operations bounded. Admin bulk
    workflows use a larger, separate limit through :func:`parse_admin_emails`.
    """
    if not isinstance(input_text, str):
        return []
    try:
        limit = int(MAX_EMAILS_PER_MESSAGE if max_emails is None else max_emails)
    except (TypeError, ValueError):
        limit = MAX_EMAILS_PER_MESSAGE
    limit = max(1, limit)
    text = input_text[:MAX_INPUT_LENGTH]
    emails = []
    seen = set()
    for part in re.split(r'[,\n\s]+', text):
        cleaned = part.strip().lower()
        if (
            cleaned
            and cleaned not in seen
            and re.fullmatch(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}', cleaned)
        ):
            seen.add(cleaned)
            emails.append(cleaned)
            if len(emails) >= limit:
                break
    return emails

def parse_admin_emails(input_text):
    """Parse email lists for trusted admin bulk-management workflows."""
    return parse_emails(input_text, max_emails=MAX_ADMIN_EMAILS_PER_MESSAGE)

def clean_urls(text):
    """Replace unapproved URLs with a placeholder. Uses a single-pass approach."""
    if not isinstance(text, str):
        return text
    url_pattern = r'https?://[^\s)\]">]+'
    def _replace_url(match):
        url = match.group(0)
        if any(url.startswith(approved) for approved in APPROVED_URLS):
            return url
        return "[LINK REMOVED]"
    return re.sub(url_pattern, _replace_url, text)

def clean_url(url):
    return re.sub(r'[)\]>"\']+$', '', url)

# --- NOTIFICATION FUNCTIONS (Telegram bot runtime removed) ---
def notify_main_admin(message, parse_mode=None):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return None

def safe_send_message(chat_id, text, parse_mode=None, **kwargs):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return None

def get_admin_channel_id():
    """Return ADMIN_CHANNEL_ID as int for -100... IDs or as string for @channelusername."""
    channel_id = str(ADMIN_CHANNEL_ID or "").strip()
    if not channel_id:
        return None
    if channel_id.startswith("@"):
        return channel_id
    try:
        return int(channel_id)
    except ValueError:
        return channel_id

def send_admin_channel_update(message):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return False

def _format_channel_email_lines(emails, max_items=30):
    emails = list(emails or [])
    shown = emails[:max_items]
    lines = [f"     {email}" for email in shown]
    if len(emails) > max_items:
        lines.append(f"     ... and {len(emails) - max_items} more")
    return "\n".join(lines)

def _renewal_decision_key(user_id, expiry_date_text):
    from email_bot.expiry import normalize_expiry_date, _user_key
    expiry_date = normalize_expiry_date(expiry_date_text)
    if not expiry_date:
        return None
    return f"{_user_key(user_id)}:{expiry_date}"

def get_renewal_decision(user_id, expiry_date_text):
    key = _renewal_decision_key(user_id, expiry_date_text)
    if not key:
        return None
    data = RENEWAL_DECISIONS.get(key)
    return data if isinstance(data, dict) else None

def mark_renewal_decision(user_id, expiry_date_text, status, emails=None, by_user_id=None):
    from email_bot.expiry import _user_key
    key = _renewal_decision_key(user_id, expiry_date_text)
    if not key:
        return False
    RENEWAL_DECISIONS[key] = {
        "status": str(status),
        "emails": list(emails or []),
        "by": _user_key(by_user_id) if by_user_id is not None else _user_key(user_id),
        "updated_at": datetime.now(IST).isoformat()
    }
    save_renewal_decisions()
    return True

def has_renewal_decision(user_id, expiry_date_text):
    return get_renewal_decision(user_id, expiry_date_text) is not None

def create_expiry_renewal_token(user_id, expiry_date_text, source="manual"):
    """Create a callback token that can also be restored after restart."""
    from email_bot.expiry import normalize_expiry_date, parse_expiry_date, _user_key, get_emails_for_expiry_date
    expiry_date = normalize_expiry_date(expiry_date_text)
    if not expiry_date:
        return None
    expiry_obj = parse_expiry_date(expiry_date)
    token = f"{_user_key(user_id)}_{expiry_obj.strftime('%Y%m%d')}_{source}_{int(time.time())}_{len(expiry_renewal_state)}"
    emails = get_emails_for_expiry_date(user_id, expiry_date)
    expiry_renewal_state[token] = {
        "user_id": _user_key(user_id),
        "emails": emails,
        "expiry_date": expiry_date
    }
    return token

def send_renewal_prompt_to_user(user_id, expiry_date_text, reason="reminder", force=False):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return False

def renew_emails_for_user_on_date(user_id, expiry_date_text, admin_user_id=None):
    """Renew all emails for a user matching expiry_date_text by exactly DEFAULT_EXPIRY_DAYS."""
    from email_bot.expiry import normalize_expiry_date, get_emails_for_expiry_date, get_user_email_expiry, is_valid_expiry_date, add_exact_subscription_days, set_user_email_expiry, _user_key
    expiry_date = normalize_expiry_date(expiry_date_text)
    if not expiry_date:
        return [], ["Invalid expiry date"]
    emails = get_emails_for_expiry_date(user_id, expiry_date)
    renewed_lines = []
    skipped_lines = []
    for email in emails:
        current_expiry = get_user_email_expiry(user_id, email)
        if not current_expiry or not is_valid_expiry_date(current_expiry):
            skipped_lines.append(f"  {email}: invalid/missing expiry")
            continue
        new_expiry = add_exact_subscription_days(current_expiry, DEFAULT_EXPIRY_DAYS)
        if set_user_email_expiry(user_id, email, new_expiry):
            renewed_lines.append(f"  {email}: {current_expiry}   {new_expiry}")
        else:
            skipped_lines.append(f"  {email}: could not update")
    if renewed_lines:
        status = "admin_renewed" if admin_user_id is not None else "renewed"
        mark_renewal_decision(user_id, expiry_date, status, emails=emails, by_user_id=admin_user_id or user_id)
    return renewed_lines, skipped_lines

def send_admin_channel_update_or_owner_fallback(message):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return False

def get_expiring_today_grouped_for_admin(admin_id=None):
    """
    Return (tomorrow_str, [(user_id, [emails]), ...]) for emails expiring tomorrow.
    Kept the old function/callback names so existing buttons do not break,
    but the logic is intentionally NEXT DAY only.
    Example: if today is 2026-05-26 IST, this returns only 2026-05-27 emails.
    """
    from email_bot.expiry import today_ist, _get_user_email_map, normalize_expiry_date, _user_key
    tomorrow_str = (today_ist() + timedelta(days=1)).strftime(DATE_FORMAT)
    if admin_id is not None and is_admin(admin_id):
        user_ids = get_manageable_users(admin_id, include_self=True)
    else:
        user_ids = list(USER_EMAIL_ASSIGNMENTS.keys())
    grouped = []
    seen = set()
    for raw_user_id in user_ids:
        user_id = _user_key(raw_user_id)
        if user_id in seen:
            continue
        seen.add(user_id)
        email_map = _get_user_email_map(user_id)
        if not isinstance(email_map, dict):
            continue
        expiring_tomorrow = sorted([
            email for email, expiry in email_map.items()
            if normalize_expiry_date(expiry) == tomorrow_str
        ])
        if expiring_tomorrow:
            grouped.append((user_id, expiring_tomorrow))
    return tomorrow_str, grouped

def format_expiring_today_management_report(admin_id=None):
    """Build the Management panel text for emails expiring tomorrow only."""
    tomorrow_str, grouped = get_expiring_today_grouped_for_admin(admin_id)
    if not grouped:
        return (
            "  EXPIRING TOMORROW\n"
            f"Date: {tomorrow_str}\n\n"
            "  No emails for tomorrow."
        )
    total_emails = sum(len(emails) for _, emails in grouped)
    parts = [
        "  EXPIRING TOMORROW",
        f"Date: {tomorrow_str}",
        f"Users: {len(grouped)}",
        f"Total emails: {total_emails}",
        "",
        "  Users/emails expiring tomorrow:",
        "Use the buttons below to renew a user's expiring emails for exactly 30 days."
    ]
    for user_id, emails in grouped:
        user_display = get_user_display_name(user_id)
        decision = get_renewal_decision(user_id, tomorrow_str)
        decision_text = f"   decision: {decision.get('status')}" if decision else ""
        parts.append(f"\n  {user_display} ({user_id}){decision_text}")
        for email in emails[:50]:
            parts.append(f"  {email}")
        if len(emails) > 50:
            parts.append(f"  ... and {len(emails) - 50} more")
    return "\n".join(parts)

def get_emails_for_expiry_date(user_id, expiry_date_text):
    """Return emails for a user that currently have the provided expiry date."""
    from email_bot.expiry import normalize_expiry_date, _get_user_email_map
    expiry_date = normalize_expiry_date(expiry_date_text)
    if not expiry_date:
        return []
    email_map = _get_user_email_map(user_id)
    if not isinstance(email_map, dict):
        return []
    return sorted([
        email for email, expiry in email_map.items()
        if normalize_expiry_date(expiry) == expiry_date
    ])

def restore_expiry_reminder_from_token(token):
    """
    Rebuild renewal context from callback token after a bot restart.
    Existing tokens are like: user_id_YYYYMMDD_counter
    """
    from email_bot.expiry import _user_key, get_emails_for_expiry_date, DATE_FORMAT
    parts = str(token).split("_")
    if len(parts) < 2:
        return None
    try:
        user_id = _user_key(parts[0])
        expiry_date = datetime.strptime(parts[1], "%Y%m%d").date().strftime(DATE_FORMAT)
    except Exception:
        return None
    emails = get_emails_for_expiry_date(user_id, expiry_date)
    return {
        "user_id": user_id,
        "emails": emails,
        "expiry_date": expiry_date,
        "restored_from_token": True
    }

def send_admin_channel_expiring_today_report():
    """Post a daily admin report of users/emails expiring tomorrow only."""
    tomorrow_str, grouped = get_expiring_today_grouped_for_admin()
    if not grouped:
        send_admin_channel_update_or_owner_fallback(
            "  Daily Expiry Report\n"
            f"Tomorrow date: {tomorrow_str}\n\n"
            "  No emails for tomorrow."
        )
        return
    total_emails = sum(len(emails) for _, emails in grouped)
    message_parts = [
        "  Daily Expiry Report",
        f"Tomorrow date: {tomorrow_str}",
        f"Users expiring tomorrow: {len(grouped)}",
        f"Total emails expiring tomorrow: {total_emails}",
        "",
        "  Expiring tomorrow / not renewed yet:"
    ]
    for user_id, emails in grouped:
        user_display = get_user_display_name(user_id)
        message_parts.append(f"\n  {user_display} ({user_id})")
        message_parts.append(_format_channel_email_lines(emails))
    send_admin_channel_update_or_owner_fallback("\n".join(message_parts))

def get_all_admin_notification_ids(include_sub_admins=True):
    """Return all admins who should receive admin-level notifications."""
    recipients = {ADMIN_ID}
    if include_sub_admins:
        for sub_admin_id in SUB_ADMIN_USERS:
            try:
                recipients.add(int(sub_admin_id))
            except (TypeError, ValueError):
                logger.warning(f"Invalid sub admin ID found in SUB_ADMIN_USERS: {sub_admin_id}")
    return recipients

def notify_admins(message, reply_markup=None, parse_mode=None, include_sub_admins=True, exclude_user_id=None):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return 0

def prompt_for_email_assignment(chat_id, target_user, reason="approval"):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return None

def remove_user_completely(user_id, notify_user=True):
    """Remove a normal user from approval, email access, and sub-admin assignment lists."""
    if user_id == ADMIN_ID:
        return False
    if user_id in SUB_ADMIN_USERS:
        return False
    removed = False
    if user_id in APPROVED_USERS:
        del APPROVED_USERS[user_id]
        removed = True
    if user_id in USER_EMAIL_ASSIGNMENTS:
        del USER_EMAIL_ASSIGNMENTS[user_id]
        removed = True
    for sub_admin_id in list(SUB_ADMIN_ASSIGNMENTS.keys()):
        if user_id in SUB_ADMIN_ASSIGNMENTS[sub_admin_id]:
            SUB_ADMIN_ASSIGNMENTS[sub_admin_id].remove(user_id)
            removed = True
    return removed

def demote_sub_admin(sub_admin_id, remove_assigned_users=False):
    """Demote a sub admin and optionally remove the normal users assigned to them."""
    assigned_users = list(SUB_ADMIN_ASSIGNMENTS.get(sub_admin_id, []))
    removed_user_count = 0
    if sub_admin_id in SUB_ADMIN_USERS:
        SUB_ADMIN_USERS.remove(sub_admin_id)
    if sub_admin_id in SUB_ADMIN_ASSIGNMENTS:
        del SUB_ADMIN_ASSIGNMENTS[sub_admin_id]
    if remove_assigned_users:
        for user_id in assigned_users:
            if remove_user_completely(user_id, notify_user=True):
                removed_user_count += 1
    save_sub_admin_users()
    save_sub_admin_assignments()
    save_approved_users()
    save_user_email_assignments()
    return assigned_users, removed_user_count

def _access_identity(from_user):
    """Return a stable identity snapshot for Telegram, web, and API callers."""
    identity = getattr(from_user, 'identity', None)
    if isinstance(identity, dict):
        return {
            'user_id': int(identity.get('id') or from_user.id),
            'user_type': identity.get('type') or 'telegram',
            'username': identity.get('username'),
            'full_name': identity.get('full_name'),
            'telegram_id': identity.get('telegram_id'),
        }
    user_id = int(from_user.id)
    return {
        'user_id': user_id,
        'user_type': 'telegram',
        'username': None,
        'full_name': get_user_display_name(user_id),
        'telegram_id': user_id,
    }


def _write_access_log(identity, category, receiver_email, fetch_time, user_message_output):
    """Write a single access-log entry to the unified SQLite database."""
    try:
        with sqlite3.connect(SQLITE_DB_PATH, timeout=30) as conn:
            conn.execute(
                "INSERT INTO access_logs(user_id, category, email, fetch_time, message, created_at, user_type, username, full_name, telegram_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identity['user_id'], category, receiver_email, fetch_time, user_message_output,
                 datetime.now(UTC).isoformat(), identity['user_type'], identity['username'],
                 identity['full_name'], identity['telegram_id']),
            )
    except Exception as e:
        logger.error(f"Error writing to access log: {e}")

def _send_with_retry(chat_id, text, retries=2, delay=0.5):
    """No-op retained for compatibility (the Telegram bot runtime was removed)."""
    return None

def log_user_access(from_user, category, receiver_email, fetch_time, user_message_output):
    """Log to file and notify admins dynamically."""
    identity = _access_identity(from_user)
    user_id = identity['user_id']
    display_name = identity['full_name'] or identity['username'] or f"User {user_id}"
    now = datetime.now(UTC)
    ist_str = now.astimezone(IST).strftime('%d/%m, %I:%M %p')

    log_entry = (
        f"📧 Email: {receiver_email} | "
        f"👤 User: {display_name} ({identity['user_type']} ID: {user_id}) | "
        f"🧾 Category: {category} | "
        f"⏱️ {ist_str} (India) | "
        f"⏱️ Fetch Time: {fetch_time:.2f}s"
    )
    _write_access_log(identity, category, receiver_email, fetch_time, user_message_output)

    full_notification = (
        f"🔔 User Notification\n"
        f"📧 Email: {receiver_email}\n"
        f"👤 User: {display_name}\n"
        f"🆔 {identity['user_type'].title()} ID: {user_id}\n"
        f"🔹 Username: {identity['username'] or 'Not available'}\n"
        f"📱 Telegram ID: {identity['telegram_id'] or 'Not linked'}\n"
        f"🧾 Category: {category}\n"
        f"⏱️ {ist_str} (India)\n"
        f"⏱️ Fetch Time: {fetch_time:.2f} seconds"
    )

    admins_to_notify = set()
    if ADMIN_ID != user_id:
        admins_to_notify.add(ADMIN_ID)

    for sub_admin_id, assigned_users in SUB_ADMIN_ASSIGNMENTS.items():
        if user_id in assigned_users and sub_admin_id != user_id:
            admins_to_notify.add(sub_admin_id)

    for admin_id in admins_to_notify:
        _send_with_retry(admin_id, full_notification)