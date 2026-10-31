#!/usr/bin/env python3
"""FFXI (HorizonXI) respawn timer.

Watches the most recently updated *.log file in the game's chatlogs folder,
detects "<player> defeats <mob>" kill lines, and keeps one row per mob type
with a respawn countdown. Each mob can use the general timer (checkbox) or a
per-mob override. When a countdown expires, a notification (sound and/or
popup) fires.

Only the newest log file is tailed; when the game rolls over to a new log
(midnight / character change) the watcher follows it automatically.

Config lives in mob_timer_config.json next to this script. No dependencies
beyond the Python standard library.

mob_tags.json maps full decimal mob IDs to NM placeholder tags and respawn
delays. Saved edits reload automatically. Optional placeholder warnings,
automatic timer overrides, and a separate kill sound require mobid addon logs.
"""

from __future__ import annotations

import json
import math
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta

from timer_ui import PALETTES, TABLE_COLUMNS, TimerInterface

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:  # allows headless import for tests / non-GUI use
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

try:
    import winsound
except ImportError:  # non-Windows
    winsound = None

if getattr(sys, "frozen", False):
    # PyInstaller bundle: keep config next to the .exe, not in the temp dir
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "mob_timer_config.json")
TAGS_PATH = os.path.join(APP_DIR, "mob_tags.json")
AUTO_WARN_SECONDS = 20
STARTUP_LOOKBACK_SECONDS = 60 * 60

DEFAULT_CONFIG = {
    "chatlog_dir": r"D:\Games\FFXI\HorizonXI\Game\chatlogs",
    "general_minutes": "16.3333333333333",
    "sound_mode": "exclamation",  # exclamation | beep | wav | none
    "sound_file": "",
    "toast_popup": True,
    "use_mobid": False,
    "auto_warn_placeholders": False,
    "auto_placeholder_timers": False,
    "placeholder_kill_sound": False,
    "placeholder_sound_mode": "beep",
    "placeholder_sound_file": "",
    "appearance": "System",
    "mobs": {},  # key -> {"label", "use_general", "override", "killed_at"}
}

SOUND_MODES = {
    "System exclamation": "exclamation",
    "Beep": "beep",
    "System asterisk": "asterisk",
    "Single chime": "chime",
    "Custom .wav file": "wav",
    "None": "none",
}

# [HH:MM:SS] Morrowindislong defeats the Buffalo.
# [HH:MM:SS] Chronus defeats Kirin.            (NMs have no "the")
# [HH:MM:SS] Asclepius defeats Humnox Drumbelly .   (trailing space seen in logs)
# The killer token must start with a letter so chat lines like
# "[1]<Sailor> is that where van damme defeats raul julia?" or
# "<Bob> defeats the lizard" never match, and "The Buffalo defeats X"
# (mob killing a player) doesn't either.
KILL_RE = re.compile(
    r"^\[(\d{2}:\d{2}:\d{2})\] ([A-Za-z][A-Za-z0-9]*) defeats (?:the )?(.+?)\s*\.?\s*$"
)

# The "mobid" addon echoes kills with the mob's unique id:
# [HH:MM:SS] [mobid] Morrowindislong defeats Buffalo | id: 16798052 | hex: 0x01005164 | idx: 356
# Mob ids are stable per spawn slot, so they identify an individual pop.
MOBID_RE = re.compile(
    r"^\[(\d{2}:\d{2}:\d{2})\] \[mobid\] [A-Za-z][A-Za-z0-9]* defeats (.+?) \| "
    r"id: (\d+) \| hex: (0x[0-9A-Fa-f]+) \| idx: (\d+)\s*$"
)
LOG_DATE_RE = re.compile(r"(?<!\d)(\d{4})[._-](\d{2})[._-](\d{2})(?!\d)")
LOG_CLOCK_RE = re.compile(r"^\[(\d{2}:\d{2}:\d{2})\]")


def log_file_date(filename):
    """Chat logs normally include the local date, e.g. Char_2026.10.31.log."""
    match = LOG_DATE_RE.search(os.path.basename(filename))
    if match:
        try:
            return datetime(*map(int, match.groups())).date()
        except ValueError:
            pass
    return None


def reverse_log_lines(path, end_offset, chunk_size=65536):
    """Read complete lines backwards up to a captured EOF without loading a log.

    Ignore an unfinished last line; the live watcher handles it when completed.
    """
    with open(path, "rb") as f:
        position = end_offset
        tail = b""
        at_end = True
        while position > 0:
            start = max(0, position - chunk_size)
            f.seek(start)
            data = f.read(position - start)
            position = start
            parts = (data + tail).split(b"\n")
            tail = parts[0]
            for line in reversed(parts[1:]):
                if at_end:
                    # Skip the last split element, even across multiple chunks.
                    at_end = False
                    continue
                yield line.decode("utf-8", errors="replace")
        if tail and not at_end:
            yield tail.decode("utf-8", errors="replace")


def recent_placeholder_kills(directory, mob_ids, now=None, active_path=None,
                             active_offset=None, stop_requested=lambda: False):
    """Return the latest tagged kill per full ID from the last hour of logs.

    Use filename dates where available. For undated logs, work backwards from
    file modification time and track midnight rollovers using all timestamped
    lines. Read only up to captured offsets so new kills stay with the live tail.
    """
    now = time.time() if now is None else now
    cutoff = now - STARTUP_LOOKBACK_SECONDS
    first_date = datetime.fromtimestamp(cutoff).date()
    last_date = datetime.fromtimestamp(now).date()
    latest = {}
    if not mob_ids or not directory:
        return []
    try:
        with os.scandir(directory) as entries:
            files = []
            for entry in entries:
                if not entry.name.lower().endswith(".log") or not entry.is_file():
                    continue
                try:
                    stat = entry.stat()
                except OSError:
                    continue
                day = log_file_date(entry.name)
                if day is not None:
                    if not first_date <= day <= last_date:
                        continue
                elif stat.st_mtime < cutoff:
                    continue
                limit = active_offset if entry.path == active_path and active_offset is not None else stat.st_size
                files.append((entry.path, day, stat.st_mtime, limit))
    except OSError:
        return []
    for path, day, modified, limit in files:
        if stop_requested():
            break
        if day is None:
            anchor = datetime.fromtimestamp(min(modified, now))
            day = anchor.date()
            previous_clock = anchor.hour * 3600 + anchor.minute * 60 + anchor.second
        else:
            previous_clock = 24 * 3600
        try:
            for line in reverse_log_lines(path, limit):
                if stop_requested():
                    break
                clock_match = LOG_CLOCK_RE.match(line)
                if not clock_match:
                    continue
                try:
                    h, m, s = map(int, clock_match.group(1).split(":"))
                    stamp = datetime(day.year, day.month, day.day, h, m, s)
                except ValueError:
                    continue
                seconds = h * 3600 + m * 60 + s
                if seconds > previous_clock:
                    day -= timedelta(days=1)
                    stamp -= timedelta(days=1)
                previous_clock = seconds
                when = stamp.timestamp()
                if when < cutoff:
                    break
                if when > now:
                    continue
                match = MOBID_RE.match(line)
                if not match:
                    continue
                key = str(int(match.group(3)))
                if key in mob_ids and (key not in latest or when > latest[key][2]):
                    latest[key] = (key, format_mob_label(key, match.group(2).strip()), when)
        except OSError:
            continue  # a missing or locked log must not prevent live watching
    return sorted(latest.values(), key=lambda kill: (kill[2], kill[0]))


def parse_positive(text):
    """Return a positive float, or None for empty/invalid input."""
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


# parse_minutes kept as the semantic alias used for respawn-timer fields
parse_minutes = parse_positive


def fmt_clock(epoch):
    return time.strftime("%H:%M:%S", time.localtime(epoch)) if epoch else "--:--:--"


def fmt_countdown(seconds):
    seconds = max(0, int(seconds + 0.5))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def format_mob_label(key, label):
    """Keep the hex ID and add the last four digits of the full decimal ID.

    Also upgrades saved labels from earlier versions without duplicating IDs.
    Name-only rows never receive an ID or a placeholder tag.
    """
    if not str(key).isascii() or not str(key).isdigit():
        return label
    name = re.sub(r"\s*\[0x[0-9a-fA-F]+(?:\s+\(\d{4}\))?\](?:\s*\(\d{4}\))?$", "", label)
    return f"{name} [0x{int(key):08X} ({int(key) % 10000:04d})]"


def load_mob_tags(path=TAGS_PATH):
    """Validate the entire editable database before replacing in-memory tags."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError('Expected a database object with "version": 1')
    mobs = data.get("mobs")
    if not isinstance(mobs, dict):
        raise ValueError('"mobs" must be an object keyed by full decimal mob ID')
    normalized = {}
    for key, entry in mobs.items():
        if not key.isascii() or not key.isdigit() or not 0 < int(key) <= 0xFFFFFFFF:
            raise ValueError(f"Invalid full decimal mob ID: {key!r}")
        if str(int(key)) in normalized:
            raise ValueError(f"Duplicate decimal mob ID: {key}")
        if not isinstance(entry, dict):
            raise ValueError(f"{key}: expected an object")
        names = entry.get("placeholder_for", [])
        tags = entry.get("tags", [])
        respawn = entry.get("respawn_seconds")
        if respawn is not None and (isinstance(respawn, bool) or parse_positive(respawn) is None):
            raise ValueError(f"{key}: respawn_seconds must be a positive number or null")
        delay = entry.get("despawn_seconds", 0)
        if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not math.isfinite(delay) or delay < 0:
            raise ValueError(f"{key}: despawn_seconds must be a nonnegative number")
        for field, values in (("placeholder_for", names), ("tags", tags)):
            if not isinstance(values, list) or any(
                not isinstance(v, str) or not v.strip() for v in values
            ):
                raise ValueError(f"{key}: {field} must be a list of nonempty strings")
        normalized[str(int(key))] = {
            **entry,
            "placeholder_for": list(dict.fromkeys(n.strip() for n in names)),
            "tags": list(dict.fromkeys(t.strip() for t in tags)),
        }
    return normalized


def ensure_mob_tags(path=TAGS_PATH):
    """Seed an external, editable database on first launch of a bundled exe."""
    if os.path.exists(path):
        return
    bundled = os.path.join(getattr(sys, "_MEIPASS", APP_DIR), "mob_tags.json")
    if os.path.abspath(bundled) != os.path.abspath(path) and os.path.isfile(bundled):
        shutil.copyfile(bundled, path)
    else:
        with open(path, "x", encoding="utf-8") as f:
            json.dump({"version": 1, "mobs": {}}, f, indent=2)


def open_tags_editor(path=TAGS_PATH):
    """Open as text even if .json is associated with a web browser on Windows."""
    if os.name == "nt":
        subprocess.Popen(["notepad.exe", os.path.abspath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-t", os.path.abspath(path)])
    else:
        subprocess.Popen(["xdg-open", os.path.abspath(path)])


class LogWatcher(threading.Thread):
    """Tails whichever *.log file in the directory was most recently written.

    Emits ("kill", key, label, hhmmss) and ("watching", filename-or-None)
    tuples onto `events`. An optional startup scan emits ("history", kills)
    once, with the latest tagged kill and its original epoch for each ID.
    `key` identifies the tracked entity (mob name, or
    the mob's unique id when mobid mode is enabled via `mobid_getter`).
    """

    POLL_SECS = 0.5

    def __init__(self, dir_getter, events, mobid_getter=lambda: False,
                 history_ids_getter=None):
        super().__init__(daemon=True)
        self._dir_getter = dir_getter
        self._mobid_getter = mobid_getter
        self._history_ids_getter = history_ids_getter
        self._startup_pending = history_ids_getter is not None
        self.events = events
        self._stop_flag = threading.Event()
        self._path = None
        self._dir = None
        self._attached = False
        self._offset = 0
        self._buf = b""

    def stop(self):
        self._stop_flag.set()

    def run(self):
        while not self._stop_flag.is_set():
            directory = self._dir_getter()
            if directory != self._dir:
                self._dir, self._path, self._attached = directory, None, False
            self._poll()
            time.sleep(self.POLL_SECS)

    def _poll(self):
        newest = self._newest_log(self._dir)
        if newest != self._path or not self._attached:
            if self._path:
                self._read_new()  # drain anything left in the old file
            self._attach(newest)
        if self._startup_pending:
            self._startup_pending = False
            # Attach first so kills appended during scanning are read live.
            kills = recent_placeholder_kills(
                self._dir, set(self._history_ids_getter()),
                active_path=self._path, active_offset=self._offset,
                stop_requested=self._stop_flag.is_set,
            )
            self.events.put(("history", kills))
        if self._path:
            self._read_new()

    def _attach(self, path):
        self._path = path
        self._attached = True
        self._offset = 0
        self._buf = b""
        if path:
            try:
                with open(path, "rb") as f:
                    f.seek(0, os.SEEK_END)
                    self._offset = f.tell()
                    # Carry an in-progress line across the startup EOF boundary.
                    f.seek(max(0, self._offset - 65536))
                    tail = f.read(self._offset - f.tell())
                    if tail and not tail.endswith(b"\n"):
                        self._buf = tail.rsplit(b"\n", 1)[-1]
            except OSError:
                self._offset = 0
        self.events.put(
            ("watching", os.path.basename(path) if path else None)
        )

    @staticmethod
    def _newest_log(directory):
        newest, newest_mtime = None, -1.0
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    if entry.name.lower().endswith(".log") and entry.is_file():
                        try:
                            mtime = entry.stat().st_mtime
                        except OSError:
                            continue
                        if mtime > newest_mtime:
                            newest, newest_mtime = entry.path, mtime
        except OSError:
            return None
        return newest

    def _read_new(self):
        try:
            size = os.path.getsize(self._path)
            if size == self._offset:
                return
            if size < self._offset:
                self._offset = 0  # truncated/rotated: start over
            with open(self._path, "rb") as f:
                f.seek(self._offset)
                data = f.read()
                self._offset = f.tell()
        except OSError:
            return
        self._buf += data
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            self._handle_line(raw.decode("utf-8", errors="replace"))

    def _handle_line(self, line):
        if self._mobid_getter():
            m = MOBID_RE.match(line)
            if m:
                name, mobid = m.group(2).strip(), str(int(m.group(3)))
                self.events.put(
                    ("kill", mobid, format_mob_label(mobid, name), m.group(1))
                )
            return
        m = KILL_RE.match(line)
        if m:
            name = m.group(3).strip()
            self.events.put(("kill", name, name, m.group(1)))


# ---------------------------------------------------------------------------
# GUI (requires tkinter)
# ---------------------------------------------------------------------------


# Shared minimum widths keep the list header and timer rows aligned.
COLUMN_WIDTHS = TABLE_COLUMNS

class MobRow:
    """State + widgets for a single mob type."""

    def __init__(self, app, key, label, use_general=True, override="",
                 killed_at=0.0, warn=False, warn_secs="", auto_timer_backup=None,
                 auto_warn_backup=None, tracked=True):
        self.app = app
        self.key = key
        self.tracked = bool(tracked)
        self.label = format_mob_label(key, label)
        self.display_label = self.label
        self.killed_at = killed_at
        self.end_at = None  # epoch when respawn is due, or None if untimed
        self.fired = False  # spawn notification already sent for this timer
        self.warned = False  # pre-spawn warning already sent for this timer
        self.auto_warned = False
        self.auto_timer_backup = auto_timer_backup
        self.auto_warn_backup = auto_warn_backup

        self.frame = tk.Frame(app.rows_inner, bd=0)
        for col, width in enumerate(COLUMN_WIDTHS):
            self.frame.grid_columnconfigure(col, minsize=width, weight=1 if col == 0 else 0)
        self.name_cell = app._frame(self.frame)
        self.name_cell.grid(row=0, column=0, sticky="ew", padx=6, pady=5)
        name, _, identity = self.label.partition(" [0x")
        self.name_lbl = app._label(self.name_cell, name, size=10, bold=True, wraplength=220)
        self.name_lbl.pack(anchor="w", fill="x")
        self.identity_lbl = app._label(self.name_cell, "[0x" + identity if identity else "",
                                       size=8, color="muted")
        if identity:
            self.identity_lbl.pack(anchor="w")
        self.tag_lbl = app._label(self.name_cell, size=9, wraplength=220, responsive=False)
        self.name_cell.bind("<Configure>", lambda e: self.tag_lbl.configure(wraplength=max(80, e.width - 4)))
        self.count_lbl = app._label(self.frame, size=14, bold=True)
        self.count_lbl.grid(row=0, column=1, sticky="w", padx=6, pady=5)

        timer = app._frame(self.frame)
        timer.grid(row=0, column=2, sticky="w", padx=6, pady=5)
        self.use_var = tk.BooleanVar(value=use_general)
        self.use_chk = app._check(timer, "Default", self.use_var, app.on_row_setting_changed, compact=True)
        self.override_var = tk.StringVar(value=override)
        duration = app._frame(timer)
        duration.pack(fill="x", pady=(2, 0))
        self.duration_label = app._label(duration, "Custom", size=9, color="muted", width=6)
        self.duration_label.pack(side="left")
        self.override_ent = app._entry(duration, self.override_var, width=6)
        self.override_ent.pack(side="left", ipady=1)
        self.override_var.trace_add("write", lambda *_: app.on_override_typed(self))

        alerts = app._frame(self.frame)
        alerts.grid(row=0, column=3, sticky="w", padx=6, pady=5)
        self.warn_var = tk.BooleanVar(value=warn)
        self.warn_chk = app._check(alerts, "Alert", self.warn_var, app.on_row_setting_changed, compact=True)
        self.warn_secs_var = tk.StringVar(value=warn_secs)
        early = app._frame(alerts)
        early.pack(fill="x", pady=(2, 0))
        app._label(early, "Early", size=9, color="muted", width=6).pack(side="left")
        self.warn_secs_ent = app._entry(early, self.warn_secs_var, width=5)
        self.warn_secs_ent.pack(side="left", ipady=1)
        self.warn_secs_var.trace_add("write", lambda *_: app.on_warn_secs_typed(self))
        self.killed_lbl = app._label(self.frame, size=9, color="muted")
        self.killed_lbl.grid(row=0, column=4, sticky="w", padx=6)
        actions = app._frame(self.frame)
        actions.grid(row=0, column=5, padx=6, pady=4)
        self.remove_btn = app._ttk.Button(actions, text="Remove", width=0,
            command=lambda: app.remove_row(self.key), style="Remove.Row.TButton", takefocus=True)
        self.remove_btn.pack(fill="x")
        self.tracking_btn = app._ttk.Button(actions, text="Untrack" if self.tracked else "Track",
            width=0, command=lambda: app.set_row_tracked(self.key, not self.tracked),
            style="Row.TButton", takefocus=True)
        self.tracking_btn.pack(fill="x", pady=(2, 0))
        self.divider = tk.Frame(self.frame, height=1)
        self.divider.grid(row=1, column=0, columnspan=len(COLUMN_WIDTHS), sticky="ew")
        self.apply_theme()
        self._show_killed()
        self.refresh_tags()

    def refresh_tags(self):
        entry = self.app.mob_tags.get(self.key, {})
        names = entry.get("placeholder_for", [])
        tags = entry.get("tags", [])
        details = (["PH for: " + ", ".join(names)] if names else []) + tags
        self.display_label = self.label + ("\n" + " | ".join(details) if details else "")
        self.tag_lbl.config(text=" | ".join(details).replace("PH for: ", "Placeholder for: "))
        if details:
            self.tag_lbl.pack(anchor="w")
        else:
            self.tag_lbl.pack_forget()

    def refresh_settings_summary(self):
        """Identify managed controls without adding height to the timer row."""
        if not hasattr(self, "duration_label"):
            return
        self.duration_label.configure(text="Auto" if self.auto_timer_backup is not None else "Custom")
        self.warn_chk.configure(text="Auto alert" if self.auto_warning_enabled() else "Alert")
        self.tracking_btn.configure(text="Untrack" if self.tracked else "Track")

    def apply_theme(self):
        p = self.app.palette
        self.frame.configure(bg=p["surface"])
        self.divider.configure(bg=p["border"])
        self.tag_lbl.configure(bg=p["tag_bg"], fg=p["tag_text"], padx=2, pady=0)
        # Shared controls are recolored by the interface's theme registry.
        for field, variable, parse in ((self.override_ent, self.override_var, parse_minutes),
                                       (self.warn_secs_ent, self.warn_secs_var, parse_positive)):
            invalid = bool(variable.get().strip()) and parse(variable.get()) is None
            field.configure(bg=p["error_bg"] if invalid else p["surface"])
        self.refresh_settings_summary()
        if hasattr(self, "_count_text"):
            self._set_count(self._count_text, self._count_color)

    def auto_warning_enabled(self):
        return bool(self.app.auto_warn_var.get() and self.app.is_placeholder(self.key))

    def apply_auto_warning(self):
        """Show and lock automatic warning settings, keeping manual values."""
        active = self.auto_warning_enabled()
        self.app._updating_auto_warn = True
        try:
            if active:
                if self.auto_warn_backup is None:
                    self.auto_warn_backup = {
                        "warn": bool(self.warn_var.get()),
                        "warn_secs": self.warn_secs_var.get(),
                    }
                self.warn_var.set(True)
                self.warn_secs_var.set(str(AUTO_WARN_SECONDS))
            elif self.auto_warn_backup is not None:
                self.warn_var.set(self.auto_warn_backup.get("warn", False))
                self.warn_secs_var.set(self.auto_warn_backup.get("warn_secs", ""))
                self.auto_warn_backup = None
            ws = self.warn_secs_var.get().strip()
            bad = bool(ws) and parse_positive(ws) is None
            self.warn_secs_ent.config(
                state="disabled" if active else "normal",
                bg=self.app.palette["error_bg"] if bad else self.app.palette["surface"],
            )
            self.warn_chk.config(state="disabled" if active else "normal")
        finally:
            self.app._updating_auto_warn = False
        self.refresh_timer()

    def apply_auto_timer(self):
        entry = self.app.mob_tags.get(self.key, {})
        seconds = parse_positive(entry.get("respawn_seconds"))
        active = bool(
            self.app.auto_timer_var.get() and entry.get("placeholder_for") and seconds
        )
        self.app._updating_auto_timer = True
        try:
            if active:
                if self.auto_timer_backup is None:
                    self.auto_timer_backup = {
                        "use_general": bool(self.use_var.get()),
                        "override": self.override_var.get(),
                    }
                delay = entry.get("despawn_seconds", 0)
                self.override_var.set(format((seconds + delay) / 60, ".12g"))
                self.use_var.set(False)
            elif self.auto_timer_backup is not None:
                self.override_var.set(self.auto_timer_backup.get("override", ""))
                self.use_var.set(self.auto_timer_backup.get("use_general", True))
                self.auto_timer_backup = None
            self.override_ent.config(state="disabled" if active else "normal")
            self.use_chk.config(state="disabled" if active else "normal")
        finally:
            self.app._updating_auto_timer = False
        self.refresh_timer()

    def destroy(self):
        self.frame.destroy()

    def effective_minutes(self):
        ov = parse_minutes(self.override_var.get())
        if ov is not None:
            return ov
        if self.use_var.get():
            return parse_minutes(self.app.general_var.get())
        return None

    def warn_seconds(self):
        return parse_positive(self.warn_secs_var.get())

    def record_kill(self, when):
        self.killed_at = when
        self.fired = False
        self.warned = False
        self.auto_warned = False
        mins = self.effective_minutes()
        self.end_at = when + mins * 60 if mins else None
        self._show_killed()

    def refresh_timer(self):
        """Recompute end_at after a setting changes.

        An already-overdue timer is marked fired so tweaking settings
        never triggers a retroactive alert; a timer still in the
        future is re-armed. Same for the pre-spawn warning point.
        """
        self.refresh_settings_summary()
        if not self.killed_at:
            self.end_at = None
            return
        mins = self.effective_minutes()
        self.end_at = self.killed_at + mins * 60 if mins else None
        now = time.time()
        self.fired = bool(self.end_at and self.end_at <= now)
        warn_at = self._warn_at()
        if warn_at is None or warn_at > now:
            # warn point is in the future (or gone) -> re-arm. If it is
            # already past, keep the flag: a stale True prevents repeat
            # warnings, a fresh False fires immediately next tick (warn
            # enabled while already inside the window).
            self.warned = False
        if self.end_at is None or self.end_at - AUTO_WARN_SECONDS > now:
            self.auto_warned = False

    def _warn_at(self):
        ws = self.warn_seconds()
        if self.end_at is None or ws is None:
            return None
        return self.end_at - ws

    def _show_killed(self):
        self.killed_lbl.config(text=fmt_clock(self.killed_at))

    def update_display(self, now):
        self.refresh_settings_summary()
        if not self.tracked:
            self._set_count("Paused", "muted")
            return False
        manual_on = bool(self.warn_var.get())
        auto_on = self.auto_warning_enabled()
        warn_on = manual_on or auto_on
        if self.end_at is None:
            self._set_count("No timer", "muted")
            return False
        remaining = self.end_at - now
        if remaining > 0:
            self._set_count(
                fmt_countdown(remaining), "forest green" if warn_on else "black"
            )
            warn_at = self._warn_at()
            manual_due = manual_on and warn_at is not None and now >= warn_at and not self.warned
            auto_due = auto_on and remaining <= AUTO_WARN_SECONDS and not self.auto_warned
            if manual_due:
                self.warned = True
            if auto_due:
                self.auto_warned = True
            if manual_due or auto_due:
                self.app.notify_warn(
                    self.display_label, max(0, int(round(remaining)))
                )
            return True
        self._set_count("Due now", "dark orange" if warn_on else "red")
        if not self.fired:
            self.fired = True
            if warn_on:
                self.app.notify(self.display_label)
        return True

    def _set_count(self, text, color):
        self._count_text, self._count_color = text, color
        p = getattr(self.app, "palette", PALETTES["Light"])
        semantic = {"black": "text", "forest green": "success", "dark orange": "warning", "red": "warning"}
        self.count_lbl.config(text=text, fg=p[semantic.get(color, color)])

    def sort_key(self, now):
        if self.end_at is None:
            return (2, 0, self.label.lower())
        if self.end_at > now:
            return (0, self.end_at, self.label.lower())
        return (1, -(self.killed_at or 0), self.label.lower())

class App(TimerInterface):
    sound_modes = SOUND_MODES
    format_countdown = staticmethod(fmt_countdown)
    parse_timer = staticmethod(parse_minutes)

    def __init__(self, root):
        self.root = root
        self._tk, self._ttk = tk, ttk
        root.title("FFXI Respawn Timer")

        self.cfg = self._load_config()
        self.events = queue.Queue()
        self.rows = {}          # mob name -> MobRow
        self._order = []        # current row display order
        self._toasts = []
        self.chatlog_dir = self.cfg["chatlog_dir"]
        self.use_mobid = bool(self.cfg.get("use_mobid", False))
        self.mob_tags = {}
        self._tags_signature = None
        self._tags_error = ""
        self._updating_auto_timer = False
        self._updating_auto_warn = False

        self._build_ui()
        self.reload_tags()
        for key, saved in self.cfg["mobs"].items():
            self._get_or_create_row(
                key,
                label=saved.get("label", key),
                use_general=saved.get("use_general", True),
                override=saved.get("override", ""),
                killed_at=saved.get("killed_at", 0.0),
                warn=saved.get("warn", False),
                warn_secs=saved.get("warn_secs", ""),
                auto_timer_backup=saved.get("auto_timer_backup"),
                auto_warn_backup=saved.get("auto_warn_backup"),
                tracked=saved.get("tracked", True),
            )
        for row in self.rows.values():
            row.refresh_timer()

        self.watcher = LogWatcher(
            lambda: self.chatlog_dir,
            self.events,
            mobid_getter=lambda: self.use_mobid,
            history_ids_getter=lambda: {
                key for key, entry in self.mob_tags.items() if entry.get("placeholder_for")
            },
        )
        self.watcher.start()

        root.after(200, self._drain_events)
        root.after(500, self._tick)
        root.after(15000, self._autosave)
        root.after(2000, self._check_tags_file)
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- config -------------------------------------------------------

    def _load_config(self):
        cfg = dict(DEFAULT_CONFIG)
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except (OSError, ValueError):
            pass
        return cfg

    def save_config(self):
        self.cfg["chatlog_dir"] = self.chatlog_dir
        self.cfg["general_minutes"] = self.general_var.get()
        self.cfg["sound_mode"] = SOUND_MODES[self.sound_var.get()]
        self.cfg["sound_file"] = self.sound_file_var.get()
        self.cfg["toast_popup"] = bool(self.popup_var.get())
        self.cfg["use_mobid"] = bool(self.mobid_var.get())
        self.cfg["auto_warn_placeholders"] = bool(self.auto_warn_var.get())
        self.cfg["auto_placeholder_timers"] = bool(self.auto_timer_var.get())
        self.cfg["placeholder_kill_sound"] = bool(self.kill_sound_var.get())
        self.cfg["placeholder_sound_mode"] = SOUND_MODES[self.kill_sound_mode_var.get()]
        self.cfg["placeholder_sound_file"] = self.kill_sound_file_var.get()
        self.cfg["appearance"] = self.appearance_var.get()
        self.cfg["mobs"] = {
            key: {
                "label": row.label,
                "tracked": row.tracked,
                "use_general": bool(row.use_var.get()),
                "override": row.override_var.get(),
                "killed_at": row.killed_at,
                "warn": bool(row.warn_var.get()),
                "warn_secs": row.warn_secs_var.get(),
                "auto_timer_backup": row.auto_timer_backup,
                "auto_warn_backup": row.auto_warn_backup,
            }
            for key, row in self.rows.items()
        }
        try:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, indent=2)
            os.replace(tmp, CONFIG_PATH)  # atomic: no half-written config
        except OSError as e:
            self.status_var.set(f"Config save failed: {e}")

    # -- UI construction -----------------------------------------------

    # -- mob rows ------------------------------------------------------

    def is_placeholder(self, key):
        return bool(self.mob_tags.get(key, {}).get("placeholder_for"))

    def reload_tags(self):
        try:
            ensure_mob_tags()
            tags = load_mob_tags()
            stat = os.stat(TAGS_PATH)
        except (OSError, ValueError) as e:
            self._tags_error = f"Tag database error: {e} (previous tags kept)"
            self.tags_status_var.set("Tag file error — see status")
            self.status_var.set(self._tags_error)
            return False
        self.mob_tags = tags
        self._tags_signature = (stat.st_mtime_ns, stat.st_size)
        self._tags_error = ""
        count = sum(bool(e.get("placeholder_for")) for e in tags.values())
        self.tags_status_var.set(f"{count} placeholder IDs")
        for row in self.rows.values():
            row.refresh_tags()
            row.apply_auto_warning()
            row.apply_auto_timer()
        self.status_var.set(f"Loaded {len(tags)} mob tags from {TAGS_PATH}")
        self._refresh_tag_table()
        self._refresh_overview()
        return True

    def _edit_tags(self):
        try:
            ensure_mob_tags()
            open_tags_editor()
            self.status_var.set(f"Tag database opened. Saved edits reload automatically: {TAGS_PATH}")
        except OSError as e:
            self.status_var.set(f"Cannot open tag editor: {e}. File: {TAGS_PATH}")

    def _check_tags_file(self):
        try:
            stat = os.stat(TAGS_PATH)
            signature = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            signature = None
        if signature != self._tags_signature:
            # Remember failed versions too; retry once the user saves again.
            self.reload_tags()
            self._tags_signature = signature
        self.root.after(2000, self._check_tags_file)

    def _get_or_create_row(self, key, label=None, **kwargs):
        row = self.rows.get(key)
        if row is None:
            row = MobRow(self, key, label or key, **kwargs)
            self.rows[key] = row
            row.apply_auto_warning()
            row.apply_auto_timer()
            self._order = None  # force re-sort
        return row

    def remove_row(self, key):
        row = self.rows.pop(key, None)
        if row:
            focused = self.root.focus_get()
            restore_focus = focused and str(focused).startswith(str(row.frame) + ".")
            row.destroy()
            if restore_focus:
                self.search_entry.focus_set()
            self._order = None
            self.save_config()
            self.status_var.set(f"Removed {row.label}.")
            self._refresh_overview()

    def set_row_tracked(self, key, tracked):
        row = self.rows.get(key)
        if row is None or row.tracked == bool(tracked):
            return
        row.tracked = bool(tracked)
        # Keep the saved defeat and settings; suppress stale due alerts on return.
        row.refresh_timer()
        row.update_display(time.time())
        focused = self.root.focus_get()
        if focused and str(focused).startswith(str(row.frame) + "."):
            self.search_entry.focus_set()
        self._order = None
        self.status_var.set(f"Tracking {row.label} again." if row.tracked else
                            f"Moved {row.label} to Untracked. Kills and alerts are paused; choose Track to restore it.")
        self.save_config()
        self._refresh_overview()

    def _clear_all(self):
        untracked_view = self.filter_var.get() == "Untracked"
        keys = [key for key, row in self.rows.items() if row.tracked != untracked_view]
        if not keys:
            return
        scope = "untracked" if untracked_view else "tracked"
        if not messagebox.askyesno(
            "Clear all",
            f"Remove all {len(keys)} {scope} mob entries and their settings?",
        ):
            return
        for key in keys:
            self.rows.pop(key).destroy()
        self._order = None
        self.save_config()
        self._refresh_overview()
        self.status_var.set(f"Cleared {len(keys)} {scope} mobs. New kills will appear automatically unless untracked.")

    def on_kill(self, key, label, hhmmss):
        row = self._get_or_create_row(key, label=label)
        if not row.tracked:
            return False
        row.record_kill(time.time())
        if self.kill_sound_var.get() and self.is_placeholder(key):
            self.play_placeholder_kill_sound()
        self.save_config()
        self._refresh_overview()
        return True

    def restore_history(self, kills):
        """Restore original kill times quietly, preserving newer saved state."""
        restored = 0
        now = time.time()
        for key, label, when in kills:
            if not self.is_placeholder(key):
                continue
            row = self._get_or_create_row(key, label=label)
            if not row.tracked or when <= row.killed_at:
                continue
            row.record_kill(when)
            row.refresh_timer()
            warn_at = row._warn_at()
            row.warned = bool(warn_at is not None and warn_at <= now)
            row.auto_warned = bool(row.end_at is not None and row.end_at - AUTO_WARN_SECONDS <= now)
            restored += 1
        if restored:
            self._order = None
            self.save_config()
        self.status_var.set(
            f"Restored {restored} NM placeholder timers from the last hour   |   {self._watching}"
        )
        self._history_finished = True
        self._refresh_overview()

    def on_row_setting_changed(self):
        for row in self.rows.values():
            row.refresh_timer()
        self.save_config()
        self._refresh_overview()

    def on_override_typed(self, row):
        if self._updating_auto_timer:
            return
        ov = row.override_var.get().strip()
        bad = bool(ov) and parse_minutes(ov) is None
        row.override_ent.config(bg=self.palette["error_bg"] if bad else self.palette["surface"])
        if bad:
            self.status_var.set(f"{row.label}: Custom minutes needs a positive number. Clear it to use the default timer.")
        else:
            self.status_var.set(f"Timer updated for {row.label.split(' [0x', 1)[0]}.")
        row.refresh_timer()
        self._order = None
        self.save_config()
        self._refresh_overview()

    def _auto_timers_changed(self):
        for row in self.rows.values():
            row.apply_auto_timer()
        self._order = None
        self.save_config()
        self._refresh_overview()
        self.status_var.set("Classic placeholder timers enabled. Known timers are filled in automatically."
                            if self.auto_timer_var.get() else "Automatic placeholder timers off. Previous row settings restored.")

    def on_warn_secs_typed(self, row):
        if self._updating_auto_warn:
            return
        ws = row.warn_secs_var.get().strip()
        bad = bool(ws) and parse_positive(ws) is None
        row.warn_secs_ent.config(bg=self.palette["error_bg"] if bad else self.palette["surface"])
        if bad:
            self.status_var.set(f"{row.label}: Early warning needs a positive number of seconds.")
        else:
            self.status_var.set(f"Warning settings updated for {row.label.split(' [0x', 1)[0]}.")
        row.refresh_timer()
        self.save_config()

    def _auto_warnings_changed(self):
        for row in self.rows.values():
            row.apply_auto_warning()
        self.save_config()
        self.status_var.set("20-second placeholder warnings enabled. Warn and Early are managed automatically."
                            if self.auto_warn_var.get() else "Automatic warnings off. Previous row warning settings restored.")

    def _general_changed(self):
        if getattr(self, "_ui_ready", False):
            valid = parse_minutes(self.general_var.get()) is not None
            self.general_entry.configure(bg=self.palette["surface"] if valid else self.palette["error_bg"])
            self.status_var.set("Default timer updated. Timers using it are recalculated from their last defeat."
                                if valid else "Default timer needs a positive number of minutes.")
        for row in self.rows.values():
            row.refresh_timer()
        self._order = None
        self.save_config()
        self._refresh_overview()

    # -- events / ticking -----------------------------------------------

    def _drain_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                if ev[0] == "kill":
                    if self.on_kill(ev[1], ev[2], ev[3]):
                        self.status_var.set(
                            f"Kill: {ev[2]} @ {ev[3]}   |   {self._watching}"
                        )
                elif ev[0] == "history":
                    self.restore_history(ev[1])
                elif ev[0] == "watching":
                    self._watching = (
                        f"Watching: {ev[1]}" if ev[1] else "No .log file found"
                    )
                    self.status_var.set(self._watching)
                    self._update_connection(ev[1])
        except queue.Empty:
            pass
        self.root.after(200, self._drain_events)

    _watching = "Waiting for log files..."

    def _tick(self):
        now = time.time()
        order = sorted(self.rows.values(), key=lambda r: r.sort_key(now))
        for row in order:
            row.update_display(now)
        names = [r.key for r in order]
        if names != self._order:
            self._order = names
        self._refresh_overview()
        self.root.after(500, self._tick)

    # -- notification ---------------------------------------------------

    def notify(self, name):
        self.play_sound()
        if self.popup_var.get():
            self._toast(f"{name} respawn due!")
        self.status_var.set(f"RESPAWN DUE: {name}   |   {self._watching}")

    def notify_warn(self, name, secs_left):
        self.play_sound()
        if self.popup_var.get():
            self._toast(f"{name} spawning in ~{secs_left}s")
        self.status_var.set(
            f"Soon: {name} in ~{secs_left}s   |   {self._watching}"
        )

    def play_sound(self, test=False):
        mode = SOUND_MODES[self.sound_var.get()]
        self._play_sound(mode, self.sound_file_var.get(), placeholder=False)

    def play_placeholder_kill_sound(self):
        mode = SOUND_MODES[self.kill_sound_mode_var.get()]
        self._play_sound(mode, self.kill_sound_file_var.get(), placeholder=True)

    def _play_sound(self, mode, sound_file, placeholder=False):
        if mode == "none":
            return
        if winsound is None:
            self.root.bell()
            return
        try:
            if mode == "wav":
                path = sound_file.strip()
                if path:
                    winsound.PlaySound(
                        path,
                        winsound.SND_FILENAME
                        | winsound.SND_ASYNC
                        | winsound.SND_NODEFAULT,
                    )
                    return
                mode = "chime" if placeholder else "exclamation"
            if mode == "beep":
                threading.Thread(
                    target=self._beep, args=(placeholder,), daemon=True,
                ).start()
            elif mode == "chime":
                threading.Thread(target=self._beep, args=(True,), daemon=True).start()
            elif mode in ("exclamation", "asterisk"):
                winsound.PlaySound(
                    "SystemAsterisk" if mode == "asterisk" else "SystemExclamation",
                    winsound.SND_ALIAS | winsound.SND_ASYNC,
                )
        except Exception:
            self.root.bell()

    @staticmethod
    def _beep(placeholder=False):
        try:
            if placeholder:
                winsound.Beep(1320, 120)
                return
            for _ in range(3):
                winsound.Beep(880, 180)
                time.sleep(0.08)
        except Exception:
            pass

    def _toast(self, msg):
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        p = self.palette
        t.configure(bg=p["border"])
        body = tk.Frame(t, bg=p["surface"], padx=18, pady=14)
        body.pack(padx=1, pady=1)
        tk.Label(body, text="Respawn alert", bg=p["surface"], fg=p["text"],
                 font=(self.ui_font, 10, "bold"), anchor="w").pack(side="top", anchor="w")
        tk.Label(
            body,
            text=msg,
            fg=p["text"], bg=p["surface"], font=(self.ui_font, 11),
            wraplength=420, justify="left", anchor="w",
        ).pack(pady=(6, 0))
        t.bind("<Button-1>", lambda e: self._close_toast(t))
        t.update_idletasks()
        idx = len(self._toasts)
        x = t.winfo_screenwidth() - t.winfo_width() - 24
        y = t.winfo_screenheight() - t.winfo_height() - 60 - idx * 56
        t.geometry(f"+{x}+{y}")
        self._toasts.append(t)
        t.after(6000, lambda: self._close_toast(t))

    def _close_toast(self, t):
        if t in self._toasts:
            self._toasts.remove(t)
        t.destroy()

    # -- folder / wav browsing ------------------------------------------

    def _mobid_changed(self):
        self.use_mobid = bool(self.mobid_var.get())
        self.save_config()
        self.status_var.set("Tracking individual mob IDs." if self.use_mobid else "Tracking mobs by name. Placeholder features require mobid log messages.")

    def _autosave(self):
        """Periodic save so an ungraceful exit can't lose state."""
        self.save_config()
        self.root.after(15000, self._autosave)

    def _apply_dir(self):
        new = self.dir_var.get().strip()
        if new and new != self.chatlog_dir:
            self.chatlog_dir = new
            self.save_config()
            self.status_var.set(f"Log folder updated: {new}")

    def _browse_dir(self):
        d = filedialog.askdirectory(
            initialdir=self.chatlog_dir or APP_DIR,
            title="Select FFXI chatlogs folder",
        )
        if d:
            self.dir_var.set(d)
            self._apply_dir()

    def _browse_wav(self):
        f = filedialog.askopenfilename(
            title="Select notification sound",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if f:
            self.sound_file_var.set(f)
            self.sound_var.set("Custom .wav file")
            self.save_config()

    def _browse_kill_wav(self):
        path = filedialog.askopenfilename(
            title="Select NM placeholder killed sound",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")],
        )
        if path:
            self.kill_sound_file_var.set(path)
            self.kill_sound_mode_var.set("Custom .wav file")
            self.save_config()

    def _sound_changed(self, save=True):
        self.wav_btn.config(
            state="normal"
            if SOUND_MODES[self.sound_var.get()] == "wav"
            else "disabled"
        )
        if save:
            self.save_config()

    def _on_close(self):
        self.save_config()
        self.watcher.stop()
        self.root.destroy()


def main():
    if tk is None:
        sys.exit("tkinter is not installed; install python3-tk or use Windows Python.")
    # single-instance guard: a second copy would fight over the config file
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        lock.bind(("127.0.0.1", 49215))
        lock.listen(1)
    except OSError:
        r = tk.Tk()
        r.withdraw()
        messagebox.showwarning(
            "FFXI Respawn Timer", "Already running - check your taskbar/windows."
        )
        r.destroy()
        sys.exit(1)
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
