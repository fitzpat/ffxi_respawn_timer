"""Smoke-test the Windows executable in a temporary folder without user data."""
import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=Path(__file__).resolve().parents[1] / 'dist' / 'FFXIRespawnTimer.exe')
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Run this check with Windows Python.')
    # The application deliberately allows only one instance. Do not disturb one.
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', 49215))
        except OSError:
            raise RuntimeError('Another timer instance is running; packaged check cannot start.')
    with tempfile.TemporaryDirectory() as temp:
        folder = Path(temp)
        exe = folder / args.exe.name
        shutil.copy2(args.exe, exe)
        config = folder / 'mob_timer_config.json'
        saved = {'chatlog_dir': str(folder), 'sound_mode': 'none', 'toast_popup': False,
                 'appearance': 'Dark', 'mobs': {'sample': {'label': 'Packaging check',
                 'killed_at': time.time(), 'override': '5', 'use_general': False},
                 '17498518': {'label': 'Devil Manta', 'tracked': False,
                             'killed_at': 1000, 'override': '8'}}}
        config.write_text(json.dumps(saved), encoding='utf-8')
        process = subprocess.Popen([str(exe)], cwd=folder)
        user32 = ctypes.windll.user32
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        windows = []

        @callback_type
        def collect(hwnd, _):
            text = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, text, len(text))
            if text.value == 'FFXI Respawn Timer' and user32.IsWindowVisible(hwnd):
                windows.append(hwnd)
            return True

        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f'Executable exited early with {process.returncode}.')
                user32.EnumWindows(collect, 0)
                if windows and (folder / 'mob_tags.json').exists():
                    break
                time.sleep(.2)
            assert windows, 'Application window did not open.'
            tags = json.loads((folder / 'mob_tags.json').read_text(encoding='utf-8'))
            assert len(tags['mobs']) == 442
            for mid in ('17498518', '17498520'):
                entry = tags['mobs'][mid]
                assert entry['respawn_seconds'] + entry['despawn_seconds'] == 980
            # Ask this isolated app to close normally, exercising its save path.
            user32.PostMessageW(windows[0], 0x0010, 0, 0)
            process.wait(timeout=10)
            assert process.returncode == 0
            restored = json.loads(config.read_text(encoding='utf-8'))
            assert restored['appearance'] == 'Dark'
            assert restored['mobs']['sample']['label'] == 'Packaging check'
            assert restored['mobs']['sample']['override'] == '5'
            assert restored['mobs']['sample']['tracked'] is True
            assert restored['mobs']['17498518']['tracked'] is False
            assert restored['mobs']['17498518']['killed_at'] == 1000
            print('Packaged app passed: window opened, bundled tags seeded, saved timer preserved, clean exit.')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == '__main__':
    main()
