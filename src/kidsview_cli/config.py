from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):  # type: ignore[misc]
    """CLI configuration loaded from environment or .env."""

    client_id: str = Field(
        default="4k8c50cn6ri9hk6197p9bnl0g4",
        description="Cognito App Client ID for Kidsview.",
    )
    user_pool_id: str | None = Field(
        default="eu-west-1_PZZVGIN20",
        description="Cognito User Pool ID (required for SRP auth).",
    )
    region: str = Field(default="eu-west-1", description="AWS region for Cognito.")
    locale: str = Field(default="pl", description="Locale sent with CLI requests when applicable.")
    api_url: str = Field(
        default="https://backend.kidsview.pl/graphql",
        description="Kidsview GraphQL endpoint for authenticated calls.",
    )
    origin_url: str = Field(
        default="https://backend.kidsview.pl",
        description="Kidsview origin base URL for non-GraphQL calls.",
    )
    app_url: str = Field(
        default="https://app.kidsview.pl",
        description="Kidsview app origin used for CORS headers.",
    )
    auth_token_preference: str = Field(
        default="id",
        description="Which token to send in Authorization header: 'id' or 'access'.",
    )
    debug: bool = Field(
        default=False,
        description="Enable verbose error output (set via KIDSVIEW_DEBUG=1).",
    )
    cookies: str | None = Field(
        default=None,
        description="Optional semicolon-delimited cookie string to send with API calls "
        "(e.g., 'active_child=...; active_year=...').",
    )
    user_agent: str = Field(
        default="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/26.0 Safari/605.1.15",
        description="User-Agent header sent to Kidsview backend.",
    )
    config_dir: Path = Field(
        default=Path.home() / ".config" / "kidsview-cli",
        description="Config directory for CLI artifacts.",
    )
    session_file: Path = Field(
        default=Path.home() / ".config" / "kidsview-cli" / "session.json",
        description="Session cache file for auth tokens.",
    )
    context_file: Path = Field(
        default=Path.home() / ".config" / "kidsview-cli" / "context.json",
        description="Selected preschool/child/year context.",
    )
    download_dir: Path = Field(
        default=Path.home() / "Pictures" / "Kidsview",
        description="Default directory for gallery downloads.",
    )

    model_config = SettingsConfigDict(env_prefix="KIDSVIEW_", env_file=".env", extra="ignore")
