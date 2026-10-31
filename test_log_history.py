"""Startup history recovery and the handoff to live log watching."""

from datetime import datetime
import os
from pathlib import Path
import queue
import tempfile
import unittest
from unittest.mock import Mock, patch

import ffxi_mob_timer as timer
from test_placeholders import Var, make_row


PH = "17215867"
OTHER_PH = "17215887"


def epoch(day=31, hour=12, minute=0, second=0):
    return datetime(2026, 10, day, hour, minute, second).timestamp()


def kill(clock, key=PH, name="Rock Lizard"):
    return f"[{clock}] [mobid] Player defeats {name} | id: {key} | hex: 0x{int(key):08X} | idx: {int(key) & 4095}\n"


class TestRecentKills(unittest.TestCase):
    def test_latest_tagged_kill_across_files_within_hour(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A_2026.10.31.log").write_text(
                kill("10:59:59") + kill("11:00:00", OTHER_PH) + kill("11:40:00")
                + kill("11:41:00", "17225867") + "[11:42:00] Player defeats the Rock Lizard.\n"
                + kill("11:43:00", "11111"), encoding="utf-8")
            Path(d, "B_2026.10.31.log").write_text(kill("11:55:00"), encoding="utf-8")
            Path(d, "Old_2026.10.30.log").write_text(kill("11:59:59"), encoding="utf-8")
            Path(d, "Ignored_2026.10.31.log.swp").write_text(kill("11:59:59"), encoding="utf-8")
            found = timer.recent_placeholder_kills(d, {PH, OTHER_PH}, now=epoch())
        self.assertEqual([(i, t) for i, _, t in found], [
            (OTHER_PH, epoch(hour=11)), (PH, epoch(hour=11, minute=55))])
        self.assertIn("(5867)", found[1][1])

    def test_reads_both_days_across_midnight(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A_2026.10.30.log").write_text(kill("23:14:59") + kill("23:40:00"), encoding="utf-8")
            Path(d, "A_2026.10.31.log").write_text(kill("00:05:00", OTHER_PH), encoding="utf-8")
            found = timer.recent_placeholder_kills(d, {PH, OTHER_PH}, now=epoch(hour=0, minute=15))
        self.assertEqual([(i, t) for i, _, t in found], [
            (PH, epoch(day=30, hour=23, minute=40)), (OTHER_PH, epoch(hour=0, minute=5))])

    def test_undated_log_uses_mtime_and_midnight_context(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "session.log")
            path.write_text(kill("00:10:00", OTHER_PH) + kill("23:40:00")
                            + "[00:14:00] New day chat.\n", encoding="utf-8")
            os.utime(path, (epoch(hour=0, minute=14),) * 2)
            found = timer.recent_placeholder_kills(d, {PH, OTHER_PH}, now=epoch(hour=0, minute=15))
        # The older 00:10 line belongs to yesterday, not today's lookback window.
        self.assertEqual([(i, t) for i, _, t in found], [(PH, epoch(day=30, hour=23, minute=40))])

    def test_invalid_or_future_timestamps_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A_2026.10.31.log").write_text(
                kill("11:30:00") + kill("99:99:99") + kill("12:01:00"), encoding="utf-8")
            found = timer.recent_placeholder_kills(d, {PH}, now=epoch())
        self.assertEqual(found[0][2], epoch(hour=11, minute=30))

    def test_no_directory_or_no_tags_is_harmless(self):
        self.assertEqual(timer.recent_placeholder_kills("/nonexistent/ffxi-log-history", {PH}), [])
        self.assertEqual(timer.recent_placeholder_kills(None, set()), [])
        self.assertEqual(timer.recent_placeholder_kills(None, {PH}), [])

    def test_unreadable_log_does_not_block_other_files(self):
        real_reader = timer.reverse_log_lines
        with tempfile.TemporaryDirectory() as d:
            for name in ("Bad", "Good"):
                Path(d, f"{name}_2026.10.31.log").write_text(kill("11:40:00"), encoding="utf-8")
            def reader(path, limit):
                if Path(path).name.startswith("Bad"):
                    raise PermissionError("locked log")
                return real_reader(path, limit)
            with patch.object(timer, "reverse_log_lines", side_effect=reader):
                found = timer.recent_placeholder_kills(d, {PH}, now=epoch())
        self.assertEqual(len(found), 1)

    def test_cancelled_scan_does_not_read_files(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "A_2026.10.31.log").write_text(kill("11:59:00"), encoding="utf-8")
            with patch.object(timer, "reverse_log_lines") as reader:
                self.assertEqual(timer.recent_placeholder_kills(d, {PH}, now=epoch(), stop_requested=lambda: True), [])
                reader.assert_not_called()

    def test_reverse_reader_respects_boundaries_and_long_partial_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "test.log")
            for data, expected in (("one\ntwö\nthree\n", ["three", "twö", "one"]),
                                   ("one\ntwö\n" + "unfinished" * 20, ["twö", "one"]),
                                   ("unfinished" * 20, [])):
                with self.subTest(data=data):
                    path.write_bytes(data.encode("utf-8"))
                    self.assertEqual(list(timer.reverse_log_lines(path, path.stat().st_size, chunk_size=7)), expected)
            path.write_bytes(b"old\nnew\n")
            self.assertEqual(list(timer.reverse_log_lines(path, 4, chunk_size=2)), ["old"])


class TestHistoryHandoff(unittest.TestCase):
    def test_scan_once_then_live_append_without_replay_or_dropped_kill(self):
        real_scan = timer.recent_placeholder_kills
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "A_2026.10.31.log")
            path.write_text(kill("11:58:00"), encoding="utf-8")
            events = queue.Queue()
            watcher = timer.LogWatcher(lambda: d, events, lambda: True, history_ids_getter=lambda: {PH})
            watcher._dir = d
            def scan(*args, **kwargs):
                with path.open("a", encoding="utf-8") as f:
                    f.write(kill("12:00:00"))
                return real_scan(*args, now=epoch(), **kwargs)
            with patch.object(timer, "recent_placeholder_kills", side_effect=scan) as scanner:
                watcher._poll()
                watcher._poll()
                scanner.assert_called_once()
            got = list(events.queue)
        self.assertEqual(got[1][0], "history")
        self.assertEqual(got[1][1][0][2], epoch(hour=11, minute=58))
        live = [e for e in got if e[0] == "kill"]
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0][-1], "12:00:00")

    def test_partial_line_at_startup_completes_as_one_live_kill(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d, "A_2026.10.31.log")
            line = kill("12:00:00")
            path.write_text(line[:40], encoding="utf-8")
            events = queue.Queue()
            watcher = timer.LogWatcher(lambda: d, events, lambda: True, history_ids_getter=lambda: {PH})
            watcher._dir = d
            with patch.object(timer.time, "time", return_value=epoch()):
                watcher._poll()
                with path.open("a", encoding="utf-8") as f:
                    f.write(line[40:])
                watcher._poll()
            got = list(events.queue)
        self.assertIn(("history", []), got)
        self.assertEqual(len([e for e in got if e[0] == "kill"]), 1)


class TestHistoryRestore(unittest.TestCase):
    def app_with_row(self):
        row, app = make_row()
        app.rows = {row.key: row}
        app._get_or_create_row = Mock(return_value=row)
        app.save_config = Mock()
        app.status_var = Var()
        app.play_placeholder_kill_sound = Mock()
        return row, app

    def test_original_kill_time_is_used_without_old_alerts(self):
        for seconds_ago in (600, 290):
            with self.subTest(seconds_ago=seconds_ago):
                row, app = self.app_with_row()
                with patch.object(timer.time, "time", return_value=epoch()):
                    app.restore_history([(PH, row.label, epoch() - seconds_ago)])
                    row.update_display(epoch())
                self.assertEqual(row.killed_at, epoch() - seconds_ago)
                self.assertEqual(row.end_at, row.killed_at + 300)
                app.notify_warn.assert_not_called()
                app.notify.assert_not_called()
                app.play_placeholder_kill_sound.assert_not_called()
                app.save_config.assert_called_once()

    def test_future_warning_is_still_armed(self):
        row, app = self.app_with_row()
        with patch.object(timer.time, "time", return_value=epoch()):
            app.restore_history([(PH, row.label, epoch() - 200)])
        row.update_display(epoch() + 80)
        app.notify_warn.assert_called_once_with(row.display_label, 20)

    def test_newer_saved_kill_and_manual_settings_are_preserved(self):
        row, app = self.app_with_row()
        row.override_var.set("8")
        row.record_kill(epoch() - 30)
        with patch.object(timer.time, "time", return_value=epoch()):
            app.restore_history([(PH, row.label, epoch() - 60)])
        self.assertEqual(row.killed_at, epoch() - 30)
        self.assertEqual(row.override_var.get(), "8")
        app.save_config.assert_not_called()

    def test_history_respects_tag_removed_during_scan(self):
        row, app = self.app_with_row()
        app.mob_tags.clear()
        app.restore_history([(PH, row.label, epoch() - 60)])
        app._get_or_create_row.assert_not_called()


if __name__ == "__main__":
    unittest.main()
