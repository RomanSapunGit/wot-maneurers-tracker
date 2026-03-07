"""
WoT Maneuvers Tank Tracker — tkinter GUI
"""

import struct
import json
import time
import threading
import urllib.request
import urllib.parse
import tkinter as tk
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False
try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False
try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False
import sys
import traceback
from tkinter import ttk, filedialog, messagebox
from pathlib import Path

# ── constants ──────────────────────────────────────────────────────────────────

CONFIG_FILE              = Path(__file__).parent / "config.json"
APP_ID                   = "8520bbd86713bb4f2f6c4f2cd7a66d29"
INCOMPLETE_GRACE_SECONDS = 600
WATCH_POLL_INTERVAL      = 3

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


# ── log redirector ────────────────────────────────────────────────────────────

class LogRedirector:
    """Redirects writes to a tkinter Text widget. Thread-safe via after()."""
    def __init__(self, widget: "tk.Text", app: "tk.Tk", tag: str = "normal"):
        self.widget = widget
        self.app    = app
        self.tag    = tag

    def write(self, msg: str):
        if msg.strip():
            self.app.after(0, lambda m=msg, t=self.tag: self._insert(m, t))

    def _insert(self, msg: str, tag: str):
        self.widget.configure(state="normal")
        self.widget.insert("end", msg if msg.endswith("\n") else msg + "\n", tag)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


# ── config ─────────────────────────────────────────────────────────────────────

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


# ── tankopedia ─────────────────────────────────────────────────────────────────

def fetch_tag_to_name(app_id: str, realm: str, tier: int = 10, progress_cb=None) -> tuple[dict[str, str], dict[int, str]]:
    base_url    = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    tag_to_name: dict[str, str] = {}
    tank_id_to_name: dict[int, str] = {}
    page        = 1
    while True:
        enc = {
            "application_id": app_id,
            "fields": "tag,name,tank_id",
            "page_no": page,
            "limit": 100,
        }
        if tier and tier > 0:
            enc["tier"] = tier
        params = urllib.parse.urlencode(enc)
        url = f"{base_url}/wot/encyclopedia/vehicles/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            if progress_cb: progress_cb(f"[!] Tankopedia fetch error: {e}")
            break
        if data.get("status") != "ok":
            if progress_cb: progress_cb(f"[!] Tankopedia API error: {data.get('error', data)}")
            break
        for _, info in data["data"].items():
            if isinstance(info, dict) and "tag" in info and "name" in info:
                tag_to_name[info["tag"]] = info["name"]
                if "tank_id" in info:
                    tank_id_to_name[info["tank_id"]] = info["name"]
        meta        = data.get("meta", {})
        total_pages = meta.get("page_total", 1)
        if progress_cb:
            progress_cb(f"Tankopedia: page {page}/{total_pages} ({len(tag_to_name)} tanks)")
        if page >= total_pages:
            break
        page += 1
    return tag_to_name, tank_id_to_name


def resolve_vehicle_name(vehicle_type: str, tag_to_name: dict[str, str]) -> str | None:
    tag = vehicle_type.split(":", 1)[-1]
    return tag_to_name.get(tag)


# ── remaining tanks: Excel ─────────────────────────────────────────────────────

def _is_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def _normalize_excel_url(url: str) -> str:
    """
    Converts Google Sheets / Google Drive share URLs to a direct CSV export URL.
    Also passes through OneDrive and other direct links unchanged.
    """
    # Google Sheets: /spreadsheets/d/<ID>/edit... → export as CSV
    if "docs.google.com/spreadsheets" in url:
        import re
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
        if m:
            sheet_id = m.group(1)
            # Use gid if present, else default sheet
            gid_m = re.search(r"[#&?]gid=(\d+)", url)
            gid   = gid_m.group(1) if gid_m else "0"
            return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
    # Google Drive file link → direct download
    if "drive.google.com/file/d/" in url:
        import re
        m = re.search(r"/file/d/([a-zA-Z0-9_-]+)", url)
        if m:
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return url


def load_tanks_from_excel(path: str) -> dict[str, list[str] | str]:
    """
    Reads tank names from columns of an Excel file or URL.
    Assigns each column to a player (first non-numeric row is player name, rest are tanks).
    """
    result: dict[str, list[str] | str] = {}
    
    def _process_cells(cells):
        name = None
        tanks = []
        for cell in cells:
            if not name:
                # Skip small numbers at top (like row indices or ratings)
                if cell.isdigit() and len(cell) <= 3:
                    continue
                name = cell.replace("⭐", "").strip()
            else:
                t = cell.replace("⭐", "").strip()
                if t: tanks.append(t)
        if name:
            result[name.lower()] = tanks
            result[f"{name.lower()}_display"] = name

    if _is_url(path):
        if not HAS_PANDAS:
            return {}
        try:
            url = _normalize_excel_url(path)
            try:
                df = pd.read_csv(url, header=None)
            except Exception:
                df = pd.read_excel(url, header=None)
            for col_idx in range(df.shape[1]):
                col = df.iloc[:, col_idx].dropna().astype(str).str.strip()
                col = col[col != ""]
                if not col.empty:
                    _process_cells(list(col))
            return result
        except Exception as e:
            print(f"[!] Failed to load tank list from URL: {e}\n{traceback.format_exc()}", file=sys.stderr)
            return {}
    else:
        if not HAS_OPENPYXL:
            print("[!] openpyxl not installed — cannot read local Excel files", file=sys.stderr)
            return {}
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            for col in ws.iter_cols(values_only=True):
                cells = [str(x).strip() for x in col if x is not None and str(x).strip()]
                if cells:
                    _process_cells(cells)
            wb.close()
            return result
        except Exception as e:
            print(f"[!] Failed to load Excel file: {e}", file=sys.stderr)
            return {}


# ── remaining tanks: WoT API ───────────────────────────────────────────────────

def fetch_clan_member_ids(app_id: str, realm: str, clan_tag: str) -> list[int]:
    """Returns list of account_ids for all members of the given clan tag."""
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])

    # Search for clan
    params = urllib.parse.urlencode({
        "application_id": app_id,
        "search": clan_tag,
        "fields": "clan_id,tag",
        "limit": 10,
    })
    url = f"{base_url}/wot/clans/list/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[!] Clan search failed: {e}", file=sys.stderr)
        return []

    clan_id = None
    for clan in data.get("data", []):
        if clan.get("tag", "").upper() == clan_tag.upper():
            clan_id = clan["clan_id"]
            break
    if not clan_id:
        return []

    # Fetch clan members
    params = urllib.parse.urlencode({
        "application_id": app_id,
        "clan_id": clan_id,
        "fields": "members",
    })
    url = f"{base_url}/wot/clans/info/?{params}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        print(f"[!] Clan info fetch failed: {e}", file=sys.stderr)
        return []

    clan_data = data.get("data", {}).get(str(clan_id), {})
    members   = clan_data.get("members", [])
    return [m["account_id"] for m in members if "account_id" in m]


def fetch_tanks_for_accounts(
        app_id: str, realm: str, account_ids: list[int],
        tank_id_to_name: dict[int, str], tier: int,
        progress_cb=None,
) -> dict[int, list[str]]:

    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])

    valid_ids = set(tank_id_to_name.keys())
    result: dict[int, list[str]] = {}

    # 1. Fetch in batches
    batch_size = 100
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i + batch_size]
        params = urllib.parse.urlencode({
            "application_id": app_id,
            "account_id": ",".join(str(a) for a in batch),
            "fields": "tank_id",
        })
        url = f"{base_url}/wot/account/tanks/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=15) as resp:
                data = json.loads(resp.read())

            if data.get("status") == "ok":
                for acc_id_str, tanks in data.get("data", {}).items():
                    acc_id = int(acc_id_str)
                    if not tanks: continue

                    owned_names = [tank_id_to_name[t['tank_id']] for t in tanks
                                   if t.get("tank_id") in valid_ids]

                    if owned_names:
                        result[acc_id] = sorted(owned_names)

        except Exception as e:
            if progress_cb: progress_cb(f"Error fetching batch: {e}")

    return result


def fetch_account_names(app_id: str, realm: str, account_ids: list[int]) -> dict[int, str]:
    """Returns {account_id: nickname}."""
    base_url = REALM_URLS.get(realm.lower(), REALM_URLS["eu"])
    result: dict[int, str] = {}
    batch_size = 100
    for i in range(0, len(account_ids), batch_size):
        batch = account_ids[i:i + batch_size]
        params = urllib.parse.urlencode({
            "application_id": app_id,
            "account_id":     ",".join(str(a) for a in batch),
            "fields":         "nickname",
        })
        url = f"{base_url}/wot/account/info/?{params}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[!] Account names fetch failed: {e}", file=sys.stderr)
            continue
        for acc_id_str, info in data.get("data", {}).items():
            if info and "nickname" in info:
                result[int(acc_id_str)] = info["nickname"]
    return result


# ── replay parsing ─────────────────────────────────────────────────────────────

def parse_replay(path: Path) -> tuple[dict | None, dict | None]:
    try:
        with open(path, "rb") as f:
            data = f.read(12)
            if len(data) < 12:
                return None, None
            _, block_count, block1_size = struct.unpack("<III", data)
            
            b1_data = f.read(block1_size)
            if len(b1_data) < block1_size:
                return None, None
            try:
                block1 = json.loads(b1_data)
            except json.JSONDecodeError as e:
                print(f"[!] Failed to parse block 1 in {path.name}: {e}", file=sys.stderr)
                return None, None
            
            block2 = None
            if block_count >= 2:
                b2_size_data = f.read(4)
                if len(b2_size_data) == 4:
                    block2_size = struct.unpack("<I", b2_size_data)[0]
                    b2_data = f.read(block2_size)
                    if len(b2_data) == block2_size:
                        try:
                            block2 = json.loads(b2_data)
                        except json.JSONDecodeError as e:
                            print(f"[!] Failed to parse block 2 in {path.name}: {e}", file=sys.stderr)
                            # block2 stays None, but we STILL return block1
        return block1, block2
    except Exception as e:
        print(f"[!] Failed to parse replay {path.name}: {e}", file=sys.stderr)
        return None, None


def get_death_label(reason: int) -> str:
    return {-1: "Alive", 0: "Destroyed", 1: "Teamkilled", 2: "Drowned"}.get(
        reason, f"Unknown({reason})"
    )


def scan_replays(replays_dir, clan_tag, tag_to_name, already_parsed, battle_type_filter, record_since=0, log_cb=None):
    events  = []
    replays = sorted(replays_dir.glob("*.wotreplay"), key=lambda f: f.stat().st_mtime)

    for replay in replays:
        if replay.name in already_parsed:
            continue

        if replay.stat().st_mtime < record_since:
            already_parsed.add(replay.name)
            continue

        block1, block2 = parse_replay(replay)

        if block1 is None:
            age = time.time() - replay.stat().st_mtime
            if age > INCOMPLETE_GRACE_SECONDS:
                already_parsed.add(replay.name)
            continue

        battle_type = block1.get("battleType")
        if battle_type_filter is not None and battle_type not in battle_type_filter:
            already_parsed.add(replay.name)
            continue

        if block2 is None:
            age = time.time() - replay.stat().st_mtime
            if age <= INCOMPLETE_GRACE_SECONDS:
                if log_cb:
                    log_cb(f"[~] {replay.name} — in progress, retrying later")
                # Emit pending event so player shows up immediately
                battle_time = block1.get("dateTime", "?")
                map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))
                owner       = block1.get("playerName", "")
                owner_veh   = "?"
                owner_clan  = ""
                for sid, veh in block1.get("vehicles", {}).items():
                    if veh.get("name", "") == owner:
                        owner_clan = veh.get("clanAbbrev", "")
                        owner_veh  = veh.get("vehicleType", "?")
                        break
                if owner and owner_clan.upper() == clan_tag.upper():
                    veh_name = resolve_vehicle_name(owner_veh, tag_to_name)
                    if veh_name:
                        events.append({
                            "player":      owner,
                            "veh_tag":     owner_veh,
                            "veh_name":    veh_name,
                            "death_label": "Possibly destroyed",
                            "battle_time": battle_time,
                            "map":         map_name,
                            "pending":     True,
                            "replay_name": replay.name,
                        })
                continue

            # Old incomplete replay — mark owner as destroyed
            already_parsed.add(replay.name)
            battle_time = block1.get("dateTime", "?")
            map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))
            owner       = block1.get("playerName", "")
            owner_clan  = ""
            owner_veh   = "?"
            for sid, veh in block1.get("vehicles", {}).items():
                if veh.get("name", "") == owner:
                    owner_clan = veh.get("clanAbbrev", "")
                    owner_veh  = veh.get("vehicleType", "?")
                    break
            if owner and owner_clan.upper() == clan_tag.upper():
                veh_name = resolve_vehicle_name(owner_veh, tag_to_name)
                if veh_name:
                    if log_cb:
                        log_cb(f"[✗] {replay.name} — left early, marking {owner} destroyed")
                    events.append({
                        "player":      owner,
                        "veh_tag":     owner_veh,
                        "veh_name":    veh_name,
                        "death_label": "Destroyed (left battle)",
                        "battle_time": battle_time,
                        "map":         map_name,
                        "pending":     False,
                        "replay_name": replay.name,
                    })
            else:
                if log_cb:
                    log_cb(f"[✗] {replay.name} — left early, owner not in clan, skipping")
            continue

        already_parsed.add(replay.name)
        battle_time = block1.get("dateTime", "?")
        map_name    = block1.get("mapDisplayName", block1.get("mapName", "?"))

        id_to_veh = {
            sid: {
                "name":    veh.get("name", "?"),
                "clan":    veh.get("clanAbbrev", ""),
                "veh_tag": veh.get("vehicleType", "?"),
            }
            for sid, veh in block1.get("vehicles", {}).items()
        }

        battle_results = block2[0] if isinstance(block2, list) and block2 else (block2 or {})
        b2_vehicles = battle_results.get("vehicles", {})

        common = battle_results.get("common", {})
        winner_team = common.get("winnerTeam", -1)

        owner_team = None
        for sid, veh in block1.get("vehicles", {}).items():
            if veh.get("clanAbbrev", "").upper() == clan_tag.upper():
                owner_team = veh.get("team")
                if owner_team:
                    break
                    
        if not owner_team:
            for session_id, stats_data in b2_vehicles.items():
                stats = stats_data[0] if isinstance(stats_data, list) and stats_data else (stats_data if isinstance(stats_data, dict) else {})
                info = id_to_veh.get(str(session_id), {})
                if info and info.get("clan", "").upper() == clan_tag.upper():
                    owner_team = stats.get("team")
                    if owner_team:
                        break

        is_defeat = (owner_team and winner_team != owner_team)

        for session_id, stats_data in b2_vehicles.items():
            stats = stats_data[0] if isinstance(stats_data, list) and stats_data else (stats_data if isinstance(stats_data, dict) else {})
            info = id_to_veh.get(str(session_id), {})
            if not info or info.get("clan", "").upper() != clan_tag.upper():
                continue
                
            death_reason = stats.get("deathReason", -1)
            
            if battle_type == 20 and is_defeat and death_reason == -1:
                death_reason = 0
                
            if death_reason == -1:
                continue
                
            veh_name = resolve_vehicle_name(info["veh_tag"], tag_to_name)
            if veh_name is None:
                continue
            events.append({
                "player":      info["name"],
                "veh_tag":     info["veh_tag"],
                "veh_name":    veh_name,
                "death_label": get_death_label(death_reason),
                "battle_time": battle_time,
                "map":         map_name,
                "pending":     False,
                "replay_name": replay.name,
            })

        if log_cb:
            log_cb(f"[✓] {replay.name} — {battle_time}, {map_name}")

    return events, already_parsed


# ── settings window ────────────────────────────────────────────────────────────

class SettingsWindow(tk.Toplevel):
    def __init__(self, parent, cfg: dict, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.on_save = on_save

        pad = {"padx": 12, "pady": 6}

        tk.Label(self, text="Settings", font=FONT_H, bg=BG, fg=ACCENT).grid(
            row=0, column=0, columnspan=3, pady=(16, 8))

        # Replays path
        tk.Label(self, text="Replays folder", font=FONT, bg=BG, fg=TEXT).grid(
            row=1, column=0, sticky="w", **pad)
        self.path_var = tk.StringVar(value=cfg.get("replays_path", ""))
        tk.Entry(self, textvariable=self.path_var, width=42, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=FONT).grid(
            row=1, column=1, sticky="ew", **pad)
        tk.Button(self, text="Browse", command=self._browse_replay, bg=BG2, fg=ACCENT,
                  activebackground=ACCENT, activeforeground=BG, relief="flat",
                  font=FONT, cursor="hand2").grid(row=1, column=2, padx=(0, 12))

        # Clan tag
        tk.Label(self, text="Clan tag", font=FONT, bg=BG, fg=TEXT).grid(
            row=2, column=0, sticky="w", **pad)
        self.clan_var = tk.StringVar(value=cfg.get("clan_tag", ""))
        tk.Entry(self, textvariable=self.clan_var, width=12, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=FONT).grid(
            row=2, column=1, sticky="w", **pad)

        # Tier
        tk.Label(self, text="Tier filter", font=FONT, bg=BG, fg=TEXT).grid(
            row=3, column=0, sticky="w", **pad)
        self.tier_var = tk.IntVar(value=cfg.get("tier", 10))
        tier_frame = tk.Frame(self, bg=BG)
        tier_frame.grid(row=3, column=1, sticky="w", **pad)
        for t in range(1, 11):
            tk.Radiobutton(tier_frame, text=str(t), variable=self.tier_var, value=t,
                           bg=BG, fg=TEXT, selectcolor=BG2, activebackground=BG,
                           font=FONT).pack(side="left", padx=2)
        tk.Radiobutton(tier_frame, text="All", variable=self.tier_var, value=0,
                       bg=BG, fg=TEXT, selectcolor=BG2, activebackground=BG,
                       font=FONT).pack(side="left", padx=6)

        # Realm
        tk.Label(self, text="Realm", font=FONT, bg=BG, fg=TEXT).grid(
            row=4, column=0, sticky="w", **pad)
        self.realm_var = tk.StringVar(value=cfg.get("realm", "eu"))
        realm_frame = tk.Frame(self, bg=BG)
        realm_frame.grid(row=4, column=1, sticky="w", **pad)
        for r in ("eu", "na", "asia"):
            tk.Radiobutton(realm_frame, text=r.upper(), variable=self.realm_var, value=r,
                           bg=BG, fg=TEXT, selectcolor=BG2, activebackground=BG,
                           font=FONT).pack(side="left", padx=4)

        # Battle type
        tk.Label(self, text="Battle type", font=FONT, bg=BG, fg=TEXT).grid(
            row=5, column=0, sticky="w", **pad)
        self.bt_var = tk.StringVar(value=cfg.get("battle_type_choice", "2"))
        bt_frame = tk.Frame(self, bg=BG)
        bt_frame.grid(row=5, column=1, sticky="w", **pad)
        for key, (label, _) in BATTLE_TYPE_OPTIONS.items():
            tk.Radiobutton(bt_frame, text=label, variable=self.bt_var, value=key,
                           bg=BG, fg=TEXT, selectcolor=BG2, activebackground=BG,
                           font=FONT).pack(side="left", padx=4)

        # Excel file (optional)
        tk.Label(self, text="Tank list (Excel)", font=FONT, bg=BG, fg=TEXT).grid(
            row=6, column=0, sticky="w", **pad)
        self.excel_var = tk.StringVar(value=cfg.get("excel_path", ""))
        excel_entry = tk.Entry(self, textvariable=self.excel_var, width=42, bg=BG2, fg=TEXT,
                               insertbackground=TEXT, relief="flat", font=FONT)
        excel_entry.grid(row=6, column=1, sticky="ew", **pad)
        btn_frame = tk.Frame(self, bg=BG)
        btn_frame.grid(row=6, column=2, padx=(0, 12))
        tk.Button(btn_frame, text="Browse", command=self._browse_excel, bg=BG2, fg=ACCENT,
                  activebackground=ACCENT, activeforeground=BG, relief="flat",
                  font=FONT, cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(btn_frame, text="✕", command=lambda: self.excel_var.set(""),
                  bg=BG2, fg=RED, activebackground=RED, activeforeground=BG,
                  relief="flat", font=FONT, cursor="hand2", width=2).pack(side="left")
        tk.Label(self, text="URL or local path — falls back to WoT API", font=FONT_SM,
                 bg=BG, fg=TEXT_DIM).grid(row=7, column=1, sticky="w", padx=12, pady=(0, 4))

        # Players order
        tk.Label(self, text="Players order", font=FONT, bg=BG, fg=TEXT).grid(
            row=8, column=0, sticky="nw", padx=12, pady=6)
        order_frame = tk.Frame(self, bg=BG)
        order_frame.grid(row=8, column=1, sticky="ew", padx=12, pady=6)
        self.order_text = tk.Text(order_frame, bg=BG2, fg=TEXT, insertbackground=TEXT,
                                  relief="flat", font=FONT, height=4, width=36,
                                  wrap="none")
        order_sb = ttk.Scrollbar(order_frame, orient="vertical", command=self.order_text.yview)
        self.order_text.configure(yscrollcommand=order_sb.set)
        self.order_text.grid(row=0, column=0, sticky="nsew")
        order_sb.grid(row=0, column=1, sticky="ns")
        order_frame.columnconfigure(0, weight=1)
        existing_order = "\n".join(cfg.get("players_order", []))
        self.order_text.insert("1.0", existing_order)
        tk.Label(self, text="one name per line — shown first in Remaining Tanks",
                 font=FONT_SM, bg=BG, fg=TEXT_DIM).grid(
            row=9, column=1, sticky="w", padx=12, pady=(0, 4))

        # Record since timestamp
        tk.Label(self, text="Record since", font=FONT, bg=BG, fg=TEXT).grid(
            row=10, column=0, sticky="nw", padx=12, pady=6)
        
        default_ts = cfg.get("record_since", time.time() - 7200)
        dt_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(default_ts))
        self.record_since_var = tk.StringVar(value=dt_str)
        
        rs_frame = tk.Frame(self, bg=BG)
        rs_frame.grid(row=10, column=1, sticky="w", padx=12, pady=6)
        tk.Entry(rs_frame, textvariable=self.record_since_var, width=20, bg=BG2, fg=TEXT,
                 insertbackground=TEXT, relief="flat", font=FONT).pack(side="left")
        tk.Label(rs_frame, text=" (YYYY-MM-DD HH:MM:SS)", font=FONT_SM, bg=BG, fg=TEXT_DIM).pack(side="left")

        # Save button
        tk.Button(self, text="Save & Start", command=self._save,
                  bg=ACCENT, fg=BG, activebackground=TEXT, activeforeground=BG,
                  relief="flat", font=FONT_BOLD, cursor="hand2", padx=16, pady=6).grid(
            row=11, column=0, columnspan=3, pady=(8, 16))

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _browse_replay(self):
        path = filedialog.askdirectory(title="Select replays folder")
        if path:
            self.path_var.set(path)

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Select tank list Excel file",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        if path:
            self.excel_var.set(path)

    def _save(self):
        path = self.path_var.get().strip()
        clan = self.clan_var.get().strip().upper()
        if not path or not clan:
            messagebox.showerror("Missing fields", "Replays path and clan tag are required.",
                                 parent=self)
            return
            
        try:
            record_since = time.mktime(time.strptime(self.record_since_var.get().strip(), '%Y-%m-%d %H:%M:%S'))
        except ValueError:
            messagebox.showerror("Invalid Date format", "Record since must be YYYY-MM-DD HH:MM:SS",
                                 parent=self)
            return

        raw_order  = self.order_text.get("1.0", "end").split("\n")
        order_list = [n.strip() for n in raw_order if n.strip()]
        cfg = {
            "replays_path":       path,
            "clan_tag":           clan,
            "realm":              self.realm_var.get(),
            "battle_type_choice": self.bt_var.get(),
            "tier":               self.tier_var.get(),
            "excel_path":         self.excel_var.get().strip(),
            "players_order":      order_list,
            "record_since":       record_since,
        }
        save_config(cfg)
        self.on_save(cfg)
        self.destroy()


# ── main window ────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WoT Maneuvers Tank Tracker")
        self.configure(bg=BG)
        self.geometry("900x680")
        self.minsize(700, 500)

        self._cfg             = load_config()
        self._tag_to_name:    dict[str, str]   = {}
        self._tank_id_to_name: dict[int, str]  = {}
        self._already_parsed: set[str]         = set()
        self._destroyed:      dict[str, list]  = {}
        self._battle_filter:  list[int] | None = [20]
        self._pending_keys:   set[str]         = set()
        self._replays_dir:    Path | None      = None
        self._observer:       Observer | None  = None
        self._watcher:        threading.Thread | None = None
        self._watcher_stop    = threading.Event()

        # Remaining tanks data: list of tank names (from excel or API)
        # and per-player owned tanks if from API
        self._remaining_tanks:  list[str]             = []  # excel mode: flat list
        self._member_tanks:     dict[str, list[str]]  = {}  # api mode: player→[tanks]
        self._remaining_source: str                   = ""  # "excel" | "api" | ""

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self._cfg.get("replays_path") or not self._cfg.get("clan_tag"):
            self.after(100, self._open_settings)
        else:
            self.after(100, lambda: self._apply_config(self._cfg))

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Top bar
        top = tk.Frame(self, bg=BG, pady=8)
        top.pack(fill="x", padx=12)
        tk.Label(top, text="💥 WoT Maneuvers Tracker", font=FONT_H,
                 bg=BG, fg=ACCENT).pack(side="left")
        btn_frame = tk.Frame(top, bg=BG)
        btn_frame.pack(side="right")
        self._status_lbl = tk.Label(btn_frame, text="Not started", font=FONT_SM,
                                    bg=BG, fg=TEXT_DIM)
        self._status_lbl.pack(side="left", padx=12)
        for text, cmd in [("⚙ Settings", self._open_settings),
                          ("🔄 Scan now", self._manual_scan),
                          ("🗑 Reset", self._reset)]:
            tk.Button(btn_frame, text=text, command=cmd, bg=BG2, fg=TEXT,
                      activebackground=ACCENT, activeforeground=BG,
                      relief="flat", font=FONT, cursor="hand2",
                      padx=10, pady=4).pack(side="left", padx=3)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12)

        # Notebook (tabs)
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Tracker.Treeview",
                        background=BG2, foreground=TEXT,
                        fieldbackground=BG2, rowheight=24,
                        font=FONT, borderwidth=0)
        style.configure("Tracker.Treeview.Heading",
                        background=BG, foreground=ACCENT,
                        font=FONT_BOLD, relief="flat")
        style.map("Tracker.Treeview",
                  background=[("selected", "#3a3a5e")],
                  foreground=[("selected", TEXT)])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG2, foreground=TEXT_DIM,
                        font=FONT, padding=(12, 6))
        style.map("TNotebook.Tab",
                  background=[("selected", BG)],
                  foreground=[("selected", ACCENT)])

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=8)

        # ── Tab 1: Destroyed vehicles ──
        tab1 = tk.Frame(nb, bg=BG)
        nb.add(tab1, text="💀 Destroyed Vehicles")

        pane1 = tk.PanedWindow(tab1, orient="vertical", bg=BG, sashwidth=5)
        pane1.pack(fill="both", expand=True)

        tree_outer = tk.Frame(pane1, bg=BG)
        pane1.add(tree_outer, minsize=200)

        tree_frame = tk.Frame(tree_outer, bg=BG)
        tree_frame.pack(fill="both", expand=True)

        self._tree = ttk.Treeview(tree_frame, style="Tracker.Treeview",
                                  columns=("tank", "status", "map", "time"),
                                  show="tree headings", selectmode="browse")
        self._tree.heading("#0",     text="Player")
        self._tree.heading("tank",   text="Tank")
        self._tree.heading("status", text="Status")
        self._tree.heading("map",    text="Map")
        self._tree.heading("time",   text="Time")
        self._tree.column("#0",     width=160, minwidth=120)
        self._tree.column("tank",   width=200, minwidth=140)
        self._tree.column("status", width=180, minwidth=100)
        self._tree.column("map",    width=140, minwidth=100)
        self._tree.column("time",   width=130, minwidth=100)
        vsb = ttk.Scrollbar(tree_frame, orient="vertical",   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient="horizontal", command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        log_frame = tk.Frame(pane1, bg=BG)
        pane1.add(log_frame, minsize=80)
        tk.Label(log_frame, text="LOG", font=FONT_BOLD, bg=BG, fg=TEXT_DIM).pack(
            anchor="w", pady=(4, 2))
        log_inner = tk.Frame(log_frame, bg=BG)
        log_inner.pack(fill="both", expand=True)
        self._log = tk.Text(log_inner, bg=BG2, fg=TEXT_DIM, font=FONT_SM,
                            relief="flat", state="disabled", wrap="none",
                            height=6, insertbackground=TEXT)
        log_vsb = ttk.Scrollbar(log_inner, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=log_vsb.set)
        self._log.grid(row=0, column=0, sticky="nsew")
        log_vsb.grid(row=0, column=1, sticky="ns")
        log_inner.rowconfigure(0, weight=1)
        log_inner.columnconfigure(0, weight=1)

        # Configure log text tags
        self._log.tag_configure("normal", foreground=TEXT_DIM)
        self._log.tag_configure("error",  foreground=RED)
        self._log.tag_configure("warn",   foreground=YELLOW)

        # Redirect stdout and stderr to the log widget
        sys.stdout = LogRedirector(self._log, self, tag="normal")
        sys.stderr = LogRedirector(self._log, self, tag="error")

        # ── Tab 2: Remaining tanks ──
        tab2 = tk.Frame(nb, bg=BG)
        nb.add(tab2, text="🛡 Remaining Tanks")

        rem_top = tk.Frame(tab2, bg=BG)
        rem_top.pack(fill="x", pady=(8, 4))
        self._remaining_lbl = tk.Label(rem_top, text="Loading…", font=FONT_SM,
                                       bg=BG, fg=TEXT_DIM)
        self._remaining_lbl.pack(side="left", padx=4)
        tk.Button(rem_top, text="🔄 Refresh", command=self._load_remaining,
                  bg=BG2, fg=TEXT, activebackground=ACCENT, activeforeground=BG,
                  relief="flat", font=FONT, cursor="hand2",
                  padx=8, pady=3).pack(side="right", padx=4)

        rem_frame = tk.Frame(tab2, bg=BG)
        rem_frame.pack(fill="both", expand=True)

        self._rem_tree = ttk.Treeview(rem_frame, style="Tracker.Treeview",
                                      columns=("tank", "owner", "status"),
                                      show="tree headings", selectmode="browse")
        self._rem_tree.heading("#0",     text="")
        self._rem_tree.heading("tank",   text="Tank")
        self._rem_tree.heading("owner",  text="Owner")
        self._rem_tree.heading("status", text="Status")
        self._rem_tree.column("#0",     width=0, minwidth=0, stretch=False)
        self._rem_tree.column("tank",   width=260, minwidth=160)
        self._rem_tree.column("owner",  width=160, minwidth=120)
        self._rem_tree.column("status", width=160, minwidth=100)
        rem_vsb = ttk.Scrollbar(rem_frame, orient="vertical",   command=self._rem_tree.yview)
        rem_hsb = ttk.Scrollbar(rem_frame, orient="horizontal", command=self._rem_tree.xview)
        self._rem_tree.configure(yscrollcommand=rem_vsb.set, xscrollcommand=rem_hsb.set)
        self._rem_tree.grid(row=0, column=0, sticky="nsew")
        rem_vsb.grid(row=0, column=1, sticky="ns")
        rem_hsb.grid(row=1, column=0, sticky="ew")
        rem_frame.rowconfigure(0, weight=1)
        rem_frame.columnconfigure(0, weight=1)

    # ── helpers ────────────────────────────────────────────────────────────────

    def _log_msg(self, msg: str):
        msg_lower = msg.lower()
        if any(w in msg_lower for w in ("error", "failed", "exception", "[!")):
            tag = "error"
        elif any(w in msg_lower for w in ("warning", "warn", "[~]", "retry")):
            tag = "warn"
        else:
            tag = "normal"
        ts = time.strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert("end", f"[{ts}] {msg}\n", tag)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_status(self, msg: str, colour: str = TEXT_DIM):
        self._status_lbl.configure(text=msg, fg=colour)

    def _open_settings(self):
        SettingsWindow(self, self._cfg, on_save=self._apply_config)

    def _apply_config(self, cfg: dict):
        self._cfg = cfg
        replays_path = Path(cfg["replays_path"])
        if (replays_path / "replays").exists():
            replays_path = replays_path / "replays"
        if not replays_path.exists():
            messagebox.showerror("Path not found", f"Replays folder not found:\n{replays_path}")
            return
        self._replays_dir  = replays_path
        bt_choice          = cfg.get("battle_type_choice", "2")
        _, self._battle_filter = BATTLE_TYPE_OPTIONS.get(bt_choice, BATTLE_TYPE_OPTIONS["2"])
        self._set_status("Loading tankopedia…", ACCENT)
        threading.Thread(target=self._load_tankopedia, daemon=True).start()

    def _load_tankopedia(self):
        def progress(msg):
            self.after(0, lambda: self._log_msg(msg))
            self.after(0, lambda: self._set_status(msg, ACCENT))
        self._tag_to_name, self._tank_id_to_name = fetch_tag_to_name(
            APP_ID, self._cfg.get("realm", "eu"),
            self._cfg.get("tier", 10), progress
        )
        self.after(0, self._on_tankopedia_ready)

    def _on_tankopedia_ready(self):
        self._log_msg(f"Tankopedia loaded: {len(self._tag_to_name)} tanks")
        self._set_status(f"Watching [{self._cfg['clan_tag']}]", GREEN)
        self._already_parsed.clear()
        self._destroyed.clear()
        self._do_scan()
        self._start_watcher()
        self._load_remaining()

    # ── remaining tanks ────────────────────────────────────────────────────────

    def _load_remaining(self):
        """Load tank list from Excel/URL if configured, else fetch from WoT API."""
        excel_path = self._cfg.get("excel_path", "").strip()
        if excel_path and (_is_url(excel_path) or Path(excel_path).exists()):
            self._load_remaining_excel(excel_path)
        else:
            self._load_remaining_api()

    def _load_remaining_excel(self, path: str):
        self._remaining_lbl.configure(text="Loading from Excel…", fg=ACCENT)
        def run():
            names = load_tanks_from_excel(path)
            self.after(0, lambda: self._on_remaining_excel(names))
        threading.Thread(target=run, daemon=True).start()

    def _on_remaining_excel(self, named_tanks: dict):
        self._member_tanks     = named_tanks
        self._remaining_tanks  = []
        self._remaining_source = "excel"
        tier = self._cfg.get("tier", 10)
        
        total_tanks = sum(len(v) for k, v in named_tanks.items() if not k.endswith("_display"))
        total_players = len(named_tanks) // 2

        self._remaining_lbl.configure(
            text=f"Source: Excel — {total_tanks} tanks across {total_players} members (Tier {tier if tier else 'All'})",
            fg=TEXT_DIM
        )
        self._log_msg(f"[tanks] Loaded {total_tanks} tanks for {total_players} players from Excel")
        self._refresh_remaining()

    def _load_remaining_api(self):
        if not self._cfg.get("clan_tag"):
            return
        self._remaining_lbl.configure(text="Fetching clan tanks from API…", fg=ACCENT)
        def run():
            def progress(msg):
                self.after(0, lambda m=msg: self._log_msg(f"[tanks] {m}"))
            realm    = self._cfg.get("realm", "eu")
            clan_tag = self._cfg["clan_tag"]
            tier     = self._cfg.get("tier", 10)

            progress(f"Looking up clan [{clan_tag}]…")
            acc_ids = fetch_clan_member_ids(APP_ID, realm, clan_tag)
            if not acc_ids:
                msg = f"[!] Could not find clan [{clan_tag}] on {realm.upper()}"
                self.after(0, lambda m=msg: self._remaining_lbl.configure(text=m, fg=RED))
                return

            progress(f"Found {len(acc_ids)} members, fetching tank lists…")
            # Fetch tanks (returns {id: [tanks]})
            member_tanks_by_id = fetch_tanks_for_accounts(APP_ID, realm, acc_ids,
                                                          self._tank_id_to_name, tier, progress)
            self.after(0, lambda: self._on_remaining_api(member_tanks_by_id, tier))
        threading.Thread(target=run, daemon=True).start()

    def _on_remaining_api(self, member_tanks_by_id: dict, tier: int):
        realm = self._cfg.get("realm", "eu")

        def run_mapping():
            acc_ids = list(member_tanks_by_id.keys())
            if not acc_ids:
                return self.after(0, lambda: self._finalize_api_data({}, tier))

            id_to_name = fetch_account_names(APP_ID, realm, acc_ids)

            named_tanks = {}
            for acc_id, tanks in member_tanks_by_id.items():
                nickname = id_to_name.get(acc_id)
                if nickname:
                    named_tanks[nickname.lower()] = tanks
                    named_tanks[f"{nickname.lower()}_display"] = nickname

            self.after(0, lambda: self._finalize_api_data(named_tanks, tier))

        threading.Thread(target=run_mapping, daemon=True).start()

    def _finalize_api_data(self, named_tanks, tier):
        self._member_tanks = named_tanks
        self._remaining_tanks = []
        self._remaining_source = "api"
        total = sum(len(v) for k, v in named_tanks.items() if not k.endswith("_display"))

        self._remaining_lbl.configure(
            text=f"API Load: {total} tanks (Tier {tier if tier else 'All'})",
            fg=TEXT_DIM
        )
        self._log_msg(f"[tanks] Successfully mapped {len(named_tanks) // 2} players")
        self._refresh_remaining()

    def _refresh_remaining(self):
        self._rem_tree.delete(*self._rem_tree.get_children())

        # 1. Normalize destroyed names to lowercase for robust matching
        player_destroyed: dict[str, set[str]] = {}
        for player, entries in self._destroyed.items():
            p_low = player.lower().strip()
            for e in entries:
                is_pending = e[4] if len(e) > 4 else False
                if not is_pending:
                    # e[0] is the Tank Name
                    player_destroyed.setdefault(p_low, set()).add(e[0].strip())

        players_order = self._cfg.get("players_order", [])

        # If no order, just use everyone we have data for
        if not players_order:
            if self._remaining_source in ("api", "excel"):
                # Get all unique nicknames from the member_tanks keys (using _display helper)
                players_order = sorted([v for k, v in self._member_tanks.items() if str(k).endswith("_display")])
            else:
                players_order = sorted(self._destroyed.keys())

        for player_input in players_order:
            p_low = player_input.lower().strip()

            # 2. Get the list of all tanks this player owns
            if self._remaining_source in ("api", "excel"):
                all_tanks = self._member_tanks.get(p_low, [])
                display_name = self._member_tanks.get(f"{p_low}_display", player_input)
            else:
                all_tanks = self._remaining_tanks
                display_name = player_input

            # 3. Intersection Logic
            dead_names = player_destroyed.get(p_low, set())

            # IMPORTANT: Case-insensitive tank matching
            # Sometimes API says "T-100 LT" and Replay says "T-100 lt"
            available = []
            destroyed = []

            # Map of lower names for comparison
            dead_names_lower = {d.lower() for d in dead_names}

            for t in all_tanks:
                if t.lower().strip() in dead_names_lower:
                    destroyed.append(t)
                else:
                    available.append(t)

            # Add "Extra" dead tanks found in replays that weren't in the API list
            all_tanks_lower = {t.lower().strip() for t in all_tanks}
            for d in dead_names:
                if d.lower().strip() not in all_tanks_lower:
                    destroyed.append(d)

            # Sort results
            available.sort()
            destroyed.sort()

            # 4. UI Insertion
            if not available and not destroyed:
                # Still show the player name so we know the app tried to load them
                self._rem_tree.insert("", "end", values=(f"👤 {display_name} (No tanks found)", "", ""))
                continue

            parent = self._rem_tree.insert("", "end", values=(f"👤 {display_name}", "", ""),
                                           tags=("player_header",), open=True)

            if available:
                avail_node = self._rem_tree.insert(parent, "end", values=(f"✅ Available ({len(available)})", "", ""),
                                                   tags=("group_header",), open=True)
                for t in available:
                    self._rem_tree.insert(avail_node, "end", values=(t, display_name, "✅ Available"), tags=("alive",))

            if destroyed:
                dead_node = self._rem_tree.insert(parent, "end", values=(f"💀 Destroyed ({len(destroyed)})", "", ""),
                                                  tags=("group_dead",), open=False)
                for t in destroyed:
                    self._rem_tree.insert(dead_node, "end", values=(t, display_name, "💀 Destroyed"), tags=("dead",))

        self._rem_tree.tag_configure("player_header", foreground=ACCENT, font=FONT_BOLD)
        self._rem_tree.tag_configure("group_header", foreground=GREEN)
        self._rem_tree.tag_configure("group_dead", foreground=RED)

    # ── destroyed tab ──────────────────────────────────────────────────────────

    def _start_watcher(self):
        self._stop_watcher()
        self._watcher_stop.clear()
        if HAS_WATCHDOG:
            app_ref = self
            class ReplayHandler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory and event.src_path.endswith(".wotreplay"):
                        app_ref.after(0, lambda: app_ref._do_scan(silent=True))
                def on_modified(self, event):
                    if not event.is_directory and event.src_path.endswith(".wotreplay"):
                        app_ref.after(0, lambda: app_ref._do_scan(silent=True))
            self._observer = Observer()
            self._observer.schedule(ReplayHandler(), str(self._replays_dir), recursive=False)
            self._observer.start()
            self._log_msg("[watcher] Using watchdog (OS native events)")
        else:
            self._log_msg(f"[watcher] Polling every {WATCH_POLL_INTERVAL}s")
            def poll():
                known: set = set()
                while not self._watcher_stop.is_set():
                    time.sleep(WATCH_POLL_INTERVAL)
                    if self._replays_dir:
                        current = set(self._replays_dir.glob("*.wotreplay"))
                        if current != known:
                            known = current
                            self.after(0, lambda: self._do_scan(silent=True))
            self._watcher = threading.Thread(target=poll, daemon=True, name="replay-poll")
            self._watcher.start()

    def _stop_watcher(self):
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        if self._watcher and self._watcher.is_alive():
            self._watcher_stop.set()
            self._watcher = None

    def _do_scan(self, silent: bool = False):
        if not self._replays_dir or not self._tag_to_name:
            return
        def run():
            new_events, _ = scan_replays(
                self._replays_dir, self._cfg["clan_tag"],
                self._tag_to_name, self._already_parsed, self._battle_filter,
                self._cfg.get("record_since", time.time() - 7200),
                log_cb=lambda msg: self.after(0, lambda m=msg: self._log_msg(m)),
            )
            self.after(0, lambda: self._apply_events(new_events, silent))
        threading.Thread(target=run, daemon=True).start()

    def _apply_events(self, events: list[dict], silent: bool):
        new_count = 0
        for ev in events:
            player      = ev["player"]
            replay_name = ev.get("replay_name", "")
            is_pending  = ev.get("pending", False)
            self._destroyed.setdefault(player, [])

            if not is_pending:
                # Remove matching pending entry for this replay
                if replay_name in self._pending_keys:
                    self._pending_keys.discard(replay_name)
                    self._destroyed[player] = [
                        e for e in self._destroyed[player]
                        if not (len(e) > 4 and e[4] and len(e) > 5 and e[5] == replay_name)
                    ]
                existing = [(e[0], e[1], e[2], e[3]) for e in self._destroyed[player]]
                if (ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"]) not in existing:
                    self._destroyed[player].append(
                        (ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"], False, replay_name)
                    )
                    new_count += 1
            else:
                if replay_name not in self._pending_keys:
                    self._pending_keys.add(replay_name)
                    self._destroyed[player].append(
                        (ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"], True, replay_name)
                    )
                    new_count += 1

        # Always refresh if anything changed (new events or pending upgrades)
        changed = new_count > 0 or len(events) > 0
        if changed or not silent:
            self._refresh_tree()
            self._refresh_remaining()

        if new_count > 0:
            self._set_status(f"Last scan: {time.strftime('%H:%M:%S')} — {new_count} new event(s)", ACCENT)
        elif not silent:
            self._set_status(f"Last scan: {time.strftime('%H:%M:%S')} — no new events", TEXT_DIM)

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())
        
        players_order = self._cfg.get("players_order", [])
        if not players_order:
            if self._remaining_source in ("api", "excel"):
                players_order = sorted([v for k, v in self._member_tanks.items() if str(k).endswith("_display")])
            else:
                players_order = sorted(self._destroyed.keys())

        player_destroyed_lower = {k.lower().strip(): (k, v) for k, v in self._destroyed.items()}

        for player_input in players_order:
            p_low = player_input.lower().strip()
            actual_player = player_input
            entries = []

            if p_low in player_destroyed_lower:
                actual_player, entries = player_destroyed_lower[p_low]
            else:
                for d_low, (d_actual, d_ents) in player_destroyed_lower.items():
                    if p_low in d_low or d_low in p_low:
                        actual_player, entries = d_actual, d_ents
                        break

            node = self._tree.insert("", "end", text=f"👤 {actual_player}",
                                     open=True, tags=("player",))
            
            if not entries:
                self._tree.insert(node, "end", text="",
                                  values=("(No vehicles destroyed yet)", "", "", ""),
                                  tags=("entry",))
            else:
                for entry in entries:
                    tank, status, map_name, battle_time = entry[0], entry[1], entry[2], entry[3]
                    is_pending  = entry[4] if len(entry) > 4 else False
                    tag         = "pending" if is_pending else "entry"
                    disp_status = f"❓ {status}" if is_pending else status
                    self._tree.insert(node, "end", text="",
                                      values=(tank, disp_status, map_name, battle_time),
                                      tags=(tag,))
                                      
        self._tree.tag_configure("player",  foreground=ACCENT)
        self._tree.tag_configure("entry",   foreground=TEXT)
        self._tree.tag_configure("pending", foreground=YELLOW)

    def _manual_scan(self):
        self._log_msg("Manual scan triggered.")
        self._do_scan(silent=False)

    def _reset(self):
        if messagebox.askyesno("Reset",
                               "Clear all destroyed vehicle data?\nOnly replays from this point forward will be tracked.",
                               parent=self):
            self._destroyed.clear()
            self._pending_keys.clear()
            self._cfg["record_since"] = time.time()
            save_config(self._cfg)
            self._refresh_tree()
            self._refresh_remaining()
            if self._replays_dir:
                self._already_parsed = set(
                    r.name for r in self._replays_dir.glob("*.wotreplay")
                )
            self._log_msg(f"State reset at {time.strftime('%H:%M:%S')} — tracking from now on.")
            self._set_status(f"Reset at {time.strftime('%H:%M:%S')} — waiting for new replays", TEXT_DIM)

    def _on_close(self):
        self._stop_watcher()
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        self.destroy()


# ── entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()