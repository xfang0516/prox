import asyncio
import logging
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

WEBHOOK_PATHS = [
    "/api/dcs/corporateVA/webhooks",
    "/api/dcs/safeheron/webhook/transaction",
]

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}

app = FastAPI(title="Webhook Forwarder", version="1.0.0")


def extract_origin(url: str) -> str:
    """从配置中提取 scheme://host[:port]，丢弃路径/查询参数。"""
    parts = urlsplit(url.strip())
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"invalid FORWARD_URL: {url!r}")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def get_forward_origins() -> list[str]:
    raw_urls = [
        os.getenv("FORWARD_URL_1", "").strip(),
        os.getenv("FORWARD_URL_2", "").strip(),
    ]
    origins: list[str] = []
    for raw in raw_urls:
        if not raw:
            continue
        origins.append(extract_origin(raw))
    return origins


def build_forward_urls(request_path: str) -> list[str]:
    """目标地址 = 配置主机源 + 当前请求路径。"""
    path = request_path if request_path.startswith("/") else f"/{request_path}"
    return [f"{origin}{path}" for origin in get_forward_origins()]


def build_forward_headers(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower() in HOP_BY_HOP_HEADERS:
            continue
        headers[name] = value
    headers["X-Forwarded-From"] = "webhook-forwarder"
    return headers


async def forward_to_target(
    client: httpx.AsyncClient,
    target_url: str,
    method: str,
    headers: dict[str, str],
    content: bytes,
    query_params: list[tuple[str, str]],
) -> dict[str, Any]:
    try:
        response = await client.request(
            method=method,
            url=target_url,
            headers=headers,
            content=content,
            params=query_params,
        )
        ok = 200 <= response.status_code < 300
        return {
            "url": target_url,
            "success": ok,
            "status_code": response.status_code,
            "response_body": response.text[:2000],
        }
    except Exception as exc:
        logger.exception("Forward failed: %s -> %s", target_url, exc)
        return {
            "url": target_url,
            "success": False,
            "error": str(exc),
        }


async def receive_webhook(request: Request) -> Response:
    request_path = request.url.path
    try:
        forward_urls = build_forward_urls(request_path)
    except ValueError as exc:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": str(exc)},
        )

    if len(forward_urls) < 2:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "FORWARD_URL_1 and FORWARD_URL_2 must both be configured",
            },
        )

    body = await request.body()
    headers = build_forward_headers(request)
    query_params = list(request.query_params.multi_items())
    timeout = float(os.getenv("FORWARD_TIMEOUT", "30"))

    logger.info(
        "Received %s %s, body=%d bytes, forwarding to %s",
        request.method,
        request_path,
        len(body),
        forward_urls,
    )

    # Webhook 不应跟随重定向，避免 POST 被转到首页导致 405
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        results = await asyncio.gather(
            *[
                forward_to_target(
                    client,
                    url,
                    request.method,
                    headers,
                    body,
                    query_params,
                )
                for url in forward_urls
            ]
        )

    all_success = all(item.get("success") for item in results)
    status_code = 200 if all_success else 207

    return JSONResponse(
        status_code=status_code,
        content={
            "success": all_success,
            "received": {
                "method": request.method,
                "path": request_path,
                "query_params": dict(request.query_params),
                "headers": dict(request.headers),
                "body_length": len(body),
            },
            "forwards": results,
        },
    )


for _path in WEBHOOK_PATHS:
    app.add_api_route(
        _path,
        receive_webhook,
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
