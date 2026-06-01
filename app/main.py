import asyncio
import logging
import os
from typing import Any

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

WEBHOOK_PATH = "/api/dcs/corporateVA/webhooks"

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


def get_forward_urls() -> list[str]:
    urls = [
        os.getenv("FORWARD_URL_1", "").strip(),
        os.getenv("FORWARD_URL_2", "").strip(),
    ]
    return [url for url in urls if url]


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
        return {
            "url": target_url,
            "success": True,
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


@app.api_route(WEBHOOK_PATH, methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def receive_webhook(request: Request) -> Response:
    forward_urls = get_forward_urls()
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
        request.url.path,
        len(body),
        forward_urls,
    )

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
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
                "path": str(request.url.path),
                "query_params": dict(request.query_params),
                "headers": dict(request.headers),
                "body_length": len(body),
            },
            "forwards": results,
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
