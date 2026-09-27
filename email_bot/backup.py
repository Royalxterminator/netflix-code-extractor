"""Manual and automatic backups for persistent bot data.

Daily backups run at 12:00 AM IST, and older backups are automatically
pruned to keep disk usage under control.
"""

import os
import shutil
import threading
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from email_bot.config import DATA_DIR, logger, IST, SQLITE_DB_PATH

# Number of backup folders to keep (oldest are deleted)
MAX_BACKUPS = 1

_daily_backup_thread_started = False


def _backup_directory_for_now(now=None):
    """Return a unique timestamped backup directory using Indian Standard Time."""
    now = now or datetime.now(IST)
    base_name = now.strftime("%Y%m%d_%H%M%S_IST")
    backup_root = os.path.join(DATA_DIR, "backups")
    os.makedirs(backup_root, exist_ok=True)

    backup_dir = os.path.join(backup_root, base_name)
    suffix = 1
    while os.path.exists(backup_dir):
        backup_dir = os.path.join(backup_root, f"{base_name}_{suffix}")
        suffix += 1

    os.makedirs(backup_dir, exist_ok=False)
    return backup_dir


def _backup_sqlite_database(destination_path):
    """Create a consistent SQLite snapshot while the bot is running."""
    if not os.path.exists(SQLITE_DB_PATH):
        return False

    source_conn = None
    destination_conn = None
    try:
        source_conn = sqlite3.connect(SQLITE_DB_PATH, timeout=30)
        destination_conn = sqlite3.connect(destination_path, timeout=30)
        source_conn.backup(destination_conn)
        destination_conn.commit()
        return True
    finally:
        if destination_conn is not None:
            destination_conn.close()
        if source_conn is not None:
            source_conn.close()


def _cleanup_old_backups(backup_root, keep=MAX_BACKUPS):
    """Delete oldest backup folders if more than `keep` exist."""
    if not os.path.isdir(backup_root):
        return

    items = []
    for entry in os.scandir(backup_root):
        if entry.is_dir():
            items.append((entry.name, entry.path))

    items.sort(key=lambda x: x[0])

    to_delete = len(items) - keep
    if to_delete > 0:
        for _, dir_path in items[:to_delete]:
            try:
                shutil.rmtree(dir_path, ignore_errors=True)
                logger.info(f"Deleted old backup folder: {dir_path}")
            except Exception as e:
                logger.error(f"Failed to delete old backup folder {dir_path}: {e}")


def create_data_backup():
    """Create a timestamped backup of all persistent bot data."""
    backup_dir = _backup_directory_for_now()

    backed_up_files = []

    sqlite_name = os.path.basename(SQLITE_DB_PATH)
    try:
        if _backup_sqlite_database(os.path.join(backup_dir, sqlite_name)):
            backed_up_files.append(sqlite_name)
    except Exception as exc:
        logger.error(f"Failed to include SQLite database in backup: {exc}")

    manifest = {
        "created_at_ist": datetime.now(IST).isoformat(),
        "timezone": "Asia/Kolkata",
        "files": backed_up_files,
    }
    manifest_path = os.path.join(backup_dir, "backup_manifest.txt")
    with open(manifest_path, "w", encoding="utf-8") as manifest_file:
        manifest_file.write(f"created_at_ist={manifest['created_at_ist']}\n")
        manifest_file.write(f"timezone={manifest['timezone']}\n")
        manifest_file.write(f"files={','.join(backed_up_files)}\n")
    backed_up_files.append("backup_manifest.txt")

    backup_root = os.path.join(DATA_DIR, "backups")
    _cleanup_old_backups(backup_root)

    return backed_up_files, backup_dir


def next_midnight_ist(now=None):
    """Return the next 12:00 AM boundary in Asia/Kolkata."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = IST.localize(current)
    else:
        current = current.astimezone(IST)

    tomorrow = current.date() + timedelta(days=1)
    return IST.localize(datetime.combine(tomorrow, datetime.min.time()))


def seconds_until_next_midnight_ist(now=None):
    """Return seconds until the next midnight in Indian Standard Time."""
    current = now or datetime.now(IST)
    if current.tzinfo is None:
        current = IST.localize(current)
    else:
        current = current.astimezone(IST)
    return max(1.0, (next_midnight_ist(current) - current).total_seconds())


def _daily_backup_loop():
    """Create one backup every day at 12:00 AM IST and clean up old ones."""
    while True:
        current = datetime.now(IST)
        next_run = next_midnight_ist(current)
        wait_seconds = seconds_until_next_midnight_ist(current)
        logger.info(
            "Next automatic data backup scheduled for %s",
            next_run.strftime("%Y-%m-%d %I:%M:%S %p IST"),
        )
        time.sleep(wait_seconds)

        try:
            backed_up_files, backup_dir = create_data_backup()
            logger.info(
                "Automatic midnight IST backup completed at %s with %d file(s): %s",
                backup_dir,
                len(backed_up_files),
                ", ".join(backed_up_files),
            )
        except Exception as exc:
            logger.exception(f"Automatic midnight IST backup failed: {exc}")

        time.sleep(1)


def start_daily_backup_thread():
    """Start the singleton daemon thread for 12:00 AM IST backups."""
    global _daily_backup_thread_started

    if _daily_backup_thread_started:
        return False

    _daily_backup_thread_started = True
    thread = threading.Thread(
        target=_daily_backup_loop,
        name="daily-backup-ist",
        daemon=True,
    )
    thread.start()
    logger.info("Started automatic daily backup thread for 12:00 AM IST.")
    return True