# Unified Telegram/Web email administration

After deployment, the super-admin can manage Telegram and Web-only accounts
from the Telegram Email Management panel. Web accounts use `web_<id>` target
identifiers. Keep the Web assignment store and the Telegram assignment store
on the same persistent volume/database configuration so cross-backend
duplicate detection and expiry management see the complete account set.

# 🚀 Deployment Guide - Run Your Bot 24/7 in the Cloud

Your bot is ready to deploy! This guide shows you how to run it on **Railway** (recommended) or **Heroku**.

---

## Why Deploy to Cloud?

- ✅ Bot runs 24/7 (even if your computer is off)
- ✅ Free tier available ($5-7/month after free credits)
- ✅ Easy updates and automatic restarts
- ✅ Professional hosting (good uptime)

---

## 📋 Prerequisites

Before deploying, you need:

1. **Git installed** - [git-scm.com](https://git-scm.com)
2. **GitHub account** - [github.com](https://github.com) (free)
3. **Your project on GitHub**
4. **All credentials ready** (BOT_TOKEN, EMAIL credentials, etc.)

---

## Option 1: Railway (⭐ Recommended - Easiest)

Railway is the easiest option. New users get $5 free credit/month!

### Step 1: Push Code to GitHub

```bash
# Initialize git (if not already done)
git init

# Add all files
git add .

# Commit
git commit -m "Initial bot setup"

# Create GitHub repo at github.com/new

# Add GitHub as remote
git remote add origin https://github.com/YOUR_USERNAME/gmail-bot.git

# Push code
git branch -M main
git push -u origin main
```

### Step 2: Connect Railway to GitHub

1. Go to [railway.app](https://railway.app)
2. Click **"New Project"** or **"Deploy from GitHub"**
3. Sign up with GitHub
4. Select your repo (`gmail-bot`)
5. Railway auto-detects Python + creates environment

### Step 3: Add Environment Variables

Railway reads your `.env` file. Add these variables:

1. Click **"Variables"** tab
2. Click **"+ Add Variable"**
3. Add each from your `.env`:

```
BOT_TOKEN          → your token here
EMAIL_USER         → your-email@gmail.com
EMAIL_PASS         → app-specific password
ADMIN_ID           → your user ID
FLASK_SECRET_KEY   → generated secret
SESSION_COOKIE_SECURE → true when serving the dashboard over HTTPS
WEB_ADMIN_USERNAME → admin
WEB_ADMIN_PASSWORD → a strong unique password (required)
FLASK_PORT         → 5000
```

### Step 4: Deploy

1. Click **"Deploy"** button
2. Wait for build to complete (~2 minutes)
3. See the deployment URL at the top

### Step 5: Test It

- **Telegram Bot:** Message your bot `/start` (should work!)
- **Web Dashboard:** Go to the Railway URL (shown in dashboard)
  - Login with the values configured in `WEB_ADMIN_USERNAME` and `WEB_ADMIN_PASSWORD`.

### Step 6: View Logs

Click **"Logs"** to see bot output and debug issues:

```
[2024-01-15 10:30:45] Bot is polling...
[2024-01-15 10:30:46] Flask server running...
```

### 🎉 Done! Your bot is live!

---

## Option 2: Heroku (Free Tier Removed, Not Recommended)

⚠️ **Note:** Heroku discontinued free tier in November 2022. Paid plans start at $7/month.

If you still want to use Heroku:

### Step 1: Set Up Heroku CLI

```bash
# Download from: heroku.com/products/heroku-cli

# Login to Heroku
heroku login

# Create new app
heroku create gmail-forwarding-bot
```

### Step 2: Set Environment Variables

```bash
heroku config:set BOT_TOKEN=your_token_here
heroku config:set EMAIL_USER=your-email@gmail.com
heroku config:set EMAIL_PASS=your_app_password
heroku config:set ADMIN_ID=your_id
heroku config:set FLASK_SECRET_KEY=generated_key
heroku config:set WEB_ADMIN_USERNAME=admin
heroku config:set WEB_ADMIN_PASSWORD=your-strong-unique-password
```

### Step 3: Deploy

```bash
git push heroku main
```

### Step 4: View Logs

```bash
heroku logs --tail
```

---

## Option 3: Other Platforms

### **Render.com** (Free tier with limitations)

1. Go to [render.com](https://render.com)
2. Create account → New Web Service
3. Connect GitHub repo
4. Set environment variables
5. Deploy!

**Pros:** Simple UI, good documentation
**Cons:** Free tier has limited resources

### **Replit** (Educational, not production)

1. Go to [replit.com](https://replit.com)
2. Import from GitHub
3. Add secrets (environment variables)
4. Click "Run"

**Pros:** Interactive, good for learning
**Cons:** Slow for production, can't run background tasks easily

---

## 🔄 Update Your Bot (After Deployment)

### To update code on Railway:

```bash
# Make changes locally
# ... edit files ...

# Commit and push
git add .
git commit -m "Update bot features"
git push origin main
```

Railway automatically redeploys when you push! 🎉

---

## 📊 Monitoring Your Deployed Bot

### Railway Dashboard:

- **Deployments:** See all versions
- **Logs:** Watch what's happening in real-time
- **Metrics:** CPU usage, memory, network
- **Variables:** Change settings without redeploying

### Check Bot Status:

Send your bot `/status` command:
```
Bot running since: 2024-01-15 10:30:00
Uptime: 48 hours
Users online: 12
Memory usage: 85MB
```

---

## 🚨 Common Deployment Issues

### Issue: "Build Failed"

**Solution:**
1. Check Railway logs for error message
2. Make sure `requirements.txt` is in root folder
3. Verify no syntax errors: `python -m py_compile app.py`
4. Push fix and redeploy: `git push origin main`

### Issue: "Bot doesn't respond after deployment"

**Solution:**
1. Check BOT_TOKEN is correct in Environment Variables
2. Check ADMIN_ID is your actual Telegram ID
3. View logs: `Logs` tab in Railway
4. Make sure bot was running: Look for "Bot is polling..." message

### Issue: "502 Bad Gateway" on web dashboard

**Solution:**
1. Bot might be starting. Wait 30 seconds.
2. Check FLASK_PORT is set to 5000
3. Check FLASK_SECRET_KEY is set in variables
4. View logs to see error

### Issue: "Database errors" or "Can't save data"

**Solution:**
1. Make sure DATA_DIR folder exists (auto-created)
2. Check file permissions
3. For Railway: Use `/tmp` or Railway's persistent storage
4. Check logs for specific database errors

---

## 🔐 Production Checklist

Before going live:

- [ ] Set `WEB_ADMIN_PASSWORD` to a strong unique value
- [ ] Generate new `FLASK_SECRET_KEY` (don't use example)
- [ ] Make sure `.env` is in `.gitignore` (don't commit secrets!)
- [ ] Enable 2FA on Gmail account
- [ ] Use app-specific password (not regular password)
- [ ] Test bot on Telegram
- [ ] Test web dashboard with HTTPS (if using public URL)
- [ ] Set up admin notifications channel (optional)
- [ ] Test backup functionality
- [ ] Monitor logs regularly

---

## 💰 Cost Estimation

| Service | Free Tier | Paid Tier |
|---------|-----------|-----------|
| **Railway** | $5/month credit | $0.50/GB RAM/month |
| **Heroku** | Removed | $7+/month |
| **Render** | Limited (100 hours/month) | $7+/month |
| **Replit** | Yes | $7+/month |

**Recommendation:** Railway is the best value for this bot.

---

## 📞 Getting Help

- Railway support: [railway.app/support](https://railway.app)
- See deployment logs for specific errors
- Check [README.md](README.md) for general troubleshooting
- Check [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for common issues

---

## 🎓 Next Steps

1. ✅ Deploy to Railway
2. ✅ Test bot on Telegram
3. ✅ Test web dashboard
4. ✅ Monitor logs for issues
5. ✅ Share bot with users!

**Happy deploying!** 🚀
