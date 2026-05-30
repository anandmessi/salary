"""
sync_client.py — HTTP Proxy for PayrollPro LAN Sync (CLIENT side)
=================================================================
Mirrors the database.py public API surface but routes all calls
through the HOST's Flask REST API over HTTP.

Usage (set up by lan_sync.py when role == "client"):
    from sync_client import SyncClient
    client = SyncClient(host_ip="192.168.1.10", port=5050)
    client.start_polling()          # begins 2-second background poll
    database.set_sync_client(client)
"""

import logging
import threading
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

POLL_INTERVAL = 2.0          # seconds between version/change polls
CONNECT_TIMEOUT = 3.0        # seconds for initial connection attempts
REQUEST_TIMEOUT = 8.0        # seconds for regular API calls


class SyncClient:
    """
    HTTP client that mirrors the database.py public API.
    All methods are thread-safe.
    """

    def __init__(self, host_ip: str, port: int = 5050):
        self.base_url = f"http://{host_ip}:{port}/api"
        self._host_ip = host_ip
        self._port = port
        self._last_ts: float = 0.0          # last seen change timestamp
        self._last_version: int = -1        # last seen /api/version counter (-1 = uninitialised)
        self._connected: bool = False
        self._stop_evt = threading.Event()
        self._poll_thread: Optional[threading.Thread] = None
        self._on_change: Optional[callable] = None  # UI callback

        try:
            import requests
            self._requests = requests
        except ImportError:
            raise RuntimeError("requests library not installed. Run: pip install requests flask")

    # ── Connection ─────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """Return True if host server is reachable."""
        try:
            r = self._requests.get(
                f"{self.base_url}/ping", timeout=CONNECT_TIMEOUT
            )
            if r.status_code == 200:
                self._connected = True
                return True
        except Exception:
            pass
        self._connected = False
        return False

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def host_address(self) -> str:
        return f"{self._host_ip}:{self._port}"

    # ── Polling ────────────────────────────────────────────────────────────────

    def start_polling(self, on_change: Optional[callable] = None):
        """
        Start a background thread that polls /api/changes every 2 seconds.
        Calls on_change() whenever data has changed on the host.
        """
        self._on_change = on_change
        self._stop_evt.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="SyncClient-poll"
        )
        self._poll_thread.start()

    def stop_polling(self):
        self._stop_evt.set()

    def _poll_loop(self):
        """Background poll thread.

        Tries /api/version first (monotonic integer counter added in sync_server
        alongside _write_version).  Falls back to the original /api/changes
        timestamp approach so the client stays compatible with hosts that haven't
        been updated yet.
        """
        while not self._stop_evt.is_set():
            changed = False
            try:
                # ── Primary: integer version counter (immune to clock-skew) ──
                r = self._requests.get(
                    f"{self.base_url}/version", timeout=CONNECT_TIMEOUT
                )
                if r.status_code == 200:
                    ver = r.json().get("version", -1)
                    if self._last_version == -1:
                        # First successful poll — initialise without firing on_change
                        self._last_version = ver
                    elif ver > self._last_version:
                        self._last_version = ver
                        changed = True
                    self._connected = True
                else:
                    raise ValueError(f"HTTP {r.status_code}")
            except Exception:
                # ── Fallback: timestamp-based /api/changes ────────────────────
                try:
                    r = self._requests.get(
                        f"{self.base_url}/changes", timeout=CONNECT_TIMEOUT
                    )
                    if r.status_code == 200:
                        ts = r.json().get("ts", 0.0)
                        if ts > self._last_ts:
                            self._last_ts = ts
                            changed = True
                        self._connected = True
                    else:
                        self._connected = False
                except Exception:
                    self._connected = False

            if changed and self._on_change:
                try:
                    self._on_change()
                except Exception as e:
                    logger.debug("on_change callback error: %s", e)

            self._stop_evt.wait(POLL_INTERVAL)

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _get(self, path: str, params: dict = None):
        r = self._requests.get(
            f"{self.base_url}{path}", params=params, timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        self._connected = True
        return r.json()

    def _post(self, path: str, data):
        r = self._requests.post(
            f"{self.base_url}{path}", json=data, timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        self._connected = True
        return r.json()

    def _delete(self, path: str):
        r = self._requests.delete(
            f"{self.base_url}{path}", timeout=REQUEST_TIMEOUT
        )
        r.raise_for_status()
        self._connected = True
        return r.json()

    # ── Version ────────────────────────────────────────────────────────────────

    def get_version(self) -> int:
        """Query the host's write-version counter.

        Returns -1 if the host does not support /api/version (older server).
        """
        try:
            data = self._get("/version")
            return int(data.get("version", -1))
        except Exception:
            return -1

    # ── Workers ────────────────────────────────────────────────────────────────

    def get_all_workers(self, active_only: bool = True):
        from schema import Worker
        params = {"active_only": "1" if active_only else "0"}
        data = self._get("/workers", params)
        return [Worker.from_dict(d) for d in data]

    def get_worker_by_id(self, worker_id: str):
        from schema import Worker
        data = self._get(f"/workers/{worker_id}")
        return Worker.from_dict(data) if data else None

    def upsert_worker(self, w):
        self._post("/workers", w.to_dict())

    def deactivate_worker(self, worker_id: str):
        self._post(f"/workers/{worker_id}/deactivate", {})

    def reactivate_worker(self, worker_id: str):
        self._post(f"/workers/{worker_id}/reactivate", {})

    def delete_worker(self, worker_id: str):
        self._delete(f"/workers/{worker_id}")

    def import_workers_from_csv(self, filepath: str):
        return self._post("/workers/import_csv", {"filepath": filepath})

    def get_workers_by_unit(self, unit: str, active_only: bool = True):
        from schema import Worker
        params = {"active_only": "1" if active_only else "0"}
        data = self._get(f"/units/workers/{unit}", params)
        return [Worker.from_dict(d) for d in data]

    # ── Attendance ─────────────────────────────────────────────────────────────

    def get_attendance(self, month: str):
        from schema import AttendanceRecord
        data = self._get(f"/attendance/{month}")
        return [AttendanceRecord.from_dict(d) for d in data]

    def upsert_attendance(self, rec):
        self._post("/attendance", rec.to_dict())

    def bulk_upsert_attendance(self, records: list):
        self._post("/attendance/bulk", [r.to_dict() for r in records])

    def delete_attendance_for_worker(self, worker_id: str, month: str = None):
        if month:
            self._delete(f"/attendance/{worker_id}/{month}")
        else:
            self._delete(f"/attendance/{worker_id}")

    def import_attendance_from_csv(self, filepath: str, month: str):
        return self._post("/attendance/import_csv", {
            "filepath": filepath, "month": month
        })

    def get_workers_and_attendance(self, month: str):
        from schema import Worker, AttendanceRecord
        data = self._get(f"/workers_and_attendance/{month}")
        workers = [Worker.from_dict(d) for d in data["workers"]]
        att_dict = {
            wid: AttendanceRecord.from_dict(rec)
            for wid, rec in data["attendance"].items()
        }
        return workers, att_dict

    def get_months_with_data(self):
        return self._get("/months_with_data")

    # ── Units ──────────────────────────────────────────────────────────────────

    def get_all_units(self):
        return self._get("/units")

    def add_unit(self, name: str):
        self._post("/units", {"name": name})

    def rename_unit(self, old_name: str, new_name: str):
        self._post("/units/rename", {"old_name": old_name, "new_name": new_name})

    def delete_unit(self, name: str) -> int:
        result = self._delete(f"/units/{name}")
        return result.get("workers_moved", 0)

    def unit_worker_count(self) -> dict:
        return self._get("/units/worker_count")

    # ── Banks ──────────────────────────────────────────────────────────────────

    def get_all_banks(self):
        return self._get("/banks")

    def add_bank(self, name: str):
        self._post("/banks", {"name": name})

    def update_bank(self, old_name: str, new_name: str):
        self._post("/banks/update", {"old_name": old_name, "new_name": new_name})

    def delete_bank(self, name: str):
        self._delete(f"/banks/{name}")

    # ── Skill Wages ────────────────────────────────────────────────────────────

    def get_all_skill_wages(self):
        from schema import SkillWage
        data = self._get("/skill_wages")
        return [SkillWage.from_dict(d) for d in data]

    def get_skill_wages_dict(self):
        wages = self.get_all_skill_wages()
        return {sw.skill_category: sw for sw in wages}

    def upsert_skill_wage(self, sw):
        self._post("/skill_wages", sw.to_dict())

    # ── Config ─────────────────────────────────────────────────────────────────

    def get_config(self):
        from schema import CompanyConfig
        data = self._get("/config")
        return CompanyConfig.from_dict(data)

    def save_config(self, cfg):
        self._post("/config", cfg.to_dict())
