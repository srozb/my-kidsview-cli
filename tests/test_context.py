from pathlib import Path

import respx
from httpx import Response
from typer.testing import CliRunner

from kidsview_cli.cli import app
from kidsview_cli.config import Settings
from kidsview_cli.context import ContextStore
from kidsview_cli.session import AuthTokens, SessionStore

runner = CliRunner()


def _make_session(tmp_path: Path) -> Settings:
    settings = Settings(
        session_file=tmp_path / "session.json",
        context_file=tmp_path / "context.json",
    )
    SessionStore(settings.session_file).save(
        AuthTokens(
            id_token="IDTOKEN",
            access_token="ACCESSTOKEN",
            refresh_token="REFRESH",
        )
    )
    return settings


def _mock_me(children: list[dict], preschools: list[dict]) -> dict:
    return {"data": {"me": {"children": children, "availablePreschools": preschools}}}


def _mock_years(years: list[dict]) -> dict:
    return {"data": {"years": years}}


@respx.mock
def test_context_auto_no_interactive_picks_first(tmp_path: Path, monkeypatch) -> None:
    settings = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(settings.session_file))
    monkeypatch.setenv("KIDSVIEW_CONTEXT_FILE", str(settings.context_file))

    respx.post(settings.api_url).mock(
        side_effect=[
            Response(
                200,
                json=_mock_me([{"id": "child1", "name": "A"}], [{"id": "pre1", "name": "P1"}]),
            ),
            Response(200, json=_mock_years([{"id": "year1", "displayName": "2024/25"}])),
        ]
    )

    result = runner.invoke(app, ["context", "--auto"])
    assert result.exit_code == 0

    ctx = ContextStore(settings.context_file).load()
    assert ctx is not None
    assert ctx.child_id == "child1"
    assert ctx.preschool_id == "pre1"
    assert ctx.year_id == "year1"


@respx.mock
def test_context_auto_interactive_prompts_and_saves(tmp_path: Path, monkeypatch) -> None:
    settings = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(settings.session_file))
    monkeypatch.setenv("KIDSVIEW_CONTEXT_FILE", str(settings.context_file))

    respx.post(settings.api_url).mock(
        side_effect=[
            Response(
                200,
                json=_mock_me(
                    [{"id": "child1", "name": "A"}, {"id": "child2", "name": "B"}],
                    [{"id": "pre1", "name": "P1"}, {"id": "pre2", "name": "P2"}],
                ),
            ),
            Response(
                200,
                json=_mock_years(
                    [
                        {"id": "year1", "displayName": "2024/25"},
                        {"id": "year2", "displayName": "2025/26"},
                    ]
                ),
            ),
        ]
    )

    # Choose child2 (index 2), preschool pre2 (index 2), year2 (index 2)
    result = runner.invoke(app, ["context", "--auto", "--change"], input="2\n2\n2\n")
    assert result.exit_code == 0

    ctx = ContextStore(settings.context_file).load()
    assert ctx is not None
    assert ctx.child_id == "child2"
    assert ctx.preschool_id == "pre2"
    assert ctx.year_id == "year2"
