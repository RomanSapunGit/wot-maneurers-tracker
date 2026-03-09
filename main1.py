"""
WoT Maneuvers Tank Tracker — entry point.

All application logic lives in the `tracker` package:
  tracker/constants.py          — constants & UI theme
  tracker/config.py             — config load/save
  tracker/tankopedia.py         — Tankopedia API helpers
  tracker/wot_api.py            — WoT clan/account API helpers
  tracker/replay_parser.py      — .wotreplay parsing & scanning
  tracker/excel.py              — Excel/URL I/O for destructions & tank lists
  tracker/ui/log_redirector.py  — stdout/stderr → tkinter Text widget
  tracker/ui/settings_window.py — Settings dialog
  tracker/ui/app.py             — Main application window (App)
"""

from tracker.ui.app import App


if __name__ == "__main__":
    app = App()
    app.mainloop()