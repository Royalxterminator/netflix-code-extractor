from email_bot.config import EMAIL_USER, EMAIL_PASS, logger, IST
from email_bot.utils import clean_urls
from email_bot.extractors import extract_account_region, extract_login_code, extract_verification_code, extract_verification_code_after_login, is_verification_code_after_login, extract_reset_link, extract_household_links, extract_verify_email_link, extract_tv_login_link, FLAG_EMOJIS
import imaplib, email, html, os, re, socket, time, concurrent.futures
from datetime import datetime, timedelta
import pytz
from email.header import decode_header, make_header


def _to_header_addresses(message):
    """Return normalized recipient addresses from common delivery headers."""
    addresses = set()
    for header_name in ("To", "Cc", "Delivered-To", "X-Original-To"):
        for raw_value in message.get_all(header_name, []):
            try:
                decoded_value = str(make_header(decode_header(raw_value)))
            except (TypeError, ValueError):
                decoded_value = str(raw_value)
            addresses.update(
                address.strip().lower()
                for _display_name, address in email.utils.getaddresses([decoded_value])
                if address and "@" in address
            )
    return addresses


def _to_header_matches(message, receiver_email):
    """Check the requested mailbox against delivery and recipient headers."""
    receiver = str(receiver_email).strip().lower()
    return bool(receiver) and receiver in _to_header_addresses(message)


FETCH_EXPIRY = {
    "Login Code": timedelta(minutes=15),
    "Household": timedelta(minutes=15),
    "TV Login": timedelta(minutes=15),
    "Verification Code": timedelta(minutes=15),
    "Verification Code After Login": timedelta(minutes=15),
    "Reset": timedelta(hours=24),
    "Verify Email": timedelta(hours=48),
}


def get_fetch_time_threshold(category, now=None):
    """Return the UTC cutoff for a category-specific email fetch."""
    if now is None:
        now = datetime.now(pytz.utc)
    return now - FETCH_EXPIRY.get(category, timedelta(minutes=15))


def fetch_email_for_account(receiver_email, category, imap_user=None, imap_pass=None):
    """Fetch email for a single account with retry logic."""
    imap_user = imap_user or EMAIL_USER
    imap_pass = imap_pass or EMAIL_PASS
    max_retries = 1
    imap_timeout = int(os.getenv("IMAP_TIMEOUT_SECONDS", "10"))
    for attempt in range(max_retries):
        start_time = time.time()
        imap = None
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=imap_timeout)
            imap.login(imap_user, imap_pass)

            status, _ = imap.select("inbox")
            if status != 'OK':
                raise imaplib.IMAP4.error(f"Failed to select inbox for {receiver_email}.")

            time_threshold = get_fetch_time_threshold(category)

            since_date = time_threshold.strftime("%d-%b-%Y")
            # Search recent mail broadly, then match To/Delivered-To locally.
            # This avoids Gmail timing out on complex nested HEADER queries.
            status, messages = imap.search(None, f'(SINCE "{since_date}")')

            if status != 'OK':
                raise imaplib.IMAP4.error(f"Search command failed for {receiver_email}.")

            # Only inspect the newest messages in the category window.
            email_ids = messages[0].split()[-50:]

            result_content = None
            time_info = ""
            email_found = False

            for eid in reversed(email_ids):
                status, msg_data = imap.fetch(eid, "(RFC822)")
                if not isinstance(msg_data, list):
                    continue

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])

                        # Gmail's TO search is only a preliminary filter. Validate
                        # the actual RFC To header so From, Delivered-To, mailed-by,
                        # signed-by, and other Gmail metadata cannot select a mail.
                        if not _to_header_matches(msg, receiver_email):
                            continue

                        date_ = msg.get("Date")

                        try:
                            email_date = email.utils.parsedate_to_datetime(date_)
                            if email_date.tzinfo is None:
                                email_date = email_date.replace(tzinfo=pytz.utc)
                            if email_date < time_threshold:
                                continue
                            india_time = email_date.astimezone(IST).strftime('%d/%m, %I:%M %p')
                            time_info = f"🗓 Email Time: {india_time} (India)\n"
                        except Exception:
                            time_info = "🗓 Email Time: Unavailable\n"
                            continue

                        body = ""
                        html_body = ""
                        subject = msg.get("Subject", "")
                        if msg.is_multipart():
                            for part in msg.walk():
                                if part.get_content_type() == "text/plain" and not part.get("Content-Disposition"):
                                    try:
                                        body = part.get_payload(decode=True).decode(errors="ignore")
                                        break
                                    except Exception:
                                        continue
                                if part.get_content_type() == "text/html" and not part.get("Content-Disposition"):
                                    try:
                                        html_body = part.get_payload(decode=True).decode(errors="ignore")
                                    except Exception:
                                        continue
                        else:
                            try:
                                body = msg.get_payload(decode=True).decode(errors="ignore")
                            except Exception:
                                continue

                        if not body and html_body:
                            body = html.unescape(re.sub(r"<[^>]+>", " ", html_body))

                        body = clean_urls(body)

                        region_code = extract_account_region(body)
                        region_info = ""
                        if region_code and region_code in FLAG_EMOJIS:
                            emoji, p_id, c_name = FLAG_EMOJIS[region_code]
                            region_info = f"\n🌍Account Region : {c_name}"
                        elif region_code:
                            region_info = f"\n🌍Account Region : {region_code}"

                        if category == "Login Code":
                            code = extract_login_code(body)
                            if code != "No 4-digit code found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n🔢 Login Code: {code}{region_info}")
                                email_found = True
                        elif category == "Verification Code":
                            # Post-login verification emails have their own category.
                            # Without this check, the generic six-digit extractor can
                            # return the post-login code (for example, 232323).
                            code = extract_verification_code(f"{subject}\n{body}")
                            if code != "No 6-digit verification code found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n🔢 Verification Code: {code}{region_info}\n\n⚠️ Warning: This code may allow the user to change the email or other sensitive account settings. Only share it with a trusted user.")
                                email_found = True
                        elif category == "Verification Code After Login":
                            code = extract_verification_code_after_login(subject, body)
                            if code:
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n🔢 Verification Code After Login: {code}{region_info}")
                                email_found = True
                        elif category == "Reset":
                            link = extract_reset_link(body)
                            if link != "No reset link found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n🔑 Reset Link: {link}{region_info}")
                                email_found = True
                        elif category == "Household":
                            links = extract_household_links(body)
                            if links != "No household links found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n🏠 Household Link(s):\n{links}{region_info}")
                                email_found = True
                        elif category == "Verify Email":
                            link = extract_verify_email_link(body)
                            if link != "No verification link found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n✅ Verification Link: {link}{region_info}")
                                email_found = True
                        elif category == "TV Login":
                            link = extract_tv_login_link(body)
                            if link != "No TV login link found.":
                                result_content = (f"{time_info}📧 Email: {receiver_email}\n📺 TV Login Link: {link}\n\n⚠️ Note: Link expires in 15 minutes{region_info}")
                                email_found = True

                if email_found:
                    break

            end_time = time.time()
            fetch_time = end_time - start_time

            if not email_found:
                message = "No relevant email found in the specified time frame"
                if category == "Login Code":
                    message = "No new Sign-in Mail came please check and send code again"
                elif category == "Verification Code":
                    message = "No new Verification Code Mail came in last 10 minutes, please check and send code again"
                elif category == "Verification Code After Login":
                    message = "No new Verification Code After Login Mail came in last 15 minutes, please check and send code again"
                elif category == "Household":
                    message = "No new Household code Mail came please check and send code again"
                elif category == "Reset":
                    message = "No new Reset mail came, Please send it."
                elif category == "Verify Email":
                    message = "No new Verification Email came in the last 48 hours, please check and send again."
                elif category == "TV Login":
                    message = "No new TV Login Link email came in the last 15 minutes, please check and send again."
                return message, fetch_time

            return result_content, fetch_time

        except (imaplib.IMAP4.error, ConnectionResetError, ConnectionError, TimeoutError, socket.timeout, OSError) as e:
            logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {receiver_email} with error: {e}")
            if attempt + 1 == max_retries:
                logger.error(f"All retries failed for {receiver_email}. Giving up.")
                end_time = time.time()
                return f"Error: The email server connection failed after {max_retries} attempts. Please try again later.", end_time - start_time

            delay = base_delay * (2 ** attempt)
            logger.info(f"Retrying in {delay} seconds...")
            time.sleep(delay)
        except Exception as e:
            end_time = time.time()
            logger.error(f"An unexpected error occurred while fetching email for {receiver_email}: {e}")
            return f"Error: {str(e)}", end_time - start_time

        finally:
            if imap:
                try:
                    imap.close()
                except Exception:
                    pass
                try:
                    imap.logout()
                except Exception:
                    pass

    return "Error: An unknown issue occurred in the email fetching process.", time.time() - start_time

def fetch_emails_concurrently(email_list, category, imap_user=None, imap_pass=None):
    """Process multiple emails concurrently"""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_email = {
            executor.submit(fetch_email_for_account, email, category, imap_user, imap_pass): email
            for email in email_list
        }
        for future in concurrent.futures.as_completed(future_to_email):
            email = future_to_email[future]
            try:
                results[email] = future.result()
            except Exception as e:
                results[email] = (f"Error: {str(e)}", 0)
    return results
