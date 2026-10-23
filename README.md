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
| active_window | 3 | seconds after an input that still count as active |
| afk_log_seconds | 60 | shorter AFK stretches count in the total but aren't listed as periods |
| summary_time | "18:00" | end-of-day summary notification |
| update_url | "" | link to `version.json` (see Updates); empty = no update checks |
| widget_compact | false | desktop widget minimised to one line |
| ignore_title_apps | KeePass, 1Password, Bitwarden | window titles never stored |
| private_keywords | InPrivate, Incognito, Private Browsing | titles containing these are not stored |

`config.json` is re-read every 30s. Errors go to `error.log`. Tests: `python test_core.py`.

## Minimise
Dashboard: click the **Apps** / **Timeline** headings to fold or open them. Click an app or timeline block to open it (one at a time). Desktop widget: click the **-** in its corner to shrink it to one line, **+** to expand.

## Updates
Set `update_url` in `config.json` to the link your maintainer gives you. The app checks it every 6 hours; when a newer version exists you
get a notification, and the dashboard (and tray menu) shows **Update now**. One click downloads it, verifies its SHA-256, installs it and
restarts the app. Your data and settings are kept, and the old version is saved in the `previous` folder (copy those files back to roll back).

**Maintainer:** bump `VERSION` in `core.py`, then run
`.\release.ps1 -BaseUrl https://<where-you-host-the-files> -Notes "what changed"`. It runs the tests and builds `dist\AT7-Monitor.zip`
and `dist\version.json`; upload both to that folder. With GitHub Releases use `https://github.com/<org>/<repo>/releases/latest/download`.
Colleagues' `update_url` is then `<BaseUrl>/version.json` (https only). Protect the account that can publish: it controls what gets installed.
