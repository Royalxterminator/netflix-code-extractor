# Unified admin email flow

Open Telegram **Admin → Email Management** to assign or manage either backend.
Select a numeric Telegram user or a Web target such as `web_4`. Assignment,
expiry, renewal, removal, replacement, cancellation, and duplicate confirmation
use the selected backend; duplicate warnings include both Telegram and Web
owners through cross-backend duplicate detection. Only the super-admin can
manage Web-only accounts.

# ⚡ Quick Start Guide - 5 Minutes to Launch

> **For experienced developers who want to get running NOW!**

If you want detailed explanations, read [README.md](README.md) instead.

---

## 1️⃣ Prerequisites (2 minutes)

```bash
# Install Python 3.8+
# Download from: python.org

# Install dependencies
pip install -r requirements.txt
```

---

## 2️⃣ Get Credentials (2 minutes)

| Credential | Where to Get |
|-----------|-------------|
| **BOT_TOKEN** | Message @BotFather → /newbot → copy token |
| **EMAIL_USER** | Your Gmail address |
| **EMAIL_PASS** | [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) (need 2FA enabled) |
| **ADMIN_ID** | Send any message to @userinfobot |
| **FLASK_SECRET_KEY** | `python -c "import secrets; print(secrets.token_hex(32))"` |

---

## 3️⃣ Create `.env` File (1 minute)

Copy `.env.example` to `.env` and fill it:

```env
BOT_TOKEN=your_token_here
EMAIL_USER=your-email@gmail.com
EMAIL_PASS=your-app-password
ADMIN_ID=your_id_here
FLASK_SECRET_KEY=generated-key-here
FLASK_PORT=5000
WEB_ADMIN_USERNAME=admin
WEB_ADMIN_PASSWORD=change-this-to-a-strong-password
```

---

## 4️⃣ Run It! (1 minute)

```bash
python app.py
```

You should see:
```
Bot is polling...
Running on http://localhost:5000
```

---

## 5️⃣ Test It Out (1 minute)

✅ **On Telegram:** Message your bot `/start`
✅ **On Web:** Go to `http://localhost:5000` and log in with the credentials configured in `.env`

---

## 🚀 Deploy to Railway (Bonus - 5 minutes)

1. Push code to GitHub
2. Go to [railway.app](https://railway.app)
3. Create new project → Deploy from GitHub
4. Add environment variables from `.env`
5. Done! Bot runs 24/7

---

## ❌ Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| ModuleNotFoundError | `pip install -r requirements.txt` |
| Bot not responding | Check BOT_TOKEN in `.env` |
| Gmail login failed | Use app-specific password, enable 2FA |
| Port 5000 in use | Change `FLASK_PORT` to 8000 or 3000 |
| Can't access web dashboard | Make sure server is running and go to `http://localhost:5000` |

---

## 📖 Need More Help?

- Full guide: [README.md](README.md)
- Deployment: [DEPLOYMENT.md](DEPLOYMENT.md)
- Troubleshooting: [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

**That's it! You're done!** 🎉
