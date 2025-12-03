import asyncio
from unittest.mock import patch

import pytest

from kidsview_cli.auth import AuthClient, AuthError
from kidsview_cli.config import Settings


def test_login_missing_user_pool_id():
    settings = Settings(user_pool_id="")
    client = AuthClient(settings)
    with pytest.raises(AuthError, match="Missing user pool ID"):
        # login is async, so we need to run it or mock the sync call if we are testing the wrapper
        # The wrapper calls _login_sync in a thread.
        # Let's test _login_sync directly if we want to avoid asyncio overhead,
        # OR run the async method.
        # The error is raised in the async wrapper BEFORE threads.
        asyncio.run(client.login("user", "pass"))


def test_login_failure_raises_auth_error():
    settings = Settings(user_pool_id="pool", client_id="client", region="region")
    client = AuthClient(settings)

    with patch("kidsview_cli.auth.Cognito") as mock_cognito:
        mock_instance = mock_cognito.return_value
        mock_instance.authenticate.side_effect = Exception("Cognito error")

        with pytest.raises(AuthError, match="Cognito error"):
            client._login_sync("user", "pass")


def test_refresh_missing_user_pool_id():
    settings = Settings(user_pool_id="")
    client = AuthClient(settings)
    with pytest.raises(AuthError, match="Missing user pool ID"):
        asyncio.run(client.refresh("token"))


def test_refresh_failure_raises_auth_error():
    settings = Settings(user_pool_id="pool", client_id="client", region="region")
    client = AuthClient(settings)

    with patch("kidsview_cli.auth.Cognito") as mock_cognito:
        mock_instance = mock_cognito.return_value
        mock_instance.renew_access_token.side_effect = Exception("Refresh failed")

        with pytest.raises(AuthError, match="Refresh failed"):
            client._refresh_sync("token")
