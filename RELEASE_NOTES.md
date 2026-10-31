FFXI Respawn Timer v1.0.0 is the first packaged release.

- Automatically follow FFXI chat logs and start respawn timers from defeat messages.
- Track individual spawn IDs with the mobid addon and recognize 442 placeholder IDs for 269 notorious monsters.
- Adjust duration and alerts directly in compact rows; filter upcoming, due, untimed, or untracked mobs.
- Untrack individual mob IDs persistently and restore them with Track. Untracked mobs ignore kills, recovery, sounds, and alerts.
- Recover recent placeholder defeats from the last hour of logs without replaying old alerts.
- Use whole-minute placeholder baselines plus a 20-second corpse allowance, including Charybdis at 16:20.
- Customize early warnings, respawn notifications, placeholder defeat sounds, and light/dark appearance.
- Search the placeholder library and edit its timing database with automatic reload.

Download the Windows x64 ZIP, extract it, and run FFXIRespawnTimer.exe. Python is not required. Choose your chatlogs folder in Settings. Enable the mobid addon and individual spawn ID tracking for placeholder features.

The standalone EXE is also available and creates an editable mob_tags.json beside itself on first launch. Saved timers and preferences are stored locally in mob_timer_config.json; no personal configuration is included in this release.

SHA256SUMS.txt contains checksums for the EXE and ZIP. Timing estimates and placeholder mappings can vary between servers; the included library retains source notes and supports manual corrections.
