FFXI Respawn Timer v1.0.1 fixes a dropdown-focus error that could stop countdown updates and live kill processing.

- Handle Tk-created dropdown popup widgets without raising `KeyError: 'popdown'`.
- Keep timer updates and log-event processing scheduled after a recoverable callback error.
- Ignore native popup focus and scrolling events that have no Python widget object.
- Record callback and background-thread errors in a rotating local `mob_timer_diagnostics.log`.
- Capture thread stacks if the UI heartbeat stalls, making future hangs easier to diagnose.
- Add regression coverage for open dropdowns, incoming kills, callback recovery, and logging without a console.

Validation includes 84 automated tests, a native Windows dropdown/callback recovery check, and packaged startup/persistence checks.

To upgrade, close the old timer and replace FFXIRespawnTimer.exe with this release. Keep your existing mob_timer_config.json to preserve saved timers, preferences, and untracked mob IDs. Keep your existing mob_tags.json if you have custom timing edits. No configuration migration is required.

Download the Windows x64 ZIP and extract it, or download the standalone EXE. Python is not required. The ZIP includes the stock placeholder database and usage notes; personal settings and diagnostic logs are excluded.

SHA256SUMS.txt contains checksums for the EXE and portable ZIP.
