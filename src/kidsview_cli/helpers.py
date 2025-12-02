from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import queries
from .auth import AuthClient, AuthError
from .client import ApiError, GraphQLClient
from .config import Settings
from .context import Context, ContextStore
from .session import AuthTokens, SessionStore

console = Console()


def run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def print_table(
    title: str, rows: Sequence[Sequence[str]], headers: Sequence[str], *, show_lines: bool = False
) -> None:
    table = Table(title=title, show_lines=show_lines)
    for h in headers:
        table.add_column(h)
    for row in rows:
        table.add_row(*[str(x) for x in row])
    console.print(table)


def fetch_me(settings: Settings, tokens: Any, ctx: Context | None) -> dict[str, Any]:
    return execute_graphql(settings, tokens, queries.ME, {}, ctx, label="me")


def fetch_years(settings: Settings, tokens: Any, ctx: Context | None) -> dict[str, Any]:
    return execute_graphql(settings, tokens, queries.YEARS, {}, ctx, label="years")


def load_tokens(settings: Settings) -> AuthTokens:
    store = SessionStore(settings.session_file)
    tokens = store.load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)
    return tokens


def execute_graphql(  # noqa: PLR0913
    settings: Settings,
    tokens: AuthTokens,
    query: str,
    variables: dict[str, Any] | None,
    ctx: Context | None,
    label: str = "GraphQL",
) -> dict[str, Any]:
    """Execute a GraphQL query, auto-refreshing token once on failure."""
    store = SessionStore(settings.session_file)
    attempts = 0
    current_tokens = tokens
    last_error: ApiError | None = None

    max_attempts = 2
    while attempts < max_attempts:
        client = GraphQLClient(settings, current_tokens, context=ctx)
        try:
            data = asyncio.run(client.execute(query, variables))
            return data if isinstance(data, dict) else {}
        except ApiError as exc:
            last_error = exc
            if attempts == 0 and current_tokens.refresh_token:
                console.print("[yellow]Request failed, trying token refresh...[/yellow]")
                try:
                    refreshed = run(AuthClient(settings).refresh(current_tokens.refresh_token))
                    store.save(refreshed)
                    current_tokens = refreshed
                    attempts += 1
                    continue
                except AuthError as auth_exc:
                    console.print(f"[red]Refresh failed:[/red] {auth_exc}")
                    raise typer.Exit(code=1) from auth_exc
            break

    if last_error:
        msg = str(last_error)
        lower_msg = msg.lower()
        permission_hint = (
            "permission" in lower_msg or "odmowa dost" in lower_msg or "brak uprawnie" in lower_msg
        )
        if settings.debug:
            console.print(f"[red]{label} error (debug):[/red] {msg}")
        elif permission_hint:
            console.print(
                f"[red]{label} failed: access denied or insufficient permissions.[/red] "
                f"Server message: {msg}"
            )
        else:
            console.print(
                f"[red]{label} failed.[/red] "
                f"Try `kidsview-cli refresh` or re-login. Set KIDSVIEW_DEBUG=1 for raw error."
            )
    raise typer.Exit(code=1) from last_error


def env() -> tuple[Settings, AuthTokens, Context | None]:
    settings = Settings()
    tokens = load_tokens(settings)
    ctx = ContextStore(settings.context_file).load()
    return settings, tokens, ctx


def run_query_table(  # noqa: PLR0913
    *,
    query: str,
    variables: dict[str, Any] | None,
    label: str,
    json_output: bool,
    empty_msg: str,
    headers: Sequence[str],
    title: str | Callable[[dict[str, Any]], str],
    rows_fn: Callable[[dict[str, Any]], list[Sequence[str]]],
    show_lines: bool = False,
) -> None:
    """Execute a query and render either JSON or table using a row builder."""
    settings, tokens, context = env()
    payload_data = execute_graphql(settings, tokens, query, variables or {}, context, label=label)
    payload = {label: payload_data.get(label)}
    if json_output:
        console.print_json(data=payload)
        return
    rows = rows_fn(payload)
    if not rows:
        console.print(empty_msg)
        return
    title_val = title(payload) if callable(title) else title
    print_table(title_val, rows, headers, show_lines=show_lines)
