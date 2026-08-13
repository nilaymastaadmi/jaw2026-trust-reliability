"""The provided LLM endpoint -- the only generative model this pipeline may use.

An OpenAI-compatible vLLM server, exported to us as LLM_BASE_URL, serving
qwen3.6-35b-a3b-nvfp4 with a 131,072-token context.  No API key is enforced.

Written against stdlib urllib on purpose: no `openai`, no `requests`, nothing
that could try to reach a package index or a model host once the run has
started.  The rules say no network at run time except this endpoint, and the
cheapest way to keep that promise is to have nothing else installed that could
break it.

THE THREE DOCUMENTED TRAPS, all handled here so no caller has to remember them:

  1. max_tokens must be generous (>=2048).  This is a reasoning model that
     spends budget on a hidden trace before answering.  Too small and you get
     finish_reason "length" with content None, which reads like an outage and
     is not one.  We floor it at 2048 and retry once at double on a length cut.
  2. The trace field is `reasoning`, NOT `reasoning_content`.  Reading the wrong
     one silently gives you None.  We read `content` for the answer and fall
     back to `reasoning` only to salvage a length-truncated reply.
  3. Tool calls are not deterministic even at temperature 0.  We do not use tool
     calling at all -- structured output via response_format json_schema is
     constrained during decoding, so it always parses.

SAFETY.  The failure that actually matters is not a wrong answer -- under exact
match a wrong answer costs exactly what a blank costs.  It is a HANG: a shared
server under finalist load, an HTTP call with no timeout, and a run that never
finishes.  A hang does not raise, so a try/except around it proves nothing.
Three independent guards:

  per-request timeout   no single call can block longer than TIMEOUT
  global budget         once BUDGET seconds have gone to the endpoint, stop
  circuit breaker       after CONSECUTIVE_FAILS in a row, disable for the run

Every entry point returns None instead of raising.  If the endpoint is unset,
unreachable, slow or broken, the pipeline degrades to the deterministic path
that already scores without it.
"""
import json
import os
import time
import urllib.error
import urllib.request

MODEL = "qwen3.6-35b-a3b-nvfp4"
TIMEOUT = float(os.environ.get("JAW_LLM_TIMEOUT", "90"))     # seconds, per request
BUDGET = float(os.environ.get("JAW_LLM_BUDGET", "1800"))     # seconds, whole run
CONSECUTIVE_FAILS = 5
MIN_TOKENS = 2048

_spent = 0.0
_fails = 0
_disabled = False
_calls = 0


def base_url():
    u = (os.environ.get("LLM_BASE_URL") or "").strip().rstrip("/")
    return u or None


def available():
    return bool(base_url()) and not _disabled


def stats():
    return {"calls": _calls, "seconds": round(_spent, 1),
            "disabled": _disabled, "consecutive_fails": _fails}


def _endpoint():
    # The documented call is exactly `$LLM_BASE_URL/chat/completions`. Only guard
    # against a base that already carries the suffix.
    u = base_url()
    return u if u.endswith("/chat/completions") else u + "/chat/completions"


def _post(payload):
    """One request.  Returns the decoded JSON body, or None on any failure."""
    global _spent, _fails, _disabled, _calls
    if _disabled:
        return None
    if _spent > BUDGET:
        _disabled = True
        print(f"[llm] budget of {BUDGET:.0f}s exhausted; disabling for the rest of the run")
        return None

    url = _endpoint()
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        _fails = 0
        return out
    except Exception as e:                       # timeout, HTTP error, bad JSON
        _fails += 1
        print(f"[llm] request failed ({type(e).__name__}: {e}); fail {_fails}/{CONSECUTIVE_FAILS}")
        if _fails >= CONSECUTIVE_FAILS:
            _disabled = True
            print("[llm] too many consecutive failures; disabling for the rest of the run")
        return None
    finally:
        _spent += time.time() - t0
        _calls += 1


def _message(resp):
    """Answer text from a response, handling the length-cut/None-content trap."""
    if not resp:
        return None
    try:
        choice = resp["choices"][0]
    except (KeyError, IndexError, TypeError):
        return None
    msg = choice.get("message") or {}
    content = msg.get("content")
    if content:
        return content
    # finish_reason "length": the model spent its budget on the hidden trace.
    # `reasoning` is the correct field name -- `reasoning_content` is silently None.
    if choice.get("finish_reason") == "length":
        trace = msg.get("reasoning")
        return trace or None
    return None


def chat(messages, max_tokens=MIN_TOKENS, schema=None, temperature=0):
    """Raw completion.  Returns text, or None.  Never raises."""
    if not available():
        return None
    payload = {"model": MODEL, "messages": messages,
               "max_tokens": max(MIN_TOKENS, int(max_tokens)),
               "temperature": temperature}
    if schema is not None:
        # Constrained during decoding, so the result always parses.
        payload["response_format"] = {"type": "json_schema",
                                      "json_schema": {"name": "answer",
                                                      "schema": schema,
                                                      "strict": True}}
    resp = _post(payload)
    text = _message(resp)
    if text is None and resp is not None:
        # A genuine length cut with nothing salvageable: retry once, bigger.
        payload["max_tokens"] = payload["max_tokens"] * 2
        text = _message(_post(payload))
    return text


def chat_json(messages, schema, max_tokens=MIN_TOKENS):
    """Structured completion.  Returns a dict, or None.  Never raises."""
    text = chat(messages, max_tokens=max_tokens, schema=schema)
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Constrained decoding should make this unreachable, but a truncated
        # salvage from `reasoning` is not constrained -- dig out the object.
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
        return None


def health():
    """One cheap call, to prove the endpoint answers before the run leans on it."""
    if not base_url():
        print("[llm] LLM_BASE_URL is unset -- deterministic path only")
        return False
    t0 = time.time()
    got = chat([{"role": "user", "content": "Reply with the single word: ready"}],
               max_tokens=MIN_TOKENS)
    if got is None:
        print(f"[llm] endpoint at {base_url()} did not answer -- deterministic path only")
        return False
    print(f"[llm] endpoint OK ({time.time() - t0:.1f}s): {got.strip()[:40]!r}")
    return True
