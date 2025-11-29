import json
from pathlib import Path

import respx
from httpx import Response
from typer.testing import CliRunner

from kidsview_cli.cli import app
from kidsview_cli.session import AuthTokens, SessionStore

runner = CliRunner()


def _make_session(tmp_path: Path) -> Path:
    session_path = tmp_path / "session.json"
    store = SessionStore(session_path)
    store.save(
        AuthTokens(
            id_token="IDTOKEN",
            access_token="ACCESSTOKEN",
            refresh_token="REFRESH",
            token_type="JWT",
        )
    )
    return session_path


@respx.mock
def test_announcements_json(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    route = respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json={"data": {"announcements": {"edges": [], "pageInfo": {}}}})
    )
    result = runner.invoke(app, ["announcements", "--first", "1", "--json"])

    assert result.exit_code == 0
    assert '"announcements"' in result.stdout
    assert route.called


@respx.mock
def test_announcements_pretty(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json={"data": {"announcements": {"edges": [], "pageInfo": {}}}})
    )
    result = runner.invoke(app, ["announcements", "--first", "1", "--no-json"])

    assert result.exit_code == 0
    assert "announcements" in result.stdout
    assert '"announcements"' not in result.stdout  # pretty output, not raw JSON


@respx.mock
def test_graphql_errors_raise(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    # Override with no refresh token to surface GraphQL error directly.
    SessionStore(session_path).save(
        AuthTokens(
            id_token="IDTOKEN",
            access_token="ACCESSTOKEN",
            refresh_token=None,
        )
    )
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json={"errors": [{"message": "boom"}]})
    )
    result = runner.invoke(
        app, ["graphql", "--query", "query { __typename }"], catch_exceptions=False
    )

    assert result.exit_code == 1
    assert "failed" in result.stdout


@respx.mock
def test_chat_send_uses_recipients(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    sent = {}

    def _handler(request):
        sent["headers"] = request.headers
        sent["json"] = json.loads(request.content)
        return Response(200, json={"data": {"createThread": {"success": True, "id": "abc"}}})

    route = respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=_handler)
    result = runner.invoke(
        app,
        [
            "chat-send",
            "--recipients",
            "RECIP",
            "--text",
            "hi",
            "--parents-hidden",
        ],
    )

    assert result.exit_code == 0
    assert route.called
    assert sent["json"]["variables"]["input"]["recipients"] == ["RECIP"]
    assert sent["json"]["variables"]["input"]["message"]["text"] == "hi"
    assert sent["json"]["variables"]["input"]["parentsMutualVisibility"] is False
    assert sent["headers"]["Authorization"] == "JWT IDTOKEN"


@respx.mock
def test_notifications_filter_and_pretty(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    notif_payload = {
        "data": {
            "notifications": {
                "edges": [
                    {
                        "node": {
                            "title": "A",
                            "text": "foo",
                            "type": "UPCOMING_EVENT",
                            "notifyOn": "2025-01-01",
                            "allDay": True,
                            "data": '{"date":"2025-01-01"}',
                        }
                    },
                    {
                        "node": {
                            "title": "B",
                            "text": "bar",
                            "type": "NEW_EVENT",
                            "notifyOn": "2025-01-02",
                            "allDay": False,
                            "data": '{"date":"2025-01-02"}',
                        }
                    },
                ]
            }
        }
    }
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json=notif_payload)
    )
    result = runner.invoke(app, ["notifications", "--type", "upcoming_event"])

    assert result.exit_code == 0
    assert "UPCOMING_EVENT" in result.stdout
    assert "NEW_EVENT" not in result.stdout


@respx.mock
def test_calendar_pretty(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    cal_payload = {
        "data": {
            "calendar": [
                {
                    "title": "Nieobecność",
                    "startDate": "2025-10-14T00:00:00",
                    "endDate": "2025-10-14T00:00:00",
                    "type": 5,
                    "allDay": True,
                    "absenceReportedBy": {"fullName": "Reporter"},
                }
            ]
        }
    }
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json=cal_payload)
    )
    result = runner.invoke(app, ["calendar", "--date-from", "today", "--date-to", "today"])

    assert result.exit_code == 0
    assert "Nieobecność" in result.stdout
    assert "Reporter" in result.stdout


@respx.mock
def test_me_pretty(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    me_payload = {
        "data": {
            "me": {
                "fullName": "R S",
                "email": "email@domain.eu",
                "phone": "123",
                "userPosition": "Opiekun",
                "userType": "parent",
                "children": [
                    {"id": "c1", "name": "H", "surname": "R", "group": {"name": "Klasa 2"}}
                ],
                "availablePreschools": [
                    {"id": "p1", "name": "PS1", "phone": "111", "email": "ps1@example.com"}
                ],
            }
        }
    }
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(200, json=me_payload)
    )
    result = runner.invoke(app, ["me"])

    assert result.exit_code == 0
    assert "R S" in result.stdout
    assert "Klasa 2" in result.stdout
    assert "PS1" in result.stdout
