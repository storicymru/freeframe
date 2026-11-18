"""Adborth's deploy helper: builds and restarts the site on the NAS on request.

Runs as its own small container beside the site, with the Docker socket and the
site's folder mounted. It does one thing: on a signed request, run
`docker compose build` and `docker compose up -d` for the site's compose file,
and report how that went.

Every request is signed with a shared key (HMAC-SHA256 over the method, path
and body) and carries a timestamp and a one-time value, so the key never
crosses the network and a captured request cannot be replayed. Nothing here is
reachable without the key, and it listens on the office network only.

Standard library only, so the image needs nothing but Python and the Docker
client.
"""
import hashlib
import hmac
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOME = os.environ.get("ADBORTH_HOME", "/share/Container/freeframe")
COMPOSE = os.path.join(HOME, "docker-compose.yml")
KEY_FILE = os.environ.get("ADBORTH_KEY_FILE", os.path.join(HOME, "deployer", "key"))
LOG_FILE = os.environ.get("ADBORTH_LOG_FILE", os.path.join(HOME, "deployer", "last-deploy.log"))
PORT = int(os.environ.get("ADBORTH_PORT", "8399"))
SERVICES = {"api", "web"}
# How far a request's clock may be from this one's, and how long a one-time
# value is remembered: the second has to cover the first.
MAX_SKEW = 120
BUILD_TIMEOUT = 45 * 60
UP_TIMEOUT = 15 * 60

_lock = threading.Lock()
_seen: dict[str, float] = {}
_state = {"state": "idle", "step": None, "started": None, "finished": None, "ok": None, "services": None}


def _key() -> bytes:
    with open(KEY_FILE, "rb") as handle:
        key = handle.read().strip()
    if len(key) < 32:
        raise RuntimeError("the deploy key is missing or too short")
    return key


def signature(key: bytes, method: str, path: str, body: bytes) -> str:
    message = method.encode() + b"\n" + path.encode() + b"\n" + body
    return hmac.new(key, message, hashlib.sha256).hexdigest()


def check_request(method: str, path: str, body: bytes, sent: str, payload: dict, now=None) -> str | None:
    """Why this request is refused, or None when it is good. Marks its
    one-time value as used."""
    now = time.time() if now is None else now
    try:
        expected = signature(_key(), method, path, body)
    except Exception:
        return "the helper has no key"
    if not sent or not hmac.compare_digest(expected, sent):
        return "bad signature"
    try:
        stamp = float(payload["ts"])
        nonce = str(payload["nonce"])
    except (KeyError, TypeError, ValueError):
        return "missing ts or nonce"
    if abs(now - stamp) > MAX_SKEW or len(nonce) < 16:
        return "stale request"
    with _lock:
        for old, when in list(_seen.items()):
            if now - when > MAX_SKEW * 2:
                del _seen[old]
        if nonce in _seen:
            return "replayed request"
        _seen[nonce] = now
    return None


def _log(text: str) -> None:
    with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)


def _run(step: str, command: list[str], timeout: int) -> bool:
    _state["step"] = step
    _log(f"\n=== {step}: {' '.join(command)}\n")
    try:
        with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as handle:
            done = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, timeout=timeout, cwd=HOME)
    except subprocess.TimeoutExpired:
        _log(f"\n=== {step} gave up after {timeout} seconds\n")
        return False
    _log(f"=== {step} finished with exit code {done.returncode}\n")
    return done.returncode == 0


def busy_versions() -> int | None:
    """How many uploads or transcodes are under way, or None if that could not
    be asked. A deploy restarts the workers, which would cut them off."""
    query = ("select count(*) from asset_versions where deleted_at is null "
             "and processing_status in ('uploading','processing') "
             "and coalesce(last_activity_at, created_at) > now() - interval '6 hours'")
    command = ["docker", "compose", "-f", COMPOSE, "exec", "-T", "postgres",
               "sh", "-c", f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "{query}"']
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30, cwd=HOME)
        return int(done.stdout.strip().splitlines()[-1])
    except Exception:
        return None


def deploy(services: list[str]) -> None:
    compose = ["docker", "compose", "-f", COMPOSE]
    ok = _run("build", compose + ["build"] + services, BUILD_TIMEOUT)
    if ok:
        # Everything, not just what was built: a setting changed in .env.prod
        # has to reach the workers too, and unchanged containers are left alone.
        ok = _run("restart", compose + ["up", "-d"], UP_TIMEOUT)
    _state.update(state="idle", step=None, finished=time.time(), ok=ok)
    _log(f"\n=== deploy {'succeeded' if ok else 'FAILED'}\n")


def start_deploy(payload: dict) -> tuple[int, dict]:
    services = payload.get("services") or sorted(SERVICES)
    if not isinstance(services, list) or not services or not set(services) <= SERVICES:
        return 400, {"error": f"services must be some of {sorted(SERVICES)}"}
    with _lock:
        if _state["state"] == "running":
            return 409, {"error": "a deploy is already running"}
        if not payload.get("force"):
            busy = busy_versions()
            if busy:
                return 409, {"error": f"{busy} upload(s) or video(s) are still processing", "busy": busy}
        _state.update(state="running", step="starting", started=time.time(), finished=None, ok=None, services=services)
    with open(LOG_FILE, "w", encoding="utf-8") as handle:
        handle.write(f"deploy of {', '.join(services)} started {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")
    threading.Thread(target=deploy, args=(services,), daemon=True).start()
    return 202, {"started": True, "services": services}


def status() -> dict:
    tail = ""
    try:
        with open(LOG_FILE, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 6000))
            tail = handle.read().decode("utf-8", errors="replace")
    except OSError:
        pass
    return {**_state, "log_tail": tail}


class Handler(BaseHTTPRequestHandler):
    server_version = "adborth-deployer"

    def log_message(self, *args):  # quiet: the deploy log is the record
        pass

    def _answer(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        try:
            length = min(int(self.headers.get("Content-Length") or 0), 4096)
            body = self.rfile.read(length)
            payload = json.loads(body or b"{}")
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, json.JSONDecodeError):
            return self._answer(400, {"error": "bad request"})
        if self.path not in ("/deploy", "/status"):
            return self._answer(404, {"error": "not found"})
        refusal = check_request("POST", self.path, body, self.headers.get("X-Signature", ""), payload)
        if refusal:
            # One answer for every refusal: nothing to learn by probing.
            return self._answer(401, {"error": "not authorised"})
        if self.path == "/status":
            return self._answer(200, status())
        code, answer = start_deploy(payload)
        self._answer(code, answer)

    def do_GET(self):
        # Only "am I here": everything else needs a signature.
        if self.path == "/ping":
            return self._answer(200, {"ok": True})
        self._answer(404, {"error": "not found"})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
