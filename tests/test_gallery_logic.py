from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from kidsview_cli.cli import app

runner = CliRunner()


@patch("kidsview_cli.commands.galleries._env")
@patch("kidsview_cli.commands.galleries._fetch_me")
@patch("kidsview_cli.commands.galleries.download_all")
@patch("kidsview_cli.commands.galleries._run")
def test_gallery_download_resolves_child_name(
    mock_run, mock_download, mock_fetch_me, mock_env, tmp_path
):
    # Setup mocks
    settings = MagicMock()
    settings.download_dir = str(tmp_path)
    tokens = MagicMock()
    context = MagicMock()
    context.child_id = "child1"
    mock_env.return_value = (settings, tokens, context)

    # Mock me response with child name
    mock_fetch_me.return_value = {
        "me": {
            "children": [
                {"id": "child1", "name": "John", "surname": "Doe"},
                {"id": "child2", "name": "Jane", "surname": "Doe"},
            ]
        }
    }

    # Run command
    result = runner.invoke(app, ["gallery-download", "--id", "1"])

    assert result.exit_code == 0

    # Verify download_all called with resolved child name
    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args[1]
    assert call_kwargs["child_name"] == "John Doe"
    assert call_kwargs["gallery_ids"] == ["1"]


@patch("kidsview_cli.commands.galleries._env")
@patch("kidsview_cli.commands.galleries._fetch_me")
@patch("kidsview_cli.commands.galleries.download_all")
@patch("kidsview_cli.commands.galleries._run")
def test_gallery_download_fallback_child_id(
    mock_run, mock_download, mock_fetch_me, mock_env, tmp_path
):
    # Setup mocks
    settings = MagicMock()
    settings.download_dir = str(tmp_path)
    tokens = MagicMock()
    context = MagicMock()
    context.child_id = "child1"
    mock_env.return_value = (settings, tokens, context)

    # Mock me response failing or empty
    mock_fetch_me.side_effect = Exception("API Error")

    # Run command
    result = runner.invoke(app, ["gallery-download", "--id", "1"])

    assert result.exit_code == 0

    # Verify download_all called with child ID as fallback
    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args[1]
    assert call_kwargs["child_name"] == "child1"


@patch("kidsview_cli.commands.galleries._env")
@patch("kidsview_cli.commands.galleries.download_all")
@patch("kidsview_cli.commands.galleries._run")
def test_gallery_download_all_flag(mock_run, mock_download, mock_env, tmp_path):
    # Setup mocks
    settings = MagicMock()
    settings.download_dir = str(tmp_path)
    tokens = MagicMock()
    context = MagicMock()
    context.child_id = None  # No context
    mock_env.return_value = (settings, tokens, context)

    # Run command
    result = runner.invoke(app, ["gallery-download", "--all"])

    assert result.exit_code == 0

    # Verify download_all called with skip_downloaded=True (which maps to --all logic in command)
    mock_download.assert_called_once()
    call_kwargs = mock_download.call_args[1]
    assert call_kwargs["skip_downloaded"] is True
    assert call_kwargs["child_name"] is None
