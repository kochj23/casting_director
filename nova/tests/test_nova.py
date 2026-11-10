"""Casting Director — Nova edition: unit, functional, security, integration, performance and retry tests.
Offline: a LOCAL store and the rules brain (conftest.py); model replies are faked where a backend is needed."""
import json
import time
import urllib.error
import urllib.request

import pytest

from nova import ai, prompts, rules
from nova.server import clamp_book, clamp_results
from nova.store import GameStore, PlayLog


def call(base, path, body=None, method=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Content-Type": "application/json"} if data is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=h, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read(), dict(e.headers)


# ---------------------------------------------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.unit
def test_prompts_are_austins_verbatim():
    assert "movie production database and expert Hollywood analyst" in prompts.BOOK_SYSTEM
    assert "Siskel" in prompts.RESULTS_SYSTEM.upper() or "SISKEL" in prompts.RESULTS_SYSTEM
    assert len(prompts.RESULTS_SCHEMA["required"]) == 18
    assert len(prompts.USERNAMES_90S) > 90


@pytest.mark.unit
def test_schema_converts_to_json_schema():
    js = ai.to_json_schema(prompts.FEE_SCHEMA)
    assert js == {"type": "object", "properties": {"fee": {"type": "number"}, "popularity": {"type": "string"}},
                  "required": ["fee", "popularity"]}


@pytest.mark.unit
def test_extract_json_handles_thinking_and_fences():
    assert ai.extract_json('<think>hmm {"no": 1}</think>```json\n{"fee": 5}\n```') == {"fee": 5}
    assert ai.extract_json('Sure! Here it is: {"a": {"b": "}"}} trailing') == {"a": {"b": "}"}}
    with pytest.raises(ai.AIError):
        ai.extract_json("no json here")


@pytest.mark.unit
def test_rules_are_deterministic_per_name():
    assert rules.actor_fee("Zendaya") == rules.actor_fee("  zendaya ")
    assert rules.book_info("Dune", "Frank Herbert") == rules.book_info("Dune", "Frank Herbert")
    assert rules.money("$28,200,000") == 28_200_000 and rules.money(5) == 5 and rules.money("n/a", 7) == 7


@pytest.mark.unit
def test_descriptor_bands_match_austins_table():
    assert rules.descriptor(99) == "Once-in-a-Generation"
    assert rules.descriptor(72) == "Solid Hit"
    assert rules.descriptor(3) == "Legendary Catastrophe"


# ---------------------------------------------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.security
def test_hostile_model_output_is_coerced_or_refused():
    with pytest.raises(ai.AIError):
        ai.coerce(prompts.FEE_SCHEMA, {"fee": "lots", "popularity": "A-List"})
    with pytest.raises(ai.AIError):
        ai.coerce(prompts.FEE_SCHEMA, {"fee": float("nan"), "popularity": "x"})
    out = ai.coerce(prompts.FEE_SCHEMA, {"fee": "$1,000", "popularity": "x" * 10000, "__proto__": 1, "evil": 2})
    assert out == {"fee": 1000.0, "popularity": "x" * ai.MAX_STRING}


@pytest.mark.security
def test_model_numbers_are_clamped_to_the_game():
    b = clamp_book(dict(rules.book_info("x", "y"), movieBudget=1e15, castingBudget=-5, characters=[]))
    assert b["movieBudget"] == 300e6 and b["castingBudget"] == 30e6 and b["characters"]
    r = clamp_results(dict(rules.movie_results({"bookName": "x"}), overallGameScore=500, imdbScore=-3,
                           siskelVerdict="<script>", finalVerdict="yes"))
    assert r["overallGameScore"] == 100 and r["imdbScore"] == 0
    assert r["siskelVerdict"] == "thumbs_down" and r["finalVerdict"] == "mixed"


@pytest.mark.security
def test_static_files_cannot_escape_the_game(server):
    base, _ = server
    for path in ["/../nova/server.py", "/nova/server.py", "/js/../../.git/config", "/functions/index.js",
                 "/js/services/apiService.test.js", "/README.md", "/%2e%2e/etc/passwd"]:
        assert call(base, path)[0] == 404, path


@pytest.mark.security
def test_cross_origin_writes_are_refused(server):
    base, _ = server
    st, _, _ = call(base, "/api/getActorFee", {"actorName": "x"}, headers={"Origin": "https://evil.example"})
    assert st == 403
    st, _, _ = call(base, "/api/keys", {"backend": "openai", "key": "sk-x"}, headers={"Origin": "http://evil"})
    assert st == 403


@pytest.mark.security
def test_bodies_are_bounded_and_typed(server):
    base, _ = server
    assert call(base, "/api/getActorFee", raw=b"x" * (300 * 1024))[0] == 413
    assert call(base, "/api/getActorFee", raw=b'{"actorName":"x"}',
                headers={"Content-Type": "text/plain"})[0] == 415
    assert call(base, "/api/getActorFee", raw=b"[1,2]")[0] == 400
    assert call(base, "/api/getActorFee", {"actorName": "x" * 500})[0] == 400


@pytest.mark.security
def test_security_headers_and_no_cors(server):
    base, _ = server
    _, _, h = call(base, "/")
    assert "default-src 'self'" in h["Content-Security-Policy"]
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"
    assert not any(k.lower().startswith("access-control") for k in h)


@pytest.mark.security
def test_settings_reject_bad_backend_urls(server):
    base, _ = server
    st, body, _ = call(base, "/api/settings", {"backend_overrides": {"ollama": {"base": "file:///etc/passwd"}}},
                       method="PUT")
    assert st == 400


@pytest.mark.security
def test_no_secrets_in_source():
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[2]
    for f in list((root / "nova").rglob("*.py")) + list((root / "js").rglob("*.js")):
        if f.name == "firebase.js":       # Austin's Firebase web config: a public client id, not a secret
            continue
        text = f.read_text(errors="ignore")
        assert not re.search(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{30,}|sk-or-v1-[0-9a-f]{20,})", text), f


@pytest.mark.security
def test_server_binds_loopback_by_default():
    from nova import server
    srv = server.make_server(port=0, store=GameStore(root=__import__("tempfile").mkdtemp(), remote=False))
    assert srv.server_address[0] == "127.0.0.1"
    srv.server_close()


# ---------------------------------------------------------------------------------------------------------------
# Functional
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.functional
def test_austins_three_calls_answer_in_his_shapes(server):
    base, _ = server
    st, b, _ = call(base, "/api/getBookInfo", {"bookName": "Dune", "author": "Frank Herbert"})
    book = json.loads(b)
    assert st == 200 and set(prompts.BOOK_SCHEMA["required"]) <= set(book) and book["_source"] == "rules"
    st, b, _ = call(base, "/api/getActorFee", {"actorName": "Zendaya"})
    assert st == 200 and {"fee", "popularity"} <= set(json.loads(b))
    st, b, _ = call(base, "/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                                        "castDetails": "The Lead: Zendaya", "movieBudget": "$100,000,000"})
    res = json.loads(b)
    assert st == 200 and set(prompts.RESULTS_SCHEMA["required"]) <= set(res)
    assert res["imdbUsername"] in prompts.USERNAMES_90S


@pytest.mark.functional
def test_saved_movies_show_in_recent_and_leaderboard(server):
    base, _ = server
    for score in (40, 90):
        call(base, "/api/movies", {"bookName": f"Book {score}", "author": "A", "overallGameScore": score,
                                   "boxOffice": 1e6, "directorId": "default"})
    recent = json.loads(call(base, "/api/movies/recent")[1])["movies"]
    assert [m["bookName"] for m in recent[:2]] == ["Book 90", "Book 40"]
    top = json.loads(call(base, "/api/leaderboard")[1])["entries"]
    assert top[0]["score"] == 90
    mid = recent[0]["id"]
    assert json.loads(call(base, f"/api/movies/{mid}")[1])["bookName"] == "Book 90"
    assert call(base, "/api/movies/not-a-uuid")[0] == 404


@pytest.mark.functional
def test_a_production_is_logged_as_one_play_session(server):
    base, srv = server
    game = srv.RequestHandlerClass.game
    call(base, "/api/getBookInfo", {"bookName": "Dune", "author": "Frank Herbert"})
    sid = game.play.id
    assert sid
    call(base, "/api/getActorFee", {"actorName": "Zendaya"})
    call(base, "/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                             "castDetails": "Paul: Zendaya"})
    assert game.play.id is None
    kinds = [o["args"]["kind"] for o in game.store.pending if o["op"] == "play_event"
             and o["args"]["session_id"] == sid]
    assert kinds[0] == "game_start" and {"greenlit", "quote", "released"} <= set(kinds)


@pytest.mark.functional
def test_brains_are_chosen_per_role(server):
    base, _ = server
    st, b, _ = call(base, "/api/settings", {"brains": {"critics": {"backend": "ollama", "model": "qwen3:8b"},
                                                       "nobody": {"backend": "openai"}}}, method="PUT")
    brains = json.loads(b)["brains"]
    assert st == 200 and brains["critics"] == {"backend": "ollama", "model": "qwen3:8b"} and "nobody" not in brains
    s = json.loads(call(base, "/api/settings")[1])
    assert "claude-cli" in s["backends"] and s["roles"]["analyst"]


# ---------------------------------------------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, log):
        self.log = log

    def execute(self, sql, args=()):
        self.log.append((sql.split()[0] + " " + sql.split()[2], args))

    def fetchall(self):
        return []


class FakeConn:
    closed = False

    def __init__(self):
        self.log, self.autocommit = [], False

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.mark.integration
def test_queue_syncs_movies_and_play_history_to_the_db(tmp_path):
    conn = FakeConn()
    st = GameStore(root=tmp_path, remote=True, connect=lambda user: conn)
    st.save_movie("default", {"bookName": "Dune", "overallGameScore": 70, "boxOffice": 5e8})
    play = PlayLog(st, "default")
    play.start(book="Dune")
    play.event("cast", character="Paul", actor="Zendaya")
    play.end("released", score=70)
    deadline = time.time() + 5
    while st.pending and time.time() < deadline:
        st.sync()
        time.sleep(0.05)
    assert not st.pending and st.badge() == "DB ONLINE"
    tables = {sql for sql, _ in conn.log}
    assert {"INSERT casting.movies", "INSERT play.sessions", "INSERT play.events"} <= tables
    kinds = [a[3] for sql, a in conn.log if sql == "INSERT play.events"]
    assert kinds[0] == "game_start" and "cast" in kinds and kinds[-1] == "game_over"


@pytest.mark.integration
def test_offline_writes_wait_in_the_queue(tmp_path):
    def down(user):
        raise OSError("no route to core3")
    st = GameStore(root=tmp_path, remote=True, connect=down)
    st.save_movie("default", {"bookName": "Dune"})
    st.sync()
    assert st.badge().startswith("OFFLINE") and len(st.pending) == 1
    again = GameStore(root=tmp_path, remote=True, connect=down)
    assert len(again.pending) == 1 and again.recent_movies()[0]["bookName"] == "Dune"


@pytest.mark.integration
def test_ai_path_with_a_faked_ollama(monkeypatch):
    def fake_post(url, body, headers=None, timeout=120):
        assert url.endswith("/api/chat") and body["format"]["required"] == ["fee", "popularity"]
        return {"message": {"content": '{"fee": 2500000, "popularity": "Star"}'}, "prompt_eval_count": 40,
                "eval_count": 12}
    monkeypatch.setattr(ai, "_post", fake_post)
    data, meta = ai.complete_json({"backend": "ollama", "model": "m"}, "s", "u", prompts.FEE_SCHEMA, role="agent")
    assert data == {"fee": 2500000, "popularity": "Star"} and meta["tokens_out"] == 12
    snap = ai.STATS.snapshot()
    assert snap["last_calls"][0]["backend"] == "ollama" and snap["last_calls"][0]["ok"]


@pytest.mark.integration
def test_a_dead_backend_falls_back_to_the_next(monkeypatch):
    monkeypatch.setattr(ai, "AUTO_ORDER", ["ollama"])
    monkeypatch.setattr(ai, "available", lambda b, o=None, timeout=3: True)
    seen = []

    def fake_post(url, body, headers=None, timeout=120):
        seen.append(url)
        if "openai.com" in url:
            raise ai.AIError("HTTP 401")
        return {"message": {"content": '{"fee": 1, "popularity": "x"}'}}
    monkeypatch.setattr(ai, "_post", fake_post)
    monkeypatch.setattr(ai.keychain, "get", lambda *a, **k: "k")
    data, meta = ai.complete_json({"backend": "openai"}, "s", "u", prompts.FEE_SCHEMA, sleep=lambda s: None)
    assert meta["backend"] == "ollama" and len(seen) == 2


# ---------------------------------------------------------------------------------------------------------------
# Retry (GTNW's Retry.swift policy)
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.retry
def test_transient_errors_retry_three_times_with_backoff():
    calls, sleeps = [], []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ai.Transient("HTTP 503")
        return "ok"
    assert ai.with_retry(flaky, sleep=sleeps.append) == "ok"
    assert len(calls) == 3 and sleeps == [0.5, 1.0]


@pytest.mark.retry
def test_client_errors_do_not_retry():
    calls = []

    def bad():
        calls.append(1)
        raise ai.AIError("HTTP 401")
    with pytest.raises(ai.AIError):
        ai.with_retry(bad, sleep=lambda s: None)
    assert len(calls) == 1


@pytest.mark.retry
def test_http_status_classification(monkeypatch):
    def raise_code(code):
        def f(req, timeout=0):
            raise urllib.error.HTTPError("u", code, "x", {}, None)
        return f
    for code, kind in [(429, ai.Transient), (503, ai.Transient), (408, ai.Transient), (400, ai.AIError)]:
        monkeypatch.setattr(urllib.request, "urlopen", raise_code(code))
        with pytest.raises(kind) as e:
            ai._post("http://x", {})
        assert (type(e.value) is ai.Transient) == (kind is ai.Transient), code


# ---------------------------------------------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------------------------------------------

@pytest.mark.performance
def test_rules_answer_a_whole_production_fast(server):
    base, _ = server
    t = time.perf_counter()
    for i in range(25):
        call(base, "/api/getActorFee", {"actorName": f"Actor {i}"})
    call(base, "/api/generateMovieResults", {"bookName": "Dune", "bookPopularity": "Bestseller",
                                             "castDetails": "\n".join(f"R{i}: A{i}" for i in range(8))})
    assert time.perf_counter() - t < 3.0


@pytest.mark.performance
def test_queue_and_events_stay_bounded(tmp_path):
    st = GameStore(root=tmp_path, remote=False)
    st.remote = True                      # queue but never connect
    st._db = lambda: None
    for i in range(5200):
        st.pending.append({"op": "setting", "args": {"key": "k", "value": i}, "at": ""})
    st._enqueue("setting", key="k", value=-1)
    assert len(st.pending) == 5000
    big = PlayLog._cap({"text": "x" * 20000})
    assert len(json.dumps(big)) <= 4096
