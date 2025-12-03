from datetime import date, timedelta
from unittest.mock import patch

import pytest
import typer

from kidsview_cli.auth import AuthError
from kidsview_cli.client import ApiError
from kidsview_cli.config import Settings
from kidsview_cli.helpers import execute_graphql, normalize_date, prompt_choice, prompt_multi_choice
from kidsview_cli.session import AuthTokens


def test_normalize_date():
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    assert normalize_date("today") == today
    assert normalize_date("tomorrow") == tomorrow
    assert normalize_date("yesterday") == yesterday
    assert normalize_date("2023-01-01") == "2023-01-01"


def test_prompt_multi_choice_parsing(capsys):
    options = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    # Valid single choice
    with patch("typer.prompt", return_value="1"):
        assert prompt_multi_choice(options, "Title", "name") == ["1"]

    # Valid multiple choice
    with patch("typer.prompt", return_value="1, 2"):
        assert prompt_multi_choice(options, "Title", "name") == ["1", "2"]

    # Out of range
    with patch("typer.prompt", return_value="3"), pytest.raises(typer.Exit):
        prompt_multi_choice(options, "Title", "name")

    # Invalid input
    with patch("typer.prompt", return_value="abc"), pytest.raises(typer.Exit):
        prompt_multi_choice(options, "Title", "name")


def test_prompt_choice_parsing():
    options = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

    # Single option auto-select
    assert prompt_choice([options[0]], "Title", "name") == "1"

    # Valid choice
    with patch("typer.prompt", return_value=2):
        assert prompt_choice(options, "Title", "name") == "2"

    # Out of range
    with patch("typer.prompt", return_value=3), pytest.raises(typer.Exit):
        prompt_choice(options, "Title", "name")


@patch("kidsview_cli.helpers.GraphQLClient")
@patch("kidsview_cli.helpers.AuthClient")
@patch("kidsview_cli.helpers.SessionStore")
def test_execute_graphql_retry_success(mock_store_cls, mock_auth_cls, mock_gql_cls):
    settings = Settings(session_file="sess.json")
    tokens = AuthTokens(id_token="ID", access_token="ACC", refresh_token="REF")

    # Mock GraphQL client to fail first, then succeed
    mock_gql_instance = mock_gql_cls.return_value

    async def async_execute_fail(*args, **kwargs):
        raise ApiError("401 Unauthorized")

    async def async_execute_success(*args, **kwargs):
        return {"data": "success"}

    mock_gql_instance.execute.side_effect = [async_execute_fail(), async_execute_success()]

    # Mock Auth refresh to succeed
    mock_auth_instance = mock_auth_cls.return_value
    new_tokens = AuthTokens(id_token="NEW_ID", access_token="NEW_ACC", refresh_token="REF")

    # Since AuthClient.refresh is async, we need to mock it to return a coroutine
    async def async_refresh(*args, **kwargs):
        return new_tokens

    mock_auth_instance.refresh.side_effect = async_refresh

    result = execute_graphql(settings, tokens, "query", {}, None)

    assert result == {"data": "success"}
    assert mock_gql_instance.execute.call_count == 2
    mock_auth_instance.refresh.assert_called_once()
    mock_store_cls.return_value.save.assert_called_once_with(new_tokens)


@patch("kidsview_cli.helpers.GraphQLClient")
@patch("kidsview_cli.helpers.AuthClient")
def test_execute_graphql_retry_failure(mock_auth_cls, mock_gql_cls):
    settings = Settings(session_file="sess.json")
    tokens = AuthTokens(id_token="ID", access_token="ACC", refresh_token="REF")

    # Mock GraphQL client to fail
    mock_gql_instance = mock_gql_cls.return_value
    mock_gql_instance.execute.side_effect = ApiError("401 Unauthorized")

    # Mock Auth refresh to fail
    mock_auth_instance = mock_auth_cls.return_value

    async def async_refresh_fail(*args, **kwargs):
        raise AuthError("Refresh failed")

    mock_auth_instance.refresh.side_effect = async_refresh_fail

    with pytest.raises(typer.Exit):
        execute_graphql(settings, tokens, "query", {}, None)
