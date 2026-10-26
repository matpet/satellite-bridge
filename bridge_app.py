#!/usr/bin/env python3
"""Compact operating panel; QO-100 pair editing lives in Settings."""

import json
import os
import queue
import sys
import threading
import tkinter as tk
import traceback
import uuid
from decimal import Decimal
from tkinter import ttk, messagebox

from bridge_core import Bridge, Transport, Pair, Settings, MODES, virtual_split_offsets, mhz_text, dial_band
from rumlog_test import Commander, field
from rumlog_panel import RumlogPanel, NativePowerControl, NativeRxFilterControl
from bridge_rpc import start_server, request, SOCKET_PATH
from bridge_paths import data_directory, prepare_data, instance_lock


ROOT = data_directory()


def radio_readout(state):
    radio = state.get("radio")
    age = state.get("radio_age")
    if not radio:
        return "Radio feedback: waiting for RUMlogNG", False
    recent = age is not None and age <= 3 and not state.get("radio_error")
    fresh = recent and all(radio.get(side + "_hz") is not None for side in ("rx", "tx"))
    def band(side):
        hz = radio.get(side + "_hz")
        frequency = f"{hz / 1000000:.6f}" if hz is not None else "waiting…"
        mode = radio.get(side + "_mode")
        return frequency + (f" {mode}" if mode else "")
    return ("Radio " if recent else "Last read (stale) ") + f"RX {band('rx')}   TX {band('tx')}", fresh


class App:
    def __init__(self, root):
        self.root = root
        root.title("Satellite Bridge — IC-9700")
        root.geometry("700x640")
        root.minsize(620, 600)
        root.configure(bg="#edf1f5")
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#edf1f5")
        style.configure("Card.TFrame", background="white")
        style.configure("TLabel", background="#edf1f5", foreground="#182c3e", font=("Helvetica", 11))
        style.configure("Card.TLabel", background="white")
        style.configure("Title.TLabel", font=("Helvetica", 20, "bold"))
        style.configure("TButton", font=("Helvetica", 11), padding=(10, 6))
        style.configure("Source.TButton", background="#e1e7ec", foreground="#294458", font=("Helvetica", 12, "bold"))
        style.map("Source.TButton",
                  background=[("selected", "alternate", "#f7e3b6"), ("selected", "#146a73"), ("active", "#cbd6df"), ("!selected", "#e1e7ec")],
                  foreground=[("selected", "alternate", "#76551c"), ("selected", "white"), ("!selected", "#294458")],
                  relief=[("selected", "sunken"), ("!selected", "raised")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=5)
        style.configure("Treeview", rowheight=26, font=("Helvetica", 11))
        self.settings = Settings(ROOT / "bridge-settings.json")
        self.jobs, self.control_jobs = queue.Queue(), queue.Queue()
        self.selected_id = None
        self.editor_id = None
        self.settings_window = None
        self.log = None
        self._last_event = None
        self._last_packet = None
        self.packets_visible = tk.BooleanVar(value=True)
        self.shutting_down = False
        self.name, self.rx, self.tx = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.rx_mode, self.tx_mode = tk.StringVar(value="USB-D"), tk.StringVar(value="USB-D")
        self.radio_panel = RumlogPanel()
        self.power_control = NativePowerControl(self.radio_panel)
        self.filter_control = NativeRxFilterControl(self.radio_panel)
        self.bridge = Bridge(transport_factory=self.transport, journal=ROOT / "bridge-events.jsonl", power_guard=self.power_control.limit, rx_filter=self.filter_control.select, radio_reader=self.power_control.feedback, verify_qo=True, split_controller=self.apply_virtual_split)
        self.power_control.log = self.bridge.log
        self.filter_control.log = self.bridge.log
        try:
            self.bridge.start()
        except OSError as error:
            messagebox.showerror("UDP receiver unavailable", f"Cannot listen on 127.0.0.1:9932.\n{error}\nClose the other receiver and restart.")
            root.destroy()
            raise SystemExit(1)
        self.build()
        self.refresh_presets()
        self.control_server = start_server(self.control_request)
        root.protocol("WM_DELETE_WINDOW", self.close)
        if sys.platform == "darwin":
            root.createcommand("tk::mac::Quit", self.close)
            root.createcommand("tk::mac::ReopenApplication", self.activate)
        root.after(150, self.refresh)
        # Let Cocoa/Tk draw its first frame before starting radio controls.
        # An explicit source choice during this interval cancels the default.
        self.startup_epoch = self.bridge.epoch
        root.after(300, self.start_digital_if_unchanged)

    def activate(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def transport(self, log):
        def ensure_sat():
            if not self.radio_panel.sat_on():
                if Commander("127.0.0.1", 7400, []).command("CmdSendTx", reply="CmdTX").upper() != "OFF":
                    raise RuntimeError("Release PTT before enabling satellite mode")
                self.radio_panel.enable_sat()
            log("sat_ready", state="ON")
        def write_pair(pair, previous, force):
            needs_rx = previous is None or any(getattr(previous, key) != getattr(pair, key)
                                               for key in ("rx_mode", "tx_mode", "tx_tone_hz", "rx_tone_hz")) or (
                                                   dial_band(previous.rx_hz),dial_band(previous.tx_hz)) != (dial_band(pair.rx_hz),dial_band(pair.tx_hz))
            def check_rx():
                if needs_rx and transport.command("CmdSendTx", reply="CmdTX").upper() != "OFF":
                    # A partially written pair must pause, never be replayed
                    # automatically when the operator releases PTT.
                    raise RuntimeError("Release PTT and select the pair again")
            def set_frequency(hz):
                khz = format(Decimal(hz) / 1000, ".3f")
                transport.command("CmdSetFreq", field("xcvrfreq", khz))
            self.radio_panel.apply_satellite_pair(pair, previous, set_frequency, check_rx, log,
                                                  continuous=self.bridge.source == "macdoppler",rx_profile=self.bridge.source)
            if self.bridge.source == "macdoppler" and (previous is None or
                    (dial_band(previous.tx_hz),previous.tx_mode) != (dial_band(pair.tx_hz),pair.tx_mode)):
                def require_rx():
                    if transport.command("CmdSendTx",reply="CmdTX").upper() != "OFF":
                        raise RuntimeError("Release PTT before applying MacDoppler's TX power default")
                self.power_control.set_default(80,require_rx)
            return True
        transport = Transport(log, ensure_sat=ensure_sat, pair_writer=write_pair)
        return transport

    def apply_virtual_split(self, base_hz, offset_hz, remember_base):
        def check_rx():
            if self.bridge.transport.command("CmdSendTx",reply="CmdTX").upper() != "OFF":
                raise RuntimeError("Release PTT before changing virtual split")
        def set_frequency(hz):
            self.bridge.transport.command("CmdSetFreq",field("xcvrfreq",format(Decimal(hz)/1000,".3f")))
        return self.radio_panel.apply_virtual_split(base_hz,offset_hz,remember_base,set_frequency,check_rx)

    def build(self):
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x")
        ttk.Label(header, text="Satellite Bridge", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Settings…", command=self.open_settings).pack(side="right")
        switches = ttk.Frame(outer)
        switches.pack(fill="x", pady=(10, 8))
        self.qo_button = ttk.Button(switches, text="QO-100", command=self.use_qo, style="Source.TButton")
        self.qo_button.pack(side="left", fill="x", expand=True, padx=(0, 7))
        self.md_button = ttk.Button(switches, text="MacDoppler", command=lambda: self.run_job(self.bridge.follow_macdoppler), style="Source.TButton")
        self.md_button.pack(side="left", fill="x", expand=True, padx=(0, 7))
        ttk.Button(switches, text="Pause tuning", command=lambda: self.run_job(self.bridge.pause)).pack(side="right")
        self.banner = tk.Label(outer, text="", anchor="w", padx=10, pady=7, font=("Helvetica", 11, "bold"), bg="#dbe5ed", fg="#22364a", wraplength=640, justify="left")
        self.banner.pack(fill="x", pady=(0, 10))
        ttk.Label(outer, text="QO-100 pairs — click a row to tune", font=("Helvetica", 11, "bold")).pack(anchor="w", pady=(0, 5))
        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        self.pairs = ttk.Treeview(table_frame, columns=("name", "rx", "tx", "modes"), show="headings", selectmode="browse", height=4)
        for key, title, width in (("name", "Pair", 170), ("rx", "RX MHz", 120), ("tx", "TX MHz", 120), ("modes", "RX / TX mode", 135)):
            self.pairs.heading(key, text=title)
            self.pairs.column(key, width=width, minwidth=90, stretch=True)
        self.pairs.tag_configure("active", background="#e4f3ec")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.pairs.yview)
        self.pairs.configure(yscrollcommand=scrollbar.set)
        self.pairs.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.pairs.bind("<ButtonRelease-1>", self.pair_clicked)
        self.pairs.bind("<Return>", self.pair_entered)
        split_row = ttk.Frame(outer)
        split_row.pack(fill="x",pady=(7,0))
        ttk.Label(split_row,text="Virtual split:").pack(side="left",padx=(0,8))
        self.split_choice = tk.IntVar(value=0)
        self.split_buttons = []
        for index in range(4):
            button = ttk.Radiobutton(split_row,text="Off" if index==0 else "—",variable=self.split_choice,
                                     value=0 if index==0 else index,command=self.change_virtual_split)
            button.pack(side="left",padx=(0,8))
            self.split_buttons.append(button)
        self.split_text = ttk.Label(outer,text="",foreground="#657589",font=("Helvetica",10))
        self.split_text.pack(anchor="w",pady=(3,0))
        info = ttk.Frame(outer, style="Card.TFrame", padding=(10, 9))
        info.pack(fill="x", pady=(10, 0))
        self.sent_text = ttk.Label(info, text="Radio feedback: waiting for RUMlogNG", style="Card.TLabel", font=("Menlo", 11))
        self.sent_text.pack(anchor="w")
        self.power_text = ttk.Label(info, text="QO-100 TX ceiling: 5%", style="Card.TLabel", foreground="#15593f", font=("Helvetica", 11, "bold"))
        self.power_text.pack(anchor="w", pady=(5, 0))
        self.md_text = ttk.Label(info, text="MacDoppler: waiting for packets", style="Card.TLabel", foreground="#657589", wraplength=630)
        self.md_text.pack(anchor="w", pady=(5, 0))
        packet_header = ttk.Frame(outer)
        packet_header.pack(fill="x", pady=(8, 3))
        ttk.Checkbutton(packet_header, text="MacDoppler packets", variable=self.packets_visible, command=self.toggle_packets).pack(side="left")
        self.packet_frame = ttk.Frame(outer)
        self.packet_frame.pack(fill="x")
        self.packet_text = tk.Text(self.packet_frame, height=4, wrap="word", font=("Menlo", 9), bg="white", fg="#294458", relief="flat", padx=6, pady=4, state="disabled")
        packet_scroll = ttk.Scrollbar(self.packet_frame, orient="vertical", command=self.packet_text.yview)
        self.packet_text.configure(yscrollcommand=packet_scroll.set)
        self.packet_text.pack(side="left", fill="x", expand=True)
        packet_scroll.pack(side="right", fill="y")
        self.counters = ttk.Label(outer, text="", foreground="#657589", font=("Helvetica", 10))
        self.counters.pack(anchor="w", pady=(7, 0))

    def toggle_packets(self):
        if self.packets_visible.get():
            self.packet_frame.pack(fill="x", before=self.counters)
        else:
            self.packet_frame.pack_forget()

    def refresh_presets(self):
        selected = self.selected_id
        self.pairs.delete(*self.pairs.get_children())
        for p in self.settings.data["presets"]:
            self.pairs.insert("", "end", iid=p["id"], values=(p["name"], p["rx_mhz"], p["tx_mhz"], f"{p['rx_mode']} / {p['tx_mode']}"))
        if selected and self.pairs.exists(selected):
            self.pairs.selection_set(selected)
        if self.settings_window and self.settings_window.winfo_exists():
            self.editor_choice["values"] = [p["name"] for p in self.settings.data["presets"]]

    def start_digital_if_unchanged(self):
        if not self.shutting_down and self.bridge.epoch == self.startup_epoch:
            self.start_digital()

    def start_digital(self):
        # Always enter Digital on a new launch, even when the last operation
        # selected a different pair or MacDoppler. The receiver starts blocked;
        # use_qo100 queues the normal power checks before any tuning command.
        digital = [p for p in self.settings.data["presets"] if p["name"].strip().casefold() == "digital"]
        if len(digital) != 1:
            self.bridge.pause()
            with self.bridge.lock:
                self.bridge.status = "Startup paused — configure the Digital pair in Settings"
                self.bridge.error = "A single QO-100 pair named Digital is required for automatic startup"
            self.bridge.log("startup_blocked", reason="Digital preset missing or ambiguous")
            return
        preset = digital[0]
        pair = Pair.from_values(preset["rx_mhz"], preset["tx_mhz"], preset["rx_mode"], preset["tx_mode"])
        self.select_pair(preset)
        self.bridge.use_qo100(pair, preset["name"])
        self.bridge.log("startup_digital", preset_id=preset["id"], pair=pair.view())

    def select_pair(self, preset):
        self.selected_id = preset["id"]
        self.pairs.selection_set(preset["id"])
        self.pairs.see(preset["id"])

    def pair_clicked(self, event):
        row = self.pairs.identify_row(event.y)
        if row:
            self.selected_id = row
            self.pairs.selection_set(row)
            self.use_qo()

    def pair_entered(self, event=None):
        chosen = self.pairs.selection()
        if chosen:
            self.selected_id = chosen[0]
            self.use_qo()
        return "break"

    def use_qo(self):
        preset = next((p for p in self.settings.data["presets"] if p["id"] == self.selected_id), None)
        if not preset:
            self.open_settings()
            return
        self.settings.data["home_id"] = preset["id"]
        self.settings.save()
        pair = Pair.from_values(preset["rx_mhz"], preset["tx_mhz"], preset["rx_mode"], preset["tx_mode"])
        self.run_job(lambda: self.bridge.use_qo100(pair, preset["name"]))

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = self.settings_window = tk.Toplevel(self.root)
        win.title("Satellite Bridge — Settings")
        win.geometry("650x410")
        win.minsize(600, 380)
        win.configure(bg="#edf1f5")
        tabs = ttk.Notebook(win)
        tabs.pack(fill="both", expand=True, padx=12, pady=12)
        editor = ttk.Frame(tabs, padding=16)
        diagnostics = ttk.Frame(tabs, padding=10)
        tabs.add(editor, text="QO-100 pairs")
        tabs.add(diagnostics, text="Diagnostics")
        editor.columnconfigure(0, weight=1)
        editor.columnconfigure(1, weight=1)
        self.editor_choice = ttk.Combobox(editor, state="readonly", values=[p["name"] for p in self.settings.data["presets"]])
        self.editor_choice.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        self.editor_choice.bind("<<ComboboxSelected>>", self.editor_selected)
        ttk.Label(editor, text="Pair name").grid(row=1, column=0, sticky="w")
        ttk.Entry(editor, textvariable=self.name).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(4, 12))
        ttk.Label(editor, text="RX dial MHz").grid(row=3, column=0, sticky="w")
        ttk.Label(editor, text="TX dial MHz").grid(row=3, column=1, sticky="w")
        ttk.Entry(editor, textvariable=self.rx).grid(row=4, column=0, sticky="ew", padx=(0, 8), pady=(4, 8))
        ttk.Entry(editor, textvariable=self.tx).grid(row=4, column=1, sticky="ew", pady=(4, 8))
        ttk.Combobox(editor, textvariable=self.rx_mode, values=MODES, state="readonly").grid(row=5, column=0, sticky="ew", padx=(0, 8))
        ttk.Combobox(editor, textvariable=self.tx_mode, values=MODES, state="readonly").grid(row=5, column=1, sticky="ew")
        buttons = ttk.Frame(editor)
        buttons.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(14, 8))
        ttk.Button(buttons, text="New pair", command=self.new_pair).pack(side="left")
        ttk.Button(buttons, text="Save pair", command=self.save_pair).pack(side="left", padx=8)
        ttk.Button(buttons, text="Done", command=win.destroy).pack(side="right")
        ttk.Label(editor, text="Saving does not tune the radio. Click the pair in Operations to apply it.\nQO-100 TX ≤ 5%. RX filter: CW → 2, USB/USB-D → 1; TX unchanged.", foreground="#657589", wraplength=565).grid(row=7, column=0, columnspan=2, sticky="w")
        self.log = ttk.Treeview(diagnostics, columns=("time", "event", "detail"), show="headings", height=8)
        for key, title, width in (("time", "UTC", 70), ("event", "Event", 120), ("detail", "Details", 370)):
            self.log.heading(key, text=title)
            self.log.column(key, width=width, stretch=(key == "detail"))
        self.log.pack(fill="both", expand=True)
        ttk.Label(diagnostics, text="UDP 127.0.0.1:9932 → RUMlogNG TCP 7400\nOperations shows RUMlogNG radio readback, refreshed each second.\nCommand history records requests separately.", foreground="#657589").pack(anchor="w", pady=(8, 0))
        self._last_event = None
        preset = next((p for p in self.settings.data["presets"] if p["id"] == self.selected_id), None)
        self.edit(preset) if preset else self.new_pair()

    def edit(self, preset):
        self.editor_id = preset["id"]
        self.editor_choice.set(preset["name"])
        for key, var in (("name", self.name), ("rx_mhz", self.rx), ("tx_mhz", self.tx), ("rx_mode", self.rx_mode), ("tx_mode", self.tx_mode)):
            var.set(preset[key])

    def editor_selected(self, event=None):
        index = self.editor_choice.current()
        if index >= 0:
            self.edit(self.settings.data["presets"][index])

    def new_pair(self):
        self.editor_id = None
        self.editor_choice.set("")
        self.name.set("")
        self.rx.set("")
        self.tx.set("")
        self.rx_mode.set("USB-D")
        self.tx_mode.set("USB-D")

    def store_preset(self, name, pair, identity=None):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("Give the pair a name of at most 80 characters")
        presets = self.settings.data["presets"]
        if any(p["name"].casefold() == name.casefold() and p["id"] != identity for p in presets):
            raise ValueError("That pair name is already used")
        identity = identity or str(uuid.uuid4())
        item = {"id": identity, "name": name, **pair.view()}
        existing = next((i for i, p in enumerate(presets) if p["id"] == identity), None)
        if existing is None:
            presets.append(item)
        else:
            presets[existing] = item
        if self.selected_id is None:
            self.selected_id = identity
            self.settings.data["home_id"] = identity
        self.settings.save()
        self.refresh_presets()
        return item

    def save_pair(self):
        try:
            pair = Pair.from_values(self.rx.get(), self.tx.get(), self.rx_mode.get(), self.tx_mode.get())
            self.edit(self.store_preset(self.name.get(), pair, self.editor_id))
        except (ValueError, OSError) as error:
            messagebox.showerror("Check the QO-100 pair", str(error), parent=self.settings_window)

    def run_job(self, action, status="Switching source…"):
        self.banner.configure(text=status, bg="#f7e3b6")
        def work():
            try:
                action()
            except Exception as error:
                self.jobs.put(str(error))
        threading.Thread(target=work, daemon=True).start()

    def change_virtual_split(self):
        offset = self.split_choice.get()
        self.run_job(lambda:self.bridge.set_virtual_split(offset),status="Applying virtual TX split…")

    def control_request(self, request):
        action = request.get("action")
        if action in ("activate", "quit"):
            self.control_jobs.put((action, None, None, None))
            return {"queued": action}
        if action == "check-access":
            # Read only: verify this app's own macOS permissions before tuning.
            _, power = self.power_control.read()
            return {"rumlog_access": True, "power_percent": power}
        if action == "status":
            return {**self.bridge.snapshot(), "presets": self.settings.data["presets"]}
        if action == "follow":
            self.bridge.follow_macdoppler()
            return self.bridge.snapshot()
        if action == "pause":
            self.bridge.pause()
            return self.bridge.snapshot()
        if action == "split":
            self.bridge.set_virtual_split(request.get("offset_hz"))
            return self.bridge.snapshot()
        if action == "qo100":
            preset = next((p for p in self.settings.data["presets"] if p["name"] == request.get("name")), None)
            if not preset:
                raise ValueError("QO-100 preset not found")
            pair = Pair.from_values(preset["rx_mhz"], preset["tx_mhz"], preset["rx_mode"], preset["tx_mode"])
            self.bridge.use_qo100(pair, preset["name"])
            self.control_jobs.put(("select", preset, None, None))
            return self.bridge.snapshot()
        if action == "save-preset":
            pair = Pair.from_values(request.get("rx"), request.get("tx"), request.get("rx_mode"), request.get("tx_mode"))
            event, result = threading.Event(), {}
            self.control_jobs.put(("save", {"name": request.get("name") or "", "pair": pair}, event, result))
            if not event.wait(8):
                raise RuntimeError("Bridge UI did not process the preset request")
            if "error" in result:
                raise RuntimeError(result["error"])
            return result
        raise ValueError("Unsupported bridge action")

    def refresh(self):
        if self.shutting_down:
            return
        while not self.jobs.empty():
            messagebox.showerror("Bridge action failed", self.jobs.get())
        while not self.control_jobs.empty():
            action, data, event, result = self.control_jobs.get()
            try:
                if action == "quit":
                    self.close()
                    return
                elif action == "activate":
                    self.activate()
                elif action == "save":
                    old = next((p for p in self.settings.data["presets"] if p["name"] == data["name"]), None)
                    result["preset"] = self.store_preset(data["name"], data["pair"], old["id"] if old else None)
                else:
                    self.select_pair(data)
                    self.settings.data["home_id"] = data["id"]
                    self.settings.save()
            except Exception as error:
                if result is not None:
                    result["error"] = str(error)
            finally:
                if event:
                    event.set()
        state = self.bridge.snapshot()
        for source, label, button in (("qo100", "QO-100", self.qo_button), ("macdoppler", "MacDoppler", self.md_button)):
            selected = state["source"] == source
            paused = selected and not state["enabled"]
            button.state(["selected" if selected else "!selected", "alternate" if paused else "!alternate"])
            suffix = " (checking power)" if paused and state["power_retrying"] else " (paused)" if paused else ""
            button.configure(text=f"✓ {label}" + suffix if selected else label)
        status, bg, fg = state["status"], "#dbe5ed", "#22364a"
        if state["enabled"] and state["source"] == "qo100":
            bg, fg = "#d3eee3", "#15593f"
            if status.startswith("QO-100 active"):
                status = f"QO-100 · {state['qo_name']} · MacDoppler blocked"
            else:
                bg, fg = "#f7e3b6", "#76551c"
        elif state["enabled"]:
            bg, fg = "#d8eafa", "#164c76"
            if state["age"] is None or state["age"] > self.bridge.freshness:
                status, bg = "MacDoppler selected — waiting for fresh satellite data", "#f7e3b6"
        if state["power_retrying"]:
            status, bg, fg = "Power feedback delayed — tuning held; retrying automatically", "#f7e3b6", "#76551c"
            if "Accessibility" in state["power_error"]:
                status = "Enable Satellite Bridge in Privacy & Security → Accessibility; retrying automatically"
            elif "Unlock the Mac" in state["power_error"]:
                status = state["power_error"]
        elif state["error"]:
            status += ": " + state["error"]
            bg, fg = "#f7dcdc", "#842e2e"
        pending_split=state['virtual_split']['pending_offset_hz']
        if pending_split is not None:
            status='Restoring saved TX base…' if pending_split==0 else f'Applying TX virtual split +{pending_split//1000} kHz…'
            bg,fg='#f7e3b6','#76551c'
        elif state['virtual_split']['error']:
            status='Virtual split: '+state['virtual_split']['error']
            bg,fg='#f7dcdc','#842e2e'
        self.banner.configure(text=status, bg=bg, fg=fg, wraplength=max(550, self.root.winfo_width()-50))
        if state["power_error"] and state["power_cap_active"]:
            self.power_text.configure(text="Power unverified · tuning held · retrying", foreground="#76551c")
        elif state["power_cap_active"] and state["power_percent"] is not None:
            radio_filter = (state["radio"] or {}).get("rx_filter") if not state["radio_error"] else None
            filter_text = f" · RX filter {radio_filter}" if radio_filter else ""
            self.power_text.configure(text=f"QO-100 TX ≤ 5% · reported {state['power_percent']:g}%" + filter_text, foreground="#15593f")
        elif state['source']=='macdoppler':
            reported=(state.get('radio') or {}).get('power_percent')
            text='MacDoppler TX default: 80%' + (f' · reported {reported:g}%' if reported is not None else '')
            number=(state.get('radio') or {}).get('rx_filter')
            self.power_text.configure(text=text+(f' · RX filter {number}' if number else ''),foreground='#15593f')
        else:
            self.power_text.configure(text="QO-100 TX ceiling: 5%", foreground="#657589")
        readout, radio_fresh = radio_readout(state)
        self.sent_text.configure(text=readout, foreground="#182c3e" if radio_fresh else "#76551c")
        split = state["virtual_split"]
        mode = (state.get("radio") or {}).get("tx_mode") or (state.get("qo_pair") or {}).get("tx_mode")
        offsets = virtual_split_offsets(mode)
        qo_ready = split['available'] and pending_split is None
        for index,button in enumerate(self.split_buttons):
            value = offsets[index] if index<len(offsets) else -index
            button.configure(text="Off" if index==0 else f"+{value//1000} kHz" if value>0 else "—",value=value)
            available = (qo_ready and index<len(offsets) or index==0 and state["source"]=="qo100" and split["base_tx_hz"] is not None) and pending_split is None
            button.state(["!disabled"] if available else ["disabled"])
        self.split_choice.set(split["offset_hz"] if pending_split is None else pending_split)
        split_label = f"Saved TX base {mhz_text(split['base_tx_hz'])} MHz" if split["base_tx_hz"] is not None else "Off restores the TX frequency saved when split was enabled."
        self.split_text.configure(text=split["error"] or split_label,foreground="#76551c" if split["error"] else "#657589")
        for preset in self.settings.data["presets"]:
            active = state["enabled"] and state["status"].startswith("QO-100 active") and state["last_sent_source"] == "qo100" and state["source"] == "qo100" and preset["name"] == state["qo_name"] and all(preset.get(k) == v for k, v in (state["last_sent"] or {}).items())
            self.pairs.item(preset["id"], tags=("active",) if active else ())
        incoming = state["latest"]
        if incoming:
            text = f"MacDoppler · {state['satellite']} · RX {incoming['rx_mhz']} / TX {incoming['tx_mhz']}"
            if incoming.get("tx_tone_hz") is not None:
                tone = incoming["tx_tone_hz"]
                text += " · TX CTCSS " + (f"{tone:g} Hz requested" if tone else "off requested")
        elif state["input_error"]:
            text = f"MacDoppler · {state['satellite']} · waiting for a valid satellite pair"
        else:
            text = "MacDoppler · waiting for packets"
        sent = state.get("last_sent") or {}
        if state["source"] == "macdoppler" and state.get("last_sent_source") == "macdoppler" and sent.get("tx_tone_hz") is not None:
            tone = sent["tx_tone_hz"]
            text += "\nLast applied TX CTCSS: " + (f"{tone:g} Hz" if tone else "off")
        self.md_text.configure(text=text, wraplength=max(550, self.root.winfo_width()-50))
        self.counters.configure(text=f"Received {state['received']} · ignored {state['ignored']} · rejected {state['rejected']}    |    Radio {'live' if radio_fresh else 'waiting'} · TRX 2")
        packet_events = state["packets"]
        newest_packet = packet_events[-1] if packet_events else None
        if newest_packet != self._last_packet:
            self.packet_text.configure(state="normal")
            self.packet_text.delete("1.0", "end")
            for e in packet_events[-30:]:
                disposition = "rejected" if e["kind"] == "udp_rejected" else "forwarded" if e.get("forwarded") else "blocked" if e["kind"] == "udp_received" else "received"
                self.packet_text.insert("end", f"{e['utc'][11:23]} UTC [{disposition}] {e['packet']}\n")
            self.packet_text.see("end")
            self.packet_text.configure(state="disabled")
            self._last_packet = newest_packet
        if self.settings_window and self.settings_window.winfo_exists() and self.log and self.log.winfo_exists():
            events = state["events"]
            last = events[-1] if events else None
            if last != self._last_event:
                self.log.delete(*self.log.get_children())
                for item in events:
                    detail = {k: v for k, v in item.items() if k not in ("utc", "kind")}
                    self.log.insert("", "end", values=(item["utc"][11:19], item["kind"], json.dumps(detail)))
                self._last_event = last
        self.root.after(250, self.refresh)

    def close(self):
        self.shutting_down = True
        self.bridge.close()
        try:
            self.radio_panel.release_tracking_polling()
        except Exception as error:
            # Closing the app must still release its receiver and UI when
            # RUMlogNG is unavailable; no tuning is attempted here.
            print(f"Could not restore RUMlogNG polling: {error}", file=sys.stderr)
        self.control_server.shutdown()
        self.control_server.server_close()
        if SOCKET_PATH.exists():
            SOCKET_PATH.unlink()
        self.root.destroy()


def main():
    # Launch Services normally reopens the existing app. The lock also covers
    # a second copy or a source launch, without disturbing its UDP receiver.
    lock = instance_lock(ROOT)
    if lock is None:
        try:
            request({"action": "activate"})
        except (OSError, RuntimeError):
            pass
        return
    with lock:
        prepare_data(ROOT)
        if getattr(sys, "frozen", False):
            log_path = ROOT / "bridge-app.log"
            if log_path.exists() and log_path.stat().st_size > 1024 * 1024:
                log_path.replace(ROOT / "bridge-app.previous.log")
            stream = log_path.open("a", buffering=1)
            os.dup2(stream.fileno(), 1)
            os.dup2(stream.fileno(), 2)
            sys.stdout = sys.stderr = stream
        try:
            window = tk.Tk(className="SatelliteBridge")
            App(window)
            window.mainloop()
        except Exception as error:
            traceback.print_exc()
            messagebox.showerror("Satellite Bridge could not start", str(error))
            raise


if __name__ == "__main__":
    main()
