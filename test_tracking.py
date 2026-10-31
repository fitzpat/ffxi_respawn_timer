"""Persistent untracking, alert suppression, recovery, and restoration."""
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import ffxi_mob_timer as timer
from test_placeholders import Var, Widget, fake_root, fake_ttk, make_row


class TestTracking(unittest.TestCase):
    def app_with_row(self):
        row, app = make_row()
        row.frame = Mock()
        app.rows = {row.key: row}
        app.root = fake_root()
        app.root.focus_get.return_value = None
        app.search_entry = Mock()
        app.status_var = Var('Ready')
        app.filter_var = Var('Timers')
        app.save_config = Mock()
        app.play_placeholder_kill_sound = Mock()
        return row, app

    def test_untracked_mutes_due_and_early_alerts(self):
        row, app = self.app_with_row()
        row.warn_var.set(True)
        row.warn_secs_var.set('20')
        row.record_kill(1000)
        row.tracked = False
        self.assertFalse(row.update_display(1280))
        self.assertFalse(row.update_display(1301))
        app.notify_warn.assert_not_called()
        app.notify.assert_not_called()
        row.count_lbl.config.assert_called_with(text='Paused', fg=app.palette['muted'])

    def test_untracked_ignores_new_kills_and_history(self):
        row, app = self.app_with_row()
        row.record_kill(1000)
        row.tracked = False
        app._get_or_create_row = Mock(return_value=row)
        app.kill_sound_var = Var(True)
        self.assertFalse(app.on_kill(row.key, row.label, '12:00:00'))
        app.restore_history([(row.key, row.label, 2000)])
        self.assertFalse(row.tracked)
        self.assertEqual(row.killed_at, 1000)
        app.play_placeholder_kill_sound.assert_not_called()
        app.save_config.assert_not_called()

    def test_restore_preserves_settings_without_replaying_due_alert(self):
        row, app = self.app_with_row()
        row.override_var.set('8')
        row.warn_var.set(True)
        row.warn_secs_var.set('45')
        row.record_kill(1000)
        with patch.object(timer.time, 'time', return_value=1100):
            app.set_row_tracked(row.key, False)
        self.assertFalse(row.tracked)
        with patch.object(timer.time, 'time', return_value=2000):
            app.set_row_tracked(row.key, True)
        self.assertTrue(row.tracked)
        self.assertEqual(row.killed_at, 1000)
        self.assertEqual(row.override_var.get(), '8')
        self.assertEqual(row.warn_secs_var.get(), '45')
        self.assertTrue(row.warn_var.get())
        app.notify.assert_not_called()
        app.notify_warn.assert_not_called()
        self.assertEqual(app.save_config.call_count, 2)

    def test_clear_active_preserves_untracked_and_reverse(self):
        for selection, remaining_tracked in (('Timers', False), ('Untracked', True)):
            with self.subTest(selection=selection):
                row, app = self.app_with_row()
                other, _ = make_row(key='17225867')
                other.tracked = False
                other.destroy = Mock()
                row.destroy = Mock()
                app.rows[other.key] = other
                app.filter_var.set(selection)
                with patch.object(timer, 'messagebox', SimpleNamespace(askyesno=Mock(return_value=True))):
                    app._clear_all()
                self.assertEqual(len(app.rows), 1)
                self.assertEqual(next(iter(app.rows.values())).tracked, remaining_tracked)

    def test_saved_exclusion_survives_restart_and_full_ids_do_not_collide(self):
        fake_tk = SimpleNamespace(**{name: Widget for name in (
            'Frame', 'Label', 'Entry', 'Button', 'Checkbutton', 'Canvas'
        )}, StringVar=Var, BooleanVar=Var)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'config.json'
            # Legacy rows with no tracking flag remain tracked.
            path.write_text(json.dumps({'mobs': {'17215867': {
                'label': 'Rock Lizard', 'killed_at': 1000, 'override': '8'
            }}}))
            with patch.object(timer, 'tk', fake_tk), patch.object(timer, 'ttk', fake_ttk()), \
                 patch.object(timer, 'CONFIG_PATH', str(path)), patch.object(timer, 'LogWatcher'):
                app = timer.App(fake_root())
                self.assertTrue(app.rows['17215867'].tracked)
                app.set_row_tracked('17215867', False)
                self.assertFalse(json.loads(path.read_text())['mobs']['17215867']['tracked'])
                restarted = timer.App(fake_root())
                row = restarted.rows['17215867']
                self.assertFalse(row.tracked)
                self.assertFalse(restarted.on_kill(row.key, row.label, '12:00:00'))
                self.assertEqual(row.killed_at, 1000)
                self.assertTrue(restarted.on_kill('17225867', 'Other Lizard', '12:00:00'))
                self.assertTrue(restarted.rows['17225867'].tracked)
                self.assertFalse(row.tracked)
                restarted.set_row_tracked(row.key, True)
                self.assertTrue(json.loads(path.read_text())['mobs'][row.key]['tracked'])
                self.assertEqual(row.override_var.get(), '8')
                restarted.remove_row(row.key)
                restarted.on_kill(row.key, row.label, '12:00:01')
                self.assertTrue(restarted.rows[row.key].tracked)


if __name__ == '__main__':
    unittest.main()
