"""向转发服务发送测试 webhook 并打印结果。"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8080"
WEBHOOK = f"{BASE}/api/dcs/corporateVA/webhooks"


def main() -> int:
    payload = {
        "event": "test.subscription",
        "message": "hello from webhook forwarder test",
        "timestamp": "2026-05-31T12:00:00Z",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        WEBHOOK + "?source=test&retry=0",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Test-Header": "forwarder-verify",
            "Authorization": "Bearer test-token",
        },
    )

    print(f"POST {WEBHOOK}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            print(f"Status: {resp.status}")
            print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
            return 0 if resp.status in (200, 207) else 1
    except urllib.error.HTTPError as exc:
        print(f"HTTP Error: {exc.code}")
        print(exc.read().decode("utf-8"))
        return 1
    except Exception as exc:
        print(f"Error: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
