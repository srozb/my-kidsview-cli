import json

import pytest
import respx
from httpx import Response

from kidsview_cli.client import GraphQLClient
from kidsview_cli.config import Settings
from kidsview_cli.context import Context
from kidsview_cli.session import AuthTokens


@pytest.mark.asyncio()
async def test_graphql_uses_id_token_by_default() -> None:
    settings = Settings(
        api_url="https://backend.kidsview.pl/graphql",
        cookies="active_child=foo; locale=pl",
    )
    tokens = AuthTokens(id_token="IDTOKEN", access_token="ACCESSTOKEN", refresh_token=None)
    client = GraphQLClient(settings, tokens)

    with respx.mock:
        route = respx.post(settings.api_url).mock(
            return_value=Response(200, json={"data": {"ok": True}})
        )
        data = await client.execute("query { ok }", {"a": 1})

    assert data == {"ok": True}
    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "JWT IDTOKEN"
    assert "Origin" in req.headers and "Referer" in req.headers
    body = json.loads(req.content.decode())
    assert body["query"] == "query { ok }"
    assert body["variables"] == {"a": 1}
    assert "active_child=foo" in req.headers.get("cookie", "")


@pytest.mark.asyncio()
async def test_graphql_can_use_access_token() -> None:
    settings = Settings(
        api_url="https://backend.kidsview.pl/graphql",
        auth_token_preference="access",
    )
    tokens = AuthTokens(id_token="IDTOKEN", access_token="ACCESSTOKEN", refresh_token=None)
    client = GraphQLClient(settings, tokens)

    with respx.mock:
        route = respx.post(settings.api_url).mock(
            return_value=Response(200, json={"data": {"ok": True}})
        )
        _ = await client.execute("query { ok }")

    assert route.called
    req = route.calls.last.request
    assert req.headers["Authorization"] == "JWT ACCESSTOKEN"


@pytest.mark.asyncio()
async def test_graphql_builds_cookies_from_context_when_not_overridden() -> None:
    settings = Settings(api_url="https://backend.kidsview.pl/graphql", cookies=None)
    tokens = AuthTokens(id_token="IDTOKEN", access_token="ACCESSTOKEN", refresh_token=None)
    client = GraphQLClient(
        settings,
        tokens,
        context=Context(
            child_id="childX",
            preschool_id="preX",
            year_id="yearX",
            locale="pl",
        ),
    )

    with respx.mock:
        route = respx.post(settings.api_url).mock(
            return_value=Response(200, json={"data": {"ok": True}})
        )
        _ = await client.execute("query { ok }")

    assert route.called
    cookie_header = route.calls.last.request.headers.get("cookie", "")
    assert "active_child=childX" in cookie_header
    assert "preschool=preX" in cookie_header
    assert "active_year=yearX" in cookie_header
    assert "locale=pl" in cookie_header
