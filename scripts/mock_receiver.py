"""本地测试用 mock 接收端，监听 9999 端口并记录收到的请求。"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

received: list[dict] = []


class Handler(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        record = {
            "method": self.command,
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
        }
        received.append(record)
        print(f"[mock] {self.command} {self.path} body={len(body)} bytes")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "count": len(received)}).encode())

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def log_message(self, format: str, *args) -> None:
        pass


def run() -> None:
    server = HTTPServer(("127.0.0.1", 9999), Handler)
    print("[mock] listening on http://127.0.0.1:9999")
    server.serve_forever()


if __name__ == "__main__":
    run()
