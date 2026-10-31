"""Placeholder behavior tests; no display, network, or live game needed."""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import ffxi_mob_timer as timer


class Var:
    def __init__(self, value=None, **kwargs):
        self.value = value
        self.callbacks = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.callbacks:
            callback("", "", "write")

    def trace_add(self, kind, callback):
        self.callbacks.append(callback)


class Widget:
    """Minimal Tk boundary for testing real application startup and persistence."""
    def __init__(self, *args, **kwargs):
        self.options = kwargs

    def config(self, *args, **kwargs):
        self.options.update(kwargs)

    configure = config

    def get_children(self):
        return ()

    def selection(self):
        return ()

    def __getattr__(self, name):
        return Mock()


def fake_ttk():
    return SimpleNamespace(**{name: Widget for name in (
        "Style", "Button", "Combobox", "Scrollbar", "Notebook", "Treeview", "Radiobutton"
    )})


def fake_root():
    root = Mock()
    root.winfo_height.return_value = 780
    return root


def make_row(key="17215867", tags=None, auto_warn=True, auto_timer=False):
    app = timer.App.__new__(timer.App)
    app.palette = timer.PALETTES["Light"]
    app.ui_font = "Helvetica"
    app.mob_tags = tags if tags is not None else {
        key: {"placeholder_for": ["Leaping Lizzy"], "respawn_seconds": 300, "despawn_seconds": 30}
    }
    app.auto_warn_var = Var(auto_warn)
    app.auto_timer_var = Var(auto_timer)
    app.general_var = Var("5")
    app._updating_auto_timer = False
    app._updating_auto_warn = False
    app.notify_warn = Mock()
    app.notify = Mock()
    row = timer.MobRow.__new__(timer.MobRow)
    row.app, row.key = app, key
    row.tracked = True
    row.label = timer.format_mob_label(key, "Rock Lizard")
    row.use_var, row.override_var = Var(True), Var("")
    row.warn_var, row.warn_secs_var = Var(False), Var("")
    row.auto_timer_backup = None
    row.auto_warn_backup = None
    row.name_lbl, row.killed_lbl, row.count_lbl = Mock(), Mock(), Mock()
    row.tag_lbl, row.identity_lbl = Mock(), Mock()
    row.override_ent, row.use_chk = Mock(), Mock()
    row.warn_chk, row.warn_secs_ent = Mock(), Mock()
    row.killed_at, row.end_at = 0, None
    row.fired = row.warned = row.auto_warned = False
    row.refresh_tags()
    return row, app


class TestDatabase(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "tags.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return timer.load_mob_tags(path)

    def test_full_ids_and_custom_tags(self):
        result = self.load({"version": 1, "mobs": {
            "17215867": {"placeholder_for": [" Leaping Lizzy ", "Leaping Lizzy"], "tags": ["Camp A"]},
            "17225867": {"tags": ["same suffix, different mob"]},
        }})
        self.assertEqual(result["17215867"]["placeholder_for"], ["Leaping Lizzy"])
        self.assertEqual(result["17225867"]["placeholder_for"], [])

    def test_bad_data_is_rejected(self):
        for data in ([], {}, {"version": 2, "mobs": {}}, {"version": 1, "mobs": []},
                     {"version": 1, "mobs": {"0x17B": {}}},
                     {"version": 1, "mobs": {"17215867": {"placeholder_for": "Lizzy"}}},
                     {"version": 1, "mobs": {"17215867": {"tags": [None]}}},
                     {"version": 1, "mobs": {"17215867": {"respawn_seconds": "nan"}}},
                     {"version": 1, "mobs": {"17215867": {"respawn_seconds": -1}}},
                     {"version": 1, "mobs": {"17215867": {"despawn_seconds": -1}}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.load(data)

    def test_packaged_database_contains_horizon_corrections(self):
        data = timer.load_mob_tags()
        self.assertGreater(len(data), 400)
        for mid in ("17215867", "17215887"):
            self.assertEqual(data[mid]["placeholder_for"], ["Leaping Lizzy"])
        self.assertEqual(data["17199434"]["placeholder_for"], ["Valkurm Emperor"])
        self.assertEqual(data["17645754"]["placeholder_for"], ["Ungur"])
        self.assertNotIn("17645784", data)  # retail-only Ungur PH excluded
        self.assertEqual(data["17379447"]["respawn_seconds"], 600)  # classic Ge'Dha

    def test_shipped_timers_use_whole_minutes_plus_twenty_seconds(self):
        data = timer.load_mob_tags()
        for mid, entry in data.items():
            with self.subTest(mid=mid):
                self.assertEqual(entry["despawn_seconds"], 20)
                if entry.get("respawn_seconds") is not None:
                    self.assertEqual(entry["respawn_seconds"] % 60, 0)
        for mid in ("17498518", "17498520"):
            self.assertEqual(data[mid]["placeholder_for"], ["Charybdis"])
            self.assertEqual(data[mid]["respawn_seconds"] + data[mid]["despawn_seconds"], 980)

    def test_fresh_default_timer_is_sixteen_minutes_twenty_seconds(self):
        seconds = timer.parse_minutes(timer.DEFAULT_CONFIG["general_minutes"]) * 60
        self.assertAlmostEqual(seconds, 980)
        self.assertEqual(timer.fmt_countdown(seconds), "16:20")

    def test_seed_bundle_without_overwriting_edits(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            bundle = root / "bundle"
            bundle.mkdir()
            (bundle / "mob_tags.json").write_text('{"version": 1, "mobs": {}}')
            external = root / "mob_tags.json"
            with patch.object(timer.sys, "_MEIPASS", str(bundle), create=True):
                timer.ensure_mob_tags(external)
                self.assertIn('"version": 1', external.read_text())
                external.write_text("manual edits")
                timer.ensure_mob_tags(external)
                self.assertEqual(external.read_text(), "manual edits")

    def test_bad_reload_keeps_previous_database(self):
        row, app = make_row()
        old = copy.deepcopy(app.mob_tags)
        app.rows = {row.key: row}
        app.status_var, app.tags_status_var = Var(), Var()
        with patch.object(timer, "ensure_mob_tags"), patch.object(timer, "load_mob_tags", side_effect=ValueError("bad JSON")):
            self.assertFalse(app.reload_tags())
        self.assertEqual(app.mob_tags, old)
        self.assertIn("previous tags kept", app.status_var.get())


class TestLabels(unittest.TestCase):
    def test_decimal_suffix_is_zero_padded_and_hex_preserved(self):
        self.assertEqual(timer.format_mob_label("16798052", "Buffalo"), "Buffalo [0x01005164 (8052)]")
        self.assertTrue(timer.format_mob_label("17000003", "Mob").endswith("(0003)]"))

    def test_old_saved_labels_migrate_idempotently(self):
        label = timer.format_mob_label("16798052", "Buffalo [0x01005164]")
        self.assertEqual(timer.format_mob_label("16798052", label), label)
        self.assertEqual(timer.format_mob_label("Buffalo", "Buffalo"), "Buffalo")

    def test_tags_are_only_for_exact_id(self):
        row, app = make_row()
        self.assertIn("PH for: Leaping Lizzy", row.display_label)
        self.assertFalse(app.is_placeholder("5867"))
        self.assertFalse(app.is_placeholder("17225867"))
        self.assertFalse(app.is_placeholder("Rock Lizard"))


class TestWarnings(unittest.TestCase):
    def test_auto_warning_at_20_seconds_once_and_due_once(self):
        row, app = make_row()
        row.record_kill(1000)
        row.update_display(1279)
        app.notify_warn.assert_not_called()
        row.update_display(1280)
        row.update_display(1281)
        app.notify_warn.assert_called_once_with(row.display_label, 20)
        row.update_display(1300)
        row.update_display(1301)
        app.notify.assert_called_once_with(row.display_label)

    def test_manual_warning_kept_separate(self):
        row, app = make_row()
        row.warn_var.set(True)
        row.warn_secs_var.set("60")
        row.record_kill(1000)
        row.update_display(1240)
        row.update_display(1280)
        self.assertEqual(app.notify_warn.call_count, 2)

    def test_simultaneous_manual_and_auto_warning_do_not_duplicate(self):
        row, app = make_row()
        row.warn_var.set(True)
        row.warn_secs_var.set("20")
        row.record_kill(1000)
        row.update_display(1280)
        app.notify_warn.assert_called_once()

    def test_new_kill_rearms_warning(self):
        row, app = make_row()
        for now in (1000, 2000):
            row.record_kill(now)
            row.update_display(now + 280)
        self.assertEqual(app.notify_warn.call_count, 2)

    def test_off_and_untagged_mobs_do_not_warn(self):
        for options in ({"auto_warn": False}, {"tags": {}}):
            row, app = make_row(**options)
            row.record_kill(1000)
            row.update_display(1280)
            row.update_display(1300)
            app.notify_warn.assert_not_called()
            app.notify.assert_not_called()

    def test_overdue_timer_does_not_emit_late_warning(self):
        row, app = make_row()
        row.record_kill(1000)
        row.update_display(1301)
        app.notify_warn.assert_not_called()


class TestAutoTimers(unittest.TestCase):
    def test_charybdis_correction_updates_existing_countdown_and_preserves_backup(self):
        shipped = timer.load_mob_tags()
        for mid in ("17498518", "17498520"):
            with self.subTest(mid=mid):
                previous = {**shipped[mid], "despawn_seconds": 30}
                row, app = make_row(key=mid, tags={mid: previous}, auto_timer=True)
                row.override_var.set("12")
                with patch.object(timer.time, "time", return_value=1000):
                    row.record_kill(1000)
                    row.apply_auto_timer()
                    self.assertAlmostEqual(row.end_at, 1990)
                    app.mob_tags[mid] = shipped[mid]
                    row.apply_auto_timer()
                    self.assertAlmostEqual(row.end_at, 1980)
                    self.assertEqual(timer.fmt_countdown(row.end_at - 1000), "16:20")
                    self.assertEqual(row.killed_at, 1000)
                    app.auto_timer_var.set(False)
                    row.apply_auto_timer()
                    self.assertEqual(row.override_var.get(), "12")

    def test_populates_override_and_restores_manual_settings(self):
        row, app = make_row(auto_timer=True)
        row.override_var.set("7")
        row.apply_auto_timer()
        self.assertEqual(row.override_var.get(), "5.5")
        self.assertFalse(row.use_var.get())
        row.override_ent.config.assert_called_with(state="disabled")
        row.apply_auto_timer()  # must not overwrite the saved manual values
        app.auto_timer_var.set(False)
        row.apply_auto_timer()
        self.assertEqual(row.override_var.get(), "7")
        self.assertTrue(row.use_var.get())
        self.assertIsNone(row.auto_timer_backup)

    def test_unknown_timer_does_not_disable_general(self):
        row, app = make_row(auto_timer=True)
        del app.mob_tags[row.key]["respawn_seconds"]
        row.apply_auto_timer()
        self.assertTrue(row.use_var.get())
        self.assertEqual(row.override_var.get(), "")

    def test_restores_backup_after_restart_or_removed_tag(self):
        row, app = make_row(auto_timer=True)
        row.auto_timer_backup = {"use_general": False, "override": "12"}
        row.apply_auto_timer()
        app.mob_tags.clear()
        row.apply_auto_timer()
        self.assertFalse(row.use_var.get())
        self.assertEqual(row.override_var.get(), "12")

    def test_changes_existing_countdown_and_uses_new_database_timer(self):
        row, app = make_row(auto_timer=True)
        with patch.object(timer.time, "time", return_value=1000):
            row.record_kill(1000)
            row.apply_auto_timer()
            self.assertEqual(row.end_at, 1330)
            app.mob_tags[row.key]["respawn_seconds"] = 960
            row.apply_auto_timer()
            self.assertEqual(row.end_at, 1990)


class TestAutoWarningControls(unittest.TestCase):
    def test_checks_fills_and_disables_placeholder_controls(self):
        row, app = make_row()
        row.apply_auto_warning()
        self.assertTrue(row.warn_var.get())
        self.assertEqual(row.warn_secs_var.get(), "20")
        row.warn_chk.config.assert_called_with(state="disabled")
        self.assertEqual(row.warn_secs_ent.config.call_args.kwargs["state"], "disabled")
        app.auto_warn_var.set(False)
        row.apply_auto_warning()
        self.assertFalse(row.warn_var.get())
        self.assertEqual(row.warn_secs_var.get(), "")
        row.warn_chk.config.assert_called_with(state="normal")
        self.assertEqual(row.warn_secs_ent.config.call_args.kwargs["state"], "normal")

    def test_restore_manual_values_on_disable_or_tag_removal(self):
        for remove_tag in (False, True):
            with self.subTest(remove_tag=remove_tag):
                row, app = make_row()
                row.warn_var.set(True)
                row.warn_secs_var.set("60")
                row.apply_auto_warning()
                row.apply_auto_warning()  # reloading tags must not replace the backup
                self.assertEqual(row.auto_warn_backup, {"warn": True, "warn_secs": "60"})
                if remove_tag:
                    app.mob_tags.clear()
                else:
                    app.auto_warn_var.set(False)
                row.apply_auto_warning()
                self.assertTrue(row.warn_var.get())
                self.assertEqual(row.warn_secs_var.get(), "60")
                self.assertIsNone(row.auto_warn_backup)

    def test_untagged_mob_keeps_editable_manual_controls(self):
        row, app = make_row(tags={})
        row.warn_secs_var.set("45")
        row.apply_auto_warning()
        self.assertFalse(row.warn_var.get())
        self.assertEqual(row.warn_secs_var.get(), "45")
        row.warn_chk.config.assert_called_with(state="normal")

    def test_managed_warning_fires_once_at_20_seconds(self):
        row, app = make_row()
        row.warn_var.set(True)
        row.warn_secs_var.set("60")
        row.apply_auto_warning()
        row.record_kill(1000)
        row.update_display(1240)
        app.notify_warn.assert_not_called()
        row.update_display(1280)
        row.update_display(1281)
        app.notify_warn.assert_called_once_with(row.display_label, 20)


class TestKillSounds(unittest.TestCase):
    def test_only_tagged_kills_trigger_separate_sound(self):
        row, app = make_row()
        app._get_or_create_row = Mock(return_value=row)
        app.save_config = Mock()
        app.kill_sound_var = Var(True)
        app.play_placeholder_kill_sound = Mock()
        app.play_sound = Mock()
        app.on_kill(row.key, row.label, "12:00:00")
        app.play_placeholder_kill_sound.assert_called_once()
        app.play_sound.assert_not_called()
        app.on_kill("Rock Lizard", "Rock Lizard", "12:00:01")
        app.on_kill("17225867", "Other Lizard", "12:00:02")
        app.play_placeholder_kill_sound.assert_called_once()
        app.kill_sound_var.set(False)
        app.on_kill(row.key, row.label, "12:00:03")
        app.play_placeholder_kill_sound.assert_called_once()

    def test_independent_sound_settings(self):
        app = timer.App.__new__(timer.App)
        app.sound_var, app.sound_file_var = Var("System exclamation"), Var("warning.wav")
        app.kill_sound_mode_var, app.kill_sound_file_var = Var("Custom .wav file"), Var("kill.wav")
        app._play_sound = Mock()
        app.play_sound()
        app._play_sound.assert_called_with("exclamation", "warning.wav", placeholder=False)
        app.play_placeholder_kill_sound()
        app._play_sound.assert_called_with("wav", "kill.wav", placeholder=True)

    def test_none_sound_is_silent_without_winsound(self):
        app = timer.App.__new__(timer.App)
        app.root = Mock()
        with patch.object(timer, "winsound", None):
            app._play_sound("none", "")
        app.root.bell.assert_not_called()

    def test_kill_beep_has_different_pattern(self):
        with patch.object(timer, "winsound") as sound, patch.object(timer.time, "sleep"):
            timer.App._beep(True)
            sound.Beep.assert_called_once_with(1320, 120)
            sound.reset_mock()
            timer.App._beep(False)
            self.assertEqual(sound.Beep.call_count, 3)
            sound.Beep.assert_called_with(880, 180)


class TestAppLifecycle(unittest.TestCase):
    def test_startup_history_creates_tagged_rows_and_applies_automatic_timers(self):
        fake_tk = SimpleNamespace(**{name: Widget for name in (
            "Frame", "Label", "Entry", "Button", "Checkbutton", "Canvas"
        )}, StringVar=Var, BooleanVar=Var)
        tags = {"17215867": {"placeholder_for": ["Leaping Lizzy"], "respawn_seconds": 300, "despawn_seconds": 30}}
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "config.json")
            with patch.object(timer, "tk", fake_tk), \
                 patch.object(timer, "ttk", fake_ttk()), \
                 patch.object(timer, "CONFIG_PATH", cfg), patch.object(timer, "LogWatcher") as watcher, \
                 patch.object(timer, "ensure_mob_tags"), patch.object(timer, "load_mob_tags", return_value=tags), \
                 patch.object(timer.time, "time", return_value=5000):
                app = timer.App(fake_root())
                self.assertEqual(watcher.call_args.kwargs["history_ids_getter"](), {"17215867"})
                app.auto_timer_var.set(True)
                app.auto_warn_var.set(True)
                app.kill_sound_var.set(True)
                app.play_placeholder_kill_sound = Mock()
                app.notify, app.notify_warn = Mock(), Mock()
                app.events.put(("history", [("17215867", "Rock Lizard", 4600)]))
                app._drain_events()
                app._tick()
                row = app.rows["17215867"]
                self.assertEqual(row.killed_at, 4600)
                self.assertEqual(row.override_var.get(), "5.5")
                self.assertFalse(row.use_var.get())
                self.assertIn("PH for: Leaping Lizzy", row.display_label)
                self.assertIn("Restored 1", app.status_var.get())
                self.assertEqual(json.loads(Path(cfg).read_text())["mobs"][row.key]["killed_at"], 4600)
                app.play_placeholder_kill_sound.assert_not_called()
                app.notify.assert_not_called()
                app.notify_warn.assert_not_called()

    def test_startup_kill_settings_save_and_restore(self):
        fake_tk = SimpleNamespace(**{name: Widget for name in (
            "Frame", "Label", "Entry", "Button", "Checkbutton", "Canvas"
        )}, StringVar=Var, BooleanVar=Var)
        tags = {"17215867": {"placeholder_for": ["Leaping Lizzy"], "respawn_seconds": 300, "despawn_seconds": 30}}
        with tempfile.TemporaryDirectory() as d:
            cfg = str(Path(d) / "config.json")
            with patch.object(timer, "tk", fake_tk), patch.object(timer, "ttk", fake_ttk()), \
                 patch.object(timer, "CONFIG_PATH", cfg), patch.object(timer, "LogWatcher"), \
                 patch.object(timer, "ensure_mob_tags"), patch.object(timer, "load_mob_tags", return_value=tags):
                app = timer.App(fake_root())
                app.on_kill("17215867", "Rock Lizard [0x0106617B]", "12:00:00")
                row = app.rows["17215867"]
                row.override_var.set("8")
                row.warn_var.set(True)
                row.warn_secs_var.set("45")
                app.auto_timer_var.set(True)
                app.auto_warn_var.set(True)
                app._auto_warnings_changed()
                app.kill_sound_var.set(True)
                app.kill_sound_mode_var.set("Custom .wav file")
                app.kill_sound_file_var.set("my-kill.wav")
                app._auto_timers_changed()
                saved = json.loads(Path(cfg).read_text())
                self.assertEqual(saved["mobs"][row.key]["override"], "5.5")
                self.assertFalse(saved["mobs"][row.key]["use_general"])
                self.assertEqual(saved["placeholder_sound_file"], "my-kill.wav")
                self.assertTrue(saved["auto_warn_placeholders"])
                self.assertEqual(saved["mobs"][row.key]["warn_secs"], "20")
                self.assertTrue(saved["mobs"][row.key]["warn"])
                restarted = timer.App(fake_root())
                restored = restarted.rows[row.key]
                self.assertEqual(restored.override_var.get(), "5.5")
                self.assertIn("PH for: Leaping Lizzy", restored.display_label)
                self.assertEqual(restored.warn_secs_var.get(), "20")
                self.assertEqual(restored.warn_chk.options["state"], "disabled")
                restarted.auto_warn_var.set(False)
                restarted._auto_warnings_changed()
                self.assertEqual(restored.warn_secs_var.get(), "45")
                self.assertTrue(restored.warn_var.get())
                self.assertEqual(restored.warn_chk.options["state"], "normal")
                restarted.auto_timer_var.set(False)
                restarted._auto_timers_changed()
                self.assertEqual(restored.override_var.get(), "8")
                self.assertTrue(restored.use_var.get())


if __name__ == "__main__":
    unittest.main()
