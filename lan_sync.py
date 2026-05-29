r"""
lan_sync.py — Automatic LAN database sharing for PayrollPro
============================================================
Uses UDP broadcast for zero-config host discovery (unchanged).
Uses an embedded Flask HTTP server for actual data sync (replaces SMB).

Flow:
  1. On startup, broadcast UDP "PAYROLLPRO_DISCOVER" on port 47474
  2. If another PC responds with "PAYROLLPRO_HOST:<ip>|<pc_name>", become CLIENT
  3. If nobody responds within 2.5s, become HOST — start Flask on port 5050
  4. HOST listens for future clients via UDP heartbeat responder
  5. CLIENT connects to HOST's Flask API; all DB calls go through HTTP
  6. Both show a status badge in the UI
"""

import os
import socket
import threading
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DISCOVER_PORT      = 47474
DISCOVER_MSG       = b"PAYROLLPRO_DISCOVER"
HOST_PREFIX        = b"PAYROLLPRO_HOST:"
BROADCAST_ADDR     = "255.255.255.255"
DISCOVER_TIMEOUT   = 2.5    # seconds to wait for a host response

from sync_server import SYNC_PORT


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


class LanSync:
    """
    Manages host/client role negotiation and DB path/sync-client setup.

    Usage:
        sync = LanSync(db_path, on_role_decided)
        sync.start()   # non-blocking; calls on_role_decided when done

    on_role_decided(role, db_path, peer_name, host_ip):
        role      : "host" | "client" | "standalone"
        db_path   : local DB path (always the local path now)
        peer_name : hostname of the other PC (or None)
        host_ip   : IP of the host (or None if host/standalone)
    """

    def __init__(self, local_db_path: str, on_role_decided):
        self.local_db_path = os.path.abspath(local_db_path)
        self._on_role      = on_role_decided
        self._role         = None            # "host" | "client" | "standalone"
        self._peer_name    = None
        self._host_ip      = None
        self._stop_evt     = threading.Event()
        self._responder    = None
        self._local_ip     = _get_local_ip()

    def start(self) -> None:
        t = threading.Thread(
            target=self._negotiate, daemon=True, name="LanSync-negotiate"
        )
        t.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._role == "host":
            try:
                import sync_server
                sync_server.stop()
            except Exception as e:
                logger.warning("Error stopping sync server: %s", e)

    @property
    def role(self) -> str | None:
        return self._role

    @property
    def peer_name(self) -> str | None:
        return self._peer_name

    @property
    def host_ip(self) -> str | None:
        return self._host_ip

    # ── Negotiation ────────────────────────────────────────────────────────────

    def _negotiate(self) -> None:
        host_ip, peer_name = self._discover_host()

        if host_ip:
            # Another PC is already hosting — become CLIENT
            logger.info("Found host at %s (%s)", host_ip, peer_name)
            # Verify the Flask server is actually reachable
            if self._check_server_reachable(host_ip):
                self._role      = "client"
                self._peer_name = peer_name
                self._host_ip   = host_ip
                self._on_role("client", self.local_db_path, peer_name, host_ip)
            else:
                logger.warning(
                    "Host at %s discovered but Flask API not reachable on port %d. "
                    "Falling back to standalone.", host_ip, SYNC_PORT
                )
                self._role = "standalone"
                self._on_role("standalone", self.local_db_path, None, None)
        else:
            # No host found — become the HOST
            logger.info("No host found — becoming HOST on %s:%d", self._local_ip, SYNC_PORT)
            import sync_server
            ok = sync_server.start(self.local_db_path)
            if ok:
                # Give Flask a moment to bind the port
                time.sleep(0.5)
                self._role      = "host"
                self._peer_name = None
                self._host_ip   = self._local_ip
                self._start_heartbeat()
                self._on_role("host", self.local_db_path, None, self._local_ip)
            else:
                logger.warning(
                    "Could not start Flask sync server — running standalone. "
                    "Ensure 'flask' is installed: pip install flask"
                )
                self._role = "standalone"
                self._on_role("standalone", self.local_db_path, None, None)

    def _check_server_reachable(self, host_ip: str) -> bool:
        """Try to reach the host's Flask /api/ping endpoint."""
        try:
            import urllib.request
            url = f"http://{host_ip}:{SYNC_PORT}/api/ping"
            with urllib.request.urlopen(url, timeout=3) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug("Server reachability check failed: %s", e)
            return False

    # ── Discovery (UDP broadcast) ──────────────────────────────────────────────

    def _discover_host(self):
        """
        Broadcast a discovery packet and wait DISCOVER_TIMEOUT seconds.
        Returns (host_ip, peer_name) or (None, None).
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(DISCOVER_TIMEOUT)
        try:
            sock.bind(("", 0))
            sock.sendto(DISCOVER_MSG, (BROADCAST_ADDR, DISCOVER_PORT))
            logger.debug("Discovery broadcast sent from %s", self._local_ip)
            deadline = time.time() + DISCOVER_TIMEOUT
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(512)
                    if data.startswith(HOST_PREFIX):
                        if addr[0] == self._local_ip:
                            continue  # ignore our own reply
                        payload = data[len(HOST_PREFIX):].decode("utf-8", errors="ignore")
                        # payload format: "IP|PC_NAME"
                        parts    = payload.split("|")
                        host_ip  = parts[0] if parts else addr[0]
                        peer     = parts[1] if len(parts) > 1 else addr[0]
                        return host_ip, peer
                except socket.timeout:
                    break
                except OSError:
                    break
        except Exception as e:
            logger.debug("Discovery error: %s", e)
        finally:
            sock.close()
        return None, None

    # ── Heartbeat (HOST broadcasts its availability) ───────────────────────────

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
            # Reply includes local IP and PC name so client can build the API URL
            reply   = HOST_PREFIX + f"{self._local_ip}|{pc_name}".encode("utf-8")
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
