"""Shared email access helpers (Telegram bot runtime removed)."""


def get_user_assigned_emails(user_id):
    """Get list of non-expired emails assigned to a user, sorted by expiry date."""
    from email_bot.expiry import _get_user_email_map, is_user_email_expired, sort_user_emails_by_expiry

    active_emails = [
        email
        for email in _get_user_email_map(user_id).keys()
        if not is_user_email_expired(user_id, email)
    ]
    return sort_user_emails_by_expiry(user_id, active_emails)


def get_user_assigned_emails_with_expired(user_id):
    """Get all assigned emails, including expired ones, sorted by expiry date."""
    from email_bot.expiry import _get_user_email_map, sort_user_emails_by_expiry

    return sort_user_emails_by_expiry(user_id, _get_user_email_map(user_id).keys())


def can_user_access_email(user_id, email):
    """Check if user is allowed to access this email and it is not expired."""
    from email_bot.permissions import is_super_admin
    from email_bot.expiry import _get_user_email_map, is_user_email_expired

    if is_super_admin(user_id):
        return True

    email_lower = str(email).strip().lower()
    email_map = _get_user_email_map(user_id)

    if email_lower not in email_map:
        return False

    return not is_user_email_expired(user_id, email_lower)
