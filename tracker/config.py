"""
Config loading and saving — reads/writes config.json next to the package root.
"""

import json
from .constants import CONFIG_FILE


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if "players_order" in cfg and isinstance(cfg["players_order"], list):
                flat = []
                for p in cfg["players_order"]:
                    flat.extend([n.strip() for n in str(p).split("\n") if n.strip()])
                cfg["players_order"] = flat
            return cfg
        except Exception:
            pass
    return {}


def save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
