"""
Application-wide constants and UI theme values.
"""

import threading
from pathlib import Path

# ── file / API constants ────────────────────────────────────────────────────────

CONFIG_FILE              = Path(__file__).parent.parent / "config.json"
APP_ID                   = "8520bbd86713bb4f2f6c4f2cd7a66d29"
INCOMPLETE_GRACE_SECONDS = 600
WATCH_POLL_INTERVAL      = 3
EXCEL_LOCK               = threading.Lock()

BATTLE_TYPE_OPTIONS = {
    "1": ("Random battles",   [1]),
    "2": ("Maneuvers only",   [20]),
    "3": ("All battle types", None),
}

REALM_URLS = {
    "eu":   "https://api.worldoftanks.eu",
    "na":   "https://api.worldoftanks.com",
    "asia": "https://api.worldoftanks.asia",
}

# ── UI theme ────────────────────────────────────────────────────────────────────

BG        = "#1e1e2e"
BG2       = "#2a2a3e"
ACCENT    = "#f5a623"
TEXT      = "#e0e0e0"
TEXT_DIM  = "#888888"
RED       = "#e05555"
GREEN     = "#55e09a"
YELLOW    = "#f5e642"
FONT      = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_SM   = ("Segoe UI", 9)
FONT_H    = ("Segoe UI", 13, "bold")
