"""
db_sync.py — Bidirectional startup database sync for PayrollPro.

On every client startup:
  1. Compare local DB vs server DB (mtime + version + row_hash).
  2. If server is newer  → PULL full snapshot from server.
  3. If local is newer   → PUSH local DB to server, then PULL back to confirm.
  4. If equal            → no action.

After sync, local DB == server DB == ground truth for all PCs.
"""

import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time

logger = logging.getLogger(__name__)

_META_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "sync_meta.json"
)


# ── Metadata helpers ───────────────────────────────────────────────────────────

def _load_meta() -> dict:
    if os.path.exists(_META_FILE):
        try:
            with open(_META_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_synced_version": -1, "last_synced_mtime": 0.0}


def _save_meta(version: int, mtime: float):
    try:
        with open(_META_FILE, "w") as f:
            json.dump(
                {"last_synced_version": version, "last_synced_mtime": mtime},
                f, indent=2
            )
    except Exception as e:
        logger.warning("Could not save sync_meta.json: %s", e)


# ── Local DB stats ─────────────────────────────────────────────────────────────

def _local_stats(db_path: str) -> dict:
    """Return mtime, size, row_hash for the local DB file."""
    result = {"mtime": 0.0, "size": 0, "row_hash": 0, "exists": False}
    if not os.path.exists(db_path):
        return result
    try:
        result["mtime"] = os.path.getmtime(db_path)
        result["size"] = os.path.getsize(db_path)
        result["exists"] = True
        conn = sqlite3.connect(db_path)
        w = conn.execute("SELECT count(*) FROM workers").fetchone()[0]
        a = conn.execute("SELECT count(*) FROM attendance").fetchone()[0]
        conn.close()
        result["row_hash"] = w * 10000 + a
    except Exception as e:
        logger.warning("Could not read local DB stats: %s", e)
    return result


# ── Who wins? ──────────────────────────────────────────────────────────────────

def _who_is_newer(server_info: dict, local: dict) -> str:
    """
    Returns "server", "local", or "equal".
    Decision order: mtime (2s tolerance) → row_hash.
    """
    if not local["exists"]:
        return "server"

    s_mtime = server_info.get("mtime", 0.0)
    l_mtime = local["mtime"]
    diff = s_mtime - l_mtime

    if diff > 2.0:
        return "server"
    if diff < -2.0:
        return "local"

    # Mtimes within 2 seconds — use row_hash as tiebreaker
    s_hash = server_info.get("row_hash", 0)
    l_hash = local["row_hash"]
    if s_hash > l_hash:
        return "server"
    if l_hash > s_hash:
        return "local"
    return "equal"


# ── PULL (server → client) ─────────────────────────────────────────────────────

def _pull_snapshot(sync_client, local_db_path: str, on_progress=None) -> bool:
    if on_progress:
        on_progress("📥 Downloading latest database from server…")
    try:
        r = sync_client._requests.get(
            f"{sync_client.base_url}/db/snapshot",
            timeout=90.0,
            stream=True,
        )
        r.raise_for_status()

        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="payroll_snap_")
        try:
            with os.fdopen(tmp_fd, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            # Validate
            try:
                conn = sqlite3.connect(tmp_path)
                conn.execute("SELECT count(*) FROM sqlite_master")
                conn.close()
            except Exception as e:
                logger.error("Snapshot validation failed: %s", e)
                os.unlink(tmp_path)
                if on_progress:
                    on_progress("❌ Snapshot invalid — using local database")
                return False

            # Backup local before replacing
            if os.path.exists(local_db_path):
                shutil.copy2(local_db_path, local_db_path + ".pre_pull.bak")

            # Close active connections first to avoid Windows lock problems
            try:
                from database import close_thread_conn
                close_thread_conn()
            except Exception:
                pass

            try:
                if os.path.exists(local_db_path):
                    os.remove(local_db_path)
                shutil.move(tmp_path, local_db_path)
            except Exception:
                shutil.copy2(tmp_path, local_db_path)
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

            server_version = int(r.headers.get("X-DB-Version", 0))
            _save_meta(server_version, time.time())

            if on_progress:
                on_progress("✅ Database pulled from server successfully")
            return True

        except Exception as e:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise e

    except Exception as e:
        logger.error("Pull snapshot failed: %s", e)
        if on_progress:
            on_progress(f"⚠️ Pull failed: {e} — using local database")
        return False


# ── PUSH (client → server) ─────────────────────────────────────────────────────

def _push_snapshot(sync_client, local_db_path: str, on_progress=None) -> bool:
    if on_progress:
        on_progress("📤 This device has newer data — uploading to server…")
    try:
        # WAL checkpoint before reading
        try:
            conn = sqlite3.connect(local_db_path)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception:
            pass

        with open(local_db_path, "rb") as f:
            data = f.read()

        r = sync_client._requests.put(
            f"{sync_client.base_url}/db/upload",
            data=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=90.0,
        )
        r.raise_for_status()
        result = r.json()

        if result.get("status") == "ok":
            _save_meta(result.get("version", 0), time.time())
            if on_progress:
                on_progress("✅ Local database pushed to server successfully")
            return True
        else:
            if on_progress:
                on_progress(f"⚠️ Server rejected upload: {result.get('error')}")
            return False

    except Exception as e:
        logger.error("Push snapshot failed: %s", e)
        if on_progress:
            on_progress(f"⚠️ Push failed: {e} — continuing with local database")
        return False


# ── Main entry point ───────────────────────────────────────────────────────────

def startup_sync(sync_client, local_db_path: str, on_progress=None) -> str:
    """
    Compare local and server DBs, sync in the right direction.

    Returns: "pulled", "pushed", "equal", or "failed"
    """
    if on_progress:
        on_progress("🔍 Comparing databases across devices…")

    # Step 1: Get server stats
    try:
        r = sync_client._requests.get(
            f"{sync_client.base_url}/db/version_info",
            timeout=5.0
        )
        r.raise_for_status()
        server_info = r.json()
    except Exception as e:
        logger.warning("Could not reach server for version_info: %s", e)
        if on_progress:
            on_progress("⚠️ Server unreachable — using local database")
        return "failed"

    # Step 2: Get local stats
    local = _local_stats(local_db_path)

    winner = _who_is_newer(server_info, local)
    logger.info(
        "Sync decision: %s wins. server_mtime=%.1f local_mtime=%.1f "
        "server_hash=%s local_hash=%s",
        winner,
        server_info.get("mtime", 0),
        local.get("mtime", 0),
        server_info.get("row_hash", 0),
        local.get("row_hash", 0),
    )

    if winner == "server":
        if on_progress:
            on_progress("📥 Server has newer data — syncing down…")
        ok = _pull_snapshot(sync_client, local_db_path, on_progress)
        return "pulled" if ok else "failed"

    elif winner == "local":
        if on_progress:
            on_progress("📤 This device has newer data — syncing up…")
        ok = _push_snapshot(sync_client, local_db_path, on_progress)
        if ok:
            # After push, pull back to ensure byte-identical copy
            if on_progress:
                on_progress("🔄 Confirming sync…")
            _pull_snapshot(sync_client, local_db_path, on_progress)
        return "pushed" if ok else "failed"

    else:
        if on_progress:
            on_progress("✅ All devices are in sync")
        return "equal"
