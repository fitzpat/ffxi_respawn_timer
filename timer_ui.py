"""Standard-library Tk interface: shared styling and task-focused views."""

import os
import sys
import time


PALETTES = {
    "Light": {
        "page": "#f3f4f7", "surface": "#ffffff", "inset": "#f8f9fb",
        "text": "#202733", "muted": "#667080", "border": "#dce1e9",
        "accent": "#0964d5", "accent_hover": "#0756ba", "on_accent": "#ffffff",
        "tag_bg": "#eaf2ff", "tag_text": "#185eaf", "success": "#237348",
        "warning": "#a44917", "error": "#b33440", "error_bg": "#ffe5e8",
    },
    "Dark": {
        "page": "#14171c", "surface": "#20242b", "inset": "#282e37",
        "text": "#f0f3f8", "muted": "#a0aab9", "border": "#3b4350",
        "accent": "#7ab5ff", "accent_hover": "#357ee2", "on_accent": "#ffffff",
        "tag_bg": "#253b58", "tag_text": "#a5ccff", "success": "#83d3a5",
        "warning": "#ffb777", "error": "#ff939e", "error_bg": "#60313a",
    },
}

# Compact columns: mob, countdown, duration, alerts, defeat time, remove.
TABLE_COLUMNS = (220, 96, 130, 130, 80, 68)
TABLE_WIDTH = sum(TABLE_COLUMNS)


def matches_timer_filter(row, selection, now):
    tracked = getattr(row, "tracked", True)
    if selection == "Untracked":
        return not tracked
    if not tracked:
        return False
    if selection == "Upcoming":
        return row.end_at is not None and row.end_at > now
    if selection == "Due now":
        return row.end_at is not None and row.end_at <= now
    if selection == "Untimed":
        return row.end_at is None
    return True


def system_appearance():
    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
                return "Light" if winreg.QueryValueEx(key, "AppsUseLightTheme")[0] else "Dark"
        except OSError:
            pass
    return "Light"


class TimerInterface:
    """UI mixin; the application supplies Tk, state, and action callbacks."""

    def _focused_widget(self):
        """Tcl-created popup children have no Python widget to return."""
        try:
            return self.root.focus_get()
        except KeyError:
            return None

    def _frame(self, parent, role="surface", **kwargs):
        if kwargs.get("highlightthickness"):
            kwargs.setdefault("highlightcolor", self.palette["border"])
        w = self._tk.Frame(parent, bg=self.palette[role], **kwargs)
        self._theme_widgets.append((w, {"bg": role}))
        if kwargs.get("highlightthickness"):
            self._theme_widgets.append((w, {"highlightcolor": "border"}))
        return w

    def _label(self, parent, text=None, *, role="surface", color="text", size=10,
               bold=False, responsive=True, **kwargs):
        w = self._tk.Label(parent, text=text, bg=self.palette[role], fg=self.palette[color],
                           font=(self.ui_font, size, "bold" if bold else "normal"),
                           anchor="w", justify="left", **kwargs)
        self._theme_widgets.append((w, {"bg": role, "fg": color}))
        if responsive and "wraplength" in kwargs:
            w.bind("<Configure>", lambda e: w.configure(wraplength=max(80, e.width)))
        return w

    def _entry(self, parent, variable, width=20):
        w = self._tk.Entry(parent, textvariable=variable, width=width, relief="flat",
                           font=(self.ui_font, 10), bg=self.palette["surface"],
                           fg=self.palette["text"], insertbackground=self.palette["text"],
                           highlightthickness=1, highlightbackground=self.palette["border"],
                           highlightcolor=self.palette["accent"],
                           disabledbackground=self.palette["inset"],
                           disabledforeground=self.palette["muted"])
        self._theme_widgets.append((w, {"bg": "surface", "fg": "text",
            "insertbackground": "text", "highlightbackground": "border",
            "highlightcolor": "accent", "disabledbackground": "inset",
            "disabledforeground": "muted"}))
        return w

    def _check(self, parent, text, variable, command, compact=False):
        w = self._tk.Checkbutton(parent, text=text, variable=variable, command=command,
                font=(self.ui_font, 9 if compact else 10), bg=self.palette["surface"], fg=self.palette["text"],
                activebackground=self.palette["surface"], activeforeground=self.palette["text"],
                selectcolor=self.palette["surface"], disabledforeground=self.palette["muted"],
                anchor="w", padx=0, pady=0 if compact else 5, takefocus=True)
        self._theme_widgets.append((w, {"bg": "surface", "fg": "text",
            "activebackground": "surface", "activeforeground": "text",
            "selectcolor": "surface", "disabledforeground": "muted"}))
        w.pack(anchor="w", fill="x")
        return w

    def _button(self, parent, text, command, primary=False, danger=False, **kwargs):
        style = "Primary.TButton" if primary else "Danger.TButton" if danger else "TButton"
        return self._ttk.Button(parent, text=text, command=command, style=style,
                                takefocus=True, **kwargs)

    def _card(self, parent, title, description=None):
        outer = self._frame(parent, highlightthickness=1,
                            highlightbackground=self.palette["border"], padx=20, pady=16)
        self._theme_widgets.append((outer, {"highlightbackground": "border"}))
        self._label(outer, title, size=12, bold=True).pack(fill="x")
        if description:
            self._label(outer, description, color="muted", wraplength=820).pack(fill="x", pady=(4, 12))
        return outer

    def _configure_styles(self):
        p, s = self.palette, self.style
        s.theme_use("clam")
        s.configure(".", font=(self.ui_font, 10), background=p["surface"], foreground=p["text"])
        s.configure("TButton", padding=(12, 7), relief="raised", borderwidth=1,
                    background=p["surface"], foreground=p["text"], bordercolor=p["border"],
                    lightcolor=p["border"], darkcolor=p["border"], focuscolor=p["accent"])
        s.map("TButton", background=[("active", p["inset"])],
              foreground=[("disabled", p["muted"])], bordercolor=[("focus", p["accent"])],
              lightcolor=[("focus", p["accent"])], darkcolor=[("focus", p["accent"])])
        s.configure("Primary.TButton", background="#0964d5", foreground=p["on_accent"], bordercolor="#0964d5")
        s.configure("Primary.TButton", lightcolor="#0964d5", darkcolor="#0964d5")
        s.map("Primary.TButton", background=[("active", "#0756ba")], foreground=[("disabled", p["muted"])])
        s.configure("Danger.TButton", foreground=p["error"])
        s.configure("Row.TButton", padding=(5, 1), font=(self.ui_font, 9))
        s.configure("Remove.Row.TButton", foreground=p["error"])
        s.configure("Filter.TRadiobutton", background=p["page"], foreground=p["muted"],
                    padding=(12, 8), relief="flat", indicatorrelief="flat")
        s.layout("Filter.TRadiobutton", [("Radiobutton.padding", {"children": [
            ("Radiobutton.focus", {"children": [("Radiobutton.label", {"sticky": "nswe"})],
                                  "sticky": "nswe"})], "sticky": "nswe"})])
        s.map("Filter.TRadiobutton", background=[("selected", p["tag_bg"]), ("active", p["inset"])],
              foreground=[("selected", p["tag_text"]), ("active", p["text"])])
        s.configure("TNotebook", background=p["page"], borderwidth=0, tabmargins=(0, 0, 0, 12))
        s.configure("TNotebook", bordercolor=p["page"], lightcolor=p["page"], darkcolor=p["page"])
        s.configure("TNotebook.Tab", background=p["page"], foreground=p["muted"],
                    padding=(20, 10), font=(self.ui_font, 10, "bold"), borderwidth=0)
        s.configure("TNotebook.Tab", bordercolor=p["page"], lightcolor=p["page"], darkcolor=p["page"])
        s.map("TNotebook.Tab", background=[("selected", p["surface"])],
              foreground=[("selected", p["accent"]), ("active", p["text"])],
              padding=[("selected", (20, 10)), ("!selected", (20, 10))],
              expand=[("selected", (0, 0, 0, 0))],
              bordercolor=[("selected", p["page"]), ("!selected", p["page"])],
              lightcolor=[("selected", p["page"]), ("!selected", p["page"])])
        s.configure("TCombobox", fieldbackground=p["surface"], background=p["inset"],
                    foreground=p["text"], arrowcolor=p["muted"], padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", p["surface"])],
              foreground=[("readonly", p["text"])])
        s.configure("Treeview", background=p["surface"], fieldbackground=p["surface"],
                    foreground=p["text"], rowheight=34, borderwidth=0)
        s.configure("Treeview.Heading", background=p["inset"], foreground=p["muted"],
                    font=(self.ui_font, 9, "bold"), padding=(10, 10), relief="flat")
        s.map("Treeview", background=[("selected", p["tag_bg"])],
              foreground=[("selected", p["tag_text"])])
        s.configure("Vertical.TScrollbar", background=p["border"], troughcolor=p["page"],
                    borderwidth=0, width=12, arrowsize=12, lightcolor=p["border"], darkcolor=p["border"])
        s.configure("Horizontal.TScrollbar", background=p["border"], troughcolor=p["page"], borderwidth=0)
        for direction, sticky in (("Vertical", "ns"), ("Horizontal", "ew")):
            s.layout(f"{direction}.TScrollbar", [(f"{direction}.Scrollbar.trough", {
                "sticky": sticky, "children": [(f"{direction}.Scrollbar.thumb", {
                    "expand": True, "sticky": "nswe"})]})])
            s.configure(f"{direction}.TScrollbar", lightcolor=p["border"], darkcolor=p["border"],
                        bordercolor=p["border"], width=12, arrowsize=12)
            s.map(f"{direction}.TScrollbar", background=[("active", p["muted"])])
        self.root.option_add("*TCombobox*Listbox.background", p["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", p["text"])

    def _build_ui(self):
        tk, ttk = self._tk, self._ttk
        self._ui_ready = False
        self._theme_widgets = []
        self.ui_font = "Segoe UI" if sys.platform == "win32" else "Helvetica"
        mode = self.cfg.get("appearance", "System")
        if mode not in ("System", "Light", "Dark"):
            mode = "System"
        self.appearance_var = tk.StringVar(value=mode)
        self.palette = PALETTES[system_appearance() if mode == "System" else mode if mode in PALETTES else "Light"]
        self.style = ttk.Style(self.root)
        self._configure_styles()
        self.root.configure(bg=self.palette["page"])
        self.root.geometry("1080x780")
        self.root.minsize(800, 640)

        # Create shared variables once; changing views never discards form state.
        self.dir_var = tk.StringVar(value=self.chatlog_dir)
        self.general_var = tk.StringVar(value=str(self.cfg["general_minutes"]))
        self.popup_var = tk.BooleanVar(value=bool(self.cfg["toast_popup"]))
        self.mobid_var = tk.BooleanVar(value=self.use_mobid)
        self.auto_warn_var = tk.BooleanVar(value=bool(self.cfg["auto_warn_placeholders"]))
        self.auto_timer_var = tk.BooleanVar(value=bool(self.cfg["auto_placeholder_timers"]))
        self.kill_sound_var = tk.BooleanVar(value=bool(self.cfg["placeholder_kill_sound"]))
        sound_modes = self.sound_modes
        inverse = {v: k for k, v in sound_modes.items()}
        self.sound_var = tk.StringVar(value=inverse.get(self.cfg["sound_mode"], "System exclamation"))
        self.sound_file_var = tk.StringVar(value=self.cfg["sound_file"])
        self.kill_sound_mode_var = tk.StringVar(value=inverse.get(self.cfg["placeholder_sound_mode"], "Beep"))
        self.kill_sound_file_var = tk.StringVar(value=self.cfg["placeholder_sound_file"])
        self.status_var = tk.StringVar(value="Checking the last hour of logs for NM placeholders…")
        self.tags_status_var = tk.StringVar(value="Loading placeholder library…")
        self.connection_var = tk.StringVar(value="Connecting to game logs…")
        self.search_var = tk.StringVar(value="")
        self.filter_var = tk.StringVar(value="Timers")
        self.results_var = tk.StringVar(value="No mobs tracked yet")
        self.tag_search_var = tk.StringVar(value="")
        self.tag_details_var = tk.StringVar(value="Select a placeholder to see its timer and source notes.")
        self._history_finished = False

        header = self._frame(self.root, "page")
        header.pack(fill="x", padx=26, pady=(14, 10))
        heading = self._frame(header, "page")
        heading.pack(side="left", fill="x", expand=True)
        self.page_title = self._label(heading, "Respawn timers", role="page", size=20, bold=True)
        self.page_title.pack(anchor="w")
        self.page_description = self._label(heading, "Track and adjust every timer in one place.", role="page", color="muted")
        self.page_description.pack(anchor="w", pady=(5, 0))
        connection = self._frame(header, "page")
        connection.pack(side="right", anchor="n", pady=5)
        self.connection_label = self._label(connection, role="page", color="muted", textvariable=self.connection_var)
        self.connection_label.pack(anchor="e")
        self._button(connection, "Log settings", self._open_log_settings).pack(anchor="e", pady=(5, 0))

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=24)
        self.timer_page = self._frame(self.notebook, "page")
        self.settings_page = self._frame(self.notebook, "page")
        self.tags_page = self._frame(self.notebook, "page")
        for page, title in ((self.timer_page, "Timers"), (self.settings_page, "Settings"), (self.tags_page, "Placeholder library")):
            self.notebook.add(page, text=title)
        self._build_timers_view()
        self._build_settings_view()
        self._build_tags_view()
        self.notebook.bind("<<NotebookTabChanged>>", self._view_changed)
        footer = self._frame(self.root, "page")
        footer.pack(side="bottom", before=self.notebook, fill="x", padx=26, pady=(10, 14))
        self._label(footer, "Activity  ", role="page", color="muted", size=9, bold=True).pack(side="left")
        activity = self._label(footer, role="page", color="muted", size=9,
                               textvariable=self.status_var, wraplength=1000)
        activity.pack(side="left", fill="x", expand=True)
        footer.bind("<Configure>", lambda e: activity.configure(wraplength=max(300, e.width - 70)))
        self.general_var.trace_add("write", lambda *_: self._general_changed())
        self.search_var.trace_add("write", lambda *_: self._timer_filters_changed())
        self.filter_var.trace_add("write", lambda *_: self._timer_filters_changed())
        self.tag_search_var.trace_add("write", lambda *_: self._refresh_tag_table())
        self.root.bind("<Control-f>", self._focus_search)
        self.root.bind("<Control-comma>", lambda e: self._select_view(1))
        self.root.bind("<Control-Key-1>", lambda e: self._select_view(0))
        self.root.bind("<Control-Key-2>", lambda e: self._select_view(1))
        self.root.bind("<Control-Key-3>", lambda e: self._select_view(2))
        self.root.bind("<Escape>", self._clear_search)
        self.root.bind("<FocusIn>", self._reveal_focus, add="+")
        for event in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind(event, self._scroll_active_view, add="+")
        self._ui_ready = True
        self._sound_changed(save=False)
        self._refresh_overview()

    def _build_timers_view(self):
        toolbar = self.timer_toolbar = self._frame(self.timer_page, "page")
        toolbar.pack(fill="x", pady=(0, 12))
        self._label(toolbar, "Find mob", role="page", color="muted").pack(side="left", padx=(0, 8))
        self.search_entry = self._entry(toolbar, self.search_var, width=20)
        self.search_entry.pack(side="left", ipady=5)
        self.clear_btn = self._button(toolbar, "Clear all…", self._clear_all)
        self.clear_btn.pack(side="right")
        self._label(toolbar, "min", role="page", color="muted").pack(side="right", padx=(4, 14))
        self.general_entry = self._entry(toolbar, self.general_var, width=6)
        self.general_entry.pack(side="right", ipady=5)
        self._label(toolbar, "Default timer", role="page", color="muted").pack(side="right", padx=(12, 6))

        filters = self._frame(self.timer_page, "page")
        filters.pack(fill="x", pady=(0, 10))
        for label in ("Timers", "Upcoming", "Due now", "Untimed", "Untracked"):
            self._ttk.Radiobutton(filters, text=label, value=label, variable=self.filter_var,
                                 style="Filter.TRadiobutton", takefocus=True).pack(side="left", padx=(0, 4))
        self._label(filters, textvariable=self.results_var, role="page", color="muted", size=9).pack(side="right")

        table = self.timer_table = self._frame(self.timer_page, highlightthickness=1,
                            highlightbackground=self.palette["border"])
        table.pack(fill="both", expand=True)
        self._theme_widgets.append((table, {"highlightbackground": "border"}))
        self.header_canvas = self._tk.Canvas(table, height=34, bg=self.palette["inset"], highlightthickness=0)
        self._theme_widgets.append((self.header_canvas, {"bg": "inset"}))
        self.header_canvas.pack(fill="x", padx=(0, 12))
        head = self._frame(self.header_canvas, "inset")
        self._header_win = self.header_canvas.create_window((0, 0), window=head, anchor="nw")
        for col, title in enumerate(("MOB / PLACEHOLDER", "RESPAWN IN", "TIMER · MINUTES", "ALERT · SECONDS", "DEFEATED", "")):
            self._label(head, title, role="inset", color="muted", size=9, bold=True).grid(row=0, column=col, sticky="w", padx=6, pady=8)
            head.grid_columnconfigure(col, minsize=TABLE_COLUMNS[col], weight=1 if col == 0 else 0)
        body = self._frame(table)
        body.pack(fill="both", expand=True)
        self.canvas = self._tk.Canvas(body, bg=self.palette["surface"], highlightthickness=0)
        self._theme_widgets.append((self.canvas, {"bg": "surface"}))
        sb = self._ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows_inner = self._frame(self.canvas)
        self.rows_inner.grid_columnconfigure(0, weight=1)
        self._canvas_win = self.canvas.create_window((0, 0), window=self.rows_inner, anchor="nw")
        self.rows_inner.bind("<Configure>", self._sync_timer_scroll)
        self.canvas.bind("<Configure>", self._resize_timer_table)
        horizontal = self._ttk.Scrollbar(table, orient="horizontal", command=self._scroll_timer_x)
        horizontal.pack(side="bottom", before=body, fill="x")
        self.canvas.configure(xscrollcommand=horizontal.set)
        self.empty_frame = self._frame(self.rows_inner, padx=32, pady=38)
        self.empty_title = self._label(self.empty_frame, "Recovering recent placeholders…", size=16, bold=True)
        self.empty_title.pack(anchor="center")
        self.empty_note = self._label(self.empty_frame, "Checking the last hour of game logs. New kills will appear here automatically.",
                                      color="muted", wraplength=600, responsive=False)
        self.empty_note.pack(anchor="center", pady=(10, 18))
        self.empty_action = self._button(self.empty_frame, "Choose log folder", self._browse_dir, primary=True)
        self.empty_action.pack(anchor="center")
        self.timer_hint = self._label(self.timer_page,
                    "Custom minutes override Default. Alert notifies when due; Early adds a warning. Auto controls are managed in Settings.",
                    role="page", color="muted", size=9, wraplength=1000)
        self.timer_hint.pack(side="bottom", before=table, fill="x", pady=(10, 0))

    def _build_settings_view(self):
        shortcuts = self._frame(self.settings_page, "page")
        shortcuts.pack(fill="x", pady=(2, 12))
        self._label(shortcuts, "Jump to", role="page", color="muted", size=9).pack(side="left", padx=(0, 12))
        self.settings_sections = {}
        for name in ("Game logs", "Automation", "Sounds", "Appearance"):
            self._button(shortcuts, name, lambda title=name: self._jump_to_setting(title)).pack(side="left", padx=(0, 6))
        self.settings_canvas = self._tk.Canvas(self.settings_page, highlightthickness=0, bg=self.palette["page"])
        self._theme_widgets.append((self.settings_canvas, {"bg": "page"}))
        scroll = self._ttk.Scrollbar(self.settings_page, orient="vertical", command=self.settings_canvas.yview)
        scroll.pack(side="right", fill="y")
        self.settings_canvas.pack(side="left", fill="both", expand=True)
        self.settings_canvas.configure(yscrollcommand=scroll.set)
        form = self._frame(self.settings_canvas, "page")
        window = self.settings_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda e: self.settings_canvas.itemconfigure(window, width=e.width))

        logs = self._card(form, "Game logs", "Choose your chatlogs folder. The app follows new logs and recovers recent NM placeholders on launch.")
        self.settings_sections["Game logs"] = logs
        logs.pack(fill="x", pady=(2, 12), padx=(0, 6))
        folder = self._frame(logs)
        folder.pack(fill="x", pady=(0, 8))
        path = self.dir_entry = self._entry(folder, self.dir_var)
        path.pack(side="left", fill="x", expand=True, ipady=6)
        path.bind("<FocusOut>", lambda e: self._apply_dir())
        path.bind("<Return>", lambda e: self._apply_dir())
        self._button(folder, "Choose folder…", self._browse_dir, primary=True).pack(side="left", padx=(10, 0))
        self._check(logs, "Track individual spawn IDs with the mobid addon", self.mobid_var, self._mobid_changed)
        self._label(logs, "Individual IDs identify placeholders and keep different spawns of the same mob separate.", color="muted", wraplength=820).pack(fill="x", pady=(2, 0))

        automation = self._card(form, "Placeholder automation", "Let recognized NM placeholders manage their own warning and timer settings.")
        self.settings_sections["Automation"] = automation
        automation.pack(fill="x", pady=(0, 12), padx=(0, 6))
        self._check(automation, "Warn 20 seconds before NM placeholders respawn", self.auto_warn_var, self._auto_warnings_changed)
        self._check(automation, "Use classic level-75 placeholder timers automatically", self.auto_timer_var, self._auto_timers_changed)
        self._label(automation, "Managed row controls are filled in and greyed out. Switching automation off restores your previous values.", color="muted", wraplength=820).pack(fill="x", pady=(6, 0))
        self._button(automation, "Review placeholder library", lambda: self._select_view(2)).pack(anchor="w", pady=(12, 0))

        sounds = self._card(form, "Respawn alerts", "Choose the sound and on-screen notification for early warnings and timers becoming due.")
        self.settings_sections["Sounds"] = sounds
        sounds.pack(fill="x", pady=(0, 12), padx=(0, 6))
        bar = self._frame(sounds)
        bar.pack(fill="x")
        combo = self._ttk.Combobox(bar, textvariable=self.sound_var, values=list(self.sound_modes), state="readonly", width=23)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._sound_changed())
        self.wav_btn = self._button(bar, "Choose WAV…", self._browse_wav)
        self.wav_btn.pack(side="left", padx=8)
        self.test_btn = self._button(bar, "Test sound", lambda: self.play_sound(test=True))
        self.test_btn.pack(side="left")
        self._label(sounds, textvariable=self.sound_file_var, color="muted", size=9, wraplength=820).pack(fill="x", pady=(6, 2))
        self._check(sounds, "Show on-screen notifications", self.popup_var, self.save_config)
        self._label(sounds, "Check Alert in a mob’s row, or turn on automatic placeholder warnings above.",
                    color="muted", size=9, wraplength=820).pack(fill="x", pady=(4, 0))

        kills = self._card(form, "Placeholder defeat sound", "A separate cue confirms that a tagged placeholder was defeated. It does not change your respawn alerts.")
        kills.pack(fill="x", pady=(0, 12), padx=(0, 6))
        self._check(kills, "Play a sound when an NM placeholder is defeated", self.kill_sound_var, self.save_config)
        bar = self._frame(kills)
        bar.pack(fill="x", pady=(6, 0))
        combo = self._ttk.Combobox(bar, textvariable=self.kill_sound_mode_var, values=list(self.sound_modes), state="readonly", width=23)
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self.save_config())
        self._button(bar, "Choose WAV…", self._browse_kill_wav).pack(side="left", padx=8)
        self._button(bar, "Test sound", self.play_placeholder_kill_sound).pack(side="left")
        self._label(kills, textvariable=self.kill_sound_file_var, color="muted", size=9, wraplength=820).pack(fill="x", pady=(6, 0))

        appearance = self._card(form, "Appearance")
        self.settings_sections["Appearance"] = appearance
        appearance.pack(fill="x", pady=(0, 12), padx=(0, 6))
        mode = self._ttk.Combobox(appearance, textvariable=self.appearance_var, values=["System", "Light", "Dark"], state="readonly", width=18)
        mode.pack(anchor="w", pady=(12, 0))
        mode.bind("<<ComboboxSelected>>", lambda e: self._appearance_changed())

    def _jump_to_setting(self, name):
        self.root.update_idletasks()
        card = self.settings_sections[name]
        height = max(1, card.master.winfo_height())
        self.settings_canvas.yview_moveto(card.winfo_y() / height)
        # Keep keyboard users in the section they navigated to.
        def focus_control(parent):
            for child in parent.winfo_children():
                if child.winfo_class() in ("Entry", "Checkbutton", "TCombobox", "TButton"):
                    child.focus_set()
                    return True
                if focus_control(child):
                    return True
            return False
        focus_control(card)

    def _build_tags_view(self):
        bar = self._frame(self.tags_page, "page")
        bar.pack(fill="x", pady=(2, 14))
        titles = self._frame(bar, "page")
        titles.pack(side="left", expand=True, fill="x")
        self._label(titles, textvariable=self.tags_status_var, role="page", color="muted").pack(anchor="w", pady=(5, 0))
        self._button(bar, "Edit database…", self._edit_tags).pack(side="right")
        self._button(bar, "Reload", self.reload_tags).pack(side="right", padx=8)
        search = self._frame(self.tags_page, "page")
        search.pack(fill="x", pady=(0, 12))
        self._label(search, "Find a mob, NM, zone or full ID", role="page", color="muted").pack(side="left", padx=(0, 10))
        self.tag_search_entry = self._entry(search, self.tag_search_var, width=30)
        self.tag_search_entry.pack(side="left", fill="x", expand=True, ipady=6)
        self._label(self.tags_page, "Edits open in your text editor and reload automatically when saved. Times below include the corpse delay.",
                    role="page", color="muted", wraplength=1000).pack(fill="x", pady=(0, 12))
        box = self._frame(self.tags_page)
        box.pack(fill="both", expand=True)
        columns = ("mob", "nm", "timer", "id", "zone")
        self.tag_tree = self._ttk.Treeview(box, columns=columns, show="headings", selectmode="browse")
        for col, title, width, minimum in zip(columns, ("Mob", "Placeholder for", "Timer from kill", "Full mob ID", "Zone"),
                                             (170, 240, 140, 110, 190), (140, 190, 130, 110, 150)):
            self.tag_tree.heading(col, text=title)
            self.tag_tree.column(col, width=width, minwidth=minimum, anchor="w")
        vertical = self._ttk.Scrollbar(box, orient="vertical", command=self.tag_tree.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = self._ttk.Scrollbar(box, orient="horizontal", command=self.tag_tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.tag_tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tag_tree.grid(row=0, column=0, sticky="nsew")
        box.grid_columnconfigure(0, weight=1)
        box.grid_rowconfigure(0, weight=1)
        self.tag_tree.bind("<<TreeviewSelect>>", self._show_tag_details)
        details = self._card(self.tags_page, "Timing & source notes")
        details.pack(side="bottom", before=box, fill="x", pady=(12, 0))
        self._label(details, textvariable=self.tag_details_var, color="muted", size=9, wraplength=980).pack(fill="x", pady=(8, 0))

    def _select_view(self, index):
        self.notebook.select(index)
        (self.search_entry, self.dir_entry, self.tag_search_entry)[index].focus_set()
        return "break"

    def _view_changed(self, event=None):
        index = self.notebook.index(self.notebook.select())
        title, description = (
            ("Respawn timers", "Track and adjust every timer in one place."),
            ("Settings", "Connect your game and make each alert your own."),
            ("Placeholder library", "Find the mobs, timing and sources behind your timers."),
        )[index]
        self.page_title.configure(text=title)
        self.page_description.configure(text=description)

    def _open_log_settings(self):
        self._select_view(1)
        self.settings_canvas.yview_moveto(0)

    def _focus_search(self, event=None):
        index = self.notebook.index(self.notebook.select())
        if index == 1:
            self._select_view(0)
        field = self.tag_search_entry if index == 2 else self.search_entry
        field.focus_set()
        field.selection_range(0, "end")
        return "break"

    def _clear_search(self, event=None):
        index = self.notebook.index(self.notebook.select())
        if index == 2:
            self.tag_search_var.set("")
        elif index == 0:
            self.search_var.set("")
            self.filter_var.set("Timers")
        return "break"

    def _scroll_active_view(self, event):
        if not hasattr(event.widget, "winfo_class") or event.widget.winfo_class() in ("Entry", "TCombobox", "Listbox", "Treeview"):
            return
        index = self.notebook.index(self.notebook.select())
        if index not in (0, 1):
            return
        delta = getattr(event, "delta", 0)
        units = -1 if getattr(event, "num", 0) == 4 or delta > 0 else 1
        canvas = self.canvas if index == 0 else self.settings_canvas
        canvas.yview_scroll(units * max(1, int(abs(delta) / 120)), "units")
        return "break"

    def _reveal_focus(self, event):
        """Tab navigation must reveal controls inside either scrollable form."""
        if not getattr(self, "_ui_ready", False):
            return
        widget = event.widget
        if not hasattr(widget, "winfo_rooty"):
            return  # Native dropdown children arrive as Tcl path strings.
        for canvas in (self.settings_canvas, self.canvas):
            if not str(widget).startswith(str(canvas) + "."):
                continue
            self.root.update_idletasks()
            top = canvas.canvasy(0)
            y = widget.winfo_rooty() - canvas.winfo_rooty() + top
            bottom = y + widget.winfo_height()
            region = canvas.bbox("all")
            if not region:
                return
            if y < top:
                canvas.yview_moveto(max(0, y - 12) / max(1, region[3]))
            elif bottom > top + canvas.winfo_height():
                canvas.yview_moveto((bottom - canvas.winfo_height() + 12) / max(1, region[3]))
            return

    def _resize_timer_table(self, event):
        width = max(TABLE_WIDTH, event.width)
        self.canvas.itemconfigure(self._canvas_win, width=width)
        self.header_canvas.itemconfigure(self._header_win, width=width)
        self.header_canvas.configure(scrollregion=(0, 0, width, 34))

    def _scroll_timer_x(self, *args):
        self.canvas.xview(*args)
        self.header_canvas.xview(*args)

    def _sync_timer_scroll(self, event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _timer_filters_changed(self):
        self.canvas.yview_moveto(0)
        self._refresh_overview()

    def _refresh_overview(self):
        if not getattr(self, "_ui_ready", False):
            return
        now = time.time()
        selection = self.filter_var.get()
        tracked_count = sum(row.tracked for row in self.rows.values())
        untracked_count = len(self.rows) - tracked_count
        count = untracked_count if selection == "Untracked" else tracked_count
        self.clear_btn.configure(state="normal" if count else "disabled",
                                 text="Clear untracked…" if selection == "Untracked" else "Clear timers…")
        self.timer_hint.configure(text="Untracked mobs stay paused across kills and restarts. Choose Track to restore one."
                                  if selection == "Untracked" else
                                  "Custom minutes override Default. Alert notifies when due; Early adds a warning. Auto controls are managed in Settings.")
        query = self.search_var.get().casefold().strip()
        order = sorted(self.rows.values(), key=lambda r: r.sort_key(now))
        # A duration change must not move the controls out from under the user.
        focused = self._focused_widget()
        if focused and focused.winfo_class() == "Entry" and any(str(focused).startswith(str(row.frame) + ".") for row in order):
            previous = {key: i for i, key in enumerate(getattr(self, "_timer_order", []))}
            order.sort(key=lambda row: previous.get(row.key, len(previous)))
        self._timer_order = [row.key for row in order]
        visible = 0
        for row in order:
            if (query and query not in (row.key + " " + row.display_label).casefold()) or not matches_timer_filter(row, self.filter_var.get(), now):
                row.frame.grid_remove()
            else:
                row.frame.grid(row=visible, column=0, sticky="ew")
                visible += 1
        self.results_var.set(f"{visible} of {count} mobs" if query or selection not in ("Timers", "Untracked")
                             else f"{count} mob{'s' if count != 1 else ''} {'untracked' if selection == 'Untracked' else 'tracked'}")
        if visible:
            self.empty_frame.grid_remove()
        else:
            self.empty_frame.grid(row=0, column=0, sticky="ew")
            if query and count:
                title, note = "No matching mobs", "Try a mob name, full ID, last four digits or NM tag."
                action, command = "Clear search", lambda: self.search_var.set("")
            elif selection == "Untracked":
                title, note = "No untracked mobs", "Choose Untrack below a mob’s Remove button to pause it here. You can bring it back with Track."
                action, command = "View timers", self._reset_timer_filters
            elif not tracked_count and untracked_count:
                title, note = "No tracked mobs", "Your saved mobs are in Untracked. Choose Track beside a mob to bring it back."
                action, command = "View untracked", lambda: self.filter_var.set("Untracked")
            elif count:
                title = {"Due now": "No respawns due yet", "Upcoming": "No upcoming respawns", "Untimed": "Every mob has a timer"}.get(selection, "No matching mobs")
                note = "Your other timers are still being tracked. View Timers to see them."
                action, command = "View timers", self._reset_timer_filters
            elif not self._history_finished:
                title, note = "Recovering recent placeholders…", "Checking the last hour of game logs. New kills will appear here automatically."
                action, command = "Log settings", self._open_log_settings
            elif getattr(self, "_watching_filename", None):
                title, note = "Ready for your next kill", "Your game logs are connected. Defeat a mob and its timer will appear here automatically."
                action, command = "Log settings", self._open_log_settings
            elif os.path.isdir(self.chatlog_dir):
                title, note = "Waiting for your first game log", "Your folder is selected. Enable chat logging in FFXI, then defeat a mob to start its timer."
                action, command = "Review log settings", self._open_log_settings
            else:
                title, note = "Your next respawn starts here", "Choose your chatlogs folder, then defeat a mob. Its timer will appear here automatically."
                action, command = "Choose log folder", self._browse_dir
            self.empty_title.configure(text=title)
            self.empty_note.configure(text=note)
            self.empty_action.configure(text=action, command=command)
        # A shrunken result set may be outside the old viewport. Explicitly
        # update its bounds even if Tk has unmapped the canvas window.
        self.root.after_idle(self._sync_timer_scroll)

    def _reset_timer_filters(self):
        self.filter_var.set("Timers")
        self.search_var.set("")

    def _refresh_tag_table(self):
        if not getattr(self, "_ui_ready", False):
            return
        query = self.tag_search_var.get().casefold().strip()
        selected = self.tag_tree.selection()
        children = self.tag_tree.get_children()
        if children:
            self.tag_tree.delete(*children)
        visible = 0
        for mid, entry in self.mob_tags.items():
            name = entry.get("name", "Mob")
            nm = ", ".join(entry.get("placeholder_for", []))
            zone = entry.get("zone", "").replace("_", " ").title()
            tags = ", ".join(entry.get("tags", []))
            if query and query not in f"{mid} {name} {nm} {zone} {tags}".casefold():
                continue
            seconds = entry.get("respawn_seconds")
            total = self.format_countdown(float(seconds) + entry.get("despawn_seconds", 0)) if seconds else "Manual timer"
            self.tag_tree.insert("", "end", iid=mid, values=(name, nm or tags or "Custom tag", total, mid, zone))
            visible += 1
        total_count = len(self.mob_tags)
        self.tags_status_var.set(f"{visible} of {total_count} tagged spawn IDs" if query else f"{total_count} tagged spawn IDs · Classic level-75 timings")
        if selected and self.tag_tree.exists(selected[0]):
            self.tag_tree.selection_set(selected[0])
            self._show_tag_details()
        else:
            self.tag_details_var.set("No matching placeholders. Try a mob, NM, zone or full ID." if not visible else "Select a placeholder to see its timer and source notes.")

    def _show_tag_details(self, event=None):
        selected = self.tag_tree.selection()
        if not selected:
            return
        entry = self.mob_tags.get(selected[0], {})
        note = entry.get("timing_note", "Manual entry; review its timer before enabling automation.")
        source = entry.get("timer_source", "Manual entry")
        self.tag_details_var.set(f"{entry.get('name', 'Mob')} · ID {selected[0]}\n{note}\nSource: {source}")

    def _appearance_changed(self):
        mode = self.appearance_var.get()
        self.palette = PALETTES[system_appearance() if mode == "System" else mode]
        self.root.configure(bg=self.palette["page"])
        self._configure_styles()
        self._theme_widgets = [(widget, roles) for widget, roles in self._theme_widgets
                               if widget.winfo_exists()]
        for widget, roles in self._theme_widgets:
            widget.configure(**{option: self.palette[role] for option, role in roles.items()})
        for row in self.rows.values():
            row.apply_theme()
        if self.parse_timer(self.general_var.get()) is None:
            self.general_entry.configure(bg=self.palette["error_bg"])
        if hasattr(self, "_watching_filename"):
            self._update_connection(self._watching_filename)
        self.save_config()
        self.status_var.set(f"Appearance changed to {mode.lower()}.")

    def _update_connection(self, filename):
        if not getattr(self, "_ui_ready", False):
            return
        self._watching_filename = filename
        self.connection_var.set("Watching game logs" if filename else
                                "Waiting for game logs" if os.path.isdir(self.chatlog_dir) else
                                "Choose a chatlogs folder to begin")
        self.connection_label.configure(fg=self.palette["success"] if filename else self.palette["warning"])
