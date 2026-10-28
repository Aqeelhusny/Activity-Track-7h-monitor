# AT7 Monitor

Tracks your daily active time (real keyboard/mouse input) against a goal, with AFK time, which apps you used, and laptop
boot/shutdown times. Everything stays on your PC (`activity.db`); nothing is sent anywhere.

## Install (Windows 10/11, no admin needed)
1. Unzip the folder anywhere.
2. Double-click **install.bat** (installs Python 3 with winget if you don't have it).
3. Done: a widget appears bottom-right, a tray icon shows your active hours, and it **starts automatically every time you sign in**.

Dashboard: http://127.0.0.1:8787 (double-click the widget or tray icon). Uninstall: **uninstall.bat**.
If Windows warns about the downloaded files: right-click the zip > Properties > Unblock, before unzipping.

## What it records
Seconds with keyboard/mouse input (not what you type), the foreground app name and window title (browser tab titles; private
windows are skipped), and boot/sleep/shutdown times. The dashboard only accepts connections from your own PC.

## How time is counted
**Active** = seconds with input in the last `active_window` seconds. Every other second after your first input of the day is **AFK**.
The goal is measured in active time. A new day starts at 00:00. Pick 4-10h from the tray menu (Daily goal) or set any value in `config.json`.

| key | default | meaning |
|---|---|---|
| goal_hours | 7 | daily target |
| active_window | 3 | seconds after an input that still count as active, i.e. you are AFK after this long without input. Pick 3 sec or 1-5 min from the tray menu (Count as AFK after) |
| afk_log_seconds | 60 | shorter AFK stretches count in the total but aren't listed as periods |
| summary_time | "18:00" | end-of-day summary notification |
| update_url | this repo's latest release | link to `version.json` (see Updates); set to "" to never check for updates |
| widget_compact | false | desktop widget minimised to one line |
| ignore_title_apps | KeePass, 1Password, Bitwarden | window titles never stored |
| private_keywords | InPrivate, Incognito, Private Browsing | titles containing these are not stored |

`config.json` is re-read every 30s. Errors go to `error.log`. Tests: `python test_core.py`.

## Minimise
Dashboard: click the **Apps** / **Timeline** headings to fold or open them. Click an app or timeline block to open it (one at a time). Desktop widget: click the **-** in its corner to shrink it to one line, **+** to expand.

## Updates
The app checks this project's latest GitHub release every 6 hours (the only network request it makes; it sends nothing about you). When a newer
version exists you get a notification, and the dashboard (and tray menu) shows **Update now**. One click downloads it, verifies its SHA-256,
installs it and restarts the app. To turn update checks off, set `"update_url": ""` in `config.json`.

**Your data is safe across updates.** Before every update the installer snapshots `activity.db` into the `backup` folder (last 5 kept), and the
previous program files go to `previous`. To roll back: quit the app, copy a file from `backup` over `activity.db` (delete `activity.db-wal` and
`activity.db-shm`), copy the files from `previous` back, and start the app again.

**Maintainer (automatic):** every merge to `main` that changes the app files runs `.github/workflows/release.yml`: it picks the next version,
writes it into `core.py` (committed as `chore: release vX.Y.Z [skip ci]`), runs the tests, builds the two release files and publishes the GitHub
release. Version rule: a commit subject starting with `feat` bumps the minor number, `[major]` or `BREAKING` bumps the major number, anything
else bumps the patch number. To choose a version yourself, edit `VERSION` in `core.py` before merging (an untagged version is released as is).
Pull requests run the tests (`.github/workflows/test.yml`).

**Maintainer (manual fallback):** run `.\release.ps1 -Notes "what changed"`, then on GitHub: Releases > Draft a new release > tag `v<VERSION>` >
attach `dist\AT7-Monitor.zip` and `dist\version.json` > Publish.
Any change to the database layout needs matching upgrade code in `init_db` (adding columns is safe; renaming or deleting is not).
Protect the GitHub account that can publish: it controls what gets installed on colleagues' PCs.

## License
MIT, see [LICENSE](LICENSE).
