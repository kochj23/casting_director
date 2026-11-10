"""AI backends for the Nova edition — GTNW's AIBackendManager, in Python.

Every brain (book analyst, talent agents, critics, advisors, ...) is a (backend, model) pair chosen in Settings.
Backends:
  nova-fleet   Nova inference router on .2:37475 (OpenAI-compatible; model may be a class: conversation, fast,
               reasoner, nova) — spreads calls over every Mac in the cluster
  ollama       any Ollama host (default 127.0.0.1:11434), models from /api/tags
  mlx          MLX server (OpenAI-compatible, default 127.0.0.1:5050)
  tinyllm      TinyLLM / TinyChat (OpenAI-compatible, default 127.0.0.1:8000)
  openwebui    OpenWebUI (default 127.0.0.1:8080/api, key in Keychain)
  openai       api.openai.com (key in Keychain)
  openrouter   openrouter.ai — frontier models (key in Keychain; falls back to Nova's key)
  gemini       Google Gemini, Austin's original backend (key in Keychain)
  anthropic    Anthropic Messages API (key in Keychain)
  claude-cli   the Claude Code CLI (`claude -p`), flat-rate, no API key
  nova         Nova herself, through Nova Gateway :18792 /api/chat
  auto         the first of ollama (this Mac), mlx, nova-fleet, openrouter that answers
  rules        no model: the deterministic game rules (always available; also the fallback for every brain)

Retries follow GTNW's Retry.swift: 3 attempts, 0.5 s then 1 s backoff; transport errors, 408, 429 and 5xx retry,
other 4xx fail at once. Model output is untrusted: it is parsed as JSON and coerced to the schema (types, required
keys, string and array caps) before the game sees it.
"""
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request

from . import keychain

BACKENDS = {
    "nova-fleet": {"kind": "openai", "base": "http://192.168.1.2:37475/v1", "model": "conversation",
                   "label": "Nova fleet (all Macs)", "local": True},
    "ollama": {"kind": "ollama", "base": "http://127.0.0.1:11434", "model": "qwen3:30b-a3b",
               "label": "Ollama", "local": True},
    "mlx": {"kind": "openai", "base": "http://127.0.0.1:5050/v1", "model": "Qwen/Qwen3-8B",
            "label": "MLX (Apple Silicon)", "local": True},
    "tinyllm": {"kind": "openai", "base": "http://127.0.0.1:8000/v1", "model": "default",
                "label": "TinyLLM / TinyChat", "local": True},
    "openwebui": {"kind": "openai", "base": "http://127.0.0.1:8080/api", "model": "qwen3:8b",
                  "label": "OpenWebUI", "local": True, "key": "casting-director-openwebui", "key_optional": True},
    "openai": {"kind": "openai", "base": "https://api.openai.com/v1", "model": "gpt-4.1-mini",
               "label": "OpenAI", "key": "casting-director-openai"},
    "openrouter": {"kind": "openai", "base": "https://openrouter.ai/api/v1", "model": "anthropic/claude-sonnet-4.5",
                   "label": "OpenRouter (frontier models)", "key": "casting-director-openrouter"},
    "gemini": {"kind": "gemini", "base": "https://generativelanguage.googleapis.com/v1beta",
               "model": "gemini-2.5-flash", "label": "Google Gemini", "key": "casting-director-gemini"},
    "anthropic": {"kind": "anthropic", "base": "https://api.anthropic.com/v1", "model": "claude-sonnet-4-5",
                  "label": "Anthropic", "key": "casting-director-anthropic"},
    "claude-cli": {"kind": "claude-cli", "model": "sonnet", "label": "Claude (Claude Code CLI)", "local": True},
    "nova": {"kind": "nova", "base": "http://127.0.0.1:18792", "model": "chat", "label": "Nova (Gateway)",
             "local": True},
    "auto": {"kind": "auto", "label": "Auto (best available)", "local": True},
    "rules": {"kind": "rules", "label": "Rules only (no AI)", "local": True},
}
AUTO_ORDER = ["ollama", "mlx", "nova-fleet", "openrouter"]   # this Mac first: the fleet class pool can land on CPU-only nodes
RETRY_STATUS = {408, 429}
MAX_STRING = 4000
MAX_ARRAY = 24


class AIError(Exception):
    """A backend could not produce usable output. The message never contains a key."""


class Transient(AIError):
    """Retryable: transport error, timeout, 408, 429, 5xx."""


# ---------------------------------------------------------------------------------------------------------------
# Stats: what the AI is doing (the Nova Cluster games screen reads /api/stats)
# ---------------------------------------------------------------------------------------------------------------

class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.calls = []          # last 200: {t, role, backend, model, ok, ms, tokens_in, tokens_out, error}
        self.inflight = {}       # id -> {role, backend, model, since}
        self._n = 0

    def start(self, role, backend, model):
        with self.lock:
            self._n += 1
            self.inflight[self._n] = {"role": role, "backend": backend, "model": model, "since": time.time()}
            return self._n

    def end(self, cid, ok, tokens_in=0, tokens_out=0, error=None):
        with self.lock:
            st = self.inflight.pop(cid, None)
            if not st:
                return None
            row = {"t": time.time(), "role": st["role"], "backend": st["backend"], "model": st["model"], "ok": ok,
                   "ms": int((time.time() - st["since"]) * 1000), "tokens_in": int(tokens_in or 0),
                   "tokens_out": int(tokens_out or 0), "error": (error or "")[:200] or None}
            self.calls.append(row)
            del self.calls[:-200]
            return row

    def snapshot(self, window=60):
        now = time.time()
        with self.lock:
            recent = [c for c in self.calls if now - c["t"] <= window]
            out_tok = sum(c["tokens_out"] for c in recent)
            busy_s = sum(c["ms"] for c in recent) / 1000.0
            return {"inflight": [dict(v, age_s=round(now - v["since"], 1)) for v in self.inflight.values()],
                    "last_calls": list(reversed(self.calls[-20:])),
                    "window_s": window, "calls_in_window": len(recent),
                    "tokens_out_per_s": round(out_tok / window, 2),
                    "decode_tok_s": round(out_tok / busy_s, 1) if busy_s else 0.0,
                    "errors_in_window": sum(1 for c in recent if not c["ok"])}


STATS = Stats()


# ---------------------------------------------------------------------------------------------------------------
# Schema: Austin's Gemini schema format (type OBJECT/ARRAY/STRING/NUMBER/BOOLEAN) is the single source
# ---------------------------------------------------------------------------------------------------------------

def to_json_schema(s: dict) -> dict:
    t = s.get("type", "STRING").upper()
    if t == "OBJECT":
        return {"type": "object", "properties": {k: to_json_schema(v) for k, v in s.get("properties", {}).items()},
                "required": list(s.get("required", []))}
    if t == "ARRAY":
        return {"type": "array", "items": to_json_schema(s.get("items", {"type": "STRING"}))}
    return {"type": {"NUMBER": "number", "INTEGER": "integer", "BOOLEAN": "boolean"}.get(t, "string")}


def coerce(schema: dict, value, path="$"):
    """Validate untrusted model output against the schema. Returns a clean copy or raises AIError."""
    t = schema.get("type", "STRING").upper()
    if t == "OBJECT":
        if not isinstance(value, dict):
            raise AIError(f"{path}: expected object")
        out = {}
        for k, sub in schema.get("properties", {}).items():
            if k in value and value[k] is not None:
                out[k] = coerce(sub, value[k], f"{path}.{k}")
        missing = [k for k in schema.get("required", []) if k not in out]
        if missing:
            raise AIError(f"{path}: missing {', '.join(missing)}")
        return out
    if t == "ARRAY":
        if not isinstance(value, list):
            raise AIError(f"{path}: expected array")
        return [coerce(schema.get("items", {"type": "STRING"}), v, f"{path}[{i}]")
                for i, v in enumerate(value[:MAX_ARRAY])]
    if t in ("NUMBER", "INTEGER"):
        if isinstance(value, str):
            value = re.sub(r"[$,\s]", "", value)
            try:
                value = float(value)
            except ValueError:
                raise AIError(f"{path}: expected number")
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise AIError(f"{path}: expected number")
        return int(value) if t == "INTEGER" else value
    if t == "BOOLEAN":
        if isinstance(value, bool):
            return value
        raise AIError(f"{path}: expected boolean")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = str(value)
    if not isinstance(value, str):
        raise AIError(f"{path}: expected string")
    return value.replace("\x00", "")[:MAX_STRING]


def extract_json(text: str):
    """The first JSON object in a model reply (drops <think> blocks and ``` fences)."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            c = text[i]
            if in_str:
                esc = (c == "\\") and not esc
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except ValueError:
                        break
        start = text.find("{", start + 1)
    raise AIError("reply had no JSON object")


# ---------------------------------------------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------------------------------------------

def _post(url, body, headers=None, timeout=120):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        if e.code in RETRY_STATUS or e.code >= 500:
            raise Transient(f"HTTP {e.code}")
        raise AIError(f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise Transient(f"unreachable ({type(e).__name__})")
    except ValueError:
        raise AIError("backend returned non-JSON")


def _get(url, headers=None, timeout=5):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as e:
        raise AIError(f"HTTP {e.code}")
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as e:
        raise Transient(f"unreachable ({type(e).__name__})")


def with_retry(fn, attempts=3, delays=(0.5, 1.0), sleep=time.sleep):
    for i in range(attempts):
        try:
            return fn()
        except Transient:
            if i == attempts - 1:
                raise
            sleep(delays[min(i, len(delays) - 1)])


# ---------------------------------------------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------------------------------------------

def _spec(backend, overrides=None):
    if backend not in BACKENDS:
        raise AIError(f"unknown backend {backend}")
    spec = dict(BACKENDS[backend])
    for k, v in (overrides or {}).get(backend, {}).items():
        if k in ("base", "model") and isinstance(v, str) and v:
            spec[k] = v
    return spec


def _key(spec):
    if not spec.get("key"):
        return None
    k = keychain.get(spec["key"])
    if not k and not spec.get("key_optional"):
        raise AIError(f"no API key for {spec['label']} (add it in Settings)")
    return k


def _call_openai(spec, model, system, user, schema, timeout):
    headers = {}
    key = _key(spec)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    if "openrouter" in spec["base"]:
        headers.update({"HTTP-Referer": "https://github.com/kochj23/casting_director", "X-Title": "Casting Director"})
    body = {"model": model, "temperature": 0.8,
            "messages": [{"role": "system", "content": system + "\n\nReply with ONE JSON object matching this "
                          "schema, nothing else:\n" + json.dumps(to_json_schema(schema))},
                         {"role": "user", "content": user}]}
    if spec["base"].startswith("https://api.openai.com") or "openrouter" in spec["base"]:
        body["response_format"] = {"type": "json_object"}
    r = _post(spec["base"].rstrip("/") + "/chat/completions", body, headers, timeout)
    try:
        text = r["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise AIError("unexpected reply shape")
    u = r.get("usage") or {}
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _call_ollama(spec, model, system, user, schema, timeout):
    body = {"model": model, "stream": False, "format": to_json_schema(schema), "keep_alive": "10m",
            "options": {"temperature": 0.8, "num_ctx": 16384},
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
    r = _post(spec["base"].rstrip("/") + "/api/chat", body, None, timeout)
    try:
        text = r["message"]["content"]
    except (KeyError, TypeError):
        raise AIError("unexpected reply shape")
    return text, r.get("prompt_eval_count", 0), r.get("eval_count", 0)


def _call_gemini(spec, model, system, user, schema, timeout):
    key = _key(spec)
    body = {"contents": [{"parts": [{"text": user}]}], "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema}}
    url = f"{spec['base']}/models/{model}:generateContent"
    r = _post(url, body, {"x-goog-api-key": key}, timeout)
    try:
        text = r["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise AIError("unexpected reply shape")
    u = r.get("usageMetadata") or {}
    return text, u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0)


def _call_anthropic(spec, model, system, user, schema, timeout):
    key = _key(spec)
    body = {"model": model, "max_tokens": 4096, "temperature": 0.8,
            "system": system + "\n\nReply with ONE JSON object matching this schema, nothing else:\n"
                      + json.dumps(to_json_schema(schema)),
            "messages": [{"role": "user", "content": user}]}
    r = _post(spec["base"] + "/messages", body, {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
    try:
        text = "".join(b.get("text", "") for b in r["content"] if b.get("type") == "text")
    except (KeyError, TypeError):
        raise AIError("unexpected reply shape")
    u = r.get("usage") or {}
    return text, u.get("input_tokens", 0), u.get("output_tokens", 0)


def _call_claude_cli(spec, model, system, user, schema, timeout):
    exe = shutil.which("claude") or "/opt/homebrew/bin/claude"
    prompt = (system + "\n\nReply with ONE JSON object matching this schema, nothing else:\n"
              + json.dumps(to_json_schema(schema)) + "\n\n" + user)
    try:
        out = subprocess.run([exe, "-p", "--model", model, "--output-format", "json"], input=prompt,
                             capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Transient("claude CLI timed out")
    except OSError:
        raise AIError("claude CLI not installed")
    if out.returncode != 0:
        raise Transient(f"claude CLI exit {out.returncode}")
    try:
        env = json.loads(out.stdout)
        u = env.get("usage") or {}
        return env.get("result", ""), u.get("input_tokens", 0), u.get("output_tokens", 0)
    except ValueError:
        return out.stdout, 0, 0


def _call_nova(spec, model, system, user, schema, timeout):
    msg = (system + "\n\nReply with ONE JSON object matching this schema, nothing else:\n"
           + json.dumps(to_json_schema(schema)) + "\n\n" + user)
    r = _post(spec["base"] + "/api/chat", {"message": msg, "session_id": "games:casting-director",
                                           "agent_id": model or "chat", "person": "casting-director"},
              None, timeout)
    if not r.get("ok"):
        raise Transient("Nova gateway error")
    return r.get("response", ""), 0, 0


CALLERS = {"openai": _call_openai, "ollama": _call_ollama, "gemini": _call_gemini, "anthropic": _call_anthropic,
           "claude-cli": _call_claude_cli, "nova": _call_nova}


def available(backend, overrides=None, timeout=3) -> bool:
    """Cheap reachability check (used by Auto and the Settings status dots)."""
    spec = _spec(backend, overrides)
    kind = spec["kind"]
    try:
        if kind == "rules":
            return True
        if kind == "auto":
            return True
        if spec.get("key") and not spec.get("key_optional"):
            return keychain.has(spec["key"])
        if kind == "ollama":
            _get(spec["base"] + "/api/tags", timeout=timeout)
        elif kind == "openai":
            if "37475" in spec["base"]:
                _get(spec["base"].replace("/v1", "") + "/health", timeout=timeout)
            else:
                _get(spec["base"].rstrip("/") + "/models", timeout=timeout)
        elif kind == "nova":
            _get(spec["base"] + "/health", timeout=timeout)
        elif kind == "claude-cli":
            return bool(shutil.which("claude") or os.path.exists("/opt/homebrew/bin/claude"))
        return True
    except AIError:
        return False


def list_models(backend, overrides=None) -> list:
    spec = _spec(backend, overrides)
    try:
        if spec["kind"] == "ollama":
            return sorted(m["name"] for m in _get(spec["base"] + "/api/tags").get("models", []))
        if backend == "nova-fleet":
            pool = _get(spec["base"].replace("/v1", "") + "/pool/status").get("backends", {})
            models = sorted({m for b in pool.values() if b.get("healthy") for m in b.get("models", [])
                             if "embed" not in m})
            return ["conversation", "fast", "reasoner", "nova"] + models
        if spec["kind"] == "openai" and not spec.get("key"):
            return sorted(m["id"] for m in _get(spec["base"].rstrip("/") + "/models").get("data", []))
        if backend == "claude-cli":
            return ["haiku", "sonnet", "opus"]
    except (AIError, KeyError, TypeError):
        pass
    return [spec.get("model")] if spec.get("model") else []


def complete_json(brain: dict, system: str, user: str, schema: dict, role="default", timeout=150,
                  overrides=None, sleep=time.sleep) -> tuple[dict, dict]:
    """Ask the brain's backend for JSON matching `schema`. Returns (data, meta).
    meta = {backend, model, tokens_in, tokens_out, ms}. Raises AIError when no backend could answer;
    callers then use the rules fallback (a turn never blocks on AI)."""
    backend = (brain or {}).get("backend") or "auto"
    if backend == "rules":
        raise AIError("rules brain")
    # The chosen backend first; if it fails, the Auto order (a turn never stalls on one dead backend), then rules.
    fallbacks = [b for b in AUTO_ORDER if b != backend and available(b, overrides)]
    order = ([] if backend == "auto" else [backend]) + fallbacks
    if not order:
        raise AIError("no backend available")
    last = None
    for b in order:
        spec = _spec(b, overrides)
        model = (brain or {}).get("model") if b == backend else None
        model = model or spec.get("model")
        cid = STATS.start(role, b, model)
        try:
            text, tin, tout = with_retry(lambda: CALLERS[spec["kind"]](spec, model, system, user, schema, timeout),
                                         sleep=sleep)
            data = coerce(schema, extract_json(text))
            row = STATS.end(cid, True, tin, tout)
            return data, {"backend": b, "model": model, "tokens_in": tin, "tokens_out": tout,
                          "ms": row["ms"] if row else 0}
        except AIError as e:
            STATS.end(cid, False, error=str(e))
            last = e
    raise last or AIError("no backend answered")
