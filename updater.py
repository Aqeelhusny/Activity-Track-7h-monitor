"""Update check + one-click self-update. The published manifest (version.json) is {"version", "url", "sha256", "notes"}."""
import hashlib, json, subprocess, urllib.request, zipfile
from pathlib import Path
from urllib.parse import urlparse


def newer(a, b):
    return tuple(int(x) for x in a.split(".")) > tuple(int(x) for x in b.split("."))


def _get(url, limit):
    u = urlparse(url)
    if u.scheme != "https" and u.hostname not in ("127.0.0.1", "localhost"):  # http only for local testing
        raise ValueError("update URL must use https")
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "AT7-Monitor"}), timeout=20) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("download too large")
    return data


def check(manifest_url, current):
    """The manifest if a newer version is published, else None."""
    m = json.loads(_get(manifest_url, 1 << 20))
    if not all(isinstance(m.get(k), str) for k in ("version", "url", "sha256")):
        raise ValueError("bad update manifest")
    return m if newer(m["version"], current) else None


def fetch(m, folder):
    """Download the zip, verify its SHA-256, extract. Returns the extracted folder (it contains install.ps1)."""
    data = _get(m["url"], 50 << 20)
    if hashlib.sha256(data).hexdigest() != m["sha256"].lower():
        raise ValueError("update failed its integrity check, not installed")
    z, out = Path(folder) / "update.zip", Path(folder) / "new"
    z.write_bytes(data)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(out)  # extractall drops absolute paths and '..' parts
    if not (out / "install.ps1").exists():
        raise ValueError("bad update package")
    return out


def apply(folder, dest):
    """Run the new package's installer detached: it stops the running monitor, replaces the code (keeps data/config) and restarts it."""
    log = open(Path(folder) / "update.log", "wb")  # installer output, so a failed update can be diagnosed
    subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(Path(folder) / "install.ps1"), "-Dest", str(dest)],
                     creationflags=0x08000000 | 0x00000200, stdin=subprocess.DEVNULL, stdout=log, stderr=log)  # hidden console | own process group (survives us being stopped)
