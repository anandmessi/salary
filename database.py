"""
database.py — SQLite Database Layer for PayrollPro
===================================================
All public functions accept an optional db_path argument.
When db_path=None (the default), get_active_db_path() is called at
call-time so that LanSync can switch the DB to a UNC path after startup.

When running as a LAN CLIENT, set_sync_client() injects a SyncClient
instance and all public functions are transparently routed over HTTP.
"""
import sqlite3
import json
import logging
import threading
from contextlib import contextmanager
from typing import List, Optional, Dict

_db_local = threading.local()

from schema import (
    SkillWage, Worker, AttendanceRecord, CompanyConfig, SKILL_CATEGORIES,
    DB_PATH, get_active_db_path,
)
from db_cache import cache

logger = logging.getLogger(__name__)


def _clean_num_str(val: str) -> str:
    """Fix values stored as scientific notation e.g. '1.23456e+15'.
    Safe no-op for normal strings like 'SBIN0001234'."""
    if not val:
        return val or ''
    v = val.strip()
    if 'e' in v or 'E' in v:
        try:
            f = float(v)
            if f == int(f):
                return str(int(f))
        except (ValueError, OverflowError):
            pass
    return v


# ── LAN CLIENT dispatch ────────────────────────────────────────────────────────
# When set, all public DB calls are forwarded to the SyncClient (HTTP proxy).
_sync_client = None   # type: Optional["sync_client.SyncClient"]


def set_sync_client(client) -> None:
    """Inject a SyncClient so all DB calls are proxied over HTTP (CLIENT mode)."""
    global _sync_client
    _sync_client = client
    logger.info("SyncClient injected — DB calls will go through HTTP proxy")


def get_sync_client():
    """Return the active SyncClient, or None if running locally."""
    return _sync_client


def _notify_host_change():
    """Bump the sync-server write-version so connected clients detect the change.

    Called at the end of every local write in HOST / standalone mode.
    Safe to call when the sync server is not running — the import will fail
    silently and the call is a no-op.

    Uses notify_callback=False so the HOST does not refresh its own UI for
    data it just wrote locally.  The HOST UI refresh callback is reserved for
    CLIENT-originated writes that arrive via the Flask API handlers.
    """
    try:
        import sync_server as _ss
        _ss._bump_change(notify_callback=False)
    except Exception:
        pass


# ── Runtime DB path resolver ───────────────────────────────────────────────────
def _db(db_path):
    """Return db_path unchanged, or the current active runtime path if None."""
    return get_active_db_path() if db_path is None else db_path


# ── PRAGMAs applied once at first connection ───────────────────────────────────
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-8000",       # 8 MB page cache
    "PRAGMA mmap_size=134217728",    # 128 MB memory-mapped I/O
    "PRAGMA temp_store=MEMORY",      # temp tables in RAM
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",      # 5 s wait on locks — safe for LAN multi-writer
)


@contextmanager
def get_conn(db_path=None):
    db_path = _db(db_path)
    conn = getattr(_db_local, 'conn', None)
    if conn is None or getattr(_db_local, 'path', None) != db_path:
        conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        for pragma in _PRAGMAS:
            conn.execute(pragma)
        _db_local.conn = conn
        _db_local.path = db_path
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def close_thread_conn():
    """Close and discard the thread-local SQLite connection.

    Call this at the end of every background thread (FetchThread.run finally block)
    to avoid file-handle leaks when many short-lived threads are created.
    """
    conn = getattr(_db_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        _db_local.conn = None
        _db_local.path = None


DDL = """
CREATE TABLE IF NOT EXISTS units (
    name TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS skill_wages (
    skill_category TEXT PRIMARY KEY,
    daily_wage     REAL NOT NULL DEFAULT 0,
    ot_rate        REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS banks (
    name      TEXT PRIMARY KEY,
    ifsc_code TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    designation    TEXT NOT NULL DEFAULT '',
    bank_account   TEXT DEFAULT '',
    bank_name      TEXT DEFAULT '',
    ifsc_code      TEXT DEFAULT '',
    uan_number     TEXT DEFAULT '',
    esic_number    TEXT DEFAULT '',
    joining_date   TEXT DEFAULT '',
    active         INTEGER NOT NULL DEFAULT 1,
    unit           TEXT NOT NULL DEFAULT '',
    skill_category TEXT NOT NULL DEFAULT 'Unskilled'
);

CREATE TABLE IF NOT EXISTS attendance (
    record_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id         TEXT NOT NULL,
    month             TEXT NOT NULL,
    days_present      REAL DEFAULT 0,
    basic_wages       REAL DEFAULT 0,
    da                REAL DEFAULT 0,
    hra               REAL DEFAULT 0,
    cca               REAL DEFAULT 0,
    overtime_hours    REAL DEFAULT 0,
    arrears           REAL DEFAULT 0,
    advances_pay      REAL DEFAULT 0,
    nfh_wages         REAL DEFAULT 0,
    maternity_benefit REAL DEFAULT 0,
    leave_wages       REAL DEFAULT 0,
    bonus             REAL DEFAULT 0,
    other_allowances  REAL DEFAULT 0,
    epf_override      REAL DEFAULT 0,
    esi_override      REAL DEFAULT 0,
    esi_applicable    INTEGER DEFAULT 1,
    welfare_fund      REAL DEFAULT 0,
    tds               REAL DEFAULT 0,
    profession_tax    REAL DEFAULT 0,
    advance_repayment REAL DEFAULT 0,
    fine              REAL DEFAULT 0,
    loss_damages      REAL DEFAULT 0,
    other_deductions  REAL DEFAULT 0,
    UNIQUE(worker_id, month),
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

CREATE TABLE IF NOT EXISTS payroll_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    month        TEXT NOT NULL,
    run_date     TEXT NOT NULL,
    total_gross  REAL NOT NULL,
    total_net    REAL NOT NULL,
    worker_count INTEGER NOT NULL,
    results_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def init_db(db_path=None, seed=True):
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.executescript(DDL)

        # --- MIGRATIONS ---
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]

        # Migration 1: phone_number column on workers
        if user_version < 1:
            try:
                conn.execute("ALTER TABLE workers ADD COLUMN phone_number TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA user_version = 1")

        # Migration 2: esi_applicable column on attendance
        if user_version < 2:
            try:
                conn.execute(
                    "ALTER TABLE attendance ADD COLUMN esi_applicable INTEGER DEFAULT 1"
                )
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA user_version = 2")

        # Migration 3: Backfill NULL esi_applicable to 0 (off by default)
        if user_version < 3:
            conn.execute(
                "UPDATE attendance SET esi_applicable = 0 WHERE esi_applicable IS NULL"
            )
            conn.execute("PRAGMA user_version = 3")

        # Migration 4: ESI now off-by-default — reset all rows so user opts in per worker
        if user_version < 4:
            conn.execute("UPDATE attendance SET esi_applicable = 0")
            conn.execute("PRAGMA user_version = 4")
        # ------------------

        # Seed skill_wages with all categories (0 wage — user sets real values)
        if seed:
            for cat in SKILL_CATEGORIES:
                conn.execute(
                    "INSERT OR IGNORE INTO skill_wages(skill_category, daily_wage, ot_rate)"
                    " VALUES(?,0,0)",
                    (cat,),
                )
            if (
                conn.execute(
                    "SELECT COUNT(*) FROM config WHERE key='company'"
                ).fetchone()[0]
                == 0
            ):
                conn.execute(
                    "INSERT INTO config VALUES('company',?)", (CompanyConfig().to_json(),)
                )


# ══════════════════════════════════════════════════════════════════════════════
#   SKILL WAGES
# ══════════════════════════════════════════════════════════════════════════════
def get_all_skill_wages(db_path=None) -> List[SkillWage]:
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_all_skill_wages")
        return _sync_client.get_all_skill_wages()
    db_path = _db(db_path)
    key = f"skill_wages:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM skill_wages ORDER BY skill_category"
        ).fetchall()
    result = [SkillWage(**dict(r)) for r in rows]
    cache.set(key, result)
    return result


def get_skill_wages_dict(db_path=None) -> Dict[str, SkillWage]:
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_skill_wages_dict")
        return _sync_client.get_skill_wages_dict()
    return {sw.skill_category: sw for sw in get_all_skill_wages(db_path)}


def upsert_skill_wage(sw: SkillWage, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → upsert_skill_wage(%s)", sw.skill_category)
        _sync_client.upsert_skill_wage(sw)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO skill_wages(skill_category, daily_wage, ot_rate) VALUES(?,?,?)
               ON CONFLICT(skill_category) DO UPDATE SET
               daily_wage=excluded.daily_wage, ot_rate=excluded.ot_rate""",
            (sw.skill_category, sw.daily_wage, sw.ot_rate),
        )
    cache.invalidate(f"skill_wages:{db_path}")
    _notify_host_change()


# ══════════════════════════════════════════════════════════════════════════════
#   BANKS  (preset bank names only)
# ══════════════════════════════════════════════════════════════════════════════
def get_all_banks(db_path=None) -> List[str]:
    """Return sorted list of bank name strings."""
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_all_banks")
        return _sync_client.get_all_banks()
    db_path = _db(db_path)
    key = f"banks:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT name FROM banks ORDER BY name").fetchall()
    result = [r["name"] for r in rows]
    cache.set(key, result)
    return result


def add_bank(name: str, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → add_bank(%r)", name)
        _sync_client.add_bank(name)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("INSERT INTO banks(name) VALUES(?)", (name.strip(),))
    cache.invalidate(f"banks:{db_path}")
    _notify_host_change()


def update_bank(old_name: str, new_name: str, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → update_bank(%r → %r)", old_name, new_name)
        _sync_client.update_bank(old_name, new_name)
        return
    db_path = _db(db_path)
    new = new_name.strip()
    with get_conn(db_path) as conn:
        conn.execute("UPDATE banks SET name=? WHERE name=?", (new, old_name))
        conn.execute(
            "UPDATE workers SET bank_name=? WHERE bank_name=?", (new, old_name)
        )
    cache.invalidate(
        f"banks:{db_path}",
        f"workers:{db_path}:active",
        f"workers:{db_path}:all",
    )
    _notify_host_change()


def delete_bank(name: str, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → delete_bank(%r)", name)
        _sync_client.delete_bank(name)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM banks WHERE name=?", (name,))
    cache.invalidate(f"banks:{db_path}")
    _notify_host_change()


# ══════════════════════════════════════════════════════════════════════════════
#   UNITS
# ══════════════════════════════════════════════════════════════════════════════
def get_all_units(db_path=None) -> List[str]:
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_all_units")
        return _sync_client.get_all_units()
    db_path = _db(db_path)
    key = f"units:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT name FROM units ORDER BY name").fetchall()
    result = [r["name"] for r in rows]
    cache.set(key, result)
    return result


def add_unit(name: str, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → add_unit(%r)", name)
        _sync_client.add_unit(name)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("INSERT INTO units(name) VALUES(?)", (name.strip(),))
    cache.invalidate(f"units:{db_path}")
    _notify_host_change()


def rename_unit(old_name: str, new_name: str, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → rename_unit(%r → %r)", old_name, new_name)
        _sync_client.rename_unit(old_name, new_name)
        return
    db_path = _db(db_path)
    new = new_name.strip()
    with get_conn(db_path) as conn:
        conn.execute("UPDATE units SET name=? WHERE name=?", (new, old_name))
        conn.execute("UPDATE workers SET unit=? WHERE unit=?", (new, old_name))
    cache.invalidate(
        f"units:{db_path}",
        f"workers:{db_path}:active",
        f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    _notify_host_change()


def delete_unit(name: str, db_path=None) -> int:
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → delete_unit(%r)", name)
        return _sync_client.delete_unit(name)
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM workers WHERE unit=?", (name,)
        ).fetchone()[0]
        if count > 0:
            conn.execute("UPDATE workers SET unit='' WHERE unit=?", (name,))
        conn.execute("DELETE FROM units WHERE name=?", (name,))
    cache.invalidate(
        f"units:{db_path}",
        f"workers:{db_path}:active",
        f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    _notify_host_change()
    return count


def unit_worker_count(db_path=None) -> Dict[str, int]:
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → unit_worker_count")
        return _sync_client.unit_worker_count()
    db_path = _db(db_path)
    key = f"unit_worker_count:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT b.name, COUNT(w.worker_id) as cnt "
            "FROM units b LEFT JOIN workers w ON b.name=w.unit AND w.active=1 "
            "GROUP BY b.name ORDER BY b.name"
        ).fetchall()
    result = {r["name"]: r["cnt"] for r in rows}
    cache.set(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#   WORKERS
# ══════════════════════════════════════════════════════════════════════════════
def get_all_workers(db_path=None, active_only=True):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_all_workers(active_only=%s)", active_only)
        return _sync_client.get_all_workers(active_only=active_only)
    db_path = _db(db_path)
    key = f"workers:{db_path}:{'active' if active_only else 'all'}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    sql = (
        "SELECT * FROM workers"
        + (" WHERE active=1" if active_only else "")
        + " ORDER BY name"
    )
    with get_conn(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    result = []
    for r in rows:
        w = Worker.from_dict(dict(r))
        w.bank_account = _clean_num_str(w.bank_account)
        w.ifsc_code    = _clean_num_str(w.ifsc_code)
        w.uan_number   = _clean_num_str(w.uan_number)
        w.esic_number  = _clean_num_str(w.esic_number)
        result.append(w)
    cache.set(key, result)
    return result


def get_workers_by_unit(unit, db_path=None, active_only=True):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_workers_by_unit(%r)", unit)
        return _sync_client.get_workers_by_unit(unit, active_only=active_only)
    db_path = _db(db_path)
    sql = "SELECT * FROM workers WHERE unit=?"
    if active_only:
        sql += " AND active=1"
    sql += " ORDER BY name"
    with get_conn(db_path) as conn:
        rows = conn.execute(sql, (unit,)).fetchall()
    return [Worker.from_dict(dict(r)) for r in rows]


def upsert_worker(w: Worker, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → upsert_worker(%r)", w.worker_id)
        _sync_client.upsert_worker(w)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute(
            """INSERT INTO workers
               (worker_id, name, designation, bank_account, bank_name, ifsc_code,
                uan_number, esic_number, joining_date, active, unit, skill_category)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(worker_id) DO UPDATE SET
               name=excluded.name, designation=excluded.designation,
               bank_account=excluded.bank_account, bank_name=excluded.bank_name,
               ifsc_code=excluded.ifsc_code, uan_number=excluded.uan_number,
               esic_number=excluded.esic_number, joining_date=excluded.joining_date,
               active=excluded.active, unit=excluded.unit,
               skill_category=excluded.skill_category""",
            (
                w.worker_id, w.name, w.designation, w.bank_account, w.bank_name,
                w.ifsc_code, w.uan_number, w.esic_number, w.joining_date,
                int(w.active), w.unit, w.skill_category,
            ),
        )
    cache.invalidate(
        f"workers:{db_path}:active",
        f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    _notify_host_change()


def deactivate_worker(worker_id, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → deactivate_worker(%r)", worker_id)
        _sync_client.deactivate_worker(worker_id)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("UPDATE workers SET active=0 WHERE worker_id=?", (worker_id,))
    cache.invalidate(
        f"workers:{db_path}:active", f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    _notify_host_change()


def reactivate_worker(worker_id, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → reactivate_worker(%r)", worker_id)
        _sync_client.reactivate_worker(worker_id)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("UPDATE workers SET active=1 WHERE worker_id=?", (worker_id,))
    cache.invalidate(
        f"workers:{db_path}:active", f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    _notify_host_change()


def delete_worker(worker_id, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → delete_worker(%r)", worker_id)
        _sync_client.delete_worker(worker_id)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM attendance WHERE worker_id=?", (worker_id,))
        conn.execute("DELETE FROM workers WHERE worker_id=?", (worker_id,))
    cache.invalidate(
        f"workers:{db_path}:active", f"workers:{db_path}:all",
        f"unit_worker_count:{db_path}",
    )
    cache.invalidate_prefix(f"attendance:{db_path}:")
    _notify_host_change()


def get_worker_by_id(worker_id, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_worker_by_id(%r)", worker_id)
        return _sync_client.get_worker_by_id(worker_id)
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM workers WHERE worker_id=?", (worker_id,)
        ).fetchone()
    if not row:
        return None
    w = Worker.from_dict(dict(row))
    w.bank_account = _clean_num_str(w.bank_account)
    w.ifsc_code    = _clean_num_str(w.ifsc_code)
    w.uan_number   = _clean_num_str(w.uan_number)
    w.esic_number  = _clean_num_str(w.esic_number)
    return w


def import_workers_from_csv(filepath, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → import_workers_from_csv(%r)", filepath)
        return _sync_client.import_workers_from_csv(filepath)
    db_path = _db(db_path)
    import csv

    records, errors = [], []
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 2):
            wid  = row.get("worker_id", "").strip()
            name = row.get("name", "").strip()
            if not wid or not name:
                errors.append(f"Row {i}: missing worker_id or name")
                continue
            try:
                w = Worker(
                    worker_id=wid,
                    name=name,
                    designation=row.get("designation", "").strip(),
                    bank_account=row.get("bank_account", "").strip(),
                    bank_name=row.get("bank_name", "").strip(),
                    ifsc_code=row.get("ifsc_code", "").strip(),
                    uan_number=row.get("uan_number", "").strip(),
                    esic_number=row.get("esic_number", "").strip(),
                    joining_date=row.get("joining_date", "").strip(),
                    active=str(row.get("active", "1")).strip().lower()
                    in ("1", "true", "yes", "y", "t"),
                    unit=row.get("unit", "").strip(),
                    skill_category=row.get("skill_category", "Unskilled").strip(),
                )
                records.append(w)
            except Exception as e:
                errors.append(f"Row {i}: {e}")

    if records:
        with get_conn(db_path) as conn:
            for w in records:
                conn.execute(
                    """INSERT INTO workers
                       (worker_id, name, designation, bank_account, bank_name, ifsc_code,
                        uan_number, esic_number, joining_date, active, unit, skill_category)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(worker_id) DO UPDATE SET
                       name=excluded.name, designation=excluded.designation,
                       bank_account=excluded.bank_account, bank_name=excluded.bank_name,
                       ifsc_code=excluded.ifsc_code, uan_number=excluded.uan_number,
                       esic_number=excluded.esic_number, joining_date=excluded.joining_date,
                       active=excluded.active, unit=excluded.unit,
                       skill_category=excluded.skill_category""",
                    (
                        w.worker_id, w.name, w.designation, w.bank_account, w.bank_name,
                        w.ifsc_code, w.uan_number, w.esic_number, w.joining_date,
                        int(w.active), w.unit, w.skill_category,
                    ),
                )
        cache.invalidate(
            f"workers:{db_path}:active",
            f"workers:{db_path}:all",
            f"unit_worker_count:{db_path}",
        )
        _notify_host_change()
    return {"imported": len(records), "errors": errors}


# ══════════════════════════════════════════════════════════════════════════════
#   ATTENDANCE
# ══════════════════════════════════════════════════════════════════════════════
_ATT_COLS = (
    "worker_id", "month", "days_present",
    "basic_wages", "da", "hra", "cca", "overtime_hours", "arrears",
    "advances_pay", "nfh_wages", "maternity_benefit", "leave_wages",
    "bonus", "other_allowances",
    "epf_override", "esi_override", "esi_applicable", "welfare_fund", "tds",
    "profession_tax", "advance_repayment", "fine", "loss_damages", "other_deductions",
)


def get_attendance(month, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_attendance(%r)", month)
        return _sync_client.get_attendance(month)
    db_path = _db(db_path)
    key = f"attendance:{db_path}:{month}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM attendance WHERE month=? ORDER BY worker_id", (month,)
        ).fetchall()
    result = [AttendanceRecord.from_dict(dict(r)) for r in rows]
    cache.set(key, result)
    return result


def upsert_attendance(a: AttendanceRecord, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → upsert_attendance(worker=%r, month=%r)", a.worker_id, a.month)
        _sync_client.upsert_attendance(a)
        return
    db_path = _db(db_path)
    vals = tuple(getattr(a, c) for c in _ATT_COLS)
    sets = ", ".join(f"{c}=excluded.{c}" for c in _ATT_COLS[2:])
    with get_conn(db_path) as conn:
        conn.execute(
            f"INSERT INTO attendance({','.join(_ATT_COLS)})"
            f" VALUES({','.join('?'*len(_ATT_COLS))})"
            f" ON CONFLICT(worker_id,month) DO UPDATE SET {sets}",
            vals,
        )
    cache.invalidate(f"attendance:{db_path}:{a.month}", f"months_with_data:{db_path}")
    _notify_host_change()


def bulk_upsert_attendance(records: List[AttendanceRecord], db_path=None):
    """Upsert all records in a single transaction — much faster than N separate calls."""
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → bulk_upsert_attendance(count=%d)", len(records))
        _sync_client.bulk_upsert_attendance(records)
        return
    db_path = _db(db_path)
    if not records:
        return
    sets = ", ".join(f"{c}=excluded.{c}" for c in _ATT_COLS[2:])
    sql = (
        f"INSERT INTO attendance({','.join(_ATT_COLS)})"
        f" VALUES({','.join('?'*len(_ATT_COLS))})"
        f" ON CONFLICT(worker_id,month) DO UPDATE SET {sets}"
    )
    with get_conn(db_path) as conn:
        conn.executemany(
            sql, [tuple(getattr(a, c) for c in _ATT_COLS) for a in records]
        )
    months = {r.month for r in records}
    for m in months:
        cache.invalidate(f"attendance:{db_path}:{m}")
    cache.invalidate(f"months_with_data:{db_path}")
    _notify_host_change()


def delete_attendance_for_worker(worker_id: str, month: str = None, db_path=None):
    """Delete attendance records for a worker. If month given, only that month; else all months."""
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → delete_attendance_for_worker(%r, month=%r)", worker_id, month)
        _sync_client.delete_attendance_for_worker(worker_id, month)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        if month:
            conn.execute(
                "DELETE FROM attendance WHERE worker_id=? AND month=?", (worker_id, month)
            )
            cache.invalidate(f"attendance:{db_path}:{month}")
        else:
            conn.execute("DELETE FROM attendance WHERE worker_id=?", (worker_id,))
            cache.invalidate_prefix(f"attendance:{db_path}:")
    cache.invalidate(f"months_with_data:{db_path}")
    _notify_host_change()


def import_attendance_from_csv(filepath, month, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → import_attendance_from_csv(%r, month=%r)", filepath, month)
        return _sync_client.import_attendance_from_csv(filepath, month)
    db_path = _db(db_path)
    import csv

    records, errors = [], []
    workers = {w.worker_id for w in get_all_workers(db_path, active_only=False)}
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 2):
            wid = row.get("worker_id", "").strip()
            if not wid:
                errors.append(f"Row {i}: missing worker_id")
                continue
            if wid not in workers:
                errors.append(f"Row {i}: '{wid}' not found")
                continue
            try:
                kwargs = {"worker_id": wid, "month": month}
                for col in _ATT_COLS[2:]:
                    if col in row:
                        kwargs[col] = float(row[col] or 0)
                records.append(AttendanceRecord(**kwargs))
            except Exception as e:
                errors.append(f"Row {i}: {e}")
    if records:
        bulk_upsert_attendance(records, db_path)
    return {"imported": len(records), "errors": errors}


def get_months_with_data(db_path=None):
    """Return distinct months that have attendance records (cached)."""
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_months_with_data")
        return _sync_client.get_months_with_data()
    db_path = _db(db_path)
    key = f"months_with_data:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT month FROM attendance ORDER BY month DESC"
        ).fetchall()
    result = [r["month"] for r in rows]
    cache.set(key, result)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#   BATCH FETCH  (workers + attendance in ONE round-trip)
# ══════════════════════════════════════════════════════════════════════════════
def get_workers_and_attendance(month: str, db_path=None):
    """
    Returns (workers, attendance_dict) in a single DB round-trip.
    attendance_dict maps worker_id -> AttendanceRecord.
    Caches both pieces independently so individual invalidation still works.
    Only active workers are fetched (active_only=True) to reduce rendering load.
    """
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_workers_and_attendance(month=%r)", month)
        return _sync_client.get_workers_and_attendance(month)
    db_path = _db(db_path)
    workers  = get_all_workers(db_path, active_only=True)
    att_list = get_attendance(month, db_path)
    att_dict = {a.worker_id: a for a in att_list}
    return workers, att_dict


# ══════════════════════════════════════════════════════════════════════════════
#   CONFIG
# ══════════════════════════════════════════════════════════════════════════════
def get_config(db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → get_config")
        return _sync_client.get_config()
    db_path = _db(db_path)
    key = f"config:{db_path}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT value FROM config WHERE key='company'"
        ).fetchone()
    result = CompanyConfig.from_json(row["value"]) if row else CompanyConfig()
    cache.set(key, result)
    return result


def save_config(cfg: CompanyConfig, db_path=None):
    if _sync_client and db_path is None:
        logger.debug("CLIENT proxy → save_config")
        _sync_client.save_config(cfg)
        return
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO config VALUES('company',?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (cfg.to_json(),),
        )
    cache.invalidate(f"config:{db_path}")
    _notify_host_change()


# ══════════════════════════════════════════════════════════════════════════════
#   PAYROLL RUNS (History / Audit Log)
# ══════════════════════════════════════════════════════════════════════════════
def save_payroll_run(
    month: str,
    run_date: str,
    total_gross: float,
    total_net: float,
    worker_count: int,
    results_json: str,
    db_path=None,
):
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO payroll_runs"
            "(month, run_date, total_gross, total_net, worker_count, results_json)"
            " VALUES(?,?,?,?,?,?)",
            (month, run_date, total_gross, total_net, worker_count, results_json),
        )


def get_payroll_runs(db_path=None):
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT id, month, run_date, total_gross, total_net, worker_count"
            " FROM payroll_runs ORDER BY id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_payroll_run(run_id: int, db_path=None):
    db_path = _db(db_path)
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM payroll_runs WHERE id=?", (run_id,)
        ).fetchone()
    return dict(row) if row else None
