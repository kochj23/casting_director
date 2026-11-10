"""Durable game state: the Nova Games DB (Postgres 17 on core3, schema `casting`) — GTNW's GameStoreService.

Local first, then queue: every write lands in the local cache and the pending queue at once, so play never waits on
the network; a background sync pass pushes the queue and the badge shows DB ONLINE / SYNCING / OFFLINE · n / LOCAL.
TLS verify-full against the bundled games-pg CA, SCRAM, passwords from the Keychain (nova-games-pg / casting).
Migrations run as casting_owner and are recorded in casting.schema_migrations; the app itself is DML-only.

Play history (schema `play`) is written through the same queue as role `casting`, game='casting', client='mac', so
Nova's game reporter can write a column about every finished production.
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import keychain

HERE = Path(__file__).resolve().parent
CA = HERE / "games-pg-ca.crt"
DB = {"host": "192.168.1.5", "port": 5433, "dbname": "games", "user": "casting", "owner": "casting_owner"}
MAX_PAYLOAD = 256 * 1024
MAX_EVENT = 4096
MAX_SUMMARY = 65536
RECENT_LOCAL = 50

MIGRATIONS = [
    (1, """
CREATE TABLE IF NOT EXISTS casting.schema_migrations (version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS casting.movies (
  id uuid PRIMARY KEY, player text NOT NULL CHECK (char_length(player) BETWEEN 1 AND 64),
  created_at timestamptz NOT NULL DEFAULT now(), book text NOT NULL CHECK (char_length(book) <= 300),
  author text CHECK (char_length(author) <= 200), studio text CHECK (char_length(studio) <= 120),
  score double precision CHECK (score IS NULL OR score BETWEEN 0 AND 100),
  box_office double precision CHECK (box_office IS NULL OR box_office BETWEEN 0 AND 1e13),
  data jsonb NOT NULL CHECK (jsonb_typeof(data) = 'object' AND octet_length(data::text) <= 262144));
CREATE INDEX IF NOT EXISTS movies_created_idx ON casting.movies (created_at DESC);
CREATE INDEX IF NOT EXISTS movies_score_idx ON casting.movies (score DESC NULLS LAST);
CREATE TABLE IF NOT EXISTS casting.book_cache (key text PRIMARY KEY CHECK (char_length(key) <= 600),
  data jsonb NOT NULL, source text, cached_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS casting.actor_cache (key text PRIMARY KEY CHECK (char_length(key) <= 200),
  data jsonb NOT NULL, source text, cached_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS casting.achievements (player text NOT NULL, key text NOT NULL,
  unlocked_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (player, key));
CREATE TABLE IF NOT EXISTS casting.saves (player text NOT NULL, slot text NOT NULL CHECK (slot ~ '^[a-z0-9_-]{1,32}$'),
  label text, data jsonb NOT NULL CHECK (octet_length(data::text) <= 262144),
  updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (player, slot));
CREATE TABLE IF NOT EXISTS casting.settings (key text PRIMARY KEY CHECK (char_length(key) <= 64),
  value jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS casting.ai_calls (id bigserial PRIMARY KEY, t timestamptz NOT NULL DEFAULT now(),
  role text, backend text, model text, ok boolean, ms integer, tokens_in integer, tokens_out integer, error text);
CREATE INDEX IF NOT EXISTS ai_calls_t_idx ON casting.ai_calls (t DESC);
"""),
    # v2: the Nova Cluster Games screen reads AI calls and movies with the platform's read-only play_reader.
    (2, """
GRANT USAGE ON SCHEMA casting TO play_reader;
GRANT SELECT ON casting.ai_calls, casting.movies TO play_reader;
"""),
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(v):
    return json.dumps(v, separators=(",", ":"), default=str)


class GameStore:
    """Local cache + pending queue + Postgres sync. Thread-safe. `remote=None` means LOCAL (tests, no DB)."""

    def __init__(self, root: Path | None = None, remote: bool = True, connect=None):
        self.root = Path(root or Path.home() / "Library/Application Support/CastingDirector")
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.remote = remote
        self._connect = connect or self._pg_connect
        self.conn = None
        self.state = "LOCAL" if not remote else "OFFLINE"
        self.last_error = None
        self.backoff_until = 0.0
        self.local = self._load("cache.json", {"movies": [], "book_cache": {}, "actor_cache": {}, "settings": {},
                                              "achievements": {}, "saves": {}})
        self.pending = self._load("pending.json", [])
        self._sync_lock = threading.Lock()

    # -- local files ------------------------------------------------------------------------------------------
    def _load(self, name, default):
        try:
            return json.loads((self.root / name).read_text())
        except (OSError, ValueError):
            return default

    def _save(self, name, value):
        tmp = self.root / (name + ".tmp")
        tmp.write_text(_json(value))
        os.chmod(tmp, 0o600)
        tmp.replace(self.root / name)

    def _persist(self):
        self._save("cache.json", self.local)
        self._save("pending.json", self.pending)

    # -- connection -------------------------------------------------------------------------------------------
    def _pg_connect(self, user):
        import psycopg2
        pw = keychain.get("nova-games-pg", user)
        if not pw:
            raise RuntimeError(f"no Games DB password for {user} in the Keychain (run --setup-credentials)")
        return psycopg2.connect(host=DB["host"], port=DB["port"], dbname=DB["dbname"], user=user, password=pw,
                                sslmode="verify-full", sslrootcert=str(CA), connect_timeout=6,
                                application_name="casting-director")

    def _db(self):
        if not self.remote:
            return None
        if self.conn is not None and not self.conn.closed:
            return self.conn
        if time.time() < self.backoff_until:
            return None
        try:
            self.conn = self._connect(DB["user"])
            self.conn.autocommit = False
            return self.conn
        except Exception as e:     # noqa: BLE001 — any connect failure means offline
            self.last_error = str(e)[:200]
            self.state = "OFFLINE"
            self.backoff_until = time.time() + 30
            return None

    def migrate(self) -> list:
        """Apply pending migrations as casting_owner. Returns the versions applied."""
        conn = self._connect(DB["owner"])
        applied = []
        try:
            cur = conn.cursor()
            cur.execute("CREATE TABLE IF NOT EXISTS casting.schema_migrations "
                        "(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
            cur.execute("SELECT version FROM casting.schema_migrations")
            have = {r[0] for r in cur.fetchall()}
            for v, sql in MIGRATIONS:
                if v in have:
                    continue
                cur.execute(sql)
                cur.execute("INSERT INTO casting.schema_migrations (version) VALUES (%s)", (v,))
                applied.append(v)
            conn.commit()
        finally:
            conn.close()
        return applied

    # -- queue ------------------------------------------------------------------------------------------------
    def _enqueue(self, op, **args):
        with self.lock:
            self.pending.append({"op": op, "args": args, "at": _now()})
            del self.pending[:-5000]
            self._persist()
        threading.Thread(target=self.sync, daemon=True).start()

    def badge(self) -> str:
        if not self.remote:
            return "LOCAL"
        n = len(self.pending)
        if self.state == "ONLINE":
            return "SYNCING" if n else "DB ONLINE"
        return f"OFFLINE · {n}"

    def sync(self) -> bool:
        """Push the queue. Concurrent callers share one pass. A row the DB rejects is dropped, never retried forever."""
        if not self.remote or not self._sync_lock.acquire(blocking=False):
            return False
        try:
            conn = self._db()
            if conn is None:
                return False
            while True:
                with self.lock:
                    if not self.pending:
                        break
                    item = self.pending[0]
                try:
                    self._apply(conn.cursor(), item["op"], item["args"])
                    conn.commit()
                except Exception as e:  # noqa: BLE001
                    import psycopg2
                    try:
                        conn.rollback()
                    except Exception:   # noqa: BLE001
                        pass
                    if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
                        self.state, self.last_error, self.conn = "OFFLINE", str(e)[:200], None
                        self.backoff_until = time.time() + 30
                        return False
                    self.last_error = f"dropped {item['op']}: {str(e)[:160]}"
                with self.lock:
                    if self.pending and self.pending[0] is item:
                        self.pending.pop(0)
                        self._persist()
            self.state = "ONLINE"
            return True
        finally:
            self._sync_lock.release()

    def _apply(self, cur, op, a):
        if op == "movie":
            d = a["data"]
            cur.execute("INSERT INTO casting.movies (id, player, created_at, book, author, studio, score, box_office, "
                        "data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING",
                        (a["id"], a["player"], d.get("createdAt"), str(d.get("bookName"))[:300],
                         str(d.get("author") or "")[:200], str(d.get("studio") or "")[:120],
                         d.get("overallGameScore"), d.get("boxOffice"), _json(d)))
        elif op in ("book_cache", "actor_cache"):
            cur.execute(f"INSERT INTO casting.{op} (key, data, source) VALUES (%s,%s,%s) ON CONFLICT (key) DO UPDATE "
                        "SET data = EXCLUDED.data, source = EXCLUDED.source, cached_at = now()",
                        (a["key"], _json(a["data"]), a.get("source")))
        elif op == "achievement":
            cur.execute("INSERT INTO casting.achievements (player, key) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                        (a["player"], a["key"]))
        elif op == "save":
            cur.execute("INSERT INTO casting.saves (player, slot, label, data) VALUES (%s,%s,%s,%s) "
                        "ON CONFLICT (player, slot) DO UPDATE SET label = EXCLUDED.label, data = EXCLUDED.data, "
                        "updated_at = now()", (a["player"], a["slot"], a.get("label"), _json(a["data"])))
        elif op == "setting":
            cur.execute("INSERT INTO casting.settings (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE "
                        "SET value = EXCLUDED.value, updated_at = now()", (a["key"], _json(a["value"])))
        elif op == "ai_call":
            r = a["row"]
            cur.execute("INSERT INTO casting.ai_calls (t, role, backend, model, ok, ms, tokens_in, tokens_out, error) "
                        "VALUES (to_timestamp(%s),%s,%s,%s,%s,%s,%s,%s,%s)",
                        (r["t"], r["role"], r["backend"], r["model"], r["ok"], r["ms"], r["tokens_in"],
                         r["tokens_out"], r["error"]))
        elif op == "play_session":
            cur.execute("INSERT INTO play.sessions (id, game, client, player, started_at, last_seen_at, ended_at, "
                        "outcome, score, actions, summary) VALUES (%s,'casting','mac',%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT (id) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at, "
                        "ended_at = EXCLUDED.ended_at, outcome = EXCLUDED.outcome, score = EXCLUDED.score, "
                        "actions = EXCLUDED.actions, summary = EXCLUDED.summary",
                        (a["id"], a["player"], a["started_at"], a["last_seen_at"], a.get("ended_at"), a.get("outcome"),
                         a.get("score"), a.get("actions", 0), _json(a.get("summary") or {})))
        elif op == "play_event":
            cur.execute("INSERT INTO play.events (session_id, seq, ts, kind, detail) VALUES (%s,%s,%s,%s,%s) "
                        "ON CONFLICT DO NOTHING", (a["session_id"], a["seq"], a["ts"], a["kind"], _json(a["detail"])))
        else:
            raise ValueError(f"unknown op {op}")

    # -- reads (DB first, local cache when offline) -----------------------------------------------------------
    def _query(self, sql, args=()):
        conn = self._db()
        if conn is None:
            return None
        try:
            cur = conn.cursor()
            cur.execute(sql, args)
            rows = cur.fetchall()
            conn.commit()
            self.state = "ONLINE"
            return rows
        except Exception as e:  # noqa: BLE001
            try:
                conn.rollback()
            except Exception:   # noqa: BLE001
                pass
            self.last_error, self.conn, self.state = str(e)[:200], None, "OFFLINE"
            return None

    # -- public API -------------------------------------------------------------------------------------------
    def save_movie(self, player: str, data: dict) -> str:
        if len(_json(data)) > MAX_PAYLOAD:
            raise ValueError("movie payload too large")
        mid = str(uuid.uuid4())
        data = dict(data, id=mid, createdAt=data.get("createdAt") or _now())
        with self.lock:
            self.local["movies"].insert(0, data)
            del self.local["movies"][RECENT_LOCAL:]
        self._enqueue("movie", id=mid, player=player, data=data)
        return mid

    def recent_movies(self, limit=10) -> list:
        rows = self._query("SELECT data FROM casting.movies ORDER BY created_at DESC LIMIT %s", (int(limit),))
        if rows is not None:
            return [r[0] for r in rows]
        return self.local["movies"][:limit]

    def movie(self, mid: str):
        try:
            uuid.UUID(str(mid))
        except ValueError:
            return None
        rows = self._query("SELECT data FROM casting.movies WHERE id = %s", (mid,))
        if rows:
            return rows[0][0]
        return next((m for m in self.local["movies"] if m.get("id") == mid), None)

    def leaderboard(self, limit=20) -> list:
        rows = self._query("SELECT data->>'id', book, studio, score, box_office, player, created_at FROM casting.movies "
                           "WHERE score IS NOT NULL ORDER BY score DESC, box_office DESC LIMIT %s", (int(limit),))
        if rows is not None:
            return [{"id": r[0], "book": r[1], "studio": r[2], "score": r[3], "boxOffice": r[4], "player": r[5],
                     "createdAt": r[6].isoformat()} for r in rows]
        ms = sorted((m for m in self.local["movies"] if m.get("overallGameScore") is not None),
                    key=lambda m: -m["overallGameScore"])[:limit]
        return [{"id": m["id"], "book": m.get("bookName"), "studio": m.get("studio"), "score": m["overallGameScore"],
                 "boxOffice": m.get("boxOffice"), "player": m.get("directorId"), "createdAt": m.get("createdAt")}
                for m in ms]

    def cache_get(self, kind: str, key: str):
        assert kind in ("book_cache", "actor_cache")
        rows = self._query(f"SELECT data FROM casting.{kind} WHERE key = %s", (key,))
        if rows:
            return rows[0][0]
        return self.local[kind].get(key)

    def cache_put(self, kind: str, key: str, data: dict, source: str):
        assert kind in ("book_cache", "actor_cache")
        with self.lock:
            self.local[kind][key] = data
        self._enqueue(kind, key=key, data=data, source=source)

    def setting(self, key: str, default=None):
        if key in self.local["settings"]:
            return self.local["settings"][key]
        rows = self._query("SELECT value FROM casting.settings WHERE key = %s", (key,))
        if rows:
            with self.lock:
                self.local["settings"][key] = rows[0][0]
            return rows[0][0]
        return default

    def set_setting(self, key: str, value):
        with self.lock:
            self.local["settings"][key] = value
        self._enqueue("setting", key=key, value=value)

    def unlock(self, player: str, key: str) -> bool:
        with self.lock:
            have = self.local["achievements"].setdefault(player, [])
            if key in have:
                return False
            have.append(key)
        self._enqueue("achievement", player=player, key=key)
        return True

    def achievements(self, player: str) -> list:
        rows = self._query("SELECT key FROM casting.achievements WHERE player = %s", (player,))
        if rows is not None:
            keys = sorted({r[0] for r in rows} | set(self.local["achievements"].get(player, [])))
            return keys
        return sorted(self.local["achievements"].get(player, []))

    def save_slot(self, player, slot, label, data):
        with self.lock:
            self.local["saves"].setdefault(player, {})[slot] = {"label": label, "data": data, "updated_at": _now()}
        self._enqueue("save", player=player, slot=slot, label=label, data=data)

    def load_slot(self, player, slot):
        rows = self._query("SELECT data FROM casting.saves WHERE player = %s AND slot = %s", (player, slot))
        if rows:
            return rows[0][0]
        return (self.local["saves"].get(player, {}).get(slot) or {}).get("data")

    def record_ai_call(self, row: dict):
        if row:
            self._enqueue("ai_call", row=row)

    def status(self) -> dict:
        return {"badge": self.badge(), "pending": len(self.pending), "state": self.state,
                "last_error": self.last_error, "host": f"{DB['host']}:{DB['port']}", "schema": "casting"}


class PlayLog:
    """One play session per production (book → release), written through the store's queue.
    Events are capped at 4 KB (long text shortened, never dropped); the summary at 64 KB."""

    def __init__(self, store: GameStore, player: str):
        self.store, self.player = store, player
        self.id = None
        self.seq = 0
        self.started = None
        self.actions = 0
        self.summary = {}

    def start(self, **summary):
        self.id, self.seq, self.actions = str(uuid.uuid4()), 0, 0
        self.started = _now()
        self.summary = dict(summary)
        self._upsert()
        self.event("game_start", **summary)
        return self.id

    @staticmethod
    def _cap(detail: dict) -> dict:
        d = dict(detail)
        while len(_json(d)) > MAX_EVENT:
            k = max((k for k in d if isinstance(d[k], str)), key=lambda k: len(d[k]), default=None)
            if k is None or len(d[k]) < 40:
                break
            d[k] = d[k][: len(d[k]) // 2] + "…"
        return d

    def event(self, kind: str, **detail):
        if not self.id:
            return
        self.seq += 1
        self.actions += 1
        self.store._enqueue("play_event", session_id=self.id, seq=self.seq, ts=_now(), kind=kind,
                            detail=self._cap(detail))
        self._upsert()

    def update(self, **summary):
        self.summary.update(summary)
        self._upsert()

    def end(self, outcome: str, score=None, **summary):
        if not self.id:
            return
        self.summary.update(summary)
        self.event("game_over", outcome=outcome, score=score)
        self._upsert(ended=True, outcome=outcome, score=score)
        self.id = None

    def _upsert(self, ended=False, outcome=None, score=None):
        s = self.summary
        while len(_json(s)) > MAX_SUMMARY and s:
            s = dict(s)
            s.pop(max(s, key=lambda k: len(_json(s[k]))))
        self.store._enqueue("play_session", id=self.id, player=self.player, started_at=self.started,
                            last_seen_at=_now(), ended_at=_now() if ended else None, outcome=outcome, score=score,
                            actions=self.actions, summary=s)
