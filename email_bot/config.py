"""Imports, environment validation, logging, data directory, and shared runtime state.

Loaded by app.py into one shared runtime context.
"""

import os
import sys
import logging
import imaplib
import email
from email.header import decode_header
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pytz
import re
import threading
import time
import html
import concurrent.futures

# Load environment variables
load_dotenv()
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
ADMIN_ID = os.getenv("ADMIN_ID")
ADMIN_CHANNEL_ID = os.getenv("ADMIN_CHANNEL_ID", "").strip()
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "").strip()

# IMAP credentials may also be provided at login time, so they are optional here.
try:
    ADMIN_ID = int(ADMIN_ID or 0)
except ValueError:
    raise ValueError("ADMIN_ID must be a valid integer")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ==============================================================================
# DATA STORAGE CONFIGURATION
# ==============================================================================

# Determine the data directory
if os.getenv('RAILWAY_VOLUME_MOUNT_PATH') and os.path.isdir(os.getenv('RAILWAY_VOLUME_MOUNT_PATH')):
    DATA_DIR = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
elif os.path.exists('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    logger.warning(f"No persistent volume found. Falling back to local directory: {DATA_DIR}")

os.makedirs(DATA_DIR, exist_ok=True)

def verify_data_directory():
    """Verify that the data directory is writable and ready."""
    test_file = os.path.join(DATA_DIR, "write_test.tmp")
    try:
        with open(test_file, 'w') as f:
            f.write("test")
        os.remove(test_file)
        logger.info(f"Data directory is writable and configured at: {DATA_DIR}")
        return True
    except Exception as e:
        logger.error(f"FATAL: Data directory '{DATA_DIR}' is not writable: {e}")
        return False

# ==============================================================================
# STATE INITIALIZATION
# ==============================================================================

# ==============================================================================
# STATE, CONSTANTS & RUNTIME DICTIONARIES
# ==============================================================================

APPROVED_USERS = {
    ADMIN_ID: {
        "permissions": ["Household", "Reset", "Login Code", "Verification Code", "Verification Code After Login", "Verify Email", "TV Login"],
        "approved_by": ADMIN_ID,
        "name": "Super Admin"
    }
}

SUB_ADMIN_USERS = set()
SUB_ADMIN_ASSIGNMENTS = {}
USER_EMAIL_ASSIGNMENTS = {}
ADMIN_CAN_EDIT_EXPIRY = {}

APPROVED_URLS = [
    "https://www.netflix.com/account/travel/",
    "https://www.netflix.com/account/update-primary-location?",
    "https://www.netflix.com/account/confirmdevice?",
    "https://www.netflix.com/password?",
    "https://www.netflix.com/verifyemail",
    "https://www.netflix.com/ilum?"
]

expiry_renewal_state = {}
RENEWAL_DECISIONS = {}
_expiry_reminder_thread_started = False
_expiry_reminder_last_run_slot = None
_expiry_channel_report_last_run_date = None

IST = pytz.timezone("Asia/Kolkata")
UTC = pytz.UTC
DATE_FORMAT = "%Y-%m-%d"
DEFAULT_EXPIRY_DAYS = 30

MAX_EMAILS_TO_DISPLAY = 50
EMAILS_PER_MANAGEMENT_PAGE = 50
MAX_INPUT_LENGTH = 4000
MAX_EMAILS_PER_MESSAGE = int(os.getenv("MAX_EMAILS_PER_MESSAGE", "20"))
MAX_ADMIN_EMAILS_PER_MESSAGE = int(os.getenv("MAX_ADMIN_EMAILS_PER_MESSAGE", "500"))
RATE_LIMIT_WINDOW_SECONDS = 60
RATE_LIMIT_MAX_REQUESTS = 30

STATE_LOCK = threading.Lock()
SQLITE_DB_PATH = os.path.join(DATA_DIR, "email_bot.sqlite3")
SQLITE_READY = False
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))