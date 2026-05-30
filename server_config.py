"""
server_config.py — Persistent server connection configuration for PayrollPro.
Stores the central server IP/port so the app knows where to connect.
Config is saved to a local JSON file next to the database.
"""
import json
import os

_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server_config.json")

DEFAULT_PORT = 5050


def get_server_config() -> dict:
    """Returns {"ip": str|None, "port": int, "enabled": bool}"""
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {
                    "ip":      data.get("ip") or None,
                    "port":    int(data.get("port", DEFAULT_PORT)),
                    "enabled": bool(data.get("enabled", False)),
                }
        except Exception:
            pass
    return {"ip": None, "port": DEFAULT_PORT, "enabled": False}


def save_server_config(ip: str | None, port: int = DEFAULT_PORT, enabled: bool = True):
    """Persist server connection settings to disk."""
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump({"ip": ip or "", "port": int(port), "enabled": bool(enabled)}, f, indent=2)


def clear_server_config():
    """Reset to standalone mode."""
    save_server_config(ip=None, port=DEFAULT_PORT, enabled=False)
