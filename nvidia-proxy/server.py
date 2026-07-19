#!/usr/bin/env python3
"""Local OpenAI-compatible reverse proxy for NVIDIA integrate API.

Hermes has no per-provider proxy. This service listens on localhost and
forwards only NVIDIA traffic via HTTP(S)_PROXY, so the main Hermes process
can run without a global proxy.
"""
from __future__ import annotations

import os
from typing import Iterable

from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse
import httpx
import uvicorn

UPSTREAM = os.environ.get("NVIDIA_UPSTREAM", "https://integrate.api.nvidia.com").rstrip("/")
LISTEN_HOST = os.environ.get("NVIDIA_PROXY_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("NVIDIA_PROXY_PORT", "18319"))
HTTP_PROXY = os.environ.get("NVIDIA_HTTP_PROXY", "http://127.0.0.1:7890")
HTTPS_PROXY = os.environ.get("NVIDIA_HTTPS_PROXY", HTTP_PROXY)
TIMEOUT = float(os.environ.get("NVIDIA_PROXY_TIMEOUT", "300"))

DROP_REQ = {
    "host", "content-length", "connection", "proxy-connection",
    "transfer-encoding", "keep-alive", "te", "trailer", "upgrade",
    "proxy-authorization", "proxy-authenticate",
}
DROP_RESP = DROP_REQ | {"content-encoding"}

app = FastAPI(title="nvidia-selective-proxy", docs_url=None, redoc_url=None)


def _proxy_map() -> dict:
    # httpx 0.23 needs Proxy objects for AsyncHTTPTransport(proxy=...),
    # but AsyncClient(proxies=...) accepts plain URL strings.
    return {
        "http://": HTTP_PROXY,
        "https://": HTTPS_PROXY,
        "all://": HTTPS_PROXY,
    }


@app.get("/health")
async def health():
    return {
        "ok": True,
        "upstream": UPSTREAM,
        "proxy": HTTPS_PROXY,
        "listen": f"{LISTEN_HOST}:{LISTEN_PORT}",
    }


async def _forward(request: Request, path: str) -> Response:
    url = f"{UPSTREAM}/{path}" if path else UPSTREAM + "/"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in DROP_REQ
    }
    body = await request.body()

    client = httpx.AsyncClient(
        proxies=_proxy_map(),
        timeout=httpx.Timeout(TIMEOUT, connect=30.0),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        req = client.build_request(
            request.method,
            url,
            headers=headers,
            content=body if body else None,
        )
        upstream = await client.send(req, stream=True)
    except Exception as e:
        await client.aclose()
        return Response(content=f"nvidia-proxy error: {e}".encode(), status_code=502)

    resp_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in DROP_RESP
    }

    async def stream() -> Iterable[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("content-type"),
    )


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
async def catch_all(path: str, request: Request):
    return await _forward(request, path)


def main() -> None:
    print(
        f"nvidia-proxy listen={LISTEN_HOST}:{LISTEN_PORT} upstream={UPSTREAM} via={HTTPS_PROXY}",
        flush=True,
    )
    uvicorn.run(app, host=LISTEN_HOST, port=LISTEN_PORT, log_level="info")


if __name__ == "__main__":
    main()
