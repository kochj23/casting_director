"""Casting Director — Nova edition server.

Serves Austin Fonacier's game (index.html, js/, css/) and replaces its three Firebase Cloud Functions with the same
request/response shapes, answered by whichever AI backend each brain is set to (see ai.py), with the Nova Games DB
(store.py) in place of Firestore. Loopback only by default (127.0.0.1:37445): API keys live in this Mac's Keychain,
so the server is never exposed to the LAN unless started with --lan.

  python3 -m nova.server                 serve on 127.0.0.1:37445
  python3 -m nova.server --migrate       apply Games DB migrations (as casting_owner)
  python3 -m nova.server --setup-credentials   fetch the casting / casting_owner passwords from core3 over SSH
  python3 -m nova.server --smoke         start, self-check every route offline, exit 0/1 (GTNW's --launch-smoke)
"""
import argparse
import json
import mimetypes
import random
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import ai, keychain, prompts, rules
from .store import GameStore, PlayLog

ROOT = Path(__file__).resolve().parent.parent
VERSION = "nova-1.0.0"
PORT = 37445
PLAYER = "default"
MAX_BODY = 256 * 1024
STATIC_DIRS = ("css/", "js/", "images/", "assets/", "audio/")
STATIC_FILES = {"index.html", "app.js", "favicon.ico", "version.js"}
ROLES = {
    "analyst": "Book analyst (reads the book, sets the budget and studio)",
    "agent": "Talent agents (quote actor fees)",
    "critics": "Critics and box office (reviews, awards, the score)",
}
# Measured 2026-11-10 on Project Hail Mary: Claude (CLI, flat-rate) names the real cast in ~70 s; local qwen3:30b-a3b
# answers in ~18 s but invents characters, so it gets the fast, forgiving jobs (fees, reviews).
DEFAULT_BRAINS = {"analyst": {"backend": "claude-cli", "model": "sonnet"},
                  "agent": {"backend": "ollama", "model": "qwen3:30b-a3b"},
                  "critics": {"backend": "ollama", "model": "qwen3:30b-a3b"}}
# Austin's artwork is deployed on his site but not committed to his repo. It is fetched from there once, cached
# outside git (never redistributed from this fork), and served locally.
ART_ORIGIN = "https://casting-director-1990.web.app"
ART_CACHE = Path.home() / "Library/Application Support/CastingDirector/art"
ART_NAME = re.compile(r"^images/[A-Za-z0-9_-]{1,64}\.(png|jpg|jpeg|gif|webp)$")
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'none'; form-action 'self'")


class Game:
    """Server-side state shared by every request: the store, the brains and the open play session."""

    def __init__(self, store: GameStore):
        self.store = store
        self.play = PlayLog(store, PLAYER)
        self.lock = threading.Lock()

    # -- brains -----------------------------------------------------------------------------------------------
    def brains(self) -> dict:
        b = dict(DEFAULT_BRAINS)
        saved = self.store.setting("brains", {}) or {}
        for role in ROLES:
            if isinstance(saved.get(role), dict) and saved[role].get("backend") in ai.BACKENDS:
                b[role] = {"backend": saved[role]["backend"], "model": str(saved[role].get("model") or "")[:120]}
        return b

    def overrides(self) -> dict:
        return self.store.setting("backend_overrides", {}) or {}

    def ask(self, role, system, user, schema, timeout=150):
        """(data, meta) from the role's brain, or (None, meta) when the rules must answer."""
        try:
            data, meta = ai.complete_json(self.brains()[role], system, user, schema, role=role, timeout=timeout,
                                          overrides=self.overrides())
            self.store.record_ai_call(ai.STATS.calls[-1] if ai.STATS.calls else None)
            return data, meta
        except ai.AIError as e:
            if ai.STATS.calls:
                self.store.record_ai_call(ai.STATS.calls[-1])
            return None, {"backend": "rules", "model": None, "reason": str(e)[:160]}

    # -- Austin's three calls -----------------------------------------------------------------------------------
    def book_info(self, book: str, author: str) -> dict:
        with self.lock:
            if self.play.id:
                self.play.end("abandoned")
            self.play.start(book=book[:300], author=author[:200])
        key = f"{book.strip().lower()}|{author.strip().lower()}"
        cached = self.store.cache_get("book_cache", key)
        if cached:
            self.play.event("greenlit", studio=cached.get("studio"), budget=cached.get("movieBudget"), source="cache")
            return dict(cached, _source="cache")
        data, meta = self.ask("analyst", prompts.BOOK_SYSTEM, prompts.book_query(book, author), prompts.BOOK_SCHEMA)
        if data is None:
            data = rules.book_info(book, author)
        data = clamp_book(data)
        if meta["backend"] != "rules":
            self.store.cache_put("book_cache", key, data, f"{meta['backend']}:{meta['model']}")
        self.play.event("greenlit", studio=data["studio"], budget=data["movieBudget"], source=meta["backend"])
        return dict(data, _source=meta["backend"], _model=meta.get("model"))

    def actor_fee(self, actor: str) -> dict:
        key = actor.strip().lower()
        cached = self.store.cache_get("actor_cache", key)
        if cached:
            self.play.event("quote", actor=actor[:120], fee=cached.get("fee"), source="cache")
            return dict(cached, _source="cache")
        data, meta = self.ask("agent", prompts.FEE_SYSTEM, prompts.fee_query(actor), prompts.FEE_SCHEMA, timeout=60)
        if data is None:
            data = rules.actor_fee(actor)
        data = {"fee": max(0.0, min(float(data["fee"]), 100e6)), "popularity": str(data["popularity"])[:40]}
        if meta["backend"] != "rules":
            self.store.cache_put("actor_cache", key, data, f"{meta['backend']}:{meta['model']}")
        self.play.event("quote", actor=actor[:120], fee=data["fee"], source=meta["backend"])
        return dict(data, _source=meta["backend"])

    def movie_results(self, d: dict) -> dict:
        data, meta = self.ask("critics", prompts.RESULTS_SYSTEM, prompts.results_query(d), prompts.RESULTS_SCHEMA,
                              timeout=240)
        if data is None:
            data = rules.movie_results(d)
        data = clamp_results(data)
        r = random.Random()
        for k in ("imdbUsername", "letterboxdUsername", "rtUsername"):
            data[k] = r.choice(prompts.USERNAMES_90S)
        data["_source"], data["_model"] = meta["backend"], meta.get("model")
        self.play.event("released", cast=str(d.get("castDetails") or "")[:2000], score=data["overallGameScore"],
                        box_office=data["boxOffice"], source=meta["backend"])
        with self.lock:
            self.play.end("released", data["overallGameScore"], book=str(d.get("bookName") or "")[:300],
                          verdict=data["scoreDescriptor"])
        return data


def clamp_book(d: dict) -> dict:
    d = dict(d)
    d["movieBudget"] = max(1e6, min(float(d["movieBudget"]), 300e6))
    d["castingBudget"] = max(d["movieBudget"] * 0.1, min(float(d["castingBudget"]), d["movieBudget"] * 0.4))
    d["characters"] = [c for c in d.get("characters", []) if c.get("name")][:8] or rules.book_info("", "")["characters"]
    return d


def clamp_results(d: dict) -> dict:
    d = dict(d)
    lim = {"imdbScore": (0, 10), "letterboxdScore": (0, 5), "rtCriticsScore": (0, 100), "rtAudienceScore": (0, 100),
           "overallGameScore": (0, 100), "boxOffice": (0, 5e9)}
    for k, (lo, hi) in lim.items():
        d[k] = max(lo, min(float(d[k]), hi))
    for k in ("siskelVerdict", "ebertVerdict"):
        d[k] = d[k] if d[k] in ("thumbs_up", "thumbs_down") else "thumbs_down"
    if d["finalVerdict"] not in ("recommended", "not_recommended", "mixed"):
        d["finalVerdict"] = "mixed"
    d["castingScores"] = [dict(c, score=max(0, min(float(c["score"]), 10))) for c in d.get("castingScores", [])]
    d["awards"] = [a[:120] for a in d.get("awards", [])][:12]
    return d


def _str(body, key, maxlen=200, required=True):
    v = body.get(key)
    if v is None and not required:
        return ""
    if not isinstance(v, str) or not v.strip() or len(v) > maxlen:
        raise ValueError(f"{key} must be a non-empty string of at most {maxlen} characters")
    return v.strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "CastingDirector"
    sys_version = ""
    game: Game = None

    def log_message(self, *a):  # quiet; no request bodies or keys in logs
        pass

    # -- plumbing ---------------------------------------------------------------------------------------------
    def _headers(self, code, ctype, length):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(length))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()

    def _json(self, code, obj):
        body = json.dumps(obj, default=str).encode()
        self._headers(code, "application/json", len(body))
        self.wfile.write(body)

    def _err(self, code, msg, **extra):
        self._json(code, {"error": msg, "statusCode": code, **extra})

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = self.headers.get("Host", "")
        return urlparse(origin).netloc == host

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise OverflowError
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            raise TypeError
        raw = self.rfile.read(n) if n else b"{}"
        body = json.loads(raw or b"{}")
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        return body

    # -- static -----------------------------------------------------------------------------------------------
    def _version_js(self):
        """version.js is generated by Austin's Node script at deploy; here it comes from git on the fly."""
        def git(*a):
            try:
                return subprocess.run(["git", "-C", str(ROOT), *a], capture_output=True, text=True,
                                      timeout=5).stdout.strip()
            except (OSError, subprocess.TimeoutExpired):
                return ""
        info = {"commitHash": git("rev-parse", "--short", "HEAD") or "unknown",
                "branch": git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
                "commitDate": git("log", "-1", "--format=%cd", "--date=short") or "unknown", "tag": "",
                "commitMessage": "", "buildDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "edition": "nova", "server": VERSION}
        body = ("export const VERSION_INFO = " + json.dumps(info) + ";\n"
                f"export const VERSION_STRING = {json.dumps(info['commitHash'])};\n"
                "export function getVersionDisplay() { return VERSION_STRING; }\n"
                "export function getFullVersionInfo() { return `v${VERSION_STRING} (Nova edition)`; }\n").encode()
        self._headers(200, "text/javascript; charset=utf-8", len(body))
        self.wfile.write(body)

    def _art(self, rel):
        target = ART_CACHE / Path(rel).name
        if not target.is_file():
            try:
                ART_CACHE.mkdir(parents=True, exist_ok=True)
                req = urllib.request.Request(f"{ART_ORIGIN}/{rel}", headers={"User-Agent": "CastingDirector-Nova"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read(8 * 1024 * 1024 + 1)
                    ctype = r.headers.get("Content-Type", "")
                if len(data) > 8 * 1024 * 1024 or not ctype.startswith("image/"):
                    return self._err(404, "not found")
                tmp = target.with_suffix(".part")
                tmp.write_bytes(data)
                tmp.replace(target)
            except (urllib.error.URLError, OSError, TimeoutError):
                return self._err(404, "art unavailable offline")
        data = target.read_bytes()
        self._headers(200, mimetypes.guess_type(target.name)[0] or "image/png", len(data))
        self.wfile.write(data)

    def _static(self, path):
        rel = path.lstrip("/") or "index.html"
        if rel == "version.js" and not (ROOT / rel).is_file():
            return self._version_js()
        if ART_NAME.match(rel) and not (ROOT / rel).is_file():
            return self._art(rel)
        if rel not in STATIC_FILES and not rel.startswith(STATIC_DIRS):
            return self._err(404, "not found")
        target = (ROOT / rel).resolve()
        if ROOT not in target.parents or not target.is_file() or ".test." in target.name:
            return self._err(404, "not found")
        data = target.read_bytes()
        if rel == "index.html":
            data = data.replace(b"<head>", b'<head>\n    <meta name="casting-edition" content="nova">', 1)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._headers(200, ctype, len(data))
        self.wfile.write(data)

    # -- routes -----------------------------------------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        g = self.game
        if p == "/healthz":
            return self._json(200, {"ok": True, "version": VERSION, "db": g.store.badge()})
        if p == "/api/edition":
            return self._json(200, {"edition": "nova", "version": VERSION, "player": PLAYER,
                                    "credit": "Casting Director by Austin Fonacier (github.com/austinrfnd)"})
        if p == "/api/status":
            return self._json(200, {"db": g.store.status(), "version": VERSION})
        if p == "/api/stats":
            return self._json(200, {"ai": ai.STATS.snapshot(), "db": g.store.status(), "brains": g.brains(),
                                    "play_session": g.play.id, "version": VERSION})
        if p == "/api/movies/recent":
            return self._json(200, {"movies": g.store.recent_movies(10)})
        if p.startswith("/api/movies/"):
            m = g.store.movie(p.rsplit("/", 1)[1])
            return self._json(200, m) if m else self._err(404, "no such movie")
        if p == "/api/leaderboard":
            return self._json(200, {"entries": g.store.leaderboard(20)})
        if p == "/api/achievements":
            return self._json(200, {"unlocked": g.store.achievements(PLAYER)})
        if p == "/api/settings":
            ov = g.overrides()
            return self._json(200, {
                "brains": g.brains(), "roles": ROLES,
                "backends": {k: {"label": v["label"], "kind": v["kind"], "default_model": v.get("model"),
                                 "needs_key": bool(v.get("key")) and not v.get("key_optional"),
                                 "has_key": keychain.has(v["key"]) if v.get("key") else None,
                                 "base": (ov.get(k) or {}).get("base") or v.get("base")}
                             for k, v in ai.BACKENDS.items()}})
        if p == "/api/backends/available":
            names = [n for n in ai.BACKENDS if n not in ("auto", "rules")]
            res = {}
            threads = [threading.Thread(target=lambda n=n: res.__setitem__(n, ai.available(n, g.overrides())))
                       for n in names]
            for t in threads:
                t.start()
            for t in threads:
                t.join(6)
            return self._json(200, {"available": res})
        if p == "/api/models":
            b = (q.get("backend") or [""])[0]
            if b not in ai.BACKENDS:
                return self._err(400, "unknown backend")
            return self._json(200, {"backend": b, "models": ai.list_models(b, g.overrides())})
        if p.startswith("/api/"):
            return self._err(404, "not found")
        return self._static(p)

    def do_POST(self):
        self._write("POST")

    def do_PUT(self):
        self._write("PUT")

    def _write(self, method):
        if not self._same_origin():
            return self._err(403, "cross-origin request refused")
        try:
            body = self._body()
        except OverflowError:
            return self._err(413, "body too large")
        except TypeError:
            return self._err(415, "Content-Type must be application/json")
        except ValueError as e:
            return self._err(400, str(e) or "bad JSON")
        p, g = urlparse(self.path).path, self.game
        try:
            if p in ("/api/getBookInfo", "/getBookInfo"):
                return self._json(200, g.book_info(_str(body, "bookName", 300), _str(body, "author", 200)))
            if p in ("/api/getActorFee", "/getActorFee"):
                return self._json(200, g.actor_fee(_str(body, "actorName", 120)))
            if p in ("/api/generateMovieResults", "/generateMovieResults"):
                for k in ("bookName", "bookPopularity", "castDetails"):
                    _str(body, k, 8000)
                return self._json(200, g.movie_results(body))
            if p == "/api/movies":
                mid = g.store.save_movie(PLAYER, body)
                return self._json(200, {"id": mid})
            if p == "/api/play/start":
                return self._json(200, {"session": g.play.start(**_clean_detail(body))})
            if p == "/api/play/event":
                kind = _str(body, "kind", 48)
                if not re.match(r"^[a-z0-9][a-z0-9_.-]{0,47}$", kind):
                    raise ValueError("bad event kind")
                g.play.event(kind, **_clean_detail(body.get("detail") or {}))
                return self._json(200, {"ok": True})
            if p == "/api/play/end":
                g.play.end(_str(body, "outcome", 64), body.get("score"), **_clean_detail(body.get("summary") or {}))
                return self._json(200, {"ok": True})
            if p == "/api/settings" and method == "PUT":
                return self._json(200, self._put_settings(body))
            if p == "/api/keys":
                b = _str(body, "backend", 40)
                spec = ai.BACKENDS.get(b)
                if not spec or not spec.get("key"):
                    raise ValueError("that backend takes no key")
                if not keychain.put(spec["key"], _str(body, "key", 4096)):
                    return self._err(400, "could not store the key")
                return self._json(200, {"ok": True, "has_key": True})
        except ValueError as e:
            return self._err(400, str(e))
        return self._err(404, "not found")

    def _put_settings(self, body):
        g = self.game
        brains = g.brains()
        for role, b in (body.get("brains") or {}).items():
            if role in ROLES and isinstance(b, dict) and b.get("backend") in ai.BACKENDS:
                brains[role] = {"backend": b["backend"], "model": str(b.get("model") or "")[:120]}
        g.store.set_setting("brains", brains)
        ov = g.overrides()
        for name, o in (body.get("backend_overrides") or {}).items():
            if name in ai.BACKENDS and isinstance(o, dict):
                base = str(o.get("base") or "")
                if base and not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?(/[\w\-./]*)?$", base):
                    raise ValueError("base must be an http(s) URL")
                ov[name] = {"base": base, "model": str(o.get("model") or "")[:120]}
        g.store.set_setting("backend_overrides", ov)
        return {"brains": brains, "backend_overrides": ov}


def _clean_detail(d: dict) -> dict:
    """Play-log details: flat-ish JSON, short strings, no nesting beyond 3 levels."""
    def c(v, depth=0):
        if isinstance(v, str):
            return v[:2000]
        if isinstance(v, (int, float, bool)) or v is None:
            return v
        if depth >= 3:
            return str(v)[:200]
        if isinstance(v, list):
            return [c(x, depth + 1) for x in v[:40]]
        if isinstance(v, dict):
            return {str(k)[:48]: c(x, depth + 1) for k, x in list(v.items())[:60]}
        return str(v)[:200]
    return {str(k)[:48]: c(v) for k, v in list(d.items())[:60] if k not in ("kind",)}


def setup_credentials() -> list:
    """GTNW's 'Fetch from core3 (SSH)': BatchMode, so it can never prompt. Values go straight to the Keychain."""
    stored = []
    for role in ("casting", "casting_owner"):
        out = subprocess.run(["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "kochj@192.168.1.5",
                              f"sudo bash /srv/games/repo/deploy/remote.sh getpw {role}"],
                             capture_output=True, text=True, timeout=30, stdin=subprocess.DEVNULL)
        pw = out.stdout.strip()
        if out.returncode != 0 or not re.match(r"^[\x21-\x7e]{8,256}$", pw):
            raise SystemExit(f"getpw {role} failed (exit {out.returncode})")
        if not keychain.put("nova-games-pg", pw, account=role):
            raise SystemExit(f"could not store {role} in the Keychain")
        stored.append(role)
    return stored


def make_server(host="127.0.0.1", port=PORT, store=None) -> ThreadingHTTPServer:
    handler = type("BoundHandler", (Handler,), {"game": Game(store or GameStore())})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.daemon_threads = True
    return srv


def smoke() -> int:
    """Start on a free port with a LOCAL store and the rules brain, hit every route, exit 0 if all pass."""
    import tempfile
    import urllib.request
    store = GameStore(root=Path(tempfile.mkdtemp()), remote=False)
    store.set_setting("brains", {r: {"backend": "rules"} for r in ROLES})
    srv = make_server(port=0, store=store)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(path, body=None):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"},
                                     method="POST" if body is not None else "GET")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()

    checks = [("/healthz", None), ("/", None), ("/api/edition", None), ("/api/settings", None),
              ("/api/getBookInfo", {"bookName": "Dune", "author": "Frank Herbert"}),
              ("/api/getActorFee", {"actorName": "Zendaya"}),
              ("/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                             "castDetails": "- The Lead: Zendaya", "movieBudget": 1e8}),
              ("/api/leaderboard", None), ("/api/stats", None)]
    ok = True
    for path, body in checks:
        try:
            status, _ = call(path, body)
            ok &= status == 200
            print(f"  {'ok ' if status == 200 else 'BAD'} {path}")
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"  BAD {path}: {e}")
    srv.shutdown()
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Casting Director — Nova edition server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--lan", action="store_true", help="listen on all interfaces (keys stay server-side)")
    ap.add_argument("--migrate", action="store_true")
    ap.add_argument("--setup-credentials", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    if a.smoke:
        return smoke()
    if a.setup_credentials:
        print("credentials stored:", setup_credentials())
    if a.migrate:
        print("migrations applied:", GameStore().migrate())
    if a.setup_credentials or a.migrate:
        return 0
    srv = make_server("0.0.0.0" if a.lan else a.host, a.port)
    print(f"Casting Director (Nova edition) on http://{srv.server_address[0]}:{srv.server_address[1]}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    sys.exit(main())
