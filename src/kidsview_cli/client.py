from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from .config import Settings
from .context import Context
from .session import AuthTokens


class ApiError(RuntimeError):
    """Raised when Kidsview API returns an error."""


class GraphQLClient:
    """Thin GraphQL client for Kidsview backend."""

    def __init__(
        self, settings: Settings, tokens: AuthTokens, context: Context | None = None
    ) -> None:
        self.settings = settings
        self.tokens = tokens
        self.context = context

    def _set_extra_cookies(self, client: httpx.AsyncClient) -> None:
        cookie_str = self.settings.cookies
        if not cookie_str:
            cookie_parts: dict[str, str] = self.context.cookies() if self.context else {}
            if not cookie_parts:
                return
            cookie_str = "; ".join(f"{k}={v}" for k, v in cookie_parts.items())
        for part in cookie_str.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            client.cookies.set(name.strip(), value.strip(), domain="backend.kidsview.pl")

    async def execute(
        self, query: str, variables: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        base_headers = {
            **self.tokens.authorization_header(self.settings.auth_token_preference),
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": self.settings.app_url,
            "Referer": f"{self.settings.app_url}/",
            "Accept-Language": f"{self.settings.locale},en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "User-Agent": self.settings.user_agent,
        }
        payload: dict[str, Any] = {"query": query, "variables": variables or {}}

        async with httpx.AsyncClient(timeout=20.0) as client:
            self._set_extra_cookies(client)
            resp = await client.post(self.settings.api_url, json=payload, headers=base_headers)

        if resp.is_error:
            raise ApiError(f"GraphQL HTTP error {resp.status_code}: {resp.text}")

        data_raw: Any = resp.json()
        if not isinstance(data_raw, dict):
            return {}
        if "errors" in data_raw:
            raise ApiError(f"GraphQL errors: {data_raw['errors']} | raw: {resp.text}")
        data_section = data_raw.get("data")
        return data_section if isinstance(data_section, dict) else {}
