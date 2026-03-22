"""
App — main tkinter application window and orchestrator of all tracker components.
"""

import sys
import time
import asyncio
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    HAS_WATCHDOG = True
except ImportError:
    HAS_WATCHDOG = False

from tracker.constants import (
    APP_ID, BATTLE_TYPE_OPTIONS, WATCH_POLL_INTERVAL,
    BG, BG2, ACCENT, TEXT, TEXT_DIM, RED, GREEN, YELLOW,
    FONT, FONT_BOLD, FONT_SM, FONT_H,
)
from tracker.config import load_config, save_config
from tracker.tankopedia import fetch_tag_to_name
from tracker.wot_api import (
    fetch_clan_member_ids,
    fetch_tanks_for_accounts,
    fetch_account_names,
)
from tracker.replay_parser import scan_replays
from tracker.excel import record_destruction, load_tanks_from_excel, _is_url
from tracker.ui.log_redirector import LogRedirector
from tracker.ui.settings_window import SettingsWindow
from tracker.server import TankServer


CYRILLIC_FALLBACK = {
    'Об. 260':   'ussr:R100_Object_260',
    'Об. 277':   'ussr:R149_Object_277',
    'СТ-ІІ':     'ussr:R159_ST_II',
    'ИС-4':      'ussr:R10_IS-4M',
    'Об. 279(р)':'ussr:R152_Object_279_early',
    'Об. 780':   'ussr:R176_Object_780',
    'Об. 452К':  'ussr:R178_Object_452K',
    'ИС-7':      'ussr:R45_IS-7',
    'Об. 140':   'ussr:R97_Object_140',
    'Об. 430у':  'ussr:R99_Object_430U',
    'Об. 907':   'ussr:R148_Object_907',
    'Об. 268/4':'ussr:R153_Object_268_v4',
    'Об. 268':   'ussr:R68_Object_268',
}

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WoT Maneuvers Tank Tracker")
        self.configure(bg=BG)
        self.geometry("900x680")
        self.minsize(700, 500)

        self._cfg              = load_config()
        self._tag_to_name:     dict[str, dict]        = {}
        self._tank_id_to_name: dict[int, dict]        = {}
        self._name_to_tag:     dict[str, str]         = {}
        self._acc_id_to_name:  dict[int, str]         = {}
        self._already_parsed:  set[str]               = set()
        self._destroyed:       dict[str, list]        = {}
        self._battle_filter:   list[int] | None       = [20]
        self._pending_keys:    set[str]               = set()
        self._replays_dir:     Path | None            = None
        self._observer:        "Observer | None"      = None
        self._watcher:         threading.Thread | None = None
        self._watcher_stop     = threading.Event()

        # Remaining tanks data
        self._remaining_tanks:  list[str]            = []   # excel mode: flat list
        self._member_tanks:     dict[str, list[str]] = {}   # api mode: player→[tanks]
        self._remaining_source: str                  = ""   # "excel" | "api" | ""
        self._clan_members:     set[str]             = set()
        self._server:           TankServer           = TankServer(port=8082, get_tanks_cb=self._get_tanks_for_server)


        # Asyncio infrastructure
        self._loop = asyncio.new_event_loop()
        self._destruction_queue = asyncio.Queue()
        self._async_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._async_thread.start()

        self._server.start()
        self._build_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        if not self._cfg.get("replays_path") or not self._cfg.get("clan_tag"):
            self.after(100, self._open_settings)
        else:
            self.after(100, lambda: self.submit_async(self._apply_config_async(self._cfg)))

    # ── async infrastructure ────────────────────────────────────────────────────

    def _run_async_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._destruction_worker())
        self._loop.run_forever()

    def submit_async(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def _destruction_worker(self):
        """Consume and process destruction events from the queue sequentially."""
        while True:
            args = await self._destruction_queue.get()
            try:
                await asyncio.to_thread(record_destruction, *args)
            except Exception as e:
                print(f"[!] Destruction worker error: {e}", file=sys.stderr)
            finally:
                self._destruction_queue.task_done()

    # ── UI building ─────────────────────────────────────────────────────────────

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
        for text, cmd in [("⚙ Settings",    self._open_settings),
                          ("🔍 Scan Now",    self._manual_scan),
                          ("📤 Export Results", self._manual_export),
                          ("🗑 Reset",       self._reset)]:
            tk.Button(btn_frame, text=text, command=cmd, bg=BG2, fg=TEXT,
                      activebackground=ACCENT, activeforeground=BG,
                      relief="flat", font=FONT, cursor="hand2",
                      padx=10, pady=4).pack(side="left", padx=3)

        ttk.Separator(self, orient="horizontal").pack(fill="x", padx=12)

        # Notebook
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

        self._log.tag_configure("normal", foreground=TEXT_DIM)
        self._log.tag_configure("error",  foreground=RED)
        self._log.tag_configure("warn",   foreground=YELLOW)

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

    # ── helpers ─────────────────────────────────────────────────────────────────

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
        self.submit_async(self._apply_config_async(cfg))

    # ── config / startup async chain ────────────────────────────────────────────

    async def _apply_config_async(self, cfg: dict):
        self._cfg = cfg
        replays_path = Path(cfg["replays_path"])
        if (replays_path / "replays").exists():
            replays_path = replays_path / "replays"
        if not replays_path.exists():
            self.after(0, lambda: messagebox.showerror(
                "Path not found", f"Replays folder not found:\n{replays_path}"))
            return
        self._replays_dir = replays_path
        bt_choice = cfg.get("battle_type_choice", "2")
        _, self._battle_filter = BATTLE_TYPE_OPTIONS.get(bt_choice, BATTLE_TYPE_OPTIONS["2"])

        self.after(0, lambda: self._set_status("Loading tankopedia…", ACCENT))
        await self._load_tankopedia_async()

    async def _load_tankopedia_async(self):
        def progress(msg):
            self.after(0, lambda m=msg: self._set_status(m, ACCENT))
            self.after(0, lambda m=msg: self._log_msg(f"Tankopedia: {m}"))

        # Fetch all tiers (0) by default to ensure we can map Tier 8/9 tanks 
        # from Excel/replay even if the UI is currently filtered.
        fetch_tier = 0

        self._tag_to_name, self._tank_id_to_name = await asyncio.to_thread(
            fetch_tag_to_name,
            APP_ID, self._cfg.get("realm", "eu"), fetch_tier, progress,
        )
        
        # Populate mapping with BOTH full names, short names, and tags for better resolution
        self._name_to_tag = {}
        for tag, info in self._tag_to_name.items():
            self._name_to_tag[info["name"]] = tag
            self._name_to_tag[info["short_name"]] = tag
            # Also map the raw tag part for direct tag matches (e.g., GB98_T95_FV4201_Chieftain)
            pure_tag = tag.split(":", 1)[-1]
            self._name_to_tag[pure_tag] = tag
            
        self.after(0, self._on_tankopedia_ready)

    def _normalize_tank_name(self, name: str) -> str:
        """Robust normalization for fuzzy matching (accents, abbreviations)."""
        if not name: return ""
        import unicodedata
        # Normalize to NFD to separate accents, then filter them out
        s = "".join(c for c in unicodedata.normalize('NFD', str(name)) if unicodedata.category(c) != 'Mn')
        s = s.lower()
        # Remove common delimiters
        for char in " .-/_'\"":
            s = s.replace(char, "")
        # Common abbreviations
        s = s.replace("object", "obj")
        s = s.replace("pzkpfw", "pz")
        s = s.replace("panhard", "")
        return s

    def _on_tankopedia_ready(self):
        self._log_msg(f"Tankopedia loaded: {len(self._tag_to_name)} tanks")
        self._set_status("Fetching clan members…", ACCENT)
        self.submit_async(self._load_clan_members_async())

    async def _load_clan_members_async(self):
        cfg = self._cfg
        member_ids = await asyncio.to_thread(
            fetch_clan_member_ids, APP_ID, cfg.get("realm", "eu"), cfg["clan_tag"]
        )
        if member_ids:
            names_dict = await asyncio.to_thread(
                fetch_account_names, APP_ID, cfg.get("realm", "eu"), member_ids
            )
            self._clan_members = set(names_dict.values())
            self._acc_id_to_name.update(names_dict)
            self.after(0, lambda: self._log_msg(
                f"Clan members fetched: {len(self._clan_members)} members"))
        else:
            self._clan_members = set()
            self.after(0, lambda: self._log_msg(
                "[!] Failed to fetch clan members, filtering will be less accurate"))

        self.after(0, self._on_clan_ready)

    def _on_clan_ready(self):
        self._set_status(f"Watching [{self._cfg['clan_tag']}]", GREEN)
        self._already_parsed.clear()
        self._destroyed.clear()
        self.submit_async(self._do_scan_async(silent=False, do_export=False))
        self._start_watcher()
        self.submit_async(self._load_remaining_async())

    # ── remaining tanks ─────────────────────────────────────────────────────────

    def _load_remaining(self):
        self.submit_async(self._load_remaining_async())

    async def _load_remaining_async(self):
        excel_path = self._cfg.get("excel_path", "").strip()
        if excel_path and (_is_url(excel_path) or Path(excel_path).exists()):
            await self._load_remaining_excel_async(excel_path)
        else:
            await self._load_remaining_api_async()

    async def _load_remaining_excel_async(self, path: str):
        self.after(0, lambda: self._remaining_lbl.configure(
            text="Loading from Excel…", fg=ACCENT))
        names = await asyncio.to_thread(
            load_tanks_from_excel, path, clan_members=self._clan_members)
        self.after(0, lambda: self._on_remaining_excel(names))

    def _on_remaining_excel(self, named_tanks: dict):
        self._member_tanks     = named_tanks
        self._remaining_tanks  = []
        self._remaining_source = "excel"
        tier = self._cfg.get("tier", 10)

        total_tanks   = sum(len(v) for k, v in named_tanks.items() if not k.endswith("_display"))
        total_players = len(named_tanks) // 2

        self._remaining_lbl.configure(
            text=f"Source: Excel — {total_tanks} tanks across {total_players} members "
                 f"(Tier {tier if tier else 'All'})",
            fg=TEXT_DIM,
        )
        self._log_msg(f"[tanks] Loaded {total_tanks} tanks for {total_players} players from Excel")
        self._refresh_remaining()

    async def _load_remaining_api_async(self):
        if not self._cfg.get("clan_tag"):
            return
        self.after(0, lambda: self._remaining_lbl.configure(
            text="Fetching clan tanks from API…", fg=ACCENT))

        def progress(msg):
            self.after(0, lambda m=msg: self._log_msg(f"[tanks] {m}"))

        realm    = self._cfg.get("realm", "eu")
        clan_tag = self._cfg["clan_tag"]
        tier     = self._cfg.get("tier", 10)

        progress(f"Looking up clan [{clan_tag}]…")
        acc_ids = await asyncio.to_thread(fetch_clan_member_ids, APP_ID, realm, clan_tag)

        if not acc_ids:
            msg = f"[!] Could not find clan [{clan_tag}] on {realm.upper()}"
            self.after(0, lambda m=msg: self._remaining_lbl.configure(text=m, fg=RED))
            return

        progress(f"Found {len(acc_ids)} members, fetching tank lists…")
        member_tanks_by_id = await asyncio.to_thread(
            fetch_tanks_for_accounts,
            APP_ID, realm, acc_ids, self._tank_id_to_name, tier, progress,
        )
        await self._finalize_api_data_async(member_tanks_by_id, tier)

    async def _finalize_api_data_async(self, member_tanks_by_id: dict, tier: int):
        realm   = self._cfg.get("realm", "eu")
        acc_ids = list(member_tanks_by_id.keys())

        if not acc_ids:
            self.after(0, lambda: self._on_api_mapped({}, tier))
            return

        id_to_name = await asyncio.to_thread(fetch_account_names, APP_ID, realm, acc_ids)
        named_tanks = {}
        for acc_id, tanks in member_tanks_by_id.items():
            nickname = id_to_name.get(acc_id)
            if nickname:
                named_tanks[nickname.lower()] = tanks
                named_tanks[f"{nickname.lower()}_display"] = nickname

        self.after(0, lambda: self._on_api_mapped(named_tanks, tier))

    def _on_api_mapped(self, named_tanks: dict, tier: int):
        self._member_tanks     = named_tanks
        self._remaining_tanks  = []
        self._remaining_source = "api"
        total = sum(len(v) for k, v in named_tanks.items() if not k.endswith("_display"))

        self._remaining_lbl.configure(
            text=f"API Load: {total} tanks (Tier {tier if tier else 'All'})",
            fg=TEXT_DIM,
        )
        self._log_msg(f"[tanks] Successfully mapped {len(named_tanks) // 2} players")
        self._refresh_remaining()

    def _refresh_remaining(self):
        self._rem_tree.delete(*self._rem_tree.get_children())

        player_destroyed: dict[str, set[str]] = {}
        for player, entries in self._destroyed.items():
            p_low = player.lower().strip()
            for e in entries:
                is_pending = e[4] if len(e) > 4 else False
                if not is_pending:
                    player_destroyed.setdefault(p_low, set()).add(e[0].strip())

        players_order = self._cfg.get("players_order", [])
        if not players_order:
            if self._remaining_source in ("api", "excel"):
                players_order = [
                    v for k, v in self._member_tanks.items() if str(k).endswith("_display")
                ]
            else:
                players_order = list(self._destroyed.keys())
        
        # Filter out anything that looks like a tank name to prevent pollution
        valid_players = []
        tank_names_lower = {n.lower() for n in self._name_to_tag.keys()}
        for p in players_order:
            if str(p).lower().strip() not in tank_names_lower:
                valid_players.append(p)
        players_order = sorted(valid_players)

        for player_input in players_order:
            p_low = player_input.lower().strip()

            if self._remaining_source in ("api", "excel"):
                all_tanks    = self._member_tanks.get(p_low, [])
                display_name = self._member_tanks.get(f"{p_low}_display", player_input)
            else:
                all_tanks    = self._remaining_tanks
                display_name = player_input

            dead_names       = player_destroyed.get(p_low, set())
            dead_names_norm  = {self._normalize_tank_name(d): d for d in dead_names}

            available = []
            destroyed = []
            for t in all_tanks:
                t_norm = self._normalize_tank_name(t)
                matched_dead = False
                for d_norm in dead_names_norm:
                    if t_norm == d_norm or (t_norm and d_norm and (t_norm in d_norm or d_norm in t_norm)):
                        matched_dead = True
                        break
                if matched_dead:
                    destroyed.append(t)
                else:
                    available.append(t)

            all_tanks_norm = {self._normalize_tank_name(t): t for t in all_tanks}
            for d in dead_names:
                d_norm = self._normalize_tank_name(d)
                matched_all = False
                for t_norm in all_tanks_norm:
                    if t_norm == d_norm or (t_norm and d_norm and (t_norm in d_norm or d_norm in t_norm)):
                        matched_all = True
                        break
                if not matched_all:
                    destroyed.append(d)

            available.sort()
            destroyed.sort()

            if not available and not destroyed:
                self._rem_tree.insert(
                    "", "end", values=(f"👤 {display_name} (No tanks found)", "", ""))
                continue

            parent = self._rem_tree.insert(
                "", "end", values=(f"👤 {display_name}", "", ""),
                tags=("player_header",), open=True)

            if available:
                avail_node = self._rem_tree.insert(
                    parent, "end",
                    values=(f"✅ Available ({len(available)})", "", ""),
                    tags=("group_header",), open=True)
                for t in available:
                    self._rem_tree.insert(avail_node, "end",
                                          values=(t, display_name, "✅ Available"),
                                          tags=("alive",))

            if destroyed:
                dead_node = self._rem_tree.insert(
                    parent, "end",
                    values=(f"💀 Destroyed ({len(destroyed)})", "", ""),
                    tags=("group_dead",), open=False)
                for t in destroyed:
                    self._rem_tree.insert(dead_node, "end",
                                          values=(t, display_name, "💀 Destroyed"),
                                          tags=("dead",))

        self._rem_tree.tag_configure("player_header", foreground=ACCENT, font=FONT_BOLD)
        self._rem_tree.tag_configure("group_header", foreground=GREEN)
        self._rem_tree.tag_configure("group_dead", foreground=RED)

    def _get_tanks_for_server(self, account_id: int) -> list[str]:
        """Server callback: returns non-destroyed tank internal tags for the given account_id."""
        self._log_msg(f"[server] Request for account_id={account_id}")

        nickname = self._acc_id_to_name.get(account_id)
        if not nickname:
            try:
                realm = self._cfg.get("realm", "eu")
                res = fetch_account_names(APP_ID, realm, [account_id])
                if account_id in res:
                    nickname = res[account_id]
                    self._acc_id_to_name[account_id] = nickname
            except Exception as e:
                self._log_msg(f"[server] Failed to fetch name for ID {account_id}: {e}")

        if not nickname:
            return []

        p_low = nickname.lower().strip()
        if p_low not in self._member_tanks:
            found = False
            for k, v in self._member_tanks.items():
                if k.endswith("_display"):
                    if str(v).lower().strip() == p_low:
                        p_low = k.replace("_display", "")
                        found = True
                        break
            if not found:
                return []

        all_tanks = self._member_tanks.get(p_low, [])
        dead_names_norm = {self._normalize_tank_name(d) for d in self._get_dead_names(nickname, p_low)}
        norm_map = {self._normalize_tank_name(n): tg for n, tg in self._name_to_tag.items() if n}

        result = []
        seen = set()
        for t_display in all_tanks:
            norm_t = self._normalize_tank_name(t_display)
            if norm_t in dead_names_norm:
                continue

            # Resolve display name to internal tag
            tag = self._name_to_tag.get(t_display) or norm_map.get(norm_t)
            if not tag:
                for n_norm, tg in norm_map.items():
                    if norm_t and n_norm and (norm_t in n_norm or n_norm in norm_t):
                        tag = tg
                        break
            if not tag:
                tag = CYRILLIC_FALLBACK.get(t_display)

            if tag and tag not in seen:
                display_name = tag
                if tag in self._tag_to_name:
                    display_name = self._tag_to_name[tag].get("short_name", self._tag_to_name[tag].get("name", tag))
                result.append(display_name)
                seen.add(tag)
            elif not tag:
                self._log_msg(f"[server] Could not resolve tag for: '{t_display}'")

        self._log_msg(f"[server] Returning {len(result)} tank(s) for '{nickname}'")
        return result

    def _get_dead_names(self, nickname: str, p_low: str) -> set[str]:
        """Helper to get list of destroyed tank names for various possible keys."""
        dead = set()
        possible_keys = {nickname, p_low}
        display_name = self._member_tanks.get(f"{p_low}_display")
        if display_name:
            possible_keys.add(display_name)
            
        for key in possible_keys:
            entries = self._destroyed.get(key, [])
            for e in entries:
                is_pending = e[4] if len(e) > 4 else False
                if not is_pending:
                    dead.add(str(e[0]))
        return dead

    # ── watcher ─────────────────────────────────────────────────────────────────

    def _start_watcher(self):
        self._stop_watcher()
        self._watcher_stop.clear()
        if HAS_WATCHDOG:
            app_ref = self

            class ReplayHandler(FileSystemEventHandler):
                def on_created(self, event):
                    if not event.is_directory and event.src_path.endswith(".wotreplay"):
                        app_ref.submit_async(app_ref._do_scan_async(silent=True))

                def on_modified(self, event):
                    if not event.is_directory and event.src_path.endswith(".wotreplay"):
                        app_ref.submit_async(app_ref._do_scan_async(silent=True))

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
                            self.submit_async(self._do_scan_async(silent=True))

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

    # ── scanning ────────────────────────────────────────────────────────────────

    async def _do_scan_async(self, silent: bool = False, do_export: bool = True):
        if not self._replays_dir or not self._tag_to_name:
            return

        preset = self._cfg.get("time_window_preset", "2h")
        now    = time.time()

        if preset == "2h":
            record_since = now - 7200
        elif preset == "4h":
            record_since = now - 14400
        elif preset == "8h":
            record_since = now - 28800
        elif preset == "24h":
            record_since = now - 86400
        elif preset == "today":
            lt = time.localtime(now)
            record_since = time.mktime(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
        else:
            record_since = self._cfg.get("record_since", now - 7200)

        new_events, _ = await asyncio.to_thread(
            scan_replays,
            self._replays_dir, self._cfg["clan_tag"],
            self._tag_to_name, self._already_parsed, self._battle_filter,
            record_since,
            log_cb=lambda msg: self.after(0, lambda m=msg: self._log_msg(m)),
            tier_filter=self._cfg.get("tier", 10),
        )
        self.after(0, lambda: self._apply_events(new_events, silent, do_export))

    def _apply_events(self, events: list[dict], silent: bool, do_export: bool = True):
        players_order = self._cfg.get("players_order", [])
        order_dict = {p.lower().strip(): i for i, p in enumerate(players_order)}

        def get_priority(p_name: str) -> int:
            p_low = p_name.lower().strip()
            if p_low in order_dict:
                return order_dict[p_low]
            for o_name, idx in order_dict.items():
                if p_low in o_name or o_name in p_low:
                    return idx
            return len(players_order) + 1

        events.sort(key=lambda ev: (get_priority(ev["player"]), ev.get("battle_time", "")))

        new_count = 0
        for ev in events:
            player      = ev["player"]
            replay_name = ev.get("replay_name", "")
            is_pending  = ev.get("pending", False)
            self._destroyed.setdefault(player, [])

            if not is_pending:
                pk = (player, replay_name)
                if pk in self._pending_keys:
                    self._pending_keys.discard(pk)
                    self._destroyed[player] = [
                        e for e in self._destroyed[player]
                        if not (len(e) > 4 and e[4] and len(e) > 5 and e[5] == replay_name)
                    ]
                existing = [(e[0], e[1], e[2], e[3]) for e in self._destroyed[player]]
                if (ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"]) not in existing:
                    results_path = self._cfg.get("results_excel_path")
                    is_exported  = False
                    if results_path and do_export:
                        self._loop.call_soon_threadsafe(
                            self._destruction_queue.put_nowait,
                            (results_path, player, ev["veh_name"], ev["map"], ev["battle_time"]),
                        )
                        is_exported = True

                    self._destroyed[player].append((
                        ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"],
                        False, replay_name, is_exported,
                    ))
                    new_count += 1
            else:
                pk = (player, replay_name)
                if pk not in self._pending_keys:
                    self._pending_keys.add(pk)
                    self._destroyed[player].append((
                        ev["veh_name"], ev["death_label"], ev["map"], ev["battle_time"],
                        True, replay_name,
                    ))
                    new_count += 1

        changed = new_count > 0 or len(events) > 0
        if changed or not silent:
            self._refresh_tree()
            self._refresh_remaining()

        if new_count > 0:
            self._set_status(
                f"Last scan: {time.strftime('%H:%M:%S')} — {new_count} new event(s)", ACCENT)
        elif not silent:
            self._set_status(
                f"Last scan: {time.strftime('%H:%M:%S')} — no new events", TEXT_DIM)

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())

        players_order = self._cfg.get("players_order", [])
        if not players_order:
            if self._remaining_source in ("api", "excel"):
                players_order = [
                    v for k, v in self._member_tanks.items() if str(k).endswith("_display")
                ]
            else:
                players_order = list(self._destroyed.keys())
        
        # Filter out anything that looks like a tank name
        valid_players = []
        tank_names_lower = {n.lower() for n in self._name_to_tag.keys()}
        for p in players_order:
            if str(p).lower().strip() not in tank_names_lower:
                valid_players.append(p)
        players_order = sorted(valid_players)

        player_destroyed_lower = {
            k.lower().strip(): (k, v) for k, v in self._destroyed.items()
        }

        for player_input in players_order:
            p_low         = player_input.lower().strip()
            actual_player = player_input
            entries: list = []

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
                    tank, status, map_name, battle_time = (
                        entry[0], entry[1], entry[2], entry[3])
                    is_pending  = entry[4] if len(entry) > 4 else False
                    tag         = "pending" if is_pending else "entry"
                    disp_status = f"❓ {status}" if is_pending else status
                    self._tree.insert(node, "end", text="",
                                      values=(tank, disp_status, map_name, battle_time),
                                      tags=(tag,))

        self._tree.tag_configure("player",  foreground=ACCENT)
        self._tree.tag_configure("entry",   foreground=TEXT)
        self._tree.tag_configure("pending", foreground=YELLOW)

    # ── button handlers ─────────────────────────────────────────────────────────

    def _manual_scan(self):
        self._log_msg("Manual scan triggered (UI update only).")
        self.submit_async(self._do_scan_async(silent=False, do_export=False))

    def _manual_export(self):
        self._log_msg("Manual export triggered (Syncing displayed tanks to Excel).")
        self.submit_async(self._do_scan_async(silent=False, do_export=False))
        self.after(500, self._push_unexported_results)

    def _push_unexported_results(self):
        results_path = self._cfg.get("results_excel_path")
        if not results_path:
            self._log_msg("[!] No Results Output path configured.")
            return

        players_order = self._cfg.get("players_order", [])
        order_dict = {p.lower().strip(): i for i, p in enumerate(players_order)}

        def get_priority(p_name: str) -> int:
            p_low = p_name.lower().strip()
            if p_low in order_dict:
                return order_dict[p_low]
            for o_name, idx in order_dict.items():
                if p_low in o_name or o_name in p_low:
                    return idx
            return len(players_order) + 1

        sorted_players = sorted(self._destroyed.keys(), key=get_priority)

        count = 0
        for player in sorted_players:
            entries = self._destroyed[player]
            for i, entry in enumerate(entries):
                tank, _, m, t, is_pending, replay_name = (
                    entry[0], entry[1], entry[2], entry[3], entry[4], entry[5])
                exported = entry[6] if len(entry) > 6 else False

                if not is_pending and not exported:
                    self._loop.call_soon_threadsafe(
                        self._destruction_queue.put_nowait,
                        (results_path, player, tank, m, t),
                    )
                    new_entry = list(entry)
                    if len(new_entry) < 7:
                        new_entry.append(True)
                    else:
                        new_entry[6] = True
                    entries[i] = tuple(new_entry)
                    count += 1

        if count > 0:
            self._log_msg(f"[✓] Queued {count} destructions for export.")
        else:
            self._log_msg("[~] Nothing new to export (all tanks already synced).")

    def _reset(self):
        if messagebox.askyesno(
            "Reset",
            "Clear all destroyed vehicle data?\nOnly replays from this point forward will be tracked.",
            parent=self,
        ):
            self._destroyed.clear()
            self._pending_keys.clear()
            self._cfg["record_since"] = time.time()
            save_config(self._cfg)
            self._refresh_tree()
            self._refresh_remaining()
            if self._replays_dir:
                self._already_parsed = set(
                    r.name for r in self._replays_dir.glob("*.wotreplay"))
            self._log_msg(
                f"State reset at {time.strftime('%H:%M:%S')} — tracking from now on.")
            self._set_status(
                f"Reset at {time.strftime('%H:%M:%S')} — waiting for new replays", TEXT_DIM)

    # ── shutdown ────────────────────────────────────────────────────────────────

    def _on_close(self):
        self._stop_watcher()
        self._server.stop()
        self._loop.call_soon_threadsafe(self._loop.stop)

        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__
        self.destroy()
