"""
SettingsWindow — tkinter Toplevel dialog for configuring the tracker.
"""

import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from tracker.constants import (
    BG, BG2, ACCENT, TEXT, TEXT_DIM, RED, FONT, FONT_BOLD, FONT_SM, FONT_H,
    BATTLE_TYPE_OPTIONS,
)
from tracker.config import save_config


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

        # Results Excel (optional)
        tk.Label(self, text="Results Output", font=FONT, bg=BG, fg=TEXT).grid(
            row=7, column=0, sticky="w", **pad)
        self.results_var = tk.StringVar(value=cfg.get("results_excel_path", ""))
        results_entry = tk.Entry(self, textvariable=self.results_var, width=42, bg=BG2, fg=TEXT,
                                 insertbackground=TEXT, relief="flat", font=FONT)
        results_entry.grid(row=7, column=1, sticky="ew", **pad)
        res_btn_frame = tk.Frame(self, bg=BG)
        res_btn_frame.grid(row=7, column=2, padx=(0, 12))
        tk.Button(res_btn_frame, text="Browse", command=self._browse_results, bg=BG2, fg=ACCENT,
                  activebackground=ACCENT, activeforeground=BG, relief="flat",
                  font=FONT, cursor="hand2").pack(side="left", padx=(0, 4))
        tk.Button(res_btn_frame, text="✕", command=lambda: self.results_var.set(""),
                  bg=BG2, fg=RED, activebackground=RED, activeforeground=BG,
                  relief="flat", font=FONT, cursor="hand2", width=2).pack(side="left")

        tk.Label(self, text="Input URL or path for tanks / Output path/URL for results",
                 font=FONT_SM, bg=BG, fg=TEXT_DIM).grid(
            row=8, column=1, sticky="w", padx=12, pady=(0, 4))

        # Players order
        tk.Label(self, text="Players order", font=FONT, bg=BG, fg=TEXT).grid(
            row=9, column=0, sticky="nw", padx=12, pady=6)
        order_frame = tk.Frame(self, bg=BG)
        order_frame.grid(row=9, column=1, sticky="ew", padx=12, pady=6)
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
            row=10, column=1, sticky="w", padx=12, pady=(0, 4))

        # Scan Window (time presets)
        tk.Label(self, text="Scan Window", font=FONT, bg=BG, fg=TEXT).grid(
            row=11, column=0, sticky="nw", padx=12, pady=6)

        rs_frame = tk.Frame(self, bg=BG)
        rs_frame.grid(row=11, column=1, sticky="w", padx=12, pady=6)

        self.preset_map = {
            "Last 2 hours":  "2h",
            "Last 4 hours":  "4h",
            "Last 8 hours":  "8h",
            "Last 24 hours": "24h",
            "Today (00:00)": "today",
            "Custom Date":   "custom",
        }
        self.preset_rev = {v: k for k, v in self.preset_map.items()}

        current_preset = cfg.get("time_window_preset", "2h")
        self.preset_var = tk.StringVar(value=self.preset_rev.get(current_preset, "Last 2 hours"))

        self.preset_combo = ttk.Combobox(rs_frame, textvariable=self.preset_var,
                                         values=list(self.preset_map.keys()),
                                         state="readonly", width=15)
        self.preset_combo.pack(side="left")

        default_ts = cfg.get("record_since", time.time() - 7200)
        dt_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(default_ts))
        self.record_since_var = tk.StringVar(value=dt_str)

        self.custom_entry = tk.Entry(rs_frame, textvariable=self.record_since_var, width=20,
                                     bg=BG2, fg=TEXT, insertbackground=TEXT, relief="flat",
                                     font=FONT)
        self.custom_entry.pack(side="left", padx=(10, 0))

        self.custom_lbl = tk.Label(rs_frame, text=" (YYYY-MM-DD HH:MM:SS)", font=FONT_SM,
                                   bg=BG, fg=TEXT_DIM)
        self.custom_lbl.pack(side="left")

        def _on_preset_change(e=None):
            if self.preset_map.get(self.preset_var.get()) == "custom":
                self.custom_entry.pack(side="left", padx=(10, 0))
                self.custom_lbl.pack(side="left")
            else:
                self.custom_entry.pack_forget()
                self.custom_lbl.pack_forget()

        self.preset_combo.bind("<<ComboboxSelected>>", _on_preset_change)
        _on_preset_change()

        # Save button
        tk.Button(self, text="Save & Start", command=self._save,
                  bg=ACCENT, fg=BG, activebackground=TEXT, activeforeground=BG,
                  relief="flat", font=FONT_BOLD, cursor="hand2", padx=16, pady=6).grid(
            row=12, column=0, columnspan=3, pady=(8, 16))

        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ── file browsing ────────────────────────────────────────────────────────────

    def _browse_replay(self):
        path = filedialog.askdirectory(title="Select replays folder")
        if path:
            self.path_var.set(path)

    def _browse_excel(self):
        path = filedialog.askopenfilename(
            title="Select tank list Excel file",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")],
        )
        if path:
            self.excel_var.set(path)

    def _browse_results(self):
        path = filedialog.asksaveasfilename(
            title="Select destruction results Excel file",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
        )
        if path:
            self.results_var.set(path)

    # ── save ──────────────────────────────────────────────────────────────────────

    def _save(self):
        path = self.path_var.get().strip()
        clan = self.clan_var.get().strip().upper()
        if not path or not clan:
            messagebox.showerror("Missing fields", "Replays path and clan tag are required.",
                                 parent=self)
            return

        try:
            record_since = time.mktime(
                time.strptime(self.record_since_var.get().strip(), "%Y-%m-%d %H:%M:%S")
            )
        except ValueError:
            messagebox.showerror("Invalid Date format",
                                 "Record since must be YYYY-MM-DD HH:MM:SS",
                                 parent=self)
            return

        raw_order = self.order_text.get("1.0", "end").split("\n")
        order_list = [n.strip() for n in raw_order if n.strip()]
        cfg = {
            "replays_path":       path,
            "clan_tag":           clan,
            "realm":              self.realm_var.get(),
            "battle_type_choice": self.bt_var.get(),
            "tier":               self.tier_var.get(),
            "excel_path":         self.excel_var.get().strip(),
            "results_excel_path": self.results_var.get().strip(),
            "players_order":      order_list,
            "record_since":       record_since,
            "time_window_preset": self.preset_map.get(self.preset_var.get(), "2h"),
        }
        save_config(cfg)
        self.on_save(cfg)
        self.destroy()
