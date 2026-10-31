"""Real Tk regression: dropdown focus, incoming kills, and callback recovery.

Run with Windows Python. Uses temporary state, no game logs, and muted sounds.
"""
import faulthandler
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffxi_mob_timer as timer


def main():
    with tempfile.TemporaryDirectory() as temp:
        cfg = dict(timer.DEFAULT_CONFIG, chatlog_dir=temp, sound_mode='none',
                   placeholder_sound_mode='none', toast_popup=False, mobs={})
        path = Path(temp) / 'config.json'
        path.write_text(json.dumps(cfg))
        log_path = Path(temp) / 'liveness.log'
        with log_path.open('w') as log:
            # Fail promptly with a stack if an idle/geometry loop really hangs.
            faulthandler.dump_traceback_later(12, file=log, exit=True)
            root = timer.tk.Tk()
            errors, checks = [], []
            counts = {'tick': 0, 'events': 0}
            original_tick, original_drain = timer.App._tick, timer.App._drain_events

            def tick(app):
                counts['tick'] += 1
                return original_tick(app)

            def drain(app):
                counts['events'] += 1
                return original_drain(app)

            def report(*info):
                errors.append(info)
                traceback.print_exception(*info, file=log)
                log.flush()

            root.report_callback_exception = report
            try:
                with patch.object(timer, 'CONFIG_PATH', str(path)), patch.object(timer, 'LogWatcher'), \
                     patch.object(timer.App, '_tick', tick), patch.object(timer.App, '_drain_events', drain):
                    app = timer.App(root)
                    combo = None

                    def find_combo(parent):
                        for child in parent.winfo_children():
                            if child.winfo_class() == 'TCombobox':
                                return child
                            found = find_combo(child)
                            if found is not None:
                                return found

                    def post_dropdown():
                        nonlocal combo
                        app._select_view(1)
                        app._jump_to_setting('Sounds')
                        combo = find_combo(app.settings_sections['Sounds'])
                        root.tk.call('ttk::combobox::Post', str(combo))
                        popup = root.tk.call('ttk::combobox::PopdownWindow', str(combo))
                        root.tk.call('focus', '-force', str(popup) + '.f.l')

                    def check_dropdown():
                        # Keep it open across ticks and a real incoming kill.
                        assert counts['tick'] >= 3, counts
                        assert counts['events'] >= 7, counts
                        assert not errors, errors
                        assert '17215867' in app.rows
                        root.tk.call('ttk::combobox::Unpost', str(combo))
                        checks.append('dropdown and live kill remained responsive')
                        # Inject one recoverable error in each recurring callback.
                        app.events.put(('kill', 'fault', 'Injected failure', '12:00:00'))
                        app.events.put(('kill', 'next', 'Recovered kill', '12:00:01'))
                        real_kill = app.on_kill
                        def kill(key, *args):
                            if key == 'fault':
                                raise RuntimeError('injected event failure')
                            return real_kill(key, *args)
                        app.on_kill = kill
                        real_display = app.rows['17215867'].update_display
                        failed = False
                        def display(now):
                            nonlocal failed
                            if not failed:
                                failed = True
                                raise RuntimeError('injected tick failure')
                            return real_display(now)
                        app.rows['17215867'].update_display = display

                    def finish():
                        try:
                            assert len(checks) == 1, checks
                            assert 'next' in app.rows
                            assert counts['tick'] >= 7, counts
                            assert len(errors) == 2, [(e[0], str(e[1])) for e in errors]
                            assert all(e[0] is RuntimeError and 'injected' in str(e[1]) for e in errors)
                            checks.append('both callbacks resumed after injected errors')
                        except Exception:
                            report(*sys.exc_info())
                        root.quit()

                    root.after(250, post_dropdown)
                    root.after(800, lambda: app.events.put(('kill', '17215867', 'Rock Lizard', '12:00:00')))
                    root.after(1900, check_dropdown)
                    root.after(4100, finish)
                    root.mainloop()
                    assert len(checks) == 2, log_path.read_text()
                    print('UI liveness passed:', '; '.join(checks))
            finally:
                root.destroy()
                faulthandler.cancel_dump_traceback_later()


if __name__ == '__main__':
    main()
