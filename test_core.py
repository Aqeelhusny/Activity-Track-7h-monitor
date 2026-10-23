"""Run: python test_core.py"""
import random
from datetime import datetime

from core import DEFAULTS, new_day, step

T0 = datetime(2026, 1, 5, 9, 0).timestamp()
CFG = dict(DEFAULTS, goal_hours=1000 / 3600, summary_time="23:59")  # goal = 1000s


def run(s, seq, cfg=CFG, t=T0, gap=1):
    """seq of idle_seconds per tick; returns (last_time, all events)."""
    evs = []
    for idle in seq:
        t += gap
        mode, ev = step(s, t, gap, idle, cfg)
        evs += ev
    return t, evs, mode


def test_first_input_starts_day():
    s = new_day("d")
    _, ev, mode = run(s, [0.2])
    assert mode == "working" and s["active"] == 1 and [e[0] for e in ev] == ["start"]


def test_any_second_without_input_is_afk():
    s = new_day("d")
    run(s, [0.2] + [30] * 10)
    assert s["active"] == 1 and s["afk"] == 10 and s["afk_since"] is None  # counted as AFK, too short to list as a period


def test_afk_period_opens_and_closes_on_return():
    s = new_day("d")
    t, _, _ = run(s, [0.2])
    t, ev, mode = run(s, [61] * 5, t=t)
    assert mode == "afk" and s["afk"] == 5 and [e[0] for e in ev] == ["afk_start"]
    t, ev, _ = run(s, [0.1], t=t)
    assert ev[0][0] == "afk_end" and ev[0][2] == t


def test_sleep_gap_not_counted_and_closes_afk_at_sleep_time():
    s = new_day("d")
    t, _, _ = run(s, [0.2] + [61] * 3)
    before = s["afk"]
    now = t + 3600
    mode, ev = step(s, now, 3600, 0.1, CFG)
    assert ev[0] == ("afk_end", s["afk_since"] or ev[0][1], now - 3600) and s["afk"] == before


def test_clock_set_backwards_never_reduces_totals():
    s = new_day("d")
    t, _, _ = run(s, [0.1] * 5)
    before = s["active"]
    step(s, t - 3600, -3600, 0.1, CFG)  # NTP/manual change moved the clock back an hour
    assert s["active"] == before


def test_usage_rows_merge_into_blocks():
    from core import blocks_of
    rows = [(0, 10, "code", "a"), (10, 20, "code", "b"), (20, 22, "chrome", "x"),   # chrome block < 5s: dropped from timeline
            (22, 60, "code", "a"), (500, 520, "code", "a")]                         # gap >= 2 min: new block
    blocks, apps = blocks_of(rows)
    assert [(b["app"], b["start"], b["stop"], b["active"]) for b in blocks] == [("code", 0, 20, 20), ("code", 22, 60, 38), ("code", 500, 520, 20)]
    assert blocks[0]["titles"] == [("a", 10), ("b", 10)] and {a: s for a, s, _ in apps} == {"code": 78, "chrome": 2}
    assert apps[0] == ("code", 78, [("a", 68), ("b", 10)])  # per-app title breakdown for the dashboard's Apps accordion


def test_version_compare():
    from updater import newer
    assert newer("1.10.0", "1.9.9") and newer("2.0.0", "1.99.99") and not newer("1.1.0", "1.1.0") and not newer("1.0.9", "1.1.0")


def test_update_download_is_verified_and_extracted():
    import hashlib, http.server, io, json, tempfile, threading, zipfile
    from pathlib import Path
    from updater import check, fetch
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("install.ps1", "# new installer")
        z.writestr("../evil.txt", "should not escape")
    pkg = buf.getvalue()
    web = {"/AT7-Monitor.zip": pkg}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass
        def do_GET(self):
            body = web.get(self.path)
            self.send_response(200 if body is not None else 404); self.end_headers(); self.wfile.write(body or b"")
    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    good = {"version": "9.0.0", "url": base + "/AT7-Monitor.zip", "sha256": hashlib.sha256(pkg).hexdigest(), "notes": "n"}
    web["/version.json"] = json.dumps(good).encode()
    assert check(base + "/version.json", "1.0.0")["version"] == "9.0.0" and check(base + "/version.json", "9.0.0") is None
    with tempfile.TemporaryDirectory() as tmp:
        out = fetch(good, tmp)
        assert (out / "install.ps1").read_text() == "# new installer" and not (Path(tmp) / "evil.txt").exists() and not (Path(tmp).parent / "evil.txt").exists()
        try:
            fetch(dict(good, sha256="0" * 64), tmp); assert False, "tampered download must be rejected"
        except ValueError as e:
            assert "integrity" in str(e)
    try:
        check("http://example.com/version.json", "1.0.0"); assert False, "plain http must be rejected"
    except ValueError:
        pass
    srv.shutdown()


def test_goal_fires_once_and_again_when_goal_raised():
    s = new_day("d")
    t, ev, _ = run(s, [0.1] * 1100)
    assert [e for e in ev if e[0] == "goal"] == [("goal",)]
    cfg = dict(CFG, goal_hours=2000 / 3600)
    t, ev, _ = run(s, [0.1], cfg=cfg, t=t)
    assert not [e for e in ev if e[0] == "goal"] and s["done"] == 0
    t, ev, _ = run(s, [0.1] * 1000, cfg=cfg, t=t)
    assert len([e for e in ev if e[0] == "goal"]) == 1


def test_summary_fires_once_after_summary_time():
    s = new_day("d")
    cfg = dict(CFG, summary_time="09:00")
    _, ev, _ = run(s, [0.1] * 3, cfg=cfg)
    assert [e[0] for e in ev].count("summary") == 1


def test_every_second_lands_in_exactly_one_bucket():
    random.seed(1)
    s = new_day("d")
    seq = [random.choice([0.1, 10, 100, 500]) for _ in range(5000)]
    run(s, seq)
    first = next(i for i, idle in enumerate(seq) if idle < 3)
    assert s["active"] + s["afk"] == len(seq) - first


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
