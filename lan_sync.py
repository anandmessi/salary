"""
lan_sync.py — DEPRECATED.
LAN UDP peer-to-peer sync has been replaced by the central server model.
The desktop app now reads server_config.py to decide whether to connect
to a remote Flask server or run in standalone mode.

Kept as a no-op stub so any lingering imports don't break the process.
"""


class LanSync:
    """No-op stub. The real sync is now handled by SyncClient + sync_server.py."""

    def __init__(self, db_path, on_role_decided):
        pass

    def start(self):
        pass

    def stop(self):
        pass
