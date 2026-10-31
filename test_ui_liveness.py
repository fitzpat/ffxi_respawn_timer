"""Native popup focus and callback errors must not stop recurring work."""
import queue
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import ffxi_mob_timer as timer
from runtime_diagnostics import RuntimeDiagnostics
from test_placeholders import Var


class TestCallbackLiveness(unittest.TestCase):
    def test_tcl_popup_focus_has_no_python_widget(self):
        app = timer.App.__new__(timer.App)
        app.root = Mock()
        app.root.focus_get.side_effect = KeyError('popdown')
        self.assertIsNone(app._focused_widget())

    def test_native_popup_focus_event_is_ignored_by_scrolling(self):
        app = timer.App.__new__(timer.App)
        app._ui_ready = True
        app.root = Mock()
        app._reveal_focus(SimpleNamespace(widget='.!combobox.popdown.f.l'))
        app._scroll_active_view(SimpleNamespace(widget='.!combobox.popdown.f.l'))
        app.root.update_idletasks.assert_not_called()

    def test_tick_is_rescheduled_after_a_callback_error(self):
        app = timer.App.__new__(timer.App)
        app.root = Mock()
        row = Mock()
        row.key = '123'
        row.sort_key.return_value = (0, 0, 'mob')
        row.update_display.side_effect = [RuntimeError('one failed tick'), None]
        app.rows, app._order = {row.key: row}, []
        app._refresh_overview = Mock()
        with self.assertRaisesRegex(RuntimeError, 'one failed tick'):
            app._tick()
        app.root.after.assert_called_once_with(500, app._tick)
        app._tick()
        self.assertEqual(app.root.after.call_count, 2)
        app._refresh_overview.assert_called_once()

    def test_event_drain_resumes_after_one_failed_event(self):
        app = timer.App.__new__(timer.App)
        app.root = Mock()
        app.status_var = Var('Ready')
        app.events = queue.Queue()
        app.events.put(('kill', 'bad', 'First', '12:00:00'))
        app.events.put(('kill', 'good', 'Second', '12:00:01'))
        app.on_kill = Mock(side_effect=[RuntimeError('one failed event'), True])
        with self.assertRaisesRegex(RuntimeError, 'one failed event'):
            app._drain_events()
        app.root.after.assert_called_once_with(200, app._drain_events)
        app._drain_events()
        self.assertEqual(app.root.after.call_count, 2)
        self.assertIn('Second', app.status_var.get())
        self.assertTrue(app.events.empty())

    def test_ui_errors_are_recorded_without_a_console(self):
        root = Mock()
        with tempfile.TemporaryDirectory() as temp:
            diagnostics = RuntimeDiagnostics(root, temp)
            try:
                try:
                    raise KeyError('popdown')
                except KeyError:
                    root.report_callback_exception(*sys.exc_info())
            finally:
                diagnostics.close()
            log = (Path(temp) / 'mob_timer_diagnostics.log').read_text()
            self.assertIn('UI callback failed', log)
            self.assertIn("KeyError: 'popdown'", log)
            self.assertIn('Application closed', log)


if __name__ == '__main__':
    unittest.main()
