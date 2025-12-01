import json
from pathlib import Path

import respx
from httpx import Response
from typer.testing import CliRunner

from kidsview_cli.cli import app
from kidsview_cli.context import Context, ContextStore
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
def test_notifications_only_unread_and_mark(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    requests: list[dict] = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if "notifications" in payload.get("query", ""):
            return Response(
                200,
                json={
                    "data": {
                        "notifications": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "n1",
                                        "isRead": False,
                                        "notification": {"id": "N1"},
                                    }
                                },
                                {
                                    "node": {
                                        "id": "n2",
                                        "isRead": True,
                                        "notification": {"id": "N2"},
                                    }
                                },
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                },
            )
        return Response(200, json={"data": {"setNotificationRead": {"success": True}}})

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["notifications", "--only-unread", "--mark-read", "--pending"])
    assert result.exit_code == 0
    # Only unread should be marked
    mut_calls = [r for r in requests if "setNotificationRead" in r.get("query", "")]
    assert mut_calls
    assert mut_calls[0]["variables"]["notificationId"] == "N1"


@respx.mock
def test_notifications_mark_read_paginates(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    call_count = {"n": 0}

    def handler(request):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return Response(
                200,
                json={
                    "data": {
                        "notifications": {
                            "edges": [{"node": {"id": "node1", "notification": {"id": "notif1"}}}],
                            "pageInfo": {"hasNextPage": True, "endCursor": "CUR1"},
                        }
                    }
                },
            )
        if call_count["n"] == 2:
            return Response(
                200,
                json={
                    "data": {
                        "notifications": {
                            "edges": [{"node": {"id": "node2", "notification": {"id": "notif2"}}}],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                },
            )
        return Response(200, json={"data": {"setNotificationRead": {"success": True}}})

    route = respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["notifications", "--mark-read", "--all-pages", "--pending"])
    assert result.exit_code == 0
    assert route.called
    mut_calls = [c for c in route.calls if b"setNotificationRead" in c.request.content]
    mut_vars = [json.loads(c.request.content)["variables"] for c in mut_calls]
    assert {"notificationId": "notif1"} in mut_vars
    assert {"notificationId": "notif2"} in mut_vars


@respx.mock
def test_notification_prefs_set_and_list(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    seen_requests: list[dict] = []

    def handler(request):
        payload = json.loads(request.content)
        seen_requests.append(payload)
        if "setUserNotificationPreferences" in payload.get("query", ""):
            return Response(
                200, json={"data": {"setUserNotificationPreferences": {"success": True}}}
            )
        return Response(
            200,
            json={
                "data": {
                    "userNotificationPreferences": [
                        {"type": "NEW_EVENT", "name": "Nowe wydarzenie", "enabled": True}
                    ]
                }
            },
        )

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["notification-prefs", "--disable", "UPCOMING_EVENT", "--json"])
    assert result.exit_code == 0
    assert "NEW_EVENT" in result.stdout
    # First request is mutation; ensure variable shape
    first_payload = seen_requests[0]
    assert first_payload["variables"]["preferences"][0] == {
        "notificationType": "UPCOMING_EVENT",
        "enabled": False,
    }


@respx.mock
def test_quick_calendar(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "quickCalendar": [
                        {
                            "date": "2025-12-01",
                            "hasEvents": True,
                            "hasNewEvents": False,
                            "holiday": False,
                            "absent": True,
                            "mealsModified": False,
                        }
                    ]
                }
            },
        )
    )
    result = runner.invoke(app, ["quick-calendar", "--json"])
    assert result.exit_code == 0
    assert "quickCalendar" in result.stdout


@respx.mock
def test_schedule(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "schedule": [
                        {
                            "title": "Math",
                            "startDate": "2025-12-01T08:00:00",
                            "endDate": "2025-12-01T09:00:00",
                            "allDay": False,
                            "type": 1,
                            "groupsNames": ["Group A"],
                        }
                    ]
                }
            },
        )
    )
    result = runner.invoke(app, ["schedule", "--group-id", "G1"])
    assert result.exit_code == 0
    assert "Math" in result.stdout


@respx.mock
def test_payments_table(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "payments": {
                        "edges": [
                            {
                                "node": {
                                    "title": "Payment A",
                                    "amount": "123.45",
                                    "paymentDate": "2025-12-01",
                                    "type": "TRANSFER",
                                    "isBooked": True,
                                    "child": {"name": "H", "surname": "R"},
                                }
                            }
                        ]
                    }
                }
            },
        )
    )
    result = runner.invoke(app, ["payments"])
    assert result.exit_code == 0
    assert "Payment A" in result.stdout


@respx.mock
def test_absence_uses_context_child(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    context_path = tmp_path / "context.json"
    ContextStore(context_path).save(Context(child_id="CHILD1"))
    monkeypatch.setenv("KIDSVIEW_CONTEXT_FILE", str(context_path))

    captured: dict | None = None

    def handler(request):
        nonlocal captured
        captured = json.loads(request.content)
        return Response(200, json={"data": {"setChildAbsence": {"success": True}}})

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["absence", "--date", "2025-12-01", "--yes"])
    assert result.exit_code == 0
    assert captured is not None
    assert captured["variables"]["childId"] == "CHILD1"
    assert captured["variables"]["date"] == "2025-12-01"


@respx.mock
def test_gallery_like(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))

    reqs: list[dict] = []

    def handler(request):
        reqs.append(json.loads(request.content))
        return Response(200, json={"data": {"setGalleryLike": {"success": True, "isLiked": True}}})

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["gallery-like", "--id", "G1"])
    assert result.exit_code == 0
    assert reqs[0]["variables"]["galleryId"] == "G1"


@respx.mock
def test_gallery_comment(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))

    reqs: list[dict] = []

    def handler(request):
        reqs.append(json.loads(request.content))
        return Response(
            200, json={"data": {"createGalleryComment": {"galleryComment": {"id": "C1"}}}}
        )

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["gallery-comment", "--id", "G1", "--content", "Nice"])
    assert result.exit_code == 0
    assert reqs[0]["variables"] == {"galleryId": "G1", "content": "Nice"}


@respx.mock
def test_chat_threads_and_messages(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))

    def handler(request):
        payload = json.loads(request.content)
        if "threads" in payload.get("query", ""):
            return Response(
                200,
                json={
                    "data": {
                        "threads": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "T1",
                                        "name": "Thread1",
                                        "type": "chat",
                                        "modified": "2025-12-01",
                                        "lastMessage": "Hello world",
                                        "isRead": False,
                                        "recipients": [{"id": "U1", "fullName": "John"}],
                                        "child": {"id": "C1", "name": "H", "surname": "R"},
                                    }
                                }
                            ]
                        }
                    }
                },
            )
        if "thread" in payload.get("query", "") and "messages" in payload.get("query", ""):
            return Response(
                200,
                json={
                    "data": {
                        "thread": {
                            "id": "T1",
                            "name": "Thread1",
                            "messages": {
                                "edges": [
                                    {
                                        "node": {
                                            "id": "M1",
                                            "text": "hello",
                                            "created": "2025-12-01",
                                            "read": True,
                                            "sender": {"fullName": "John"},
                                        }
                                    }
                                ]
                            },
                        }
                    }
                },
            )
        return Response(400)

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(app, ["chat-threads"])
    assert result.exit_code == 0
    assert "Thread1" in result.stdout

    result2 = runner.invoke(app, ["chat-messages", "--thread-id", "T1"])
    assert result2.exit_code == 0
    assert "hello" in result2.stdout


@respx.mock
def test_application_submit(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    reqs: list[dict] = []

    def handler(request):
        reqs.append(json.loads(request.content))
        return Response(200, json={"data": {"createApplication": {"success": True, "id": "APP1"}}})

    respx.post("https://backend.kidsview.pl/graphql").mock(side_effect=handler)

    result = runner.invoke(
        app,
        ["application-submit", "--form-id", "FORM1", "--comment", "Ok", "--months", "3"],
    )
    assert result.exit_code == 0
    vars = reqs[0]["variables"]
    assert vars["applicationFormId"] == "FORM1"
    assert vars["commentParent"] == "Ok"
    assert vars["months"] == 3


@respx.mock
def test_payments_summary_table(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))

    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "paymentsSummary": {
                        "fullBalance": "100.00",
                        "children": {
                            "edges": [
                                {
                                    "node": {
                                        "name": "H",
                                        "surname": "R",
                                        "amount": "50.00",
                                        "paidAmount": "30.00",
                                        "balance": "20.00",
                                        "paidMonthlyBillsCount": 5,
                                    }
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        },
                    }
                }
            },
        )
    )

    result = runner.invoke(app, ["payments-summary"])
    assert result.exit_code == 0
    assert "H R" in result.stdout


@respx.mock
def test_payment_orders_table(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "paymentOrders": {
                        "edges": [
                            {
                                "node": {
                                    "id": "PO1",
                                    "created": "2025-12-01",
                                    "amount": "123.00",
                                    "bluemediaPaymentStatus": "PENDING",
                                    "bookingDate": None,
                                }
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        )
    )
    result = runner.invoke(app, ["payment-orders"])
    assert result.exit_code == 0
    assert "PO1" in result.stdout


@respx.mock
def test_payments_summary_permission_denied(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))
    # Remove refresh token to avoid refresh branch interfering with message
    SessionStore(session_path).save(
        AuthTokens(id_token="IDTOKEN", access_token="ACCESSTOKEN", refresh_token=None)
    )

    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "errors": [
                    {
                        "message": "Odmowa dostępu lub brak uprawnień",
                        "locations": [{"line": 12, "column": 3}],
                        "path": ["paymentsSummary"],
                    }
                ],
                "data": {"paymentsSummary": None},
            },
        )
    )

    result = runner.invoke(app, ["payments-summary"])
    assert result.exit_code != 0
    assert "access denied" in result.stdout.lower() or "odmowa dostępu" in result.stdout.lower()


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


@respx.mock
def test_me_shows_years_without_extra_query(tmp_path: Path, monkeypatch) -> None:
    session_path = _make_session(tmp_path)
    monkeypatch.setenv("KIDSVIEW_SESSION_FILE", str(session_path))

    ctx_store = ContextStore(tmp_path / "context.json")
    ctx_store.save(Context(preschool_id="pre1"))
    monkeypatch.setenv("KIDSVIEW_CONTEXT_FILE", str(ctx_store.path))

    respx.post("https://backend.kidsview.pl/graphql").mock(
        return_value=Response(
            200,
            json={
                "data": {
                    "me": {
                        "fullName": "User One",
                        "email": "u@example.com",
                        "phone": "123",
                        "userPosition": "Opiekun",
                        "userType": "parent",
                        "children": [
                            {
                                "id": "c1",
                                "name": "H",
                                "surname": "R",
                                "group": {"name": "Klasa 2"},
                                "balance": "0.00",
                            }
                        ],
                        "availablePreschools": [
                            {
                                "id": "pre1",
                                "name": "PS1",
                                "phone": "111",
                                "email": "ps1@example.com",
                                "address": "Street 1",
                                "years": {
                                    "edges": [
                                        {
                                            "node": {
                                                "id": "year1",
                                                "displayName": "2024/25",
                                                "startDate": "2024-09-01",
                                                "endDate": "2025-08-31",
                                            }
                                        }
                                    ]
                                },
                            }
                        ],
                    }
                }
            },
        )
    )

    result = runner.invoke(app, ["me"])
    assert result.exit_code == 0
    assert "2024/25" in result.stdout
