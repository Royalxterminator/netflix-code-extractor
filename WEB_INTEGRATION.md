# 🌐 Web Dashboard Integration - Complete Guide

## What This Feature Does

Web users can also be managed from Telegram's Email Management panel. The
shared flow identifies them with `web_<id>`, stores assignments in the Web
assignment table, and supports the same expiry, cancellation, duplicate
confirmation, renewal, removal, replacement, and expiry-edit operations as
Telegram users. Duplicate detection is global across both stores. Web-only
accounts have no required Telegram notification channel, so notification
failure or absence is safe.

When users are **approved on the Telegram bot**, they **automatically get web dashboard access** with:
- ✅ Auto-generated username & password
- ✅ Instant access to view their assigned emails
- ✅ Real-time sync between Telegram bot and web dashboard
- ✅ Calendar view of email expiry dates
- ✅ Change password and profile settings

---

## How It Works (Step-by-Step)

### 1️⃣ User Requests Access on Telegram

```
User: /start
Bot: Shows approval request button
User: Clicks "Request Access"
Admin: Gets notification
```

### 2️⃣ Admin Approves User

```
Admin: Clicks "Approve" button
Bot: Creates user account in bot
Bot: Auto-creates web account
Bot: Sends user web credentials
```

### 3️⃣ User Gets Web Credentials

User receives message like:
```
✅ Access Approved!
🎉 You're now approved!

📱 Telegram Access:
• Use /start command
• Search emails anytime

🌐 Web Dashboard:
• URL: http://localhost:5000
• Username: user_123456789
• Password: aB3!mX9p
```

### 4️⃣ User Logs Into Web Dashboard

```
1. Visit http://localhost:5000 (or your public URL)
2. Enter username: user_123456789
3. Enter password: aB3!mX9p (from approval message)
4. Click "Login"
5. See your assigned emails in calendar view
```

### 5️⃣ Emails Stay in Sync

```
Telegram Bot               Web Dashboard
───────────────            ─────────────
User requests email ───→   Shows result
Email assigned ────────→   Shows in calendar
Expiry date set ───────→   Shows countdown
Email renewed ──────────→  Updates calendar
```

---

## 🔐 Security Features

### Web Accounts
- ✅ **Unique username** per user (format: `user_<telegram_id>`)
- ✅ **Strong random passwords** (8 chars: uppercase, lowercase, digits, special)
- ✅ **Hashed passwords** using SHA-256
- ✅ **Linked to Telegram ID** for data sync

### Password Protection
- ✅ Users **must change password** after first login (recommended)
- ✅ Sessions expire after 30 days of inactivity
- ✅ HTTPS recommended for production

---

## 📋 How to Use the Web Dashboard

### Login
1. Go to `http://localhost:5000`
2. Enter credentials from approval message
3. Click "Login"

### View Your Emails
**"My Emails" Page:**
- Calendar showing all your assigned emails
- Color-coded by status:
  - 🟢 Green = Active (still valid)
  - 🔴 Red = Expired (needs renewal)
- Click on date to see emails expiring that day

### Manage Your Account
**"Profile" Page:**
- Change password
- View your Telegram ID
- See when account was created

### Search Emails
**Search bar:**
- Search by email address
- Filter by status (active/expired)

---

## 👨‍💼 For Admins - Account Management

The system has two separate management areas. Use the area that matches the
account type; Web-only accounts are not shown in Telegram **User Management**.

### Telegram admin panel

**💫 User Management:**
- Lists visible Telegram users (approved and pending)
- Manage Telegram approval, permissions, and Telegram-user email access

**📧 Email Management:**
- Lists Telegram users whose email assignments you can manage
- Assign, remove, replace, and update expiry dates for Telegram-user emails

### Web account management

**🌐 Web manage (Super Admin only):**
- Lists linked and Web-only accounts, including pending accounts
- Approve or set a Web account pending
- Grant or revoke Web permissions
- Open **Manage Emails** for that Web account

**Web-user email operations:**
- Add or remove assigned emails
- Edit email expiry dates
- These operations remain under **🌐 Web manage**, not Telegram **📧 Email Management**

The web dashboard also has browser-based `/users` and **Email Management**
pages for administrators. Those pages are separate from the Telegram admin
menu labels above and may be used for the web dashboard's administrative view.

### Create Backup
**"Settings" Page (Admin Only):**
- Backup all data
- Download backup file
- Restore from backup

---

## 🔗 Linking Telegram and Web

### How They're Connected
```
Telegram Bot          Web Users DB
────────────          ────────────
APPROVED_USERS ───→   web_users table
  └─ user_id    └──→  telegram_id

Telegram approval synchronization can create or approve the linked Web account,
but Web-only accounts are managed separately through **🌐 Web manage**. A Web
account's email assignments are stored in the Web-user assignment store and are
not part of the Telegram-user list in **💫 User Management**.
  └─ name       └──→  full_name
  └─ perms      └──→  role

Same Data Source:
USER_EMAIL_ASSIGNMENTS (used by both)
RENEWAL_DECISIONS (used by both)
```

### Data Flow
```
1. User approved on Telegram
   ↓
2. Web account auto-created with telegram_id
   ↓
3. User logs in with username/password
   ↓
4. Web dashboard uses telegram_id to fetch their emails
   ↓
5. Both Telegram and web show same email list
```

---

## 🔄 Keeping Data in Sync

### Automatic Sync
- ✅ Email assignments sync automatically
- ✅ Expiry dates update in real-time
- ✅ Renewals reflected instantly
- ✅ Permissions sync when changed

### Manual Sync (if needed)
If data gets out of sync:

1. **Restart the bot:**
   ```bash
   # Stop the bot (Ctrl+C)
   # Start again
   python app.py
   ```

2. **Refresh web page:**
   - Press Ctrl+F5 (hard refresh)
   - Clear browser cache

3. **Re-login to web:**
   - Log out
   - Clear cookies
   - Log back in

---

## 📊 User Roles & Permissions

### Regular User
- Can see own emails on web
- Can see own expiry dates
- Can change own password
- Cannot see other users' emails

### Sub-Admin
- Can manage assigned users
- Can view assigned users' emails
- Can assign/renew emails for users
- Cannot access super-admin features

### Super Admin
- Can manage all users
- Can view all emails
- Can approve new users
- Can create backups
- Can broadcast messages
- Can promote/demote admins

### Web Roles
```
bot User ─────→ web 'user' role
bot Sub-Admin ─→ web 'admin' role (optional)
bot Super-Admin → web 'super_admin' role
```

---

## 🆘 Troubleshooting

### Problem: "Account already exists" when approving

**Cause:** User already has a web account

**Solution:**
- User can just log in with their credentials
- If lost password, admin can delete web user and re-approve

### Problem: Can't see emails on web dashboard

**Cause 1:** Not logged in properly
- Log out and log back in
- Check telegram_id is linked

**Cause 2:** Emails not assigned in bot
- Use Telegram bot to assign emails
- Check `/accounts` shows emails

**Cause 3:** Session expired
- Clear browser cookies
- Log in again

### Problem: Web shows different emails than Telegram

**Cause:** Data sync issue

**Solution:**
1. Restart bot: `python app.py`
2. Refresh web page: `Ctrl+F5`
3. Log out and log in again

### Problem: Password doesn't work

**Cause:** Wrong password typed

**Solution:**
1. Check Telegram messages for the password
2. Password is case-sensitive
3. Admin can reset: Delete user and re-approve

---

## 📱 Mobile Access

### Does it work on mobile?
- ✅ Yes! Web dashboard is mobile-friendly
- ✅ Use Telegram app for quick access
- ✅ Use web browser for detailed calendar view

### Best Practice
- **Quick lookups:** Use Telegram bot (`/start`)
- **Detailed view:** Use web dashboard (calendar)
- **Telegram-user changes:** Use Telegram admin **💫 User Management** or
  **📧 Email Management**
- **Web-account and Web-user email changes:** Use **🌐 Web manage** in Telegram
  or the administrator pages in the web dashboard

---

## 🚀 Deployment to Production

### For Railway/Heroku

1. **Set PUBLIC_API_URL:**
   ```env
   PUBLIC_API_URL=https://your-domain.com
   ```

2. **User gets this URL in approval message**

3. **Web dashboard works on deployed URL**

### For Self-Hosted

1. **Get public IP/domain**
2. **Update .env:**
   ```env
   PUBLIC_API_URL=https://your-public-domain.com
   FLASK_PORT=5000
   ```
3. **Users visit:** `https://your-public-domain.com`

---

## 💡 Best Practices

### For Users
- ✅ Change password immediately after first login
- ✅ Use a strong password
- ✅ Check web dashboard regularly for expiring emails
- ✅ Use Telegram for quick searches

### For Admins
- ✅ Share web URL with users in approval message (done automatically)
- ✅ Configure a strong password through `WEB_ADMIN_PASSWORD`
- ✅ Monitor admin logs for suspicious activity
- ✅ Regular backups

### For Security
- ✅ Use HTTPS in production
- ✅ Strong admin passwords
- ✅ Enable 2FA on Gmail account
- ✅ Change FLASK_SECRET_KEY from default

---

## 📞 Support

**For users having issues:**
1. Check [Telegram Bot Issues](TROUBLESHOOTING.md#telegram-issues)
2. Check [Web Dashboard Issues](TROUBLESHOOTING.md#web-dashboard-issues)
3. Contact admin

**For admins:**
1. Check logs: `data/access_log.txt`
2. Check bot output for errors
3. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md)

---

## 🔮 Future Improvements

Possible additions:
- [ ] Email notifications for upcoming expirations
- [ ] Mobile app
- [ ] 2FA for web dashboard
- [ ] Email templates customization
- [ ] API for third-party integrations

---

**That's it! Users can now use both Telegram and web seamlessly!** 🎉
