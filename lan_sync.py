"""
lan_sync.py — Automatic LAN Database Server Discovery & Negotiation
===================================================================
Uses UDP broadcasts to automatically elect the first PC running the app
as the "Host" (database server) and any subsequent PCs as "Clients".
"""

import logging
import os
import socket
import threading
import time

from sync_server import SYNC_PORT

logger = logging.getLogger(__name__)

DISCOVER_PORT    = 5051
DISCOVER_MSG     = b"PAYROLLPRO_DISCOVER"
HOST_PREFIX      = b"PAYROLLPRO_HOST|"
BROADCAST_ADDR   = "255.255.255.255"
DISCOVER_TIMEOUT = 1.5    # seconds to wait for a host response


def _get_local_ip() -> str:
    """Get this machine's primary LAN IP (not 127.0.0.1)."""
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
    Manages automatic Host/Client/Standalone role negotiation on startup.

    Usage:
        sync = LanSync(db_path, on_role_decided)
        sync.start()   # non-blocking background thread

    on_role_decided(role, db_path, peer_name, host_ip):
        role      : "host" | "client" | "standalone"
        db_path   : active database path
        peer_name : host PC's name (or None)
        host_ip   : host PC's IP address (or None)
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
                logger.warning("Error stopping background Flask server: %s", e)

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
        logger.info("Starting LAN server auto-discovery...")
        try:
            host_ip, peer_name = self._discover_host()

            if host_ip:
                # Another PC is already running as the Host Database Server
                logger.info("Discovered active database host at %s (%s)", host_ip, peer_name)
                if self._check_server_reachable(host_ip):
                    self._role      = "client"
                    self._peer_name = peer_name
                    self._host_ip   = host_ip
                    self._on_role("client", self.local_db_path, peer_name, host_ip)
                else:
                    logger.warning(
                        "Discovered host at %s but API port %d was not reachable. "
                        "Falling back to Standalone mode.", host_ip, SYNC_PORT
                    )
                    self._role = "standalone"
                    self._on_role("standalone", self.local_db_path, None, None)
            else:
                # No server found on the network — this PC becomes the Host!
                logger.info("No active database host found. Becoming Host on %s:%d...", self._local_ip, SYNC_PORT)
                import sync_server
                ok = sync_server.start(self.local_db_path)
                if ok:
                    time.sleep(0.5)  # Wait briefly for Flask to bind
                    self._role      = "host"
                    self._peer_name = None
                    self._host_ip   = self._local_ip
                    self._start_heartbeat()
                    self._on_role("host", self.local_db_path, None, self._local_ip)
                else:
                    logger.warning("Failed to start background Flask server. Running standalone.")
                    self._role = "standalone"
                    self._on_role("standalone", self.local_db_path, None, None)
        except Exception as e:
            logger.error("Error during LAN server negotiation: %s. Falling back to standalone.", e)
            self._role = "standalone"
            try:
                self._on_role("standalone", self.local_db_path, None, None)
            except Exception:
                pass

    def _check_server_reachable(self, host_ip: str) -> bool:
        """Verify that the Flask server is up and responding to API requests."""
        try:
            import urllib.request
            url = f"http://{host_ip}:{SYNC_PORT}/api/ping"
            with urllib.request.urlopen(url, timeout=2) as resp:
                return resp.status == 200
        except Exception as e:
            logger.debug("Server health check failed for %s: %s", host_ip, e)
            return False

    # ── Discovery (UDP Broadcast) ──────────────────────────────────────────────

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
            logger.debug("Sent discovery broadcast packet from %s", self._local_ip)
            
            deadline = time.time() + DISCOVER_TIMEOUT
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(512)
                    if data.startswith(HOST_PREFIX):
                        # Skip our own broadcast reply
                        if addr[0] == self._local_ip:
                            continue
                        payload = data[len(HOST_PREFIX):].decode("utf-8", errors="ignore")
                        parts    = payload.split("|")
                        host_ip  = parts[0] if parts else addr[0]
                        peer     = parts[1] if len(parts) > 1 else addr[0]
                        return host_ip, peer
                except socket.timeout:
                    break
                except OSError:
                    break
        except Exception as e:
            logger.debug("UDP Discovery error: %s", e)
        finally:
            sock.close()
        return None, None

    # ── Heartbeat Responder (HOST availability broadcast) ──────────────────────

    def _start_heartbeat(self) -> None:
        """Listen on the discovery port and reply to incoming client broadcasts."""
        def _responder_loop():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.settimeout(1.0)
            try:
                sock.bind(("", DISCOVER_PORT))
            except OSError as e:
                logger.error(
                    "Cannot bind discovery responder socket on port %d: %s. "
                    "Another app may be running on this port.", DISCOVER_PORT, e
                )
                return
            
            pc_name = _get_pc_name()
            reply   = HOST_PREFIX + f"{self._local_ip}|{pc_name}".encode("utf-8")
            logger.info("Host discovery responder listening on UDP port %d", DISCOVER_PORT)
            
            while not self._stop_evt.is_set():
                try:
                    data, addr = sock.recvfrom(512)
                    if data == DISCOVER_MSG:
                        sock.sendto(reply, addr)
                        logger.debug("Replied to client discovery broadcast from %s", addr[0])
                except socket.timeout:
                    continue
                except OSError:
                    break
            sock.close()
            logger.info("Host discovery responder stopped")

        self._responder = threading.Thread(
            target=_responder_loop, daemon=True, name="LanSync-heartbeat"
        )
        self._responder.start()
