from __future__ import annotations

from contextlib import suppress
from pathlib import Path

from pydantic import BaseModel


class Context(BaseModel):
    child_id: str | None = None
    preschool_id: str | None = None
    year_id: str | None = None
    locale: str = "pl"

    def cookies(self) -> dict[str, str]:
        parts: dict[str, str] = {}
        if self.child_id:
            parts["active_child"] = self.child_id
        if self.year_id:
            parts["active_year"] = self.year_id
        if self.preschool_id:
            parts["preschool"] = self.preschool_id
        if self.locale:
            parts["locale"] = self.locale
        return parts


class ContextStore:
    """Persist active preschool/child/year context."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> Context | None:
        if not self.path.exists():
            return None
        data = self.path.read_text()
        return Context.model_validate_json(data)

    def save(self, ctx: Context) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(ctx.model_dump_json(indent=2))
        with suppress(PermissionError):
            self.path.chmod(0o600)

    def delete(self) -> None:
        with suppress(FileNotFoundError):
            self.path.unlink()
