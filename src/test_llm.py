"""llm.py against a mock of the provided endpoint.

We cannot reach the real LLM_BASE_URL from here -- it exists only inside the
evaluation environment. That is exactly why this file exists: it stands up a
local OpenAI-compatible server that reproduces the response shapes the brief
warns about, so the client is exercised against them rather than written blind.

Covered, in the order the brief lists them:
  1. finish_reason "length" with content null   (the "looks like an outage" trap)
  2. the trace field is `reasoning`, NOT `reasoning_content`
  3. structured output via response_format json_schema
Plus the failure modes that would actually end a run: a hang, and a dead server.
"""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm

PORT = 8112                    # inside the 8112-8115 band reserved for us
MODE = {"mode": "ok"}
FAIL = []


def check(name, ok, detail=""):
    print(f"  {'OK ' if ok else 'XX '} {name}{'  ' + detail if detail and not ok else ''}")
    if not ok:
        FAIL.append(name)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        mode = MODE["mode"]

        if mode == "hang":
            time.sleep(30)                       # longer than the test's timeout

        if mode == "length":
            # The documented trap: content null, and the trace lives in
            # `reasoning`. A client reading `reasoning_content` sees None.
            payload = {"choices": [{"finish_reason": "length",
                                    "message": {"content": None,
                                                "reasoning": "thinking about it",
                                                "reasoning_content": "WRONG FIELD"}}]}
        elif mode == "500":
            self.send_response(500)
            self.end_headers()
            return
        elif body.get("response_format"):
            payload = {"choices": [{"finish_reason": "stop",
                                    "message": {"content": json.dumps({"answer": 42, "basis": "x"}),
                                                "reasoning": "trace"}}]}
        else:
            payload = {"choices": [{"finish_reason": "stop",
                                    "message": {"content": "ready", "reasoning": "trace"}}]}

        out = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def reset():
    llm._disabled = False
    llm._fails = 0
    llm._spent = 0.0


def main():
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    import os
    os.environ["LLM_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"

    print("--- endpoint contract ---")
    reset()
    check("health() succeeds", llm.health() is True)
    check("endpoint URL is base + /chat/completions",
          llm._endpoint() == f"http://127.0.0.1:{PORT}/v1/chat/completions", llm._endpoint())

    reset()
    got = llm.chat_json([{"role": "user", "content": "q"}],
                        schema={"type": "object",
                                "properties": {"answer": {"type": "number"},
                                               "basis": {"type": "string"}},
                                "required": ["answer", "basis"],
                                "additionalProperties": False})
    check("structured output parses", got == {"answer": 42, "basis": "x"}, str(got))

    print("\n--- trap 1/2: finish_reason length, content null, trace in `reasoning` ---")
    MODE["mode"] = "length"
    reset()
    got = llm.chat([{"role": "user", "content": "q"}])
    check("salvages `reasoning`, not `reasoning_content`", got == "thinking about it", repr(got))
    check("max_tokens floored at 2048", llm.MIN_TOKENS >= 2048)

    print("\n--- the failure that would actually end a run: a hang ---")
    MODE["mode"] = "hang"
    reset()
    llm.TIMEOUT = 2
    t0 = time.time()
    got = llm.chat([{"role": "user", "content": "q"}])
    dt = time.time() - t0
    check("a hang returns None instead of blocking", got is None)
    check(f"bounded by the timeout ({dt:.1f}s < 12s)", dt < 12, f"took {dt:.1f}s")

    print("\n--- dead server: degrade, never raise ---")
    MODE["mode"] = "500"
    reset()
    check("HTTP 500 returns None", llm.chat([{"role": "user", "content": "q"}]) is None)
    reset()
    for _ in range(llm.CONSECUTIVE_FAILS + 1):
        llm.chat([{"role": "user", "content": "q"}])
    check("circuit breaker disables after repeated failure", llm.available() is False)

    print("\n--- unset endpoint: silent no-op ---")
    reset()
    os.environ.pop("LLM_BASE_URL", None)
    check("available() is False when unset", llm.available() is False)
    check("chat() returns None when unset", llm.chat([{"role": "user", "content": "q"}]) is None)
    check("health() returns False when unset", llm.health() is False)

    srv.shutdown()
    print(f"\n{'ALL LLM CHECKS PASS' if not FAIL else f'{len(FAIL)} FAILED: {FAIL}'}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
