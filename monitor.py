"""AT7 Monitor: daily work tracker. Active (real input) time vs a configurable goal, AFK, app usage, SQLite, widget, tray, web dashboard.
Counting rules live in core.py; this file is the Windows/UI/DB glue."""
import ctypes, http.server, json, os, sqlite3, subprocess, tempfile, threading, time, tkinter as tk, traceback, urllib.parse, webbrowser
from ctypes import wintypes
from datetime import date, datetime, timedelta
from pathlib import Path

import pystray
from PIL import Image, ImageDraw, ImageFont

import updater
from core import COLS, DEFAULTS, VERSION, blocks_of, clock, close_afk, hm, hms, new_day, step, summary_text

HERE = Path(__file__).parent
DB, LOG, CFG_FILE, ERR = HERE / "activity.db", HERE / "activity.log", HERE / "config.json", HERE / "error.log"
PORT = 8787


# ---------- config (edit config.json; reloaded every 30s, or pick a goal from the tray menu) ----------
def load_cfg():
    c = dict(DEFAULTS)
    try:
        c.update(json.loads(CFG_FILE.read_text(encoding="utf-8-sig")))  # -sig: Notepad/PowerShell add a BOM
    except (OSError, ValueError):
        pass  # missing or broken file -> defaults
    try:
        h, m = map(int, str(c["summary_time"]).split(":"))
        assert 0 <= h < 24 and 0 <= m < 60
    except Exception:
        c["summary_time"] = DEFAULTS["summary_time"]
    try:
        c["goal_hours"] = min(max(float(c["goal_hours"]), 0.1), 24)
    except (TypeError, ValueError):
        c["goal_hours"] = DEFAULTS["goal_hours"]
    return c


def save_cfg():
    tmp = CFG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.replace(tmp, CFG_FILE)


cfg = load_cfg()
if not CFG_FILE.exists():
    save_cfg()


# ---------- Windows probes ----------
class LII(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


def idle_s():
    # ponytail: GetLastInputInfo also sees synthetic input (mouse jigglers); use a WH_*_LL hook + injected flag if that matters
    i = LII(ctypes.sizeof(LII))
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(i))
    return ((ctypes.windll.kernel32.GetTickCount() - i.dwTime) & 0xFFFFFFFF) / 1000


_u, _k = ctypes.windll.user32, ctypes.windll.kernel32
_u.GetForegroundWindow.restype = wintypes.HWND
_u.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_k.OpenProcess.restype = wintypes.HANDLE
_k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_k.CloseHandle.argtypes = [wintypes.HANDLE]


def foreground():
    """(app, window title) of the window you're using. Browser tab titles are in the window title; URLs are not available."""
    h = _u.GetForegroundWindow()
    title = ctypes.create_unicode_buffer(512)
    _u.GetWindowTextW(h, title, 512)
    pid = wintypes.DWORD()
    _u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    app, ph = "unknown", _k.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if ph:
        buf, size = ctypes.create_unicode_buffer(520), wintypes.DWORD(520)
        if _k.QueryFullProcessImageNameW(ph, 0, buf, ctypes.byref(size)):
            app = Path(buf.value).stem
        _k.CloseHandle(ph)
    t = title.value
    if any(k.lower() in app.lower() for k in cfg["ignore_title_apps"]):
        t = ""
    elif any(k.lower() in t.lower() for k in cfg["private_keywords"]):
        t = "(private window)"
    return app, t


PS = ("Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-Kernel-General','Microsoft-Windows-Kernel-Power';"
      "Id=12,13,41,42,107;StartTime=(Get-Date).AddDays(-DAYS)} -ErrorAction SilentlyContinue | "
      "% { \"$($_.ProviderName.Split('-')[-1])|$($_.Id)|$(([DateTimeOffset]$_.TimeCreated).ToUnixTimeSeconds())\" }")
KIND = {("General", "12"): "BOOT", ("General", "13"): "SHUTDOWN", ("Power", "41"): "POWER LOSS (unexpected shutdown)",
        ("Power", "42"): "SLEEP", ("Power", "107"): "WAKE"}
_syncing = threading.Lock()


def sync_power():
    """Copy boot/shutdown/sleep/wake times from the Windows System event log into the DB (log rolls over, DB doesn't)."""
    if not _syncing.acquire(blocking=False):
        return
    try:
        c = sqlite3.connect(DB, timeout=10)
        last = c.execute("select max(ts) from power").fetchone()[0]
        days = 30 if not last else int((time.time() - last) / 86400) + 2
        out = subprocess.run(["powershell", "-NoProfile", "-Command", PS.replace("DAYS", str(days))], capture_output=True,
                             text=True, stdin=subprocess.DEVNULL, creationflags=0x08000000, timeout=90).stdout
        for line in out.splitlines():
            try:
                p, i, ts = line.strip().split("|")
                if (p, i) in KIND:
                    c.execute("insert or ignore into power values(?,?)", (int(ts), KIND[p, i]))
            except ValueError:
                pass  # stray non-event line
        c.commit()
        c.close()
    except Exception:
        crash("sync_power")
    finally:
        _syncing.release()


# ---------- storage ----------
def crash(where):
    try:
        with ERR.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {where}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def init_db():
    c = sqlite3.connect(DB, check_same_thread=False, timeout=5)
    c.execute("pragma journal_mode=wal")
    c.execute("pragma synchronous=normal")
    c.executescript("""
        create table if not exists days(date text primary key, active real, afk real, start real, last real,
                                        done int, seen real, afk_since real);
        create table if not exists spans(date text, start real, stop real);
        create table if not exists events(ts real, msg text);
        create table if not exists power(ts real, kind text, primary key(ts, kind));
        create table if not exists usage(date text, start real, stop real, app text, title text);
        create index if not exists usage_start on usage(start);""")
    for col, typ in (("summary", "int default 0"), ("goal", "real default 0")):
        try:
            c.execute(f"alter table days add column {col} {typ}")  # upgrade DBs created by older versions
        except sqlite3.OperationalError:
            pass
    try:
        c.execute("update days set afk=afk+coalesce(idle,0), idle=0 where idle>0")  # DBs from older versions: "idle" time is now simply AFK
    except sqlite3.OperationalError:
        pass  # fresh DB has no idle column
    return c


def log(msg, ts=None):
    """Events live in SQLite; activity.log is a best-effort mirror regenerated from them."""
    con.execute("insert into events values(?,?)", (ts or time.time(), msg))
    con.commit()
    try:
        rows = con.execute("select ts,msg from (select * from events order by ts desc limit 1000) order by ts").fetchall()
        LOG.write_text("".join(f"{datetime.fromtimestamp(t):%Y-%m-%d %H:%M:%S}  {m}\n" for t, m in rows), encoding="utf-8")
    except OSError:
        pass  # e.g. the file is open in an editor; the DB still has everything


def today():
    d = str(date.today())
    r = con.execute(f"select {','.join(COLS)} from days where date=?", (d,)).fetchone()
    return dict(zip(COLS, r), date=d) if r else new_day(d)


def save():
    con.execute(f"insert or replace into days(date,{','.join(COLS)}) values(?{',?' * len(COLS)})", (s["date"], *(s[c] for c in COLS)))
    if cur:
        con.execute("update usage set stop=? where rowid=?", (cur["stop"], cur["id"]))
    con.commit()


cur = None  # open app-usage segment: {id, app, title, stop}


def end_seg():
    global cur
    if cur:
        con.execute("update usage set stop=? where rowid=?", (cur["stop"], cur["id"]))
        cur = None


# ---------- updates (needs update_url in config.json) ----------
upd = {"latest": None, "checked": None, "error": None, "busy": False, "notified": None}


def check_updates(manual=False):
    if not cfg["update_url"]:
        if manual:
            notify("AT7 Monitor", "No update_url is set in config.json, so updates are off.")
        return
    try:
        m = updater.check(cfg["update_url"], VERSION)
        upd.update(latest=m, error=None)
        if m and upd["notified"] != m["version"]:
            upd["notified"] = m["version"]
            notify("AT7 Monitor update", f"Version {m['version']} is available. Open the dashboard or tray menu to install it.")
        elif manual and not m:
            notify("AT7 Monitor", f"You're up to date (v{VERSION}).")
    except Exception as e:
        upd["error"] = str(e)[:200]
        if manual:
            notify("Update check failed", upd["error"])
    upd["checked"] = time.time()


def install_update():
    m = upd["latest"]
    if not m or upd["busy"]:
        return
    upd["busy"] = True
    try:
        log(f"UPDATE downloading v{m['version']}")
        folder = updater.fetch(m, tempfile.mkdtemp(prefix="at7-"))
        log(f"UPDATE installing v{m['version']} (the app restarts)")
        updater.apply(folder, HERE)  # install.ps1 stops this process, replaces the code (keeps data + config), restarts
    except Exception as e:
        upd.update(error=str(e)[:200], busy=False)
        crash("update")


def async_(fn, *a):
    threading.Thread(target=fn, args=a, daemon=True).start()


# ---------- web dashboard ----------
def day_json(d, lite=False):
    """lite = just the totals + laptop events (cheap, polled every second); full adds the app blocks and timeline."""
    day = date.fromisoformat(d)
    a, b = (datetime.combine(x, datetime.min.time()).timestamp() for x in (day, day + timedelta(1)))
    c = sqlite3.connect(DB, timeout=5)
    q = lambda sql, *p: c.execute(sql, p).fetchall()
    r = q("select active,afk,start,last,goal from days where date=?", d)
    summary = dict(zip(("active", "afk", "start", "last", "goal"), r[0] if r else (0, 0, None, None, 0)))
    summary["goal"] = summary["goal"] or cfg["goal_hours"] * 3600
    power = q("select ts,kind from power where ts>=? and ts<? order by ts", a, b)
    if lite:
        c.close()
        return {"date": d, "summary": summary, "power": power}
    blocks, apps = blocks_of(q("select start,stop,app,title from usage where start>=? and start<? order by start", a, b))
    out = {"date": d, "summary": summary, "blocks": blocks, "apps": apps, "power": power,
           "spans": q("select start,stop from spans where date=?", d),
           "events": q("select ts,msg from events where ts>=? and ts<? and (msg='START' or msg like 'GOAL%' or msg like 'SUMMARY%') order by ts", a, b)}
    c.close()
    return out


class Web(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, body, ctype="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):  # blocks DNS-rebinding from web pages
        return self.headers.get("Host") in (f"127.0.0.1:{PORT}", f"localhost:{PORT}")

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if not self.host_ok():
            return self.send_error(403)
        try:
            if u.path == "/api/day":
                qs = urllib.parse.parse_qs(u.query)
                self.reply(json.dumps(day_json(qs.get("d", [str(date.today())])[0], "lite" in qs)).encode())
            elif u.path == "/api/update":
                self.reply(json.dumps({"current": VERSION, "enabled": bool(cfg["update_url"]), **upd}).encode())
            elif u.path == "/":
                self.reply((HERE / "ui.html").read_bytes(), "text/html; charset=utf-8")
            else:
                self.send_error(404)
        except ValueError:
            self.send_error(400)

    def do_POST(self):  # only the dashboard's own "Update now" button: custom header + same-origin, so other web pages can't trigger it
        origin = self.headers.get("Origin")
        if not self.host_ok() or self.headers.get("X-AT7") != "1" or (origin and origin not in (f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}")):
            return self.send_error(403)
        if self.path != "/api/update/install":
            return self.send_error(404)
        async_(install_update)
        self.reply(b"{}")


def serve():
    try:
        http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Web).serve_forever()
    except OSError:
        pass


# ---------- startup ----------
_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "AT7Monitor")
if ctypes.windll.kernel32.GetLastError() == 183:  # already running: two copies would double-count
    raise SystemExit

con = init_db()
s = today()
threading.Thread(target=sync_power, daemon=True).start()
threading.Thread(target=serve, daemon=True).start()
prev, n, cfg_mtime = time.time(), 0, CFG_FILE.stat().st_mtime

# ---------- widget + tray ----------
root = tk.Tk()
root.overrideredirect(True)
root.attributes("-topmost", True, "-alpha", 0.9)
root.configure(bg="#1e1e1e")
lbl = tk.Label(root, bg="#1e1e1e", fg="#e0e0e0", font=("Segoe UI", 10), justify="left", padx=10, pady=6)
lbl.pack(side="left")
tog = tk.Label(root, text="-", bg="#1e1e1e", fg="#888888", font=("Segoe UI", 11, "bold"), padx=6, cursor="hand2")  # minimise / expand
tog.pack(side="right", anchor="n")
root.geometry(f"+{root.winfo_screenwidth() - 240}+{root.winfo_screenheight() - 200}")

drag = {}
root.bind("<Button-1>", lambda e: drag.update(x=e.x, y=e.y))
root.bind("<B1-Motion>", lambda e: root.geometry(f"+{root.winfo_x() + e.x - drag['x']}+{root.winfo_y() + e.y - drag['y']}"))


def quit_():
    end_seg()
    handle(close_afk(s, time.time()))
    save()
    log("MONITOR QUIT")
    tray.stop()
    root.destroy()


def icon_img(text, color):
    img = Image.new("RGB", (64, 64), "#1e1e1e")
    ImageDraw.Draw(img).text((32, 32), text, fill=color, anchor="mm", font=ImageFont.truetype("segoeuib.ttf", 34))
    return img


def notify(title, msg):
    try:
        tray.notify(msg, title)  # toast/balloon: doesn't steal focus from what you're typing
    except Exception:
        crash("notify")


def set_goal(h):
    cfg["goal_hours"] = h
    save_cfg()


def toggle_compact():
    cfg["widget_compact"] = not cfg["widget_compact"]
    save_cfg()


tog.bind("<Button-1>", lambda e: toggle_compact())


dashboard = lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")
goal_item = lambda h: pystray.MenuItem(f"{h}h", lambda icon, item: set_goal(h), checked=lambda item: cfg["goal_hours"] == h, radio=True)
menu = pystray.Menu(
    pystray.MenuItem(f"AT7 Monitor v{VERSION}", None, enabled=False),
    pystray.MenuItem("Dashboard", dashboard, default=True),
    pystray.MenuItem(lambda item: f"Install update v{upd['latest']['version']}", lambda: async_(install_update), visible=lambda item: bool(upd["latest"])),
    pystray.MenuItem("Check for updates", lambda: async_(check_updates, True)),
    pystray.MenuItem("Minimise / expand widget", toggle_compact),
    pystray.MenuItem("Daily goal", pystray.Menu(*(goal_item(h) for h in (4, 5, 6, 7, 8, 9, 10)))),
    pystray.MenuItem("Edit config (any goal)", lambda: os.startfile(CFG_FILE)),
    pystray.MenuItem("Open log", lambda: os.startfile(LOG)),
    pystray.MenuItem("Quit", lambda: root.after(0, quit_)))
tray = pystray.Icon("at7", icon_img("0.0", "#4cd964"), "AT7 Monitor", menu)

ctx = tk.Menu(root, tearoff=0)  # right-click the widget
ctx.add_command(label="Dashboard", command=dashboard)
ctx.add_command(label="Edit config", command=lambda: os.startfile(CFG_FILE))
ctx.add_separator()
ctx.add_command(label="Quit tracking", command=quit_)
root.bind("<Button-3>", lambda e: ctx.tk_popup(e.x_root, e.y_root))
root.bind("<Double-Button-1>", lambda e: dashboard())


# ---------- main loop ----------
def handle(events):
    for e in events:
        if e[0] == "start":
            save()
            log("START")
            notify("Work started", f"Started at {clock(e[1])}. Goal: {hm(s['goal'])}.")
        elif e[0] == "afk_start":
            log("AFK start")
        elif e[0] == "afk_end":
            con.execute("insert into spans values(?,?,?)", (s["date"], e[1], e[2]))
            log(f"AFK end   {clock(e[1])}-{clock(e[2])} ({hm(e[2] - e[1])})", e[2])
        elif e[0] == "goal":
            save()
            log(f"GOAL reached: active {hm(s['active'])} of {hm(s['goal'])}")
            notify("Daily goal reached", summary_text(s))
        elif e[0] == "summary":
            save()
            log("SUMMARY " + summary_text(s).replace("\n", " | "))
            notify("Day summary", summary_text(s))


def tick_once():
    global s, prev, n, cur, cfg_mtime
    now = time.time()
    gap, prev = now - prev, now
    if gap > 10:
        end_seg()
    if s["date"] != str(date.today()):  # midnight rollover
        end_seg()
        handle(close_afk(s, now))
        save()
        s = today()
    n += 1
    if n % 30 == 0 and CFG_FILE.exists() and CFG_FILE.stat().st_mtime != cfg_mtime:  # picked up an edit to config.json
        cfg_mtime = CFG_FILE.stat().st_mtime
        cfg.update(load_cfg())
    if n % 1800 == 0:
        threading.Thread(target=sync_power, daemon=True).start()
    if n == 30 or n % 21600 == 0:  # update check: shortly after start, then every 6h
        async_(check_updates)
    mode, events = step(s, now, gap, idle_s(), cfg)
    if mode == "working":  # app usage is recorded only for seconds with real input
        app, title = foreground()
        if cur and (app, title) == (cur["app"], cur["title"]):
            cur["stop"] = now
        else:
            end_seg()
            cur = {"app": app, "title": title, "stop": now,
                   "id": con.execute("insert into usage values(?,?,?,?,?)", (s["date"], now - max(0, min(gap, 5)), now, app, title)).lastrowid}
    else:
        end_seg()
    handle(events)
    save()  # every tick, so the dashboard shows exactly what the widget shows (and a power cut loses <1s)
    w, goal = s["active"], s["goal"] or cfg["goal_hours"] * 3600
    pct = min(w / goal, 1) * 100
    state = {"working": "Working", "afk": f"AFK since {clock(s['afk_since'])}" if s["afk_since"] else "AFK"}[mode]
    if n % 30 == 1 or mode != getattr(tick_once, "mode", None):  # tray icon: worked hours as text, grey when AFK
        tray.icon = icon_img(f"{w / 3600:.1f}", "#888888" if mode == "afk" else "#4cd964")
        tick_once.mode = mode
    if n % 30 == 1:
        tray.title = f"{state}\nActive {hm(w)} / {hm(goal)} ({pct:.0f}%)\nAFK {hm(s['afk'])}"
    compact = cfg["widget_compact"]
    tog.config(text="+" if compact else "-")
    lbl.config(fg="#e0e0e0" if mode == "working" else "#888888",
               text=f"{'Working' if mode == 'working' else 'AFK'} | {hm(w)} / {hm(goal)} ({pct:.0f}%)" if compact else
               f"{state}\nActive  {hms(w)} / {hm(goal)}  ({pct:.0f}%)\nAFK  {hms(s['afk'])}\n"
               f"Start {clock(s['start'])}   Last {clock(s['last'])}")


def tick():
    try:
        tick_once()
    except Exception:
        crash("tick")  # never let one bad tick stop tracking
    finally:
        root.after(1000, tick)


if s["afk_since"]:  # PC was off while AFK: that span ends at the last heartbeat, not now
    handle(close_afk(s, s["seen"] or s["afk_since"]))
log("MONITOR START" + (" (resumed day)" if s["start"] else ""))
tray.run_detached()
tick()
root.mainloop()
