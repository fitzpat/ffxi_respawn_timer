"""Package the tested Windows executable without saved timers or local settings."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True, help='Release tag, for example v1.0.0')
    parser.add_argument('--exe', type=Path, default=ROOT / 'dist' / 'FFXIRespawnTimer.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'release-assets')
    args = parser.parse_args()
    if not re.fullmatch(r'v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?', args.version):
        parser.error('Version must be a v-prefixed semantic version.')
    if not args.exe.is_file():
        parser.error(f'Executable not found: {args.exe}')
    args.output.mkdir(parents=True, exist_ok=True)
    exe = args.output / 'FFXIRespawnTimer.exe'
    shutil.copy2(args.exe, exe)
    archive = args.output / f'FFXIRespawnTimer-{args.version}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(exe, exe.name)
        for name in ('README.md', 'RELEASE_NOTES.md', 'mob_tags.json',
                     'docs/images/timers.png', 'docs/images/timers-dark.png'):
            bundle.write(ROOT / name, name)
    checksums = args.output / 'SHA256SUMS.txt'
    checksums.write_text(''.join(
        f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n'
        for path in (exe, archive)
    ), encoding='utf-8')
    print(f'Packaged {exe.name}, {archive.name}, and {checksums.name}')


if __name__ == '__main__':
    main()
