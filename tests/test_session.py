from pathlib import Path

from kidsview_cli.session import AuthTokens, SessionStore


def test_session_round_trip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path / "session.json")
    tokens = AuthTokens(
        id_token="id",
        access_token="access",
        refresh_token="refresh",
        expires_in=3600,
        token_type="Bearer",
    )

    store.save(tokens)
    loaded = store.load()

    assert loaded is not None
    assert loaded.id_token == "id"
    assert loaded.access_token == "access"
    assert loaded.refresh_token == "refresh"
    assert loaded.expires_in == 3600
    assert loaded.token_type == "Bearer"
