"""测试用的假模型服务：同时说两种协议，按模型名模拟各种情况。只监听 127.0.0.1，不联网。

模型名决定行为：
  ok           正常回复（内容由 responder(协议, 请求体) 决定）
  auth         401        rate      一直 429        rate-once  先 429 再成功
  server-once  先 500 再成功        slow   比超时更慢      redirect   302 跳到别处
  garbage      不是 JSON          empty  回复内容是空的    huge       回复超过 2MB
"""
from __future__ import annotations

import http.server
import json
import threading
import time

KEY = "sk-test-0123456789abcdef"


class Fake:
    def __init__(self, responder=None):
        self.responder = responder or (lambda proto, body: "OK")
        self.requests: list[dict] = []
        self.counts: dict[str, int] = {}
        fake = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None, raw=None, headers=None):
                body = raw if raw is not None else json.dumps(obj).encode()
                self.send_response(code)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def _auth(self, proto):
                if proto == "anthropic":
                    return self.headers.get("x-api-key") == KEY and self.headers.get("anthropic-version")
                return self.headers.get("authorization") == f"Bearer {KEY}"

            def do_GET(self):
                if self.path in ("/anth/v1/models", "/oai/models"):
                    proto = "anthropic" if self.path.startswith("/anth") else "openai"
                    if not self._auth(proto):
                        return self._send(401, {"error": {"message": "invalid key"}})
                    return self._send(200, {"data": [{"id": "ok"}, {"id": "model-b"}, {"id": "model-a"}]})
                self._send(404, {"error": "no"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                if self.path.startswith("/deny/"):  # 模拟“这个地址不认这把密钥”（如国内/海外账号用错了地址）
                    fake.requests.append({"proto": "deny", "path": self.path, "body": body, "ua": self.headers.get("user-agent", "")})
                    return self._send(401, {"error": {"message": "invalid api key"}})
                proto = "anthropic" if self.path == "/anth/v1/messages" else "openai" if self.path == "/oai/chat/completions" else None
                if not proto:
                    return self._send(404, {"error": {"message": "no such path"}})
                fake.requests.append({"proto": proto, "path": self.path, "body": body, "ua": self.headers.get("user-agent", ""),
                                      "auth_header_present": bool(self.headers.get("x-api-key") or self.headers.get("authorization"))})
                if not self._auth(proto):
                    return self._send(401, {"error": {"message": "invalid api key " + str(self.headers.get("authorization"))}})
                m = body.get("model", "")
                fake.counts[m] = fake.counts.get(m, 0) + 1
                c = fake.counts[m]
                if m == "auth":
                    return self._send(401, {"error": {"message": "bad key"}})
                if m == "rate" or (m == "rate-once" and c == 1):
                    return self._send(429, {"error": {"message": "slow down"}}, headers={"Retry-After": "0"})
                if m == "server-once" and c == 1:
                    return self._send(500, {"error": {"message": "oops"}})
                if m == "slow":
                    time.sleep(3)
                if m == "redirect":
                    return self._send(302, {}, headers={"Location": "http://example.com/steal"})
                if m == "garbage":
                    return self._send(200, raw=b"<html>not json</html>")
                if m == "huge":
                    return self._send(200, raw=b'{"x":"' + b"a" * (2 * 1024 * 1024 + 10) + b'"}')
                text = "" if m == "empty" else fake.responder(proto, body)
                if proto == "anthropic":
                    return self._send(200, {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 10, "output_tokens": 5}})
                return self._send(200, {"choices": [{"message": {"role": "assistant", "content": text}}], "usage": {"total_tokens": 15}})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        port = self.srv.server_address[1]
        self.anthropic_url = f"http://127.0.0.1:{port}/anth"
        self.openai_url = f"http://127.0.0.1:{port}/oai"
        self.deny_url = f"http://127.0.0.1:{port}/deny"

    def conn(self, proto="openai", model="ok", key=KEY):
        return {"id": "fake-" + proto, "name": "假服务", "protocol": proto, "needs_key": True, "key": key, "model": model,
                "base_url": self.anthropic_url if proto == "anthropic" else self.openai_url}

    def close(self):
        self.srv.shutdown()
