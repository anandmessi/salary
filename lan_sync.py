r"""
lan_sync.py — Automatic LAN database sharing for PayrollPro
============================================================
Uses UDP broadcast for zero-config host discovery.
One PC becomes the HOST (serves the DB over a TCP file-sync port).
The other becomes a CLIENT (discovers host, maps to host's shared folder).

Flow:
  1. On startup, broadcast UDP "PAYROLLPRO_DISCOVER" on port 47474
  2. If another PC responds with "PAYROLLPRO_HOST:<share_name>|<pc_name>", become CLIENT
  3. If nobody responds within 2.5s, become HOST — share the DB folder via
     Windows built-in net share and start broadcasting
  4. HOST also starts a heartbeat responder (UDP) so late-joining clients find it
  5. CLIENT switches DB_PATH to the UNC path \\HOST_IP\PayrollProShare\payroll.db
  6. Both show a status badge in the UI (🟢 Host / 🔵 Synced with HOST-PC)
"""

import os
import sys
import socket
import threading
import subprocess
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DISCOVER_PORT     = 47474
DISCOVER_MSG      = b"PAYROLLPRO_DISCOVER"
HOST_PREFIX       = b"PAYROLLPRO_HOST:"
SHARE_NAME        = "PayrollProShare"
BROADCAST_ADDR    = "255.255.255.255"
DISCOVER_TIMEOUT  = 2.5    # seconds to wait for a host response
HEARTBEAT_INTERVAL = 5     # seconds between host beacons (unused in this impl; heartbeat is reactive)


def _get_local_ip() -> str:
    """Get this machine's LAN IP (not 127.0.0.1)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _get_pc_name() -> str:
    return socket.gethostname()


def _share_exists(share_name: str) -> bool:
    result = subprocess.run(
        ["net", "share", share_name],
        capture_output=True, text=True
    )
    return result.returncode == 0


def _create_share(folder_path: str, share_name: str) -> bool:
    """Create a Windows network share. Returns True on success."""
    if _share_exists(share_name):
        logger.info("Share %s already exists", share_name)
        return True
    result = subprocess.run(
        ["net", "share",
         f"{share_name}={folder_path}",
         "/GRANT:Everyone,FULL",
         "/REMARK:PayrollPro shared database"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        logger.error("net share failed: %s", result.stderr.strip())
        return False
    logger.info("Created share: %s -> %s", share_name, folder_path)
    return True


def _remove_share(share_name: str) -> None:
    subprocess.run(
        ["net", "share", share_name, "/DELETE", "/Y"],
        capture_output=True
    )
    logger.info("Removed share: %s", share_name)


def _unc_path(host_ip: str, share_name: str, filename: str) -> str:
    return f"\\\\{host_ip}\\{share_name}\\{filename}"


def _is_valid_db(path: str) -> bool:
    import sqlite3
    try:
        con = sqlite3.connect(path, timeout=5)
        con.execute("SELECT 1")
        con.close()
        return True
    except Exception:
        return False


class LanSync:
    """
    Manages host/client role negotiation and DB path switching.

    Usage:
        sync = LanSync(db_path, on_role_decided)
        sync.start()   # non-blocking; calls on_role_decided when done

    on_role_decided(role, db_path, peer_name):
        role      : "host" | "client" | "standalone"
        db_path   : resolved DB path to use
        peer_name : hostname of the other PC (or None)
    """

    def __init__(self, local_db_path: str, on_role_decided):
        self.local_db_path = os.path.abspath(local_db_path)
        self.db_folder     = os.path.dirname(self.local_db_path)
        self.db_filename   = os.path.basename(self.local_db_path)
        self._on_role      = on_role_decided
        self._role         = None            # "host" | "client" | "standalone"
        self._peer_name    = None
        self._stop_evt     = threading.Event()
        self._responder    = None

    def start(self) -> None:
        t = threading.Thread(
            target=self._negotiate, daemon=True, name="LanSync-negotiate"
        )
        t.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._role == "host":
            try:
                _remove_share(SHARE_NAME)
            except Exception as e:
                logger.warning("Error removing share on stop: %s", e)

    @property
    def role(self) -> str | None:
        return self._role

    @property
    def peer_name(self) -> str | None:
        return self._peer_name

    # ── Negotiation ────────────────────────────────────────────────────────

    def _negotiate(self) -> None:
        host_ip, host_share, peer_name = self._discover_host()
        if host_ip:
            # Another PC is already hosting
            unc = _unc_path(host_ip, host_share or SHARE_NAME, self.db_filename)
            logger.info("Found host at %s (%s) → UNC: %s", host_ip, peer_name, unc)
            # Wait up to 5 s for the UNC path to become accessible
            for _ in range(10):
                if os.path.exists(unc):
                    break
                time.sleep(0.5)
            db_ok = _is_valid_db(unc) if os.path.exists(unc) else False
            if db_ok:
                self._role      = "client"
                self._peer_name = peer_name
                self._on_role("client", unc, peer_name)
            else:
                logger.warning(
                    "UNC path %s not accessible — falling back to standalone", unc
                )
                self._role = "standalone"
                self._on_role("standalone", self.local_db_path, None)
        else:
            # No host found — become the host
            ok = _create_share(self.db_folder, SHARE_NAME)
            if ok:
                self._role = "host"
                self._peer_name = None
                self._start_heartbeat()
                self._on_role("host", self.local_db_path, None)
            else:
                logger.warning(
                    "Could not create Windows share — running standalone. "
                    "Try launching the app as Administrator on the HOST PC."
                )
                self._role = "standalone"
                self._on_role("standalone", self.local_db_path, None)

    def _discover_host(self):
        """
        Broadcast a discovery packet and wait DISCOVER_TIMEOUT seconds.
        Returns (host_ip, share_name, peer_name) or (None, None, None).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(DISCOVER_TIMEOUT)
        local_ip = _get_local_ip()
        try:
            sock.bind(("", 0))
            sock.sendto(DISCOVER_MSG, (BROADCAST_ADDR, DISCOVER_PORT))
            logger.debug("Discovery broadcast sent from %s", local_ip)
            deadline = time.time() + DISCOVER_TIMEOUT
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(512)
                    if data.startswith(HOST_PREFIX):
                        if addr[0] == local_ip:
                            # Ignore our own reply (edge case when host/client on same PC)
                            continue
                        payload = data[len(HOST_PREFIX):].decode("utf-8", errors="ignore")
                        # payload format: "SHARE_NAME|PC_NAME"
                        parts   = payload.split("|")
                        share   = parts[0] if parts else SHARE_NAME
                        peer    = parts[1] if len(parts) > 1 else addr[0]
                        return addr[0], share, peer
                except socket.timeout:
                    break
                except OSError:
                    break
        except Exception as e:
            logger.debug("Discovery error: %s", e)
        finally:
            sock.close()
        return None, None, None

    def _start_heartbeat(self) -> None:
        """HOST: listen on the discovery port and reply to any discovery request."""
        def _responder_loop():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1.0)
            try:
                sock.bind(("", DISCOVER_PORT))
            except OSError as e:
                logger.error(
                    "Cannot bind heartbeat socket on port %d: %s. "
                    "Another process may own the port.",
                    DISCOVER_PORT, e
                )
                return
            pc_name = _get_pc_name()
            reply   = HOST_PREFIX + f"{SHARE_NAME}|{pc_name}".encode("utf-8")
            logger.info("HOST heartbeat listening on UDP port %d", DISCOVER_PORT)
            while not self._stop_evt.is_set():
                try:
                    data, addr = sock.recvfrom(512)
                    if data == DISCOVER_MSG:
                        sock.sendto(reply, addr)
                        logger.debug("Replied to discovery from %s", addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
            sock.close()
            logger.debug("HOST heartbeat stopped")

        self._responder = threading.Thread(
            target=_responder_loop, daemon=True, name="LanSync-heartbeat"
        )
        self._responder.start()
