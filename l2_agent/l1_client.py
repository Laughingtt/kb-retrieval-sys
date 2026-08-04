"""薄 httpx 客户端 —— 封装 L1 的 6 个 GET 端点。只读（硬约束 2）。"""
from __future__ import annotations

from typing import Any

import httpx

from l2_agent import config

__all__ = ["L1Client", "L1Error"]


class L1Error(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"L1 {status}: {detail}")
        self.status = status
        self.detail = detail


class L1Client:
    def __init__(self, base_url: str | None = None, timeout: float | None = None) -> None:
        self._client = httpx.Client(
            base_url=base_url or config.L1_BASE_URL,
            timeout=timeout or config.L1_TIMEOUT,
        )

    def _get(self, path: str, **params: Any) -> Any:
        r = self._client.get(path, params={k: v for k, v in params.items() if v is not None})
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise L1Error(r.status_code, str(detail))
        return r.json()

    def get_health(self) -> dict:
        return self._get("/health")

    def get_categories(self) -> list[dict]:
        return self._get("/categories")

    def get_documents(self, type: str | None = None, page: int = 1, page_size: int = 50) -> dict:
        return self._get("/documents", type=type, page=page, page_size=page_size)

    def get_document(self, slug: str) -> dict:
        return self._get(f"/documents/{slug}")

    def get_index(self) -> dict:
        return self._get("/index")

    def get_search(self, q: str, top_k: int = 10) -> dict:
        return self._get("/search", q=q, top_k=top_k)
