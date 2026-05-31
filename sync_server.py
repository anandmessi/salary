"""
sync_server.py — PayrollPro Central Database Server
====================================================
Run this on ONE dedicated "server PC" on your network:

    python sync_server.py

All other PCs (and this PC itself) connect to it via the desktop app's
Settings → Server Connection screen.  No UDP broadcasts, no role election.

Port: 5050  (change SYNC_PORT below if needed)
"""

import json
import logging
import socket
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

SYNC_PORT = 5050
_server_thread: Optional[threading.Thread] = None
_flask_app = None
_shutdown_event = threading.Event()
_backup_manager = None

# Tracks the last DB write timestamp so clients can detect changes
_last_change_ts: float = 0.0
_change_lock = threading.Lock()

# Monotonically-increasing write counter — incremented on every write operation.
# Clients poll /api/version and compare against their last known value to
# detect changes without relying on wall-clock timestamps.
_write_version: int = 0

# Callback registered by Host's main thread GUI to watch for Client changes
_on_change_callback = None


def set_change_callback(callback):
    """Register a callback to be triggered on every database modification."""
    global _on_change_callback
    _on_change_callback = callback


def _bump_change():
    """Called after every write so polling clients see a new timestamp and version."""
    global _last_change_ts, _write_version
    with _change_lock:
        _last_change_ts = time.time()
        _write_version += 1
    
    if _on_change_callback:
        try:
            _on_change_callback()
        except Exception:
            pass


def _get_db_change_counter(db_path: str) -> int:
    try:
        import os
        if os.path.exists(db_path):
            with open(db_path, "rb") as f:
                f.seek(24)
                data = f.read(4)
                if len(data) == 4:
                    return int.from_bytes(data, byteorder="big")
    except Exception:
        pass
    return 0


def _make_app(host_db_path: str):
    """Build and return the Flask application."""
    try:
        from flask import Flask, request, jsonify, Response
    except ImportError:
        raise RuntimeError(
            "Flask is not installed. Run: pip install flask"
        )

    # Import DB functions here so they use the resolved DB path
    import database as db
    import schema as sc
    from db_cache import cache as _cache

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = False

    # ── Health / discovery ────────────────────────────────────────────────────

    @app.route("/api/ping")
    def ping():
        return jsonify({"status": "ok", "version": 1, "ts": _last_change_ts})

    @app.route("/api/download_db")
    def download_db():
        """Serve the SQLite database file to clients for syncing."""
        try:
            import sqlite3
            from flask import send_file
            # Force sqlite to write WAL pages to main database file
            conn = sqlite3.connect(host_db_path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
            return send_file(host_db_path, as_attachment=True, download_name="payroll.db")
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/db_mtime")
    def db_mtime():
        """Get the modification time and change counter of the database file."""
        try:
            import os
            mtime = os.path.getmtime(host_db_path)
            cc = _get_db_change_counter(host_db_path)
            return jsonify({"mtime": mtime, "change_counter": cc})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/db/version_info", methods=["GET"])
    def db_version_info():
        import sqlite3, os, time as _time
        try:
            mtime = os.path.getmtime(host_db_path)
            size = os.path.getsize(host_db_path)
            conn = sqlite3.connect(host_db_path)
            w = conn.execute("SELECT count(*) FROM workers").fetchone()[0]
            a = conn.execute("SELECT count(*) FROM attendance").fetchone()[0]
            conn.close()
            row_hash = w * 10000 + a
        except Exception:
            mtime, size, row_hash = 0, 0, 0
        return jsonify({
            "version": _write_version,
            "mtime": mtime,
            "size": size,
            "row_hash": row_hash,
            "server_time": _time.time(),
        })

    @app.route("/api/db/snapshot", methods=["GET"])
    def db_snapshot():
        import sqlite3, os
        try:
            conn = sqlite3.connect(host_db_path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
            with open(host_db_path, "rb") as f:
                data = f.read()
            return (
                data, 200,
                {
                    "Content-Type": "application/octet-stream",
                    "Content-Disposition": "attachment; filename=payroll.db",
                    "X-DB-Version": str(_write_version),
                    "X-DB-Size": str(len(data)),
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/db/upload", methods=["PUT"])
    def db_upload():
        """
        Accept a full SQLite DB file from a client that has newer data.
        Validates, backs up current DB, replaces it, reloads connections.
        """
        import sqlite3, shutil, tempfile, time as _time, os
        from database import close_thread_conn

        try:
            data = request.get_data()
            if not data:
                return jsonify({"error": "Empty body"}), 400

            # Write to temp file
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="payroll_upload_")
            try:
                with os.fdopen(tmp_fd, "wb") as f:
                    f.write(data)

                # Validate it is a real SQLite DB
                try:
                    conn = sqlite3.connect(tmp_path)
                    workers_count = conn.execute("SELECT count(*) FROM workers").fetchone()[0]
                    conn.close()
                except Exception as e:
                    os.unlink(tmp_path)
                    return jsonify({"error": f"Invalid SQLite DB: {e}"}), 400

                # Close local database connections first to prevent Windows locking issues
                close_thread_conn()

                # Backup current server DB before replacing
                timestamp = _time.strftime("%Y%m%d_%H%M%S")
                backup_path = host_db_path + f".pre_upload_{timestamp}.bak"
                if os.path.exists(host_db_path):
                    shutil.copy2(host_db_path, backup_path)

                # WAL checkpoint on current DB before replacing
                try:
                    cur_conn = sqlite3.connect(host_db_path)
                    cur_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    cur_conn.close()
                except Exception:
                    pass

                # Replace server DB atomically
                try:
                    if os.path.exists(host_db_path):
                        os.remove(host_db_path)
                    shutil.move(tmp_path, host_db_path)
                except Exception:
                    shutil.copy2(tmp_path, host_db_path)
                    try:
                        os.remove(tmp_path)
                    except Exception:
                        pass

                # Increment write version significantly so all clients know to pull
                global _write_version
                _write_version += 1000

                new_mtime = os.path.getmtime(host_db_path)
                new_size = os.path.getsize(host_db_path)

                # Invalidate server-side cache
                _cache.clear()
                _bump_change()

                # Signal the BackupManager to run a backup immediately
                try:
                    global _backup_manager
                    if _backup_manager is not None:
                        _backup_manager.trigger_now()
                except Exception:
                    pass

                return jsonify({
                    "status": "ok",
                    "version": _write_version,
                    "mtime": new_mtime,
                    "size": new_size,
                    "workers_imported": workers_count,
                }), 200

            except Exception as e:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise e

        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/upload_db", methods=["POST"])
    def upload_db():
        """Receive a new database file from a client and replace the host database."""
        try:
            import sqlite3
            # Close connection on database module thread local first
            db.close_thread_conn()
            
            # Read binary payload
            payload = request.get_data()
            if not payload:
                return jsonify({"error": "Empty payload"}), 400
                
            # Overwrite the host database safely
            with open(host_db_path, "wb") as f:
                f.write(payload)
                
            # Force sqlite checkpoints
            conn = sqlite3.connect(host_db_path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            conn.close()
            
            # Invalidate all server-side caches
            _cache.clear()
            _bump_change()
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/changes")
    def changes():
        """Lightweight polling endpoint — returns current change timestamp."""
        return jsonify({"ts": _last_change_ts})

    @app.route("/api/version")
    def version():
        """Returns the monotonically-increasing write version counter.

        Clients poll this every 2 s and call on_change() when the version
        number increases. This is an alternative to /api/changes that is
        immune to clock-skew between host and client machines.
        """
        return jsonify({"version": _write_version})

    # ── Workers ───────────────────────────────────────────────────────────────

    @app.route("/api/workers")
    def get_workers():
        active_only = request.args.get("active_only", "1") == "1"
        workers = db.get_all_workers(host_db_path, active_only=active_only)
        return jsonify([w.to_dict() for w in workers])

    @app.route("/api/workers/<worker_id>")
    def get_worker(worker_id):
        w = db.get_worker_by_id(worker_id, host_db_path)
        if w is None:
            return jsonify({"error": "not found"}), 404
        return jsonify(w.to_dict())

    @app.route("/api/workers", methods=["POST"])
    def upsert_worker():
        data = request.get_json(force=True)
        w = sc.Worker.from_dict(data)
        db.upsert_worker(w, host_db_path)
        _cache.invalidate(
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/workers/<worker_id>/deactivate", methods=["POST"])
    def deactivate_worker(worker_id):
        db.deactivate_worker(worker_id, host_db_path)
        _cache.invalidate(
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/workers/<worker_id>/reactivate", methods=["POST"])
    def reactivate_worker(worker_id):
        db.reactivate_worker(worker_id, host_db_path)
        _cache.invalidate(
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/workers/<worker_id>", methods=["DELETE"])
    def delete_worker(worker_id):
        db.delete_worker(worker_id, host_db_path)
        _cache.invalidate(
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
            f"months_with_data:{host_db_path}",
        )
        _cache.invalidate_prefix(f"attendance:{host_db_path}:")
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/workers/import_csv", methods=["POST"])
    def import_workers_csv():
        data = request.get_json(force=True)
        filepath = data.get("filepath")
        if not filepath:
            return jsonify({"error": "filepath required"}), 400
        result = db.import_workers_from_csv(filepath, host_db_path)
        _cache.invalidate(
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify(result)

    # ── Attendance ────────────────────────────────────────────────────────────

    @app.route("/api/attendance/<month>")
    def get_attendance(month):
        records = db.get_attendance(month, host_db_path)
        return jsonify([r.to_dict() for r in records])

    @app.route("/api/attendance", methods=["POST"])
    def upsert_attendance():
        data = request.get_json(force=True)
        rec = sc.AttendanceRecord.from_dict(data)
        db.upsert_attendance(rec, host_db_path)
        _cache.invalidate(
            f"attendance:{host_db_path}:{rec.month}",
            f"months_with_data:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/attendance/bulk", methods=["POST"])
    def bulk_upsert_attendance():
        data = request.get_json(force=True)
        records = [sc.AttendanceRecord.from_dict(r) for r in data]
        db.bulk_upsert_attendance(records, host_db_path)
        months = {r.month for r in records}
        for m in months:
            _cache.invalidate(f"attendance:{host_db_path}:{m}")
        _cache.invalidate(f"months_with_data:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True, "count": len(records)})

    @app.route("/api/attendance/<worker_id>/<month>", methods=["DELETE"])
    def delete_attendance(worker_id, month):
        db.delete_attendance_for_worker(worker_id, month, host_db_path)
        _cache.invalidate(
            f"attendance:{host_db_path}:{month}",
            f"months_with_data:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/attendance/<worker_id>", methods=["DELETE"])
    def delete_attendance_all(worker_id):
        db.delete_attendance_for_worker(worker_id, None, host_db_path)
        _cache.invalidate_prefix(f"attendance:{host_db_path}:")
        _cache.invalidate(f"months_with_data:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/attendance/import_csv", methods=["POST"])
    def import_attendance_csv():
        data = request.get_json(force=True)
        filepath = data.get("filepath")
        month = data.get("month")
        if not filepath or not month:
            return jsonify({"error": "filepath and month required"}), 400
        result = db.import_attendance_from_csv(filepath, month, host_db_path)
        _cache.invalidate(
            f"attendance:{host_db_path}:{month}",
            f"months_with_data:{host_db_path}",
        )
        _bump_change()
        return jsonify(result)

    # ── Workers + Attendance batch ────────────────────────────────────────────

    @app.route("/api/workers_and_attendance/<month>")
    def workers_and_attendance(month):
        workers, att_dict = db.get_workers_and_attendance(month, host_db_path)
        return jsonify({
            "workers": [w.to_dict() for w in workers],
            "attendance": {wid: rec.to_dict() for wid, rec in att_dict.items()},
        })

    # ── Units ─────────────────────────────────────────────────────────────────

    @app.route("/api/units")
    def get_units():
        return jsonify(db.get_all_units(host_db_path))

    @app.route("/api/units", methods=["POST"])
    def add_unit():
        data = request.get_json(force=True)
        db.add_unit(data["name"], host_db_path)
        _cache.invalidate(f"units:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/units/rename", methods=["POST"])
    def rename_unit():
        data = request.get_json(force=True)
        db.rename_unit(data["old_name"], data["new_name"], host_db_path)
        _cache.invalidate(
            f"units:{host_db_path}",
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/units/<name>", methods=["DELETE"])
    def delete_unit(name):
        count = db.delete_unit(name, host_db_path)
        _cache.invalidate(
            f"units:{host_db_path}",
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
            f"unit_worker_count:{host_db_path}",
        )
        _bump_change()
        return jsonify({"ok": True, "workers_moved": count})

    @app.route("/api/units/worker_count")
    def unit_worker_count():
        return jsonify(db.unit_worker_count(host_db_path))

    @app.route("/api/units/workers/<unit>")
    def workers_by_unit(unit):
        active_only = request.args.get("active_only", "1") == "1"
        workers = db.get_workers_by_unit(unit, host_db_path, active_only=active_only)
        return jsonify([w.to_dict() for w in workers])

    # ── Banks ─────────────────────────────────────────────────────────────────

    @app.route("/api/banks")
    def get_banks():
        return jsonify(db.get_all_banks(host_db_path))

    @app.route("/api/banks", methods=["POST"])
    def add_bank():
        data = request.get_json(force=True)
        db.add_bank(data["name"], host_db_path)
        _cache.invalidate(f"banks:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/banks/update", methods=["POST"])
    def update_bank():
        data = request.get_json(force=True)
        db.update_bank(data["old_name"], data["new_name"], host_db_path)
        _cache.invalidate(
            f"banks:{host_db_path}",
            f"workers:{host_db_path}:active",
            f"workers:{host_db_path}:all",
        )
        _bump_change()
        return jsonify({"ok": True})

    @app.route("/api/banks/<name>", methods=["DELETE"])
    def delete_bank(name):
        db.delete_bank(name, host_db_path)
        _cache.invalidate(f"banks:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    # ── Skill Wages ───────────────────────────────────────────────────────────

    @app.route("/api/skill_wages")
    def get_skill_wages():
        wages = db.get_all_skill_wages(host_db_path)
        return jsonify([w.to_dict() for w in wages])

    @app.route("/api/skill_wages", methods=["POST"])
    def upsert_skill_wage():
        data = request.get_json(force=True)
        sw = sc.SkillWage.from_dict(data)
        db.upsert_skill_wage(sw, host_db_path)
        _cache.invalidate(f"skill_wages:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    # ── Config ────────────────────────────────────────────────────────────────

    @app.route("/api/config")
    def get_config():
        cfg = db.get_config(host_db_path)
        return jsonify(cfg.to_dict())

    @app.route("/api/config", methods=["POST"])
    def save_config():
        data = request.get_json(force=True)
        cfg = sc.CompanyConfig.from_dict(data)
        db.save_config(cfg, host_db_path)
        _cache.invalidate(f"config:{host_db_path}")
        _bump_change()
        return jsonify({"ok": True})

    # ── Months ────────────────────────────────────────────────────────────────

    @app.route("/api/months_with_data")
    def months_with_data():
        return jsonify(db.get_months_with_data(host_db_path))

    return app


def start(host_db_path: str) -> bool:
    """
    Start the Flask sync server in a background daemon thread.
    Returns True if started successfully, False if Flask not available.
    """
    global _server_thread, _flask_app, _backup_manager

    # Start backup manager on server startup
    if _backup_manager is None:
        try:
            from backup_manager import BackupManager
            _backup_manager = BackupManager(db_path=host_db_path, on_sync=lambda s, t: logger.info("Server Backup: %s at %s", s, t))
            _backup_manager.start()
        except Exception as e:
            logger.error("Failed to start backup manager on server: %s", e)

    try:
        _flask_app = _make_app(host_db_path)
    except RuntimeError as e:
        logger.error("Cannot start sync server: %s", e)
        return False

    _shutdown_event.clear()

    def _run():
        import logging as _logging
        # Silence Flask's default request logger to keep payroll logs clean
        _logging.getLogger("werkzeug").setLevel(_logging.WARNING)
        try:
            _flask_app.run(
                host="0.0.0.0",
                port=SYNC_PORT,
                debug=False,
                use_reloader=False,
                threaded=True,
            )
        except Exception as e:
            logger.error("Sync server crashed: %s", e)

    _server_thread = threading.Thread(
        target=_run, daemon=True, name="SyncServer-Flask"
    )
    _server_thread.start()
    logger.info("Sync server started on 0.0.0.0:%d", SYNC_PORT)
    return True


def stop():
    """Signal Flask server to shut down (best-effort)."""
    _shutdown_event.set()
    if _flask_app:
        try:
            import requests as _r
            _r.post(f"http://127.0.0.1:{SYNC_PORT}/shutdown", timeout=1)
        except Exception:
            pass
    logger.info("Sync server stop requested")


def get_local_ips():
    """Discover all non-loopback local IP addresses."""
    ips = []
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    try:
        # Fallback UDP socket trick to get primary routing IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip not in ips and not ip.startswith("127."):
            ips.append(ip)
    except Exception:
        pass
    return ips


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="PayrollPro Central Database Server")
    parser.add_argument("--db", default="payroll.db", help="Path to SQLite database file")
    parser.add_argument("--port", type=int, default=5050, help="Port to run the Flask server on")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    port = args.port

    print("=" * 60)
    print("      PayrollPro Central Database Server (Flask API)")
    print("=" * 60)
    print(f"Database Path: {db_path}")
    print(f"Server Port:   {port}")
    print("-" * 60)
    print("To connect from desktop apps, enter one of these IPs in Settings:")
    
    local_ips = get_local_ips()
    if local_ips:
        for ip in local_ips:
            print(f"  ->  {ip}")
    else:
        print("  ->  (Could not auto-detect network IPs; check ipconfig/ifconfig)")
    
    print("-" * 60)
    print("Press Ctrl+C to stop the server.")
    print("=" * 60)

    # Initialize the database if it doesn't exist
    from database import init_db
    init_db(db_path, seed=True)

    # Silence default Flask requests log
    import logging as _logging
    _logging.getLogger("werkzeug").setLevel(_logging.WARNING)

    # Start the backup manager on standalone server run
    try:
        from backup_manager import BackupManager
        _backup_manager = BackupManager(db_path=db_path, on_sync=lambda s, t: print(f"  Backup: {s} at {t}"))
        _backup_manager.start()
    except Exception as e:
        print(f"Failed to start backup manager: {e}")

    # Build Flask app
    app = _make_app(db_path)
    
    try:
        app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print("\nStopping central database server...")

