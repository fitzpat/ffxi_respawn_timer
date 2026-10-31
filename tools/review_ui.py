"""Exercise the real Tk interface with isolated data and optional Windows captures.

Run with Windows Python: python tools/review_ui.py --output ui-review
No game logs, saved timers, or tag database are changed.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path)
parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
args = parser.parse_args()
sys.path.insert(0, str(args.source))
import ffxi_mob_timer as timer


def capture(name):
    root.update()
    if not args.output:
        return
    if sys.platform != 'win32':
        raise RuntimeError('Screenshot capture requires Windows; omit --output for GUI checks.')
    root.lift()
    root.attributes('-topmost', True)
    root.update()
    time.sleep(.15)
    path = (args.output / (name + '.png')).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        'Add-Type -AssemblyName System.Drawing; '
        f'$image = New-Object System.Drawing.Bitmap {root.winfo_width()},{root.winfo_height()}; '
        '$graphics = [System.Drawing.Graphics]::FromImage($image); '
        f'$graphics.CopyFromScreen({root.winfo_rootx()},{root.winfo_rooty()},0,0,$image.Size); '
        f"$image.Save('{str(path).replace(chr(39), chr(39) * 2)}'); "
        '$graphics.Dispose(); $image.Dispose()'
    )
    subprocess.run(['powershell.exe', '-NoProfile', '-Command', script], check=True,
                   stdout=subprocess.DEVNULL)
    root.attributes('-topmost', False)


with tempfile.TemporaryDirectory() as temp:
    cfg = copy.deepcopy(timer.DEFAULT_CONFIG)
    cfg.update(chatlog_dir=temp, appearance='Light', toast_popup=False,
               sound_mode='none', placeholder_sound_mode='none')
    path = Path(temp) / 'config.json'
    path.write_text(json.dumps(cfg), encoding='utf-8')
    root = timer.tk.Tk()
    failures = []
    root.report_callback_exception = lambda *error: failures.append(error)
    try:
        with patch.object(timer, 'CONFIG_PATH', str(path)), patch.object(timer, 'LogWatcher'):
            app = timer.App(root)
            app._history_finished = True
            app.chatlog_dir = str(Path(temp) / 'missing')
            app._update_connection(None)
            app._refresh_overview()
            capture('00-setup')
            assert app.empty_action.cget('text') == 'Choose log folder'
            app.chatlog_dir = temp
            app._update_connection(None)
            app._refresh_overview()
            capture('01-empty')
            app._update_connection(str(Path(temp) / 'chat.log'))
            now = time.time()
            for key, label, minutes, elapsed in (
                ('17215867', 'Rock Lizard', '6', 22),
                ('17498521', 'Devil Manta', '16', 1040),
                ('17498518', 'Devil Manta', '16', 710),
                ('sample', 'Buffalo', '', 20),
            ):
                row = app._get_or_create_row(key, label, override=minutes,
                                             use_general=bool(minutes), killed_at=now - elapsed)
                row.refresh_timer()
            for index in range(8):
                extra = app._get_or_create_row(f'sample{index}', f'Buffalo · Camp {index + 1}',
                    override='16', killed_at=now - index * 35)
                extra.refresh_timer()
            app._tick()
            root.update()
            capture('02-timers')
            row = app.rows['17215867']
            assert row.override_ent.winfo_ismapped()
            assert row.warn_secs_ent.winfo_ismapped()
            assert row.use_chk.winfo_ismapped()
            assert row.warn_chk.winfo_ismapped()
            assert row.frame.winfo_height() <= 76, row.frame.winfo_height()
            row.override_ent.focus_force()
            root.update()
            position = row.frame.grid_info()['row']
            row.override_var.set('invalid')
            root.update()
            assert row.override_ent.cget('bg') == app.palette['error_bg']
            assert 'positive' in app.status_var.get()
            assert row.frame.grid_info()['row'] == position
            capture('03-inline-validation')
            row.override_var.set('6')
            row.warn_chk.invoke()
            row.warn_secs_var.set('30')
            saved = json.loads(path.read_text(encoding='utf-8'))
            assert saved['mobs'][row.key]['override'] == '6'
            assert saved['mobs'][row.key]['warn_secs'] == '30'
            assert saved['mobs'][row.key]['warn']
            app.auto_timer_var.set(True)
            app._auto_timers_changed()
            app.auto_warn_var.set(True)
            app._auto_warnings_changed()
            assert row.override_ent.cget('state') == 'disabled'
            assert row.warn_secs_ent.cget('state') == 'disabled'
            assert row.duration_label.cget('text') == 'Auto'
            capture('04-automatic-settings')
            app.auto_timer_var.set(False)
            app._auto_timers_changed()
            app.auto_warn_var.set(False)
            app._auto_warnings_changed()
            assert row.override_ent.cget('state') == 'normal'
            assert row.warn_secs_ent.cget('state') == 'normal'
            assert row.override_var.get() == '6'
            assert row.warn_secs_var.get() == '30'
            # Untrack and restore use the row buttons and retain settings.
            saved_kill = row.killed_at
            row.tracking_btn.invoke()
            root.update()
            assert not row.tracked
            assert not row.frame.winfo_ismapped()
            assert json.loads(path.read_text())['mobs'][row.key]['tracked'] is False
            app.on_kill(row.key, row.label, '12:00:00')
            assert row.killed_at == saved_kill
            app.filter_var.set('Untracked')
            root.update()
            assert row.frame.winfo_ismapped()
            assert row.tracking_btn.cget('text') == 'Track'
            assert row.count_lbl.cget('text') == 'Paused'
            assert row.tracking_btn.winfo_rooty() > row.remove_btn.winfo_rooty()
            capture('17-untracked')
            row.tracking_btn.invoke()
            root.update()
            assert row.tracked
            assert not row.frame.winfo_ismapped()
            assert app.empty_frame.winfo_ismapped()
            assert row.override_var.get() == '6'
            assert row.warn_secs_var.get() == '30'
            app.filter_var.set('Timers')
            root.update()
            assert row.frame.winfo_ismapped()
            app.set_row_tracked('sample0', False)
            app.filter_var.set('Due now')
            root.update()
            assert app.rows['17498521'].frame.winfo_ismapped()
            assert not row.frame.winfo_ismapped()
            capture('15-due-filter')
            app.filter_var.set('Untimed')
            root.update()
            assert app.rows['sample'].frame.winfo_ismapped()
            assert not row.frame.winfo_ismapped()
            app.filter_var.set('Timers')
            app.search_var.set('not a real mob')
            root.update()
            assert app.empty_frame.winfo_ismapped()
            capture('05-search-empty')
            app.search_var.set('')
            app._select_view(1)
            root.update()
            capture('06-settings')
            app.settings_canvas.yview_moveto(1)
            root.update()
            capture('07-settings-lower')
            if hasattr(app, 'settings_sections'):
                app._jump_to_setting('Appearance')
                root.update()
                mode = app.settings_sections['Appearance'].winfo_children()[-1]
                app.dir_entry.focus_force()
                root.update()
                app.settings_canvas.yview_moveto(0)
                root.update()
                mode.focus_force()
                root.update()
                y = mode.winfo_rooty() - app.settings_canvas.winfo_rooty()
                assert 0 <= y <= app.settings_canvas.winfo_height() - mode.winfo_height(), (y, app.settings_canvas.winfo_height(), mode.winfo_height(), app.settings_canvas.yview(), str(root.focus_get()), str(mode), failures)
            app._select_view(2)
            app.tag_search_var.set('Leaping Lizzy')
            root.update()
            children = app.tag_tree.get_children()
            assert children
            app.tag_tree.selection_set(children[0])
            app._show_tag_details()
            capture('08-library')
            app.tag_search_var.set('Charybdis')
            root.update()
            charybdis = app.tag_tree.get_children()
            assert set(charybdis) == {'17498518', '17498520'}
            assert all(app.tag_tree.item(mid, 'values')[2] == '16:20' for mid in charybdis)
            capture('16-charybdis-timing')
            app.tag_search_var.set('Leaping Lizzy')
            root.geometry('800x640')
            root.update()
            capture('09-library-small')
            app._select_view(0)
            root.update()
            capture('10-timers-small')
            app.appearance_var.set('Dark')
            app._appearance_changed()
            root.update()
            capture('11-dark-small')
            root.event_generate('<Control-f>')
            root.update()
            assert root.focus_get() == app.search_entry
            app.search_var.set('lizard')
            root.event_generate('<Escape>')
            root.update()
            assert app.search_var.get() == ''
            assert app.filter_var.get() == 'Timers'
            # Inline fields and removal stay visible even at the minimum width.
            app.canvas.yview_moveto(0)
            root.update()
            assert row.override_ent.winfo_rootx() >= app.canvas.winfo_rootx()
            assert row.remove_btn.winfo_rootx() + row.remove_btn.winfo_width() <= app.canvas.winfo_rootx() + app.canvas.winfo_width()
            viewport_top = app.canvas.canvasy(0)
            viewport_bottom = viewport_top + app.canvas.winfo_height()
            fully_visible = [r for r in app.rows.values() if r.frame.winfo_ismapped()
                             and r.frame.winfo_y() >= viewport_top
                             and r.frame.winfo_y() + r.frame.winfo_height() <= viewport_bottom]
            assert len(fully_visible) >= 4, len(fully_visible)
            app.filter_var.set('Untracked')
            root.update()
            capture('18-dark-untracked-small')
            assert app.rows['sample0'].tracking_btn.cget('text') == 'Track'
            app.filter_var.set('Timers')
            app._select_view(1)
            app.settings_canvas.yview_moveto(0)
            root.update()
            capture('13-dark-settings')
            app._select_view(2)
            root.update()
            capture('14-dark-library')
            app.remove_row('sample')
            saved = json.loads(path.read_text(encoding='utf-8'))
            assert 'sample' not in saved['mobs']
            assert saved['appearance'] == 'Dark'
            assert not failures, failures
            print('GUI checks passed; screenshots captured.' if args.output else 'GUI checks passed.')
    finally:
        root.destroy()
