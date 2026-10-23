"""Pure tracking logic (no I/O) so it can be unit-tested: what one tick of the clock means for today's totals."""
from datetime import datetime

VERSION = "1.1.0"
DEFAULTS = {
    "goal_hours": 7,            # daily target, measured in ACTIVE time (real keyboard/mouse input)
    "active_window": 3,         # a second is active only if input happened within this many seconds; otherwise it is AFK
    "afk_log_seconds": 60,      # AFK stretches shorter than this still count as AFK time, but aren't listed as periods in the log/timeline
    "update_url": "",           # https link to version.json; empty = no update checks
    "widget_compact": False,    # desktop widget minimised to one line
    "summary_time": "18:00",    # end-of-day summary notification
    "ignore_title_apps": ["KeePass", "1Password", "Bitwarden"],   # never store window titles of these apps
    "private_keywords": ["InPrivate", "Incognito", "Private Browsing"],  # titles containing these are not stored
}
COLS = ("active", "afk", "start", "last", "done", "summary", "seen", "afk_since", "goal")


def hm(sec):
    return f"{int(sec // 3600)}h {int(sec % 3600 // 60):02d}m"


def hms(sec):
    return f"{int(sec // 3600)}h {int(sec % 3600 // 60):02d}m {int(sec % 60):02d}s"


def clock(ts):
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "--:--"


def new_day(d):
    return dict(date=d, active=0, afk=0, start=None, last=None, done=0, summary=0, seen=None, afk_since=None, goal=0)


def summary_text(s):
    return f"{clock(s['start'])} -> {clock(s['last'])}   Active {hm(s['active'])} of {hm(s['goal'])} goal\nAFK {hm(s['afk'])}"


def blocks_of(rows):
    """rows: (start, stop, app, title) segments. Merge consecutive same-app segments (gap < 2 min) into timeline blocks with their
    top window titles, and total active seconds per app. Blocks under 5s are dropped from the timeline (still counted per app)."""
    blocks = []
    for a, b, app, title in rows:
        k = blocks[-1] if blocks else None
        if not (k and k["app"] == app and a - k["stop"] < 120):
            k = {"start": a, "stop": b, "app": app, "active": 0, "titles": {}}
            blocks.append(k)
        k["stop"] = max(k["stop"], b)
        k["active"] += b - a
        k["titles"][title] = k["titles"].get(title, 0) + (b - a)
    for k in blocks:
        k["titles"] = sorted(k["titles"].items(), key=lambda t: -t[1])[:8]
    apps = sorted(((app, v[0], v[1]) for app, v in app_titles(rows).items()), key=lambda t: -t[1])[:50]  # (app, seconds, top titles)
    return [k for k in blocks if k["active"] >= 5], apps


def app_titles(rows):
    """{app: (total active seconds, [(title, seconds), ...top 10])} for the whole day."""
    tot, titles = {}, {}
    for a, b, app, title in rows:
        tot[app] = tot.get(app, 0) + (b - a)
        t = titles.setdefault(app, {})
        t[title] = t.get(title, 0) + (b - a)
    return {app: (tot[app], sorted(titles[app].items(), key=lambda t: -t[1])[:10]) for app in tot}


def close_afk(s, end):
    a, s["afk_since"] = s["afk_since"], None
    return [("afk_end", a, end)] if a and end > a else []


def step(s, now, gap, idle, cfg):
    """Advance day-state `s` by one tick. `gap` = seconds since last tick, `idle` = seconds since last input.
    Returns (mode, events); mode is working|afk. After the day's first input, every second is either active or AFK."""
    ev, dt = [], max(0, min(gap, 5))  # cap so sleep gaps aren't counted; never negative if the clock is set back
    s["seen"], s["goal"] = now, cfg["goal_hours"] * 3600
    if gap > 10:  # laptop slept: an open AFK period ended when it went to sleep
        ev += close_afk(s, now - gap)
    typing = idle < cfg["active_window"]
    if typing:
        ev += close_afk(s, now)
        s["active"] += dt
        s["last"] = now
        if not s["start"]:
            s["start"] = now
            ev.append(("start", now))
        mode = "working"
    else:
        mode = "afk"
        if s["start"]:
            s["afk"] += dt
            if idle >= cfg["afk_log_seconds"] and not s["afk_since"]:
                s["afk_since"] = now
                ev.append(("afk_start", now))
    if s["active"] >= s["goal"]:
        if not s["done"]:
            s["done"] = 1
            ev.append(("goal",))
    else:
        s["done"] = 0  # goal was raised after being met: notify again at the new target
    t = datetime.fromtimestamp(now)
    hh, mm = map(int, cfg["summary_time"].split(":"))
    if s["start"] and not s["summary"] and (t.hour, t.minute) >= (hh, mm):
        s["summary"] = 1
        ev.append(("summary",))
    return mode, ev
