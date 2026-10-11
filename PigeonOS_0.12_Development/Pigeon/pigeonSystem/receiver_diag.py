#!/usr/bin/env python3
"""Developer-only receiver diagnostic tool (macOS/Linux, no Pi needed).

    python3 receiver_diag.py                    # pick adapter + IP in the window
    python3 receiver_diag.py --brand fake       # simulated receiver, no hardware
    python3 receiver_diag.py --brand denon --host 192.168.1.50

Uses the same ``Receiver`` adapters as Pigeon. Not started by Pigeon itself.
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pigeon.receiver import ADAPTERS, discover_receivers  # noqa: E402
from pigeon.receiver.diag import DiagSession  # noqa: E402

TAG_COLORS = {
    "SENT": "#2563eb", "RESP": "#15803d", "EXTERNAL": "#c2410c",
    "TIMEOUT": "#b91c1c", "CONN": "#6b7280", "ERROR": "#b91c1c",
}


class App:
    def __init__(self, root: tk.Tk, brand: str, host: str) -> None:
        self.root = root
        self.session: DiagSession | None = None
        self.dirty = queue.Queue()
        root.title("Pigeon Receiver Diagnostic")
        root.geometry("900x720")
        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Adapter").grid(row=0, column=0)
        self.brand = tk.StringVar(value=brand)
        ttk.Combobox(top, textvariable=self.brand, values=sorted(ADAPTERS), width=10, state="readonly").grid(row=0, column=1, padx=4)
        ttk.Label(top, text="IP").grid(row=0, column=2)
        self.host = tk.StringVar(value=host)
        ttk.Entry(top, textvariable=self.host, width=18).grid(row=0, column=3, padx=4)
        ttk.Button(top, text="Search…", command=self.search).grid(row=0, column=4, padx=2)
        ttk.Button(top, text="Connect", command=self.connect).grid(row=0, column=5, padx=2)
        ttk.Button(top, text="Disconnect", command=self.disconnect).grid(row=0, column=6, padx=2)
        ttk.Button(top, text="Refresh", command=lambda: self.run(lambda s: s.refresh())).grid(row=0, column=7, padx=2)
        self.status = ttk.Label(top, text="not connected", font=("Helvetica", 12, "bold"))
        self.status.grid(row=0, column=8, padx=10)

        st = ttk.LabelFrame(root, text="Live state", padding=8)
        st.pack(fill="x", padx=8)
        self.fields = {}
        for i, name in enumerate(("power", "volume", "mute", "input", "audio format", "sound mode")):
            ttk.Label(st, text=name).grid(row=0, column=i, padx=12)
            v = ttk.Label(st, text="—", font=("Helvetica", 13))
            v.grid(row=1, column=i, padx=12)
            self.fields[name] = v

        ctl = ttk.LabelFrame(root, text="Controls (async; watch the log)", padding=8)
        ctl.pack(fill="x", padx=8, pady=6)
        for text, fn in (
            ("Power on", lambda s: s.power(True)), ("Standby", lambda s: s.power(False)),
            ("Vol −", lambda s: s.volume(-1)), ("Vol +", lambda s: s.volume(1)),
            ("Mute", lambda s: s.mute()),
        ):
            ttk.Button(ctl, text=text, command=lambda f=fn: self.run(f)).pack(side="left", padx=3)
        self.input_var = tk.StringVar()
        self.input_box = ttk.Combobox(ctl, textvariable=self.input_var, width=16, state="disabled")
        self.input_box.pack(side="left", padx=(16, 3))
        self.input_btn = ttk.Button(ctl, text="Set input", state="disabled",
                                    command=lambda: self.run(lambda s: s.set_input(self.input_var.get())))
        self.input_btn.pack(side="left")

        self.sim = ttk.LabelFrame(root, text="Simulate external change (fake adapter only)", padding=8)
        self.sim_vol = tk.StringVar(value="-35")
        ttk.Entry(self.sim, textvariable=self.sim_vol, width=6).pack(side="left")
        for text, fn in (
            ("Set volume", lambda r: r.simulate_volume(float(self.sim_vol.get()))),
            ("Standby", lambda r: r.simulate_power(False)), ("Power on", lambda r: r.simulate_power(True)),
            ("Link down", lambda r: r.simulate_link(False)), ("Link up", lambda r: r.simulate_link(True)),
        ):
            ttk.Button(self.sim, text=text, command=lambda f=fn: self.run(lambda s: f(s.receiver))).pack(side="left", padx=3)

        logf = ttk.Frame(root, padding=8)
        logf.pack(fill="both", expand=True)
        bar = ttk.Frame(logf)
        bar.pack(fill="x")
        ttk.Button(bar, text="Copy log", command=self.copy_log).pack(side="left")
        ttk.Button(bar, text="Save log…", command=self.save_log).pack(side="left", padx=4)
        ttk.Button(bar, text="Clear view", command=lambda: self.log.delete("1.0", "end")).pack(side="left")
        self.log = tk.Text(logf, font=("Menlo", 11), wrap="none")
        self.log.pack(fill="both", expand=True, pady=(6, 0))
        for tag, col in TAG_COLORS.items():
            self.log.tag_configure(tag, foreground=col)
        self.shown = 0
        self.tick()

    def run(self, fn) -> None:
        s = self.session
        if s is None:
            messagebox.showinfo("Receiver", "Connect first.")
            return
        import threading
        threading.Thread(target=lambda: fn(s), daemon=True).start()

    def search(self) -> None:
        """Scan the LAN (SSDP + subnet sweep) for receivers; pick one to fill Adapter and IP."""
        import threading

        win = tk.Toplevel(self.root)
        win.title("Search for receivers")
        win.geometry("460x280")
        msg = ttk.Label(win, text="Searching the network… (can take up to a minute)", padding=8)
        msg.pack(fill="x")
        box = tk.Listbox(win, font=("Menlo", 12), activestyle="dotbox")
        box.pack(fill="both", expand=True, padx=8)
        found: list = []

        def choose(_evt=None) -> None:
            sel = box.curselection()
            if not sel:
                return
            r = found[sel[0]]
            self.brand.set(r.brand)
            self.host.set(r.host)
            win.destroy()

        btns = ttk.Frame(win, padding=8)
        btns.pack(fill="x")
        use = ttk.Button(btns, text="Use selected", command=choose, state="disabled")
        use.pack(side="left")
        ttk.Button(btns, text="Close", command=win.destroy).pack(side="right")
        box.bind("<Double-Button-1>", choose)
        results: queue.Queue = queue.Queue()

        def work() -> None:
            try:
                results.put(("ok", discover_receivers()))
            except Exception as exc:  # keep the dialog usable
                results.put(("err", str(exc)))

        def poll() -> None:
            if not win.winfo_exists():
                return
            try:
                kind, val = results.get_nowait()
            except queue.Empty:
                win.after(150, poll)
                return
            if kind == "err":
                msg.config(text=f"Search failed: {val}")
                return
            found.extend(val)
            for r in val:
                box.insert("end", r.label)
            msg.config(text=f"Found {len(val)} receiver(s)." if val else
                       "None found. Enable network control on the receiver or enter its IP.")
            if val:
                box.selection_set(0)
                use.config(state="normal")

        threading.Thread(target=work, daemon=True).start()
        poll()

    def connect(self) -> None:
        import threading
        if self.session is not None:
            self.session.disconnect()
        try:
            s = DiagSession(self.brand.get(), self.host.get().strip())
        except Exception as exc:
            messagebox.showerror("Receiver", str(exc))
            return
        self.session, self.shown = s, 0
        self.log.delete("1.0", "end")
        s.set_ui_callback(lambda: self.dirty.put(1))
        if hasattr(s.receiver, "simulate_volume"):
            self.sim.pack(fill="x", padx=8, before=self.log.master)
        else:
            self.sim.pack_forget()
        threading.Thread(target=s.connect, daemon=True).start()

    def disconnect(self) -> None:
        if self.session:
            import threading
            threading.Thread(target=self.session.disconnect, daemon=True).start()

    def tick(self) -> None:
        s = self.session
        if s is not None:
            lines = s.log_lines()
            for line in lines[self.shown:]:
                kind = line[13:21].strip()
                self.log.insert("end", line + "\n", kind)
                self.log.see("end")
            self.shown = len(lines)
            st = s.state
            self.status.config(text="CONNECTED" if st.connected else "not connected",
                               foreground="#15803d" if st.connected else "#b91c1c")
            pw = "—" if st.powered_on is None else ("on" if st.powered_on else "standby")
            vals = {"power": pw, "volume": st.volume_line or "—",
                    "mute": "—" if st.muted is None else ("MUTED" if st.muted else "off"),
                    "input": st.input_label or "—", "audio format": st.audio_format or "—",
                    "sound mode": st.sound_mode or "—"}
            for k, v in vals.items():
                self.fields[k].config(text=v)
            if s.supports_input and str(self.input_box["state"]) == "disabled":
                self.input_box.config(values=s.inputs(), state="readonly")
                self.input_btn.config(state="normal")
        while not self.dirty.empty():
            self.dirty.get_nowait()
        self.root.after(100, self.tick)

    def copy_log(self) -> None:
        if self.session:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.session.export_text())

    def save_log(self) -> None:
        if not self.session:
            return
        path = filedialog.asksaveasfilename(initialfile=self.session.default_filename(), defaultextension=".log")
        if path:
            self.session.save(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", default="denon", choices=sorted(ADAPTERS))
    ap.add_argument("--host", default="")
    a = ap.parse_args()
    root = tk.Tk()
    App(root, a.brand, a.host)
    root.mainloop()


if __name__ == "__main__":
    main()
