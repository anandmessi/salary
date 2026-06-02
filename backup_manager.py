"""
backup_manager.py — Real-Time Backup for PayrollPro
=====================================================
Watches payroll.db for changes (mtime polling every 2 s) and automatically:
  • Writes   Documents/PayrollPro/Worker_Details.csv   (all worker details)
  • Writes   <DB_DIR>/backup.db                        (1-to-1 SQLite replica)

Usage:
    from backup_manager import BackupManager
    mgr = BackupManager()
    mgr.start()          # call once at app startup
    mgr.sync_now()       # call from UI "Sync Now" button
    mgr.stop()           # call on app close (optional)
"""

import csv
import logging
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
import sys

def _get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = _get_base_dir()
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "payroll.db")

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
POLL_INTERVAL = 2.0          # seconds between mtime checks

# CSV columns – all fields from the workers table, in display order
WORKER_CSV_COLUMNS = [
    "worker_id",
    "name",
    "designation",
    "unit",
    "skill_category",
    "joining_date",
    "active",
    "bank_account",
    "bank_name",
    "ifsc_code",
    "uan_number",
    "esic_number",
]

WORKER_CSV_HEADERS = [
    "Worker ID",
    "Full Name",
    "Designation",
    "Unit",
    "Skill Category",
    "Joining Date",
    "Active",
    "Bank Account",
    "Bank Name",
    "IFSC Code",
    "UAN Number",
    "ESIC Number",
]


class BackupManager:
    """
    Background file-watcher that keeps Worker_Details.csv and backup.db
    in sync with payroll.db at all times.
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        on_sync: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Parameters
        ----------
        db_path  : Path to the primary payroll.db (absolute or relative).
        on_sync  : Optional callback(status: str, timestamp: str) invoked on
                   the main thread after each sync so the UI can update.
        """
        self.db_path = os.path.abspath(db_path)

        # backup.db lives beside payroll.db
        db_dir = os.path.dirname(self.db_path)
        self.backup_db_path = os.path.join(db_dir, "backup.db")

        # CSV goes to Documents\PayrollPro\Worker_Details.csv
        docs = Path.home() / "Documents"
        self.csv_dir = docs / "PayrollPro"
        self.csv_path = self.csv_dir / "Worker_Details.csv"

        self._on_sync = on_sync          # UI callback
        self._last_mtime: float = 0.0
        self._last_sync_time: str = "Never"
        self._last_sync_status: str = "Not yet synced"
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()    # prevents overlapping syncs

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread. Safe to call multiple times."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        # Run an immediate sync first so backups exist right at startup
        threading.Thread(target=self._initial_sync, daemon=True).start()
        self._thread = threading.Thread(
            target=self._poll_loop, name="BackupManager", daemon=True
        )
        self._thread.start()
        logger.info("BackupManager started. Watching: %s", self.db_path)

    def stop(self) -> None:
        """Signal the background thread to stop."""
        self._stop_event.set()
        logger.info("BackupManager stopped.")

    def sync_now(self) -> None:
        """Trigger an immediate sync (e.g. from a 'Sync Now' button)."""
        threading.Thread(target=self._do_sync, daemon=True).start()

    def trigger_now(self) -> None:
        """Force an immediate backup outside the normal schedule."""
        self.sync_now()

    @property
    def csv_path_str(self) -> str:
        return str(self.csv_path)

    @property
    def backup_db_path_str(self) -> str:
        return self.backup_db_path

    @property
    def last_sync_time(self) -> str:
        return self._last_sync_time

    @property
    def last_sync_status(self) -> str:
        return self._last_sync_status

    # ── Internal ───────────────────────────────────────────────────────────────

    def _initial_sync(self) -> None:
        """Run once at startup, then update the recorded mtime."""
        self._do_sync()
        try:
            self._last_mtime = os.path.getmtime(self.db_path)
        except OSError:
            pass

    def _poll_loop(self) -> None:
        """Poll payroll.db mtime every POLL_INTERVAL seconds."""
        while not self._stop_event.is_set():
            try:
                current_mtime = os.path.getmtime(self.db_path)
                if current_mtime != self._last_mtime:
                    self._last_mtime = current_mtime
                    logger.debug("payroll.db changed — triggering sync")
                    self._do_sync()
            except OSError:
                pass  # DB temporarily unavailable (e.g. during write)
            self._stop_event.wait(POLL_INTERVAL)

    def _do_sync(self) -> None:
        """Perform both CSV and DB backups. Thread-safe."""
        with self._lock:
            errors = []

            try:
                self._sync_csv()
            except Exception as exc:
                logger.error("CSV sync failed: %s", exc, exc_info=True)
                errors.append(f"CSV: {exc}")

            try:
                self._sync_db()
            except Exception as exc:
                logger.error("DB sync failed: %s", exc, exc_info=True)
                errors.append(f"DB: {exc}")

            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._last_sync_time = ts
            if errors:
                self._last_sync_status = "⚠ Error: " + " | ".join(errors)
            else:
                self._last_sync_status = "✅ Success"

            if self._on_sync:
                try:
                    self._on_sync(self._last_sync_status, ts)
                except Exception:
                    pass

    def _sync_csv(self) -> None:
        """Export all workers to Worker_Details.csv."""
        # Ensure output directory exists
        self.csv_dir.mkdir(parents=True, exist_ok=True)

        # Read workers directly from SQLite (avoids import cycles)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            try:
                rows = conn.execute(
                    "SELECT * FROM workers ORDER BY name"
                ).fetchall()
            except sqlite3.OperationalError as e:
                if "no such table" in str(e).lower():
                    # Database not initialised yet — skip this sync cycle silently.
                    logger.debug("_sync_csv: workers table not ready yet, skipping.")
                    return
                raise
            except sqlite3.DatabaseError:
                # Corrupted index — fall back to row-by-row ROWID scan
                logger.warning("_sync_csv: SELECT * failed, falling back to ROWID scan")
                try:
                    max_rowid = conn.execute(
                        "SELECT MAX(rowid) FROM workers"
                    ).fetchone()[0] or 0
                except sqlite3.OperationalError as e2:
                    if "no such table" in str(e2).lower():
                        logger.debug("_sync_csv: workers table not ready yet, skipping.")
                        return
                    raise
                rows = []
                for rowid in range(1, max_rowid + 1):
                    try:
                        row = conn.execute(
                            "SELECT * FROM workers WHERE rowid=?", (rowid,)
                        ).fetchone()
                        if row:
                            rows.append(row)
                    except Exception:
                        pass
        finally:
            conn.close()

        # Write to a temp file first, then rename (atomic on Windows too)
        tmp_path = self.csv_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(WORKER_CSV_HEADERS)
                for row in rows:
                    r = dict(row)
                    writer.writerow(
                        [
                            r.get("worker_id", ""),
                            r.get("name", ""),
                            r.get("designation", ""),
                            r.get("unit", ""),
                            r.get("skill_category", ""),
                            r.get("joining_date", ""),
                            "Yes" if r.get("active", 1) else "No",
                            r.get("bank_account", ""),
                            r.get("bank_name", ""),
                            r.get("ifsc_code", ""),
                            r.get("uan_number", ""),
                            r.get("esic_number", ""),
                        ]
                    )
            # Atomic replace
            shutil.move(str(tmp_path), str(self.csv_path))
            logger.info(
                "CSV backup written: %s (%d workers)", self.csv_path, len(rows)
            )
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def _sync_db(self) -> None:
        """Create a consistent 1-to-1 SQLite backup at backup.db."""
        src = sqlite3.connect(self.db_path, timeout=30.0)
        try:
            dst = sqlite3.connect(self.backup_db_path, timeout=30.0)
            try:
                # sqlite3.backup() is the safest way — works even under load
                src.backup(dst, pages=0)  # pages=0 = copy all at once
                logger.info("DB backup written: %s", self.backup_db_path)
            finally:
                dst.close()
        finally:
            src.close()
