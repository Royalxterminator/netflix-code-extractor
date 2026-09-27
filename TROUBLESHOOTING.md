# 🔧 Troubleshooting Guide - Fixing Common Problems

This guide helps you solve problems step-by-step. **Try the solution, test, and move to the next if it doesn't work.**

## Web user missing from Telegram email management

Web-only users are shown to the super-admin with identifiers such as
`web_4`. They are intentionally not included in sub-admin email management.
Verify that the Web account is approved and that the callback uses the full
`web_<id>` value. A Web-only user may not receive Telegram notifications, but
the assignment should still persist in the Web assignment store.

## Duplicate email warning across Telegram and Web

Duplicate checks scan both assignment stores. The warning may identify owners
as a numeric Telegram ID or a `web_<id>` target. The selected target is
excluded, so existing assignments can be renewed or edited without producing
a false duplicate warning.

---

## 🔴 Bot Won't Start

### Error: `ModuleNotFoundError: No module named 'telebot'`

**Cause:** Python packages not installed

**Solution:**
```bash
# Install all required packages
pip install -r requirements.txt

# Verify installation
pip list | grep -i telebot
```

**Still not working?**
```bash
# Uninstall and reinstall
pip uninstall pyTelegramBotAPI -y
pip install pyTelegramBotAPI==4.34.0

# Test
python -c "import telebot; print('Success!')"
```

---

### Error: `FileNotFoundError: .env file not found`

**Cause:** Missing `.env` file

**Solution:**
```bash
# Copy example to .env
copy .env.example .env

# On Mac/Linux:
cp .env.example .env

# Fill in the values (open .env with a text editor)
```

**Verify:**
```bash
# Check .env exists
dir .env        # Windows
ls -la .env     # Mac/Linux
```

---

### Error: `BOT_TOKEN is not set` or `ADMIN_ID is not set`

**Cause:** Environment variables not configured

**Solution:**

1. **Open `.env` file** and check:
   ```env
   BOT_TOKEN=123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij
   ADMIN_ID=123456789
   ```

2. **Are they empty?** Get them:
   - **BOT_TOKEN:** Message @BotFather → /newbot
   - **ADMIN_ID:** Message @userinfobot

3. **Save file** and restart:
   ```bash
   python app.py
   ```

**Still not working?**
```bash
# Check if .env is being read
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('BOT_TOKEN'))"

# Should show your token, not None
```

---

### Error: `Address already in use: ('0.0.0.0', 5000)`

**Cause:** Another program using port 5000

**Solution Option 1 - Change port:**
```bash
# Edit .env and add/change:
FLASK_PORT=8000

# Now run
python app.py
# Visit http://localhost:8000
```

**Solution Option 2 - Kill the other process:**

**Windows:**
```bash
# Find process using port 5000
netstat -ano | findstr :5000

# Kill it (replace PID with the number from above)
taskkill /PID 12345 /F
```

**Mac/Linux:**
```bash
# Kill process on port 5000
lsof -ti:5000 | xargs kill -9
```

---

## 🟠 Telegram Bot Issues

### Problem: Bot doesn't respond to `/start`

**Checklist:**
1. Is the bot running? (Terminal shows "Bot is polling")
2. Is BOT_TOKEN correct? (Copy from @BotFather exactly)
3. Can you message the bot? (Try sending "hello")

**Solution:**

```bash
# Check BOT_TOKEN
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('Token:', os.getenv('BOT_TOKEN'))"

# Compare with what @BotFather gave you - must match exactly!

# If different, update .env and restart
python app.py
```

**Still not responding?**
```bash
# Check logs for errors
# Terminal should show:
# [2024-01-15 10:30:45] Bot is polling...
# [2024-01-15 10:30:46] User received message

# If no "User received message", bot isn't receiving updates
# Check your BOT_TOKEN again!
```

---

### Problem: "This bot can't be used by bots" error

**Cause:** You're trying to talk to the bot with another bot

**Solution:** Message the bot with your personal Telegram account, not another bot

---

### Problem: Bot stopped responding after a few hours

**Cause:** Connection lost (WiFi, internet, or Telegram issue)

**Solution:**
```bash
# Restart the bot
python app.py

# The bot automatically reconnects
# You should see: "Bot is polling..." again
```

**For production (deployed):** Bot auto-restarts on Railway/Heroku if it crashes.

---

## 🟡 Email Issues

### Error: `Gmail login failed` or `[IMAP4_SSL] LOGIN failed`

**Cause:** Wrong email password or 2FA not enabled

**Solution:**

1. **Enable 2-factor authentication:**
   - Go to [myaccount.google.com/security](https://myaccount.google.com/security)
   - Find "2-Step Verification" and enable it

2. **Create app-specific password:**
   - Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
   - Select "Mail" and "Windows Computer"
   - Copy the 16-character password (with spaces)
   - Update `.env`:
     ```env
     EMAIL_PASS=abcd efgh ijkl mnop
     ```

3. **Restart bot:**
   ```bash
   python app.py
   ```

**Verify it works:**
```bash
# Check logs - should show no Gmail errors
# You should see emails being fetched
```

---

### Problem: "No emails appear in the bot"

**Cause:** Emails not being fetched properly

**Solution:**

1. **Check IMAP is enabled in Gmail:**
   - Go to [myaccount.google.com/security](https://myaccount.google.com/security)
   - Look for "Less secure app access" or "IMAP"
   - Enable IMAP access

2. **Manually test email connection:**
   ```bash
   python -c "
   import imaplib
   mail = imaplib.IMAP4_SSL('imap.gmail.com')
   mail.login('your-email@gmail.com', 'your-app-password')
   status, count = mail.select('INBOX')
   print('Emails in inbox:', count[0])
   mail.logout()
   "
   ```

   If this works, the email connection is fine. Check the bot logs.

3. **Check data folder:**
   ```bash
   # On Windows:
   dir data\

   # Should show:
   # email_bot.sqlite3
   # user_email_assignments.json
   # etc.
   ```

---

### Problem: "IMAP connection timeout"

**Cause:** Gmail server took too long to respond (network issue)

**Solution:**
- Restart bot: `python app.py`
- Try a different network connection
- Wait a few minutes and try again (Gmail might be down)

---

## 🔵 Web Dashboard Issues

### Problem: "Cannot GET http://localhost:5000"

**Cause:** Web server not running or connection refused

**Solution:**

1. **Check if server is running:**
   - Terminal should show: `Running on http://localhost:5000`
   - If not, restart: `python app.py`

2. **Check correct URL:**
   ```
   ✅ Correct:   http://localhost:5000
   ❌ Wrong:     http://127.0.0.1:5000 (won't work)
   ❌ Wrong:     https://localhost:5000 (should be http, not https)
   ```

3. **Try different port:**
   - Update `.env`: `FLASK_PORT=8000`
   - Restart: `python app.py`
   - Visit: `http://localhost:8000`

---

### Problem: "Connection refused" - Can't reach localhost:5000

**Cause:** Port blocked or server not running

**Solution:**

```bash
# Make sure bot is running
# Terminal should show:
# Bot is polling...
# Running on http://localhost:5000

# If you don't see "Running on...", restart:
python app.py

# Try again in browser
http://localhost:5000
```

---

### Problem: "ERR_CONNECTION_REFUSED" or "This site can't be reached"

**Cause 1:** Flask server crashed
**Solution:** Check terminal for errors, restart `python app.py`

**Cause 2:** Wrong port configured
**Solution:** Check `.env` for FLASK_PORT, update if needed

**Cause 3:** Firewall blocking port
**Solution:** Allow Python through Windows Firewall:
- Windows Defender Firewall → Allow app through firewall
- Check Python.exe is listed

---

### Problem: "Login failed" on web dashboard

**Cause:** Wrong username/password

**Solution:**

1. **Check credentials:**
   - Username and password come from `WEB_ADMIN_USERNAME` and `WEB_ADMIN_PASSWORD` in `.env`.
   - Check your `.env`:
     ```env
   WEB_ADMIN_USERNAME=admin
   WEB_ADMIN_PASSWORD=your-strong-password
     ```

2. **Verify exact spelling and case:**
   - Passwords are case-sensitive.

3. **Clear browser cache:**
   - Ctrl+Shift+Delete
   - Select "Cookies" and "Cached images"
   - Try again

4. **Reset account (nuclear option):**
   - Stop bot: Press Ctrl+C
   - Delete: `data/web_users.db`
   - Restart: `python app.py`
   - Log in with the credentials configured in `.env`.

---

### Problem: Dashboard is slow or takes forever to load

**Cause:** Too many emails in database

**Solution:**
1. Check available disk space: `dir C:\` (Windows)
2. Check RAM usage: Task Manager → Performance
3. Limit emails fetched:
   - Edit `email_bot/config.py`
   - Look for `MAX_EMAILS` and reduce it
   - Restart bot

---

## 💾 Database Issues

### Error: "database is locked"

**Cause:** Multiple processes accessing database at once

**Solution:**
```bash
# Stop bot
# Press Ctrl+C

# Wait 5 seconds

# Delete temp lock files
# On Windows: Look for .db-wal files in data/ folder and delete them

# Restart bot
python app.py
```

---

### Problem: "Data keeps disappearing"

**Cause:** Database file not being saved

**Solution:**

1. **Check data folder exists:**
   ```bash
   # Windows
   dir data\

   # Should show email_bot.sqlite3
   ```

2. **Check file size growing:**
   ```bash
   # Windows: Right-click email_bot.sqlite3 → Properties → Size
   # Should be more than 1 KB
   ```

3. **Backup data:**
   ```bash
   # Send /backup in Telegram to admin
   # This creates a backup file
   ```

---

## 🌐 Deployment (Railway/Heroku) Issues

### Problem: "Build failed"

**Cause:** Missing `Procfile` or `requirements.txt`

**Solution:**
```bash
# Check files exist in root folder:
# ✅ Procfile (no extension)
# ✅ requirements.txt

# Push changes
git add .
git commit -m "Fix deployment files"
git push origin main

# Check Railway/Heroku logs
```

---

### Problem: Bot works locally but not on Railway

**Cause:** Environment variables not set

**Solution:**

1. **Check variables in Railway:**
   - Go to Railway dashboard
   - Click "Variables" tab
   - Verify ALL these are set:
     - BOT_TOKEN
     - EMAIL_USER
     - EMAIL_PASS
     - ADMIN_ID
     - FLASK_SECRET_KEY
     - WEB_ADMIN_USERNAME
     - WEB_ADMIN_PASSWORD

2. **Redeploy after adding variables:**
   - Click "Deploy" button
   - Wait for deployment to finish

3. **Check logs:**
   - Click "Logs" tab
   - Look for error messages
   - Share error details for help

---

### Problem: "502 Bad Gateway" on deployed site

**Cause:** Bot crashed or port configuration wrong

**Solution:**
1. Check Railway logs
2. Make sure FLASK_PORT=5000
3. Make sure FLASK_SECRET_KEY is set
4. Redeploy: Click "Deploy" in Railway

---

## 🆘 Still Not Working?

### Debug Steps:

1. **Collect information:**
   ```bash
   # What Python version?
   python --version

   # What OS?
   echo %OS%  (Windows)
   uname -a  (Mac/Linux)

   # Are requirements installed?
   pip list
   ```

2. **Check logs:**
   - Terminal output when running `python app.py`
   - `access_log.txt` in data/ folder
   - Browser console (F12 → Console tab)

3. **Describe the problem:**
   - Exact error message
   - What you did before error
   - What works and what doesn't
   - Full terminal output

---

## 📞 Getting Help

When asking for help, include:

```
1. Error message (exact, copy-paste)
2. Steps to reproduce
3. Terminal output (full log)
4. Your .env file (WITHOUT sensitive values!)
5. Operating system
6. Python version

Example:
Error: ModuleNotFoundError: No module named 'flask'
Steps: Installed requirements, ran python app.py
OS: Windows 10
Python: 3.9.5
```

---

## ✅ Quick Diagnostic Checklist

```
Internet:
  [ ] Can you access google.com?

Python:
  [ ] Python installed? (python --version)
  [ ] requirements.txt installed? (pip list | grep telebot)

.env file:
  [ ] .env exists in root folder?
  [ ] BOT_TOKEN has a value?
  [ ] EMAIL_USER has a value?
  [ ] EMAIL_PASS has a value?
  [ ] ADMIN_ID has a value?

Bot:
  [ ] Bot starts without errors? (python app.py)
  [ ] Shows "Bot is polling..." message?
  [ ] Shows "Running on http://localhost:5000"?

Telegram:
  [ ] Can message the bot?
  [ ] Bot responds to /start?

Web:
  [ ] Can access http://localhost:5000?
  [ ] Can log in with the credentials configured in `.env`?
```

---

**Good luck! You'll get it working!** 💪
