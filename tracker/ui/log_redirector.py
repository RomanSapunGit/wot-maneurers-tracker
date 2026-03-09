"""
LogRedirector — thread-safe stdout/stderr redirect to a tkinter Text widget.
"""

import tkinter as tk


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
