from __future__ import annotations

import asyncio

from pycognito import Cognito

from .config import Settings
from .session import AuthTokens


class AuthError(RuntimeError):
    """Raised when authentication fails."""


class AuthClient:
    """Handles Cognito SRP authentication and refresh via pycognito."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def login(self, username: str, password: str) -> AuthTokens:
        """Authenticate using Cognito SRP (pycognito handles SRP math)."""
        if not self.settings.user_pool_id:
            raise AuthError(
                "Missing user pool ID. Set KIDSVIEW_USER_POOL_ID from the Kidsview app config."
            )

        return await asyncio.to_thread(
            self._login_sync,
            username,
            password,
        )

    def _login_sync(self, username: str, password: str) -> AuthTokens:
        user = Cognito(
            user_pool_id=self.settings.user_pool_id,
            client_id=self.settings.client_id,
            username=username,
            user_pool_region=self.settings.region,
        )
        try:
            user.authenticate(password=password)
        except Exception as exc:  # pragma: no cover - third-party raised exceptions
            raise AuthError(str(exc)) from exc

        return AuthTokens(
            id_token=user.id_token,
            access_token=user.access_token,
            refresh_token=user.refresh_token,
            expires_in=None,
            token_type="JWT",
        )

    async def refresh(self, refresh_token: str) -> AuthTokens:
        """Refresh tokens using pycognito helper."""
        if not self.settings.user_pool_id:
            raise AuthError(
                "Missing user pool ID. Set KIDSVIEW_USER_POOL_ID from the Kidsview app config."
            )

        return await asyncio.to_thread(self._refresh_sync, refresh_token)

    def _refresh_sync(self, refresh_token: str) -> AuthTokens:
        user = Cognito(
            user_pool_id=self.settings.user_pool_id,
            client_id=self.settings.client_id,
            user_pool_region=self.settings.region,
            refresh_token=refresh_token,
        )
        try:
            user.renew_access_token()
        except Exception as exc:  # pragma: no cover
            raise AuthError(str(exc)) from exc

        return AuthTokens(
            id_token=user.id_token,
            access_token=user.access_token,
            refresh_token=user.refresh_token or refresh_token,
            expires_in=None,
            token_type="JWT",
        )
