# Unified email-management configuration

The unified admin flow uses numeric Telegram IDs and `web_<id>` Web IDs. No
additional environment variable is required, but persistent storage must be
configured for both `USER_EMAIL_ASSIGNMENTS` and `WEB_USER_EMAIL_ASSIGNMENTS`.
Web-only accounts do not require a Telegram chat or notification setting.
Cross-backend duplicate detection requires both assignment stores to remain on
the configured persistent storage.

# 🔐 Environment Variables Guide (ENV.md)

This guide explains each variable in `.env` file in detail.

**Quick tip:** Copy `.env.example` to `.env` and fill in the values using this guide.

---

## 📋 Table of Contents

- [Required Variables](#-required-variables)
- [Recommended Variables](#-recommended-variables)
- [Web Admin Variables](#-web-admin-variables)
- [Optional Variables](#-optional-variables)
- [Setup Checklist](#-setup-checklist)

---

## 🔴 Required Variables

These variables are **REQUIRED**. The bot won't work without them!

### `BOT_TOKEN`

**What it is:** Your Telegram Bot's authentication token

**Format:** `123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij`

**How to get:**
1. Open Telegram
2. Search for **@BotFather**
3. Send `/newbot`
4. Follow the instructions:
   - Give your bot a name (example: "Gmail Forwarding Bot")
   - Give your bot a username (example: "gmail_forward_bot")
5. @BotFather will send you a token - copy it exactly

**Example:**
```env
BOT_TOKEN=987654321:XYZabcdefghijklmnopqrstuvwxyz1234567
```

**Note:** This token is like a password for your bot. Never share it publicly!

---

### `EMAIL_USER`

**What it is:** The Gmail address that will be shared/forwarded

**Format:** `your-email@gmail.com`

**Examples:**
- `netflix.shared@gmail.com`
- `support@company.com`
- `shared.account@gmail.com`

**Important:**
- Must be a valid Gmail address
- This email's inbox will be monitored
- Users can request access to view emails from this account

**Example:**
```env
EMAIL_USER=netflix.shared@gmail.com
```

---

### `EMAIL_PASS`

**What it is:** The password to access the Gmail account

**⚠️ CRITICAL:** This must be an **app-specific password**, NOT your regular Gmail password!

**Why?** Gmail requires special app passwords for security. Regular passwords won't work.

**How to get app-specific password:**

1. **Enable 2-Factor Authentication (if not already done):**
   - Go to [myaccount.google.com/security](https://myaccount.google.com/security)
   - Find "2-Step Verification"
   - Follow instructions to enable it

2. **Generate App Password:**
   - Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - You might need to log in again
   - Select "Mail" from the dropdown
   - Select "Windows Computer" (or your OS)
   - Click "Generate"
   - Gmail will show a 16-character password with spaces
   - Copy it exactly (including spaces!)

**Format:** `abcd efgh ijkl mnop` (with spaces)

**Example:**
```env
EMAIL_PASS=qwer tyui asdf ghjk
```

**Troubleshooting:**
- If you see "Login failed" error, this password is wrong
- Make sure you used "app-specific password", not regular password
- Make sure 2FA is enabled on Gmail
- If you lost the password, generate a new one at apppasswords

---

### `ADMIN_ID`

**What it is:** Your Telegram user ID (gives you admin access to the bot)

**Format:** Just numbers, example: `123456789`

**How to get:**
1. Open Telegram
2. Search for **@userinfobot**
3. Send any message to it
4. It will reply with your ID in the format: `Your ID: 123456789`
5. Copy the number

**Example:**
```env
ADMIN_ID=987654321
```

**Note:** Only you (with this ID) can use admin commands like `/admin`, `/approve`, `/backup`

---

## 🟠 Recommended Variables

These are **highly recommended** for security and functionality.

### `FLASK_SECRET_KEY`

**What it is:** A secret key that encrypts your web dashboard login sessions

**Why needed:** Without this, anyone could hijack your web dashboard session

**Format:** Long random string of letters and numbers

**How to generate:**

**Windows PowerShell:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Mac/Linux Terminal:**
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

This will print something like:
```
a7f3b8c2d9e4f1a6b3c8d7e2f9a4b1c6d3e8f7a2b9c4d1e6f3a8b5c0d7e4
```

**Example:**
```env
FLASK_SECRET_KEY=a7f3b8c2d9e4f1a6b3c8d7e2f9a4b1c6d3e8f7a2b9c4d1e6f3a8b5c0d7e4
```

**⚠️ Important:**
- Generate a NEW one (don't use the example!)
- Keep it secret
- Don't share it
- Use different one for production

---

### `FLASK_PORT`

**What it is:** The port number for the web dashboard

**Format:** A number like `5000`, `8000`, `3000`

**Default:** `5000`

**How to use:**
- Default: `http://localhost:5000`
- Custom: `http://localhost:8000` (if you set port to 8000)

**When to change:**
- If you get error "Address already in use: ('0.0.0.0', 5000)"
- Try: `FLASK_PORT=8000` or `FLASK_PORT=3000`

**Example:**
```env
FLASK_PORT=5000
```

---

## 🔵 Web Admin Variables

These create the first admin account for the web dashboard.

### `WEB_ADMIN_USERNAME`

**What it is:** Username to log into web dashboard

**Format:** Text, no spaces (example: `admin`, `yourname`)

**Default:** `admin`

**Example:**
```env
WEB_ADMIN_USERNAME=admin
```

**Note:** Only used if no web users exist (first time setup)

---

### `WEB_ADMIN_PASSWORD`

**What it is:** Password to log into web dashboard

**Format:** Any text (can have spaces, special characters)

**⚠️ SECURITY WARNING:**
- Change from `admin123` after first login!
- Use something strong: `MySecure@Pass123!`
- Don't use obvious passwords: `password`, `123456`, `admin`

**Example:**
```env
WEB_ADMIN_PASSWORD=MySecure@Pass123!
```

---

### `WEB_ADMIN_TELEGRAM_ID`

**What it is:** Your Telegram ID to send admin notifications (optional)

**Format:** Just numbers, example: `123456789`

**Purpose:** When something important happens, bot sends you a Telegram message

**Leave blank if:** You don't want Telegram notifications

**How to get:** Same as `ADMIN_ID` - message @userinfobot

**Example:**
```env
WEB_ADMIN_TELEGRAM_ID=987654321
```

---

## 🟢 Optional Variables

These are optional and can be left blank to disable features.

### `ADMIN_CHANNEL_ID`

**What it is:** A Telegram channel where the bot sends admin notifications

**Format:** Negative number like `-1001234567890`

**Purpose:**
- Get notifications when users request access
- Broadcast messages to channel
- Archive important messages

**Leave blank to:** Disable channel notifications

**How to get:**

1. **Create a Telegram channel:**
   - Open Telegram
   - Click "+" → "New Channel"
   - Choose name, description
   - Set to "Private" if you want only you to see it

2. **Add your bot to channel:**
   - Go to channel settings
   - Add members
   - Search for your bot name
   - Add it with admin privileges

3. **Find channel ID:**
   - Send any message in the channel
   - Go to @RawDataBot
   - Send `/start`
   - Forward the message from your channel to @RawDataBot
   - It will show your channel ID
   - Format will be: `-1001234567890`

**Example:**
```env
ADMIN_CHANNEL_ID=-1001234567890
```

---

### `PUBLIC_API_URL`

**What it is:** The public URL where your bot is hosted

**Format:** Full URL, example: `https://my-bot.railway.app`

**When needed:**
- You're deploying to Railway, Heroku, etc.
- You want users to access dashboard from outside
- You need to share a public link

**Leave blank if:** Using locally only

**Examples:**

For Railway:
```env
PUBLIC_API_URL=https://gmail-bot-production.up.railway.app
```

For Heroku:
```env
PUBLIC_API_URL=https://my-gmail-bot.herokuapp.com
```

---

### `USE_PREMIUM_EMOJI`

**What it is:** Use fancy emojis in Telegram messages

**Format:** `true` or `false`

**Purpose:**
- `true` = Fancy animated emojis (looks nicer)
- `false` = Basic emojis (compatible everywhere)

**Default:** `false` (works everywhere)

**Example:**
```env
USE_PREMIUM_EMOJI=false
```

---

## ✅ Setup Checklist

Follow this checklist to set up your `.env` file:

```
REQUIRED VARIABLES:
  [ ] BOT_TOKEN
      - Get from @BotFather on Telegram
      - Looks like: 123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ...

  [ ] EMAIL_USER
      - Your Gmail address
      - Example: netflix.shared@gmail.com

  [ ] EMAIL_PASS
      - App-specific password from myaccount.google.com/apppasswords
      - NOT your regular Gmail password!
      - Includes spaces: abcd efgh ijkl mnop

  [ ] ADMIN_ID
      - Your Telegram user ID from @userinfobot
      - Just numbers: 987654321

RECOMMENDED VARIABLES:
  [ ] FLASK_SECRET_KEY
      - Generate with: python -c "import secrets; print(secrets.token_hex(32))"
      - Don't use the example from .env.example

  [ ] FLASK_PORT
      - Default: 5000
      - Change if port 5000 is already in use

WEB ADMIN VARIABLES:
  [ ] WEB_ADMIN_USERNAME
      - Default: admin

  [ ] WEB_ADMIN_PASSWORD
      - Change from admin123!
      - Use something strong

  [ ] WEB_ADMIN_TELEGRAM_ID (optional)
      - For admin notifications

OPTIONAL VARIABLES:
  [ ] ADMIN_CHANNEL_ID
      - For channel notifications (leave blank if not needed)

  [ ] PUBLIC_API_URL
      - For deployed bots (leave blank if local only)

  [ ] USE_PREMIUM_EMOJI
      - true or false (default: false)
```

---

## 🔒 Security Tips

1. **Never share `.env` file**
   - It contains secrets
   - Keep it private

2. **Don't commit `.env` to GitHub**
   - Make sure `.gitignore` includes `.env`
   - Use `.env.example` as template instead

3. **Use app-specific passwords**
   - Never use your regular Gmail password
   - Enable 2FA on Gmail

4. **Change default web passwords**
   - Don't keep `admin123`
   - Use strong passwords

5. **Keep tokens secret**
   - Don't share BOT_TOKEN
   - Don't share FLASK_SECRET_KEY
   - Don't share ADMIN_ID

---

## ❓ Common Questions

### Q: Do I need all variables?

**A:** No. Only REQUIRED variables are mandatory. RECOMMENDED and OPTIONAL can be left blank.

---

### Q: What if I lose my BOT_TOKEN?

**A:** Message @BotFather `/mybots` and select your bot to see the token again.

---

### Q: Can I change these values later?

**A:** Yes! Just edit `.env` and restart the bot: `python app.py`

---

### Q: What if I use wrong EMAIL_PASS?

**A:** You'll get error "Gmail login failed". Generate a new app-specific password and update `.env`.

---

### Q: How do I reset my WEB_ADMIN_PASSWORD?

**A:**
- Stop the bot
- Delete `data/web_users.db`
- Restart bot
- It will reset to default (WEB_ADMIN_PASSWORD value)

---

## 📞 Still Need Help?

- See [README.md](README.md) for general guide
- See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common problems
- See [QUICK_START.md](QUICK_START.md) for quick setup
