"""
database.py — SQLite Database Layer
"""
import sqlite3, json, logging
from contextlib import contextmanager
from typing import List, Optional, Dict

from schema import MasterProfile, Worker, AttendanceRecord, CompanyConfig, SEED_PROFILES, SEED_WORKERS

logger  = logging.getLogger(__name__)
DB_PATH = "payroll.db"

@contextmanager
def get_conn(db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn; conn.commit()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()

DDL = """
CREATE TABLE IF NOT EXISTS master_profiles (
    profile_id TEXT PRIMARY KEY, title TEXT NOT NULL,
    daily_wage REAL NOT NULL, ot_rate REAL NOT NULL,
    location TEXT NOT NULL DEFAULT 'Head Office'
);

CREATE TABLE IF NOT EXISTS workers (
    worker_id    TEXT PRIMARY KEY, name TEXT NOT NULL,
    profile_id   TEXT NOT NULL,
    bank_account TEXT DEFAULT '', bank_name TEXT DEFAULT '',
    ifsc_code    TEXT DEFAULT '', uan_number TEXT DEFAULT '',
    esic_number  TEXT DEFAULT '', joining_date TEXT DEFAULT '',
    active       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (profile_id) REFERENCES master_profiles(profile_id)
);

CREATE TABLE IF NOT EXISTS attendance (
    record_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    worker_id         TEXT NOT NULL, month TEXT NOT NULL,
    days_present      REAL DEFAULT 0,
    basic_wages       REAL DEFAULT 0, da REAL DEFAULT 0,
    hra               REAL DEFAULT 0, cca REAL DEFAULT 0,
    overtime_wages    REAL DEFAULT 0, arrears REAL DEFAULT 0,
    advances_pay      REAL DEFAULT 0, nfh_wages REAL DEFAULT 0,
    maternity_benefit REAL DEFAULT 0, leave_wages REAL DEFAULT 0,
    bonus             REAL DEFAULT 0, other_allowances REAL DEFAULT 0,
    epf_override      REAL DEFAULT 0, esi_override REAL DEFAULT 0,
    welfare_fund      REAL DEFAULT 0, tds REAL DEFAULT 0,
    profession_tax    REAL DEFAULT 0, advance_repayment REAL DEFAULT 0,
    fine              REAL DEFAULT 0, loss_damages REAL DEFAULT 0,
    other_deductions  REAL DEFAULT 0,
    UNIQUE(worker_id, month),
    FOREIGN KEY (worker_id) REFERENCES workers(worker_id)
);

CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

def init_db(db_path=DB_PATH, seed=True):
    with get_conn(db_path) as conn:
        conn.executescript(DDL)
        if seed:
            if conn.execute("SELECT COUNT(*) FROM master_profiles").fetchone()[0] == 0:
                for p in SEED_PROFILES:
                    conn.execute("INSERT OR IGNORE INTO master_profiles VALUES(?,?,?,?,?)",
                                 (p.profile_id,p.title,p.daily_wage,p.ot_rate,p.location))
                for w in SEED_WORKERS:
                    conn.execute("INSERT OR IGNORE INTO workers VALUES(?,?,?,?,?,?,?,?,?,?)",
                                 (w.worker_id,w.name,w.profile_id,w.bank_account,w.bank_name,
                                  w.ifsc_code,w.uan_number,w.esic_number,w.joining_date,int(w.active)))
            if conn.execute("SELECT COUNT(*) FROM config WHERE key='company'").fetchone()[0] == 0:
                conn.execute("INSERT INTO config VALUES('company',?)", (CompanyConfig().to_json(),))

# ── Profiles ──────────────────────────────────────────────────────────────────
def get_all_profiles(db_path=DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM master_profiles ORDER BY title").fetchall()
    return [MasterProfile(**dict(r)) for r in rows]

def get_profiles_dict(db_path=DB_PATH):
    return {p.profile_id: p for p in get_all_profiles(db_path)}

def upsert_profile(p: MasterProfile, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("""INSERT INTO master_profiles VALUES(?,?,?,?,?)
            ON CONFLICT(profile_id) DO UPDATE SET
            title=excluded.title,daily_wage=excluded.daily_wage,
            ot_rate=excluded.ot_rate,location=excluded.location""",
            (p.profile_id,p.title,p.daily_wage,p.ot_rate,p.location))

def delete_profile(profile_id, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("DELETE FROM master_profiles WHERE profile_id=?", (profile_id,))

# ── Workers ───────────────────────────────────────────────────────────────────
def get_all_workers(db_path=DB_PATH, active_only=True):
    sql = "SELECT * FROM workers" + (" WHERE active=1" if active_only else "") + " ORDER BY name"
    with get_conn(db_path) as conn:
        rows = conn.execute(sql).fetchall()
    return [Worker.from_dict(dict(r)) for r in rows]

def upsert_worker(w: Worker, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("""INSERT INTO workers
            (worker_id,name,profile_id,bank_account,bank_name,ifsc_code,
             uan_number,esic_number,joining_date,active)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(worker_id) DO UPDATE SET
            name=excluded.name,profile_id=excluded.profile_id,
            bank_account=excluded.bank_account,bank_name=excluded.bank_name,
            ifsc_code=excluded.ifsc_code,uan_number=excluded.uan_number,
            esic_number=excluded.esic_number,joining_date=excluded.joining_date,
            active=excluded.active""",
            (w.worker_id,w.name,w.profile_id,w.bank_account,w.bank_name,
             w.ifsc_code,w.uan_number,w.esic_number,w.joining_date,int(w.active)))

def deactivate_worker(worker_id, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("UPDATE workers SET active=0 WHERE worker_id=?", (worker_id,))

# ── Attendance ────────────────────────────────────────────────────────────────
_ATT_COLS = ("worker_id","month","days_present",
             "basic_wages","da","hra","cca","overtime_wages","arrears",
             "advances_pay","nfh_wages","maternity_benefit","leave_wages",
             "bonus","other_allowances",
             "epf_override","esi_override","welfare_fund","tds",
             "profession_tax","advance_repayment","fine","loss_damages","other_deductions")

def get_attendance(month, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM attendance WHERE month=? ORDER BY worker_id",(month,)).fetchall()
    return [AttendanceRecord.from_dict(dict(r)) for r in rows]

def upsert_attendance(a: AttendanceRecord, db_path=DB_PATH):
    vals = tuple(getattr(a, c) for c in _ATT_COLS)
    sets = ", ".join(f"{c}=excluded.{c}" for c in _ATT_COLS[2:])
    with get_conn(db_path) as conn:
        conn.execute(
            f"INSERT INTO attendance({','.join(_ATT_COLS)}) VALUES({','.join('?'*len(_ATT_COLS))})"
            f" ON CONFLICT(worker_id,month) DO UPDATE SET {sets}", vals)

def bulk_upsert_attendance(records: List[AttendanceRecord], db_path=DB_PATH):
    for a in records: upsert_attendance(a, db_path)

def import_attendance_from_csv(filepath, month, db_path=DB_PATH):
    import csv
    records, errors = [], []
    workers = {w.worker_id for w in get_all_workers(db_path)}
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 2):
            wid = row.get("worker_id","").strip()
            if not wid: errors.append(f"Row {i}: missing worker_id"); continue
            if wid not in workers: errors.append(f"Row {i}: '{wid}' not found"); continue
            try:
                kwargs = {"worker_id": wid, "month": month}
                for col in _ATT_COLS[2:]:
                    if col in row: kwargs[col] = float(row[col] or 0)
                records.append(AttendanceRecord(**kwargs))
            except Exception as e:
                errors.append(f"Row {i}: {e}")
    if records: bulk_upsert_attendance(records, db_path)
    return {"imported": len(records), "errors": errors}

def get_months_with_data(db_path=DB_PATH):
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT month FROM attendance ORDER BY month DESC").fetchall()
    return [r["month"] for r in rows]

# ── Config ────────────────────────────────────────────────────────────────────
def get_config(db_path=DB_PATH):
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT value FROM config WHERE key='company'").fetchone()
    return CompanyConfig.from_json(row["value"]) if row else CompanyConfig()

def save_config(cfg: CompanyConfig, db_path=DB_PATH):
    with get_conn(db_path) as conn:
        conn.execute("INSERT INTO config VALUES('company',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (cfg.to_json(),))
