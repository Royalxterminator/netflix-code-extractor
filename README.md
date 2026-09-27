# Email Search Workspace

FastAPI web application for searching an IMAP mailbox for account emails, verification codes, login codes, reset links, household links, and TV login links.

The current application is web-only. The Telegram bot runtime and Flask stack have been removed.

## Features

- Public search dashboard at `/` and `/search`.
- Admin username/password login.
- IMAP mailbox configuration from the admin Settings page.
- Search any recipient email without email-assignment restrictions.
- Supported search categories:
  - Login Code
  - Reset Link
  - Household
  - Verify Email
  - TV Login
  - Verification Code
  - Verification Code After Login
- Optional per-category password locks configured by an admin.
- Admin dashboard with today’s searches and total searches.
- Search activity logs.
- Admin profile and API-key management.
- SQLite persistence.
- Responsive server-rendered Jinja HTML UI.
- JSON API endpoints for integrations.

## Technology Stack

- Python 3
- FastAPI
- Uvicorn
- Jinja2 templates
- Starlette `SessionMiddleware`
- SQLite via `sqlite3`
- IMAP over SSL via Python `imaplib`
- Werkzeug password hashing
- Vanilla JavaScript and CSS
- `python-dotenv` for environment configuration

## Project Structure

```text
.
├── app.py                    # FastAPI application and web routes
├── email_bot/
│   ├── api.py                # FastAPI JSON API router
│   ├── config.py             # Environment and shared configuration
│   ├── email_fetcher.py      # IMAP connection and message fetching
│   ├── extractors.py         # Code/link extraction
│   ├── storage.py            # SQLite schema and persistence helpers
│   ├── permissions.py        # Legacy account permission helpers
│   ├── expiry.py             # Legacy expiry helpers
│   └── utils.py              # Parsing, logging, and shared utilities
├── templates/                # Jinja2 HTML templates
├── static/
│   ├── css/style.css
│   └── js/app.js
├── requirements.txt
├── Procfile
└── email_bot/email_bot.sqlite3
```

## Requirements

- Python 3.10 or newer recommended
- Gmail or another IMAP-compatible mailbox
- For Gmail, use a Google App Password when 2-Step Verification is enabled

## Local Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Copy the example file:

```bash
cp .env.example .env
```

Recommended variables:

```env
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=change-this-to-a-strong-password
FLASK_SECRET_KEY=replace-with-a-long-random-secret
FLASK_PORT=5000
SESSION_COOKIE_SECURE=false
```

### IMAP credentials

IMAP credentials are configured after admin login:

1. Open `/login`.
2. Sign in with `WEB_ADMIN_USERNAME` and `WEB_ADMIN_PASSWORD`.
3. Open **Settings**.
4. Enter the IMAP email and IMAP password/app password.
5. Save the settings.

The credentials are stored in the SQLite `app_settings` table and are used by the public web search. If no Settings credentials exist, the fetcher falls back to these optional environment variables:

```env
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_app_password
```

`ADMIN_ID` is retained for legacy Telegram-account data compatibility and defaults to `0` if omitted.

Optional deployment variables:

```env
PORT=8000
PUBLIC_API_URL=https://your-domain.example
RAILWAY_VOLUME_MOUNT_PATH=/data
IMAP_TIMEOUT_SECONDS=10
```

The application accepts `FLASK_PORT` for compatibility and falls back to `PORT`, then port `5000`.

## Run the Application

```bash
python3 app.py
```

The server starts with Uvicorn. Open:

```text
http://localhost:5000/
```

If port `5000` is busy:

```bash
PORT=8765 python3 app.py
```

Then open `http://localhost:8765/`.

The Procfile uses:

```text
web: python app.py
```

## User Flow

### Public search

1. Visit `/`.
2. Select a search category.
3. Enter one or more recipient email addresses.
4. Click **Execute Search**.
5. If the category is locked, a password modal appears before the mailbox search begins.

The public search page does not require an admin login. The configured IMAP mailbox must be available in Settings or environment variables.

### Admin login

Open `/login` and use the configured web admin credentials. Public registration has been removed. Non-admin web accounts cannot log in.

After login, the admin can access:

- Dashboard
- Audit logs
- Settings
- Profile
- API guide
- Data export

The legacy Users route remains available for existing account records but is no longer shown in the main navigation.

## Category Password Locks

Category locks are configured from **Settings**.

For each category, the admin can:

- Enable or disable the lock.
- Set a category password.

When enabled:

1. The category displays a lock indicator on the search page.
2. Clicking **Execute Search** opens a password modal.
3. The search request is rejected with HTTP 403 if the password is missing or incorrect.

Lock configuration is stored as JSON in the SQLite `app_settings` table under `category_locks`.

## Search Behavior

The fetcher:

1. Connects to `imap.gmail.com` over SSL.
2. Selects the `INBOX` folder.
3. Searches recent messages within the category time window.
4. Checks the newest 50 messages.
5. Matches `To`, `Cc`, `Delivered-To`, and `X-Original-To` headers.
6. Reads plain-text or HTML message bodies.
7. Extracts the requested code or link.

Current search windows:

- Login Code: 15 minutes
- Household: 15 minutes
- TV Login: 15 minutes
- Verification Code: 15 minutes
- Verification Code After Login: 15 minutes
- Reset Link: 24 hours
- Verify Email: 48 hours

IMAP operations use a timeout controlled by `IMAP_TIMEOUT_SECONDS`, defaulting to 10 seconds. Failed connections return an error result instead of leaving the browser waiting indefinitely.

## Web Routes

Public routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/` | Public search dashboard |
| GET | `/search` | Public search dashboard |
| POST | `/api/search` | Public search request |
| GET | `/login` | Admin login |
| POST | `/login` | Admin login submission |
| GET | `/api/health` | API health check |

Admin routes:

| Method | Route | Purpose |
|---|---|---|
| GET | `/dashboard` | Search totals and recent activity |
| GET | `/logs` | Search activity log |
| GET/POST | `/settings` | IMAP settings and category locks |
| GET | `/profile` | Password and API-key management |
| GET | `/api-guide` | API documentation page |
| GET | `/download-data` | Download SQLite database ZIP |
| GET | `/logout` | End the admin session |

## JSON API

The API router is mounted under `/api`.

### Public endpoints

```text
GET /api
GET /api/health
```

### API-key endpoints

These legacy integration endpoints use `X-Api-Key` or `Authorization: Bearer <token>`:

```text
GET  /api/emails
GET  /api/permissions
POST /api/fetch
```

Example:

```bash
curl http://localhost:5000/api/health
```

API fetch requests use JSON similar to:

```json
{
  "emails": ["recipient@example.com"],
  "choice": "login_code"
}
```

The public browser search endpoint is `/api/search`; it uses the browser session CSRF token and does not require an API key.

## SQLite Data

The database is created at:

```text
email_bot/email_bot.sqlite3
```

Important tables include:

- `web_users` — admin and legacy web account records
- `access_logs` — search activity
- `app_settings` — IMAP configuration and category locks
- `api_keys` — named API keys
- Legacy Telegram/account tables retained for database compatibility

For production, mount a persistent volume and set `RAILWAY_VOLUME_MOUNT_PATH` or ensure the database directory is persistent.

## Security Notes

- Use a strong `WEB_ADMIN_PASSWORD`.
- Use a long random `FLASK_SECRET_KEY`.
- Use Gmail App Passwords instead of storing a normal Gmail password where possible.
- The IMAP password is stored in SQLite so the search service can use it. Protect the database file and its backups.
- Set `SESSION_COOKIE_SECURE=true` when serving over HTTPS.
- Do not expose the SQLite database or `.env` file publicly.
- Category lock passwords are stored in the application settings database. Protect database access accordingly.

## Troubleshooting

### Search stays on “Working…”

Check the application log and IMAP settings. The fetcher has a finite timeout and should return an error after the timeout.

```bash
```

Confirm:

- IMAP email is correct.
- Gmail App Password is correct.
- IMAP is enabled for the mailbox.
- The recipient address is correct.
- The email was received inside the category time window.

### Verification code is not found

- Use the **Verification Code** category for normal verification messages.
- Send a fresh code and search within 15 minutes.
- Confirm the recipient appears in `To`, `Cc`, `Delivered-To`, or `X-Original-To`.
- Check that the configured mailbox is the mailbox receiving the message.

### Category password rejected

Open **Settings**, disable and re-enable the category lock, set the password again, save, and refresh the public search page.

### Port already in use

```bash
PORT=8765 python3 app.py
```

## Development Verification

Compile all Python modules:

```bash
python3 -m py_compile app.py email_bot/*.py
```

Check the running service:

```bash
curl http://localhost:5000/api/health
```

Expected response:

```json
{"status":"ok"}
```
