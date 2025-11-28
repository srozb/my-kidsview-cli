from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path
from typing import Any

from pydantic import BaseModel


class AuthTokens(BaseModel):
    id_token: str
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str | None = "JWT"

    def authorization_header(self, preference: str = "id") -> dict[str, str]:
        """Return Authorization header for API calls."""
        prefix = self.token_type or "JWT"
        pref = preference.lower()
        token = None
        if pref == "access":
            token = self.access_token or self.id_token
        else:
            token = self.id_token or self.access_token
        if not token:
            raise ValueError("No token available for Authorization header")
        return {"Authorization": f"{prefix} {token}"}


class SessionStore:
    """Persists tokens to disk for reuse by humans or agents."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AuthTokens | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        return AuthTokens.model_validate(data)

    def save(self, tokens: AuthTokens) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(tokens.model_dump_json(indent=2))
        with suppress(PermissionError):
            os.chmod(self.path, 0o600)

    def delete(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def to_dict(self) -> dict[str, Any]:
        tokens = self.load()
        return tokens.model_dump() if tokens else {}
