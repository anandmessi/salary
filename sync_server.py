"""
sync_server.py — Embedded Flask REST API for PayrollPro LAN Sync
=================================================================
Runs on the HOST machine in a background thread.
Exposes all DB operations as JSON REST endpoints so CLIENT machines
can read/write data over HTTP instead of directly accessing the SQLite file.

Port: 5050  (configurable via SYNC_PORT)
"""

import json
import logging
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

SYNC_PORT = 5050
_server_thread: Optional[threading.Thread] = None
_flask_app = None
_shutdown_event = threading.Event()

# Tracks the last DB write timestamp so clients can detect changes
_last_change_ts: float = 0.0
_change_lock = threading.Lock()


def _bump_change():
    """Called after every write so polling clients see a new timestamp."""
    global _last_change_ts
    with _change_lock:
        _last_change_ts = time.time()


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

    @app.route("/api/changes")
    def changes():
        """Lightweight polling endpoint — returns current change timestamp."""
        return jsonify({"ts": _last_change_ts})

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
    global _server_thread, _flask_app

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
