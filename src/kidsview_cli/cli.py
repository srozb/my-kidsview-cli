# ruff: noqa: B008
from __future__ import annotations

import asyncio
import json
from collections.abc import Coroutine
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table

from . import queries
from .auth import AuthClient, AuthError
from .client import ApiError, GraphQLClient
from .config import Settings
from .context import Context, ContextStore
from .download import download_all
from .session import AuthTokens, SessionStore

app = typer.Typer(help="Kidsview CLI for humans and automation.")
console = Console()


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


def _prompt_choice(options: list[dict[str, Any]], title: str, label_key: str) -> str | None:
    """Interactively select an ID from a list of dicts; returns selected id or None if empty."""
    if not options:
        return None
    if len(options) == 1:
        return str(options[0].get("id"))

    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Name")
    for idx, item in enumerate(options, start=1):
        table.add_row(str(idx), str(item.get(label_key, "")))
    console.print(table)
    choice = typer.prompt(f"Choose a number 1-{len(options)}", type=int)
    if 1 <= choice <= len(options):
        return str(options[choice - 1].get("id"))
    console.print("[red]Invalid choice.[/red]")
    raise typer.Exit(code=1)


def _fetch_me(settings: Settings, tokens: Any, ctx: Context | None) -> dict[str, Any]:
    return _execute_graphql(settings, tokens, queries.ME, {}, ctx, label="me")


def _fetch_years(settings: Settings, tokens: Any, ctx: Context | None) -> dict[str, Any]:
    return _execute_graphql(settings, tokens, queries.YEARS, {}, ctx, label="years")


def _load_tokens(settings: Settings) -> AuthTokens:
    store = SessionStore(settings.session_file)
    tokens = store.load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)
    return tokens


def _execute_graphql(  # noqa: PLR0913
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
                    refreshed = _run(AuthClient(settings).refresh(current_tokens.refresh_token))
                    store.save(refreshed)
                    current_tokens = refreshed
                    attempts += 1
                    continue
                except AuthError as auth_exc:
                    console.print(f"[red]Refresh failed:[/red] {auth_exc}")
                    raise typer.Exit(code=1) from auth_exc
            break

    if settings.debug and last_error:
        console.print(f"[red]{label} error (debug):[/red] {last_error}")
    else:
        console.print(
            f"[red]{label} failed.[/red] "
            f"Try `kidsview-cli refresh` or re-login. Set KIDSVIEW_DEBUG=1 for raw error."
        )
    raise typer.Exit(code=1) from last_error


@app.command()
def login(
    username: str = typer.Option(..., prompt=True, help="Kidsview username (email)."),
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, help="Kidsview password (hidden)."
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist tokens to the session file."),
    json_output: bool = typer.Option(
        False, "--json", help="Print tokens as JSON (automation-friendly)."
    ),
) -> None:
    """Authenticate with Kidsview and cache tokens."""
    settings = Settings()
    client = AuthClient(settings)
    store = SessionStore(settings.session_file)

    try:
        tokens = _run(client.login(username, password))
    except AuthError as exc:  # pragma: no cover - CLI level handling
        console.print(f"[red]Login failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if save:
        store.save(tokens)
        console.print(f"[green]Authenticated.[/green] Tokens saved to {store.path}")
    if json_output or not save:
        console.print_json(data=tokens.model_dump())


@app.command()
def refresh(
    json_output: bool = typer.Option(False, "--json", help="Print refreshed tokens as JSON."),
) -> None:
    """Refresh tokens using the cached refresh token."""
    settings = Settings()
    store = SessionStore(settings.session_file)
    tokens = store.load()

    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)
    if not tokens.refresh_token:
        console.print("[red]No refresh token available in session cache.[/red]")
        raise typer.Exit(code=1)

    client = AuthClient(settings)
    try:
        new_tokens = _run(client.refresh(tokens.refresh_token))
    except AuthError as exc:  # pragma: no cover - CLI level handling
        console.print(f"[red]Refresh failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    store.save(new_tokens)
    console.print(f"[green]Tokens refreshed.[/green] Saved to {store.path}")
    if json_output:
        console.print_json(data=new_tokens.model_dump())


@app.command()
def session(show_tokens: bool = typer.Option(False, "--show-tokens")) -> None:
    """Show session file location and optionally the cached tokens."""
    settings = Settings()
    store = SessionStore(settings.session_file)
    tokens = store.load()

    console.print(f"Session file: {store.path}")
    if not tokens:
        console.print("No cached tokens.")
        return
    if show_tokens:
        console.print_json(data=tokens.model_dump())
    else:
        console.print("Tokens cached. Use --show-tokens to display them.")


@app.command()
def graphql(
    query: str = typer.Option(..., "--query", "-q", help="GraphQL query string or @file path."),
    variables: str | None = typer.Option(
        None, "--vars", "-v", help="Variables as JSON string (e.g. '{\"id\":1}')."
    ),
    json_output: bool = typer.Option(True, "--json/--no-json", help="Print response as JSON."),
) -> None:
    """Execute a GraphQL query against Kidsview backend using cached tokens."""
    settings = Settings()
    tokens = _load_tokens(settings)
    ctx = ContextStore(settings.context_file).load()

    # Support @file syntax for queries.
    if query.startswith("@"):
        path = Path(query[1:])
        if not path.exists():
            console.print(f"[red]Query file not found:[/red] {path}")
            raise typer.Exit(code=1)
        query_text = path.read_text()
    else:
        query_text = query

    variables_payload = None
    if variables:
        try:
            variables_payload = json.loads(variables)
        except json.JSONDecodeError as exc:
            console.print(f"[red]Invalid JSON for variables:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    result = _execute_graphql(settings, tokens, query_text, variables_payload, ctx)

    if json_output:
        console.print_json(data=result)
    else:
        console.print(Pretty(result))


@app.command()
def announcements(
    first: int = typer.Option(10, help="Number of announcements to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    status: str = typer.Option("ACTIVE", help="AnnouncementStatus value."),
    phrase: str = typer.Option("", help="Search phrase."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch announcements."""
    settings = Settings()
    tokens = _load_tokens(settings)
    variables = {"first": first, "after": after, "status": status, "phrase": phrase}
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.ANNOUNCEMENTS, variables, context, label="announcements"
    )
    payload = {"announcements": data.get("announcements")}
    if json_output:
        console.print_json(data=payload)
    else:
        edges = (payload.get("announcements") or {}).get("edges") or []
        if not edges:
            console.print("No announcements.")
            return
        table = Table(title="Announcements", show_lines=True)
        table.add_column("Title")
        table.add_column("Text")
        table.add_column("Created")
        table.add_column("Author")
        preview_len = 120
        for item in edges:
            node = item.get("node", {})
            text = node.get("text", "")
            preview = str(text)[:preview_len]
            if text and len(str(text)) > preview_len:
                preview += "..."
            table.add_row(
                str(node.get("title", "")),
                preview,
                str(node.get("created", "")),
                str((node.get("createdBy") or {}).get("fullName", "")),
            )
        console.print(table)


@app.command()
def monthly_bills(  # noqa: PLR0913
    year: str = typer.Option("", help="Year node ID (e.g., WWVhck5vZGU6MjM4OA==)."),
    child: str | None = typer.Option(None, help="Child ID."),
    is_paid: bool | None = typer.Option(True, help="Filter by paid status."),
    first: int = typer.Option(10, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch monthly bills."""
    settings = Settings()
    tokens = _load_tokens(settings)
    variables = {
        "year": year,
        "child": child,
        "isPaid": is_paid,
        "first": first,
        "after": after,
    }
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.MONTHLY_BILLS, variables, context, label="monthly_bills"
    )
    payload = {"monthlyBills": data.get("monthlyBills")}
    if json_output:
        console.print_json(data=payload)
    else:
        bills_raw = payload.get("monthlyBills") or {}
        bills: dict[str, Any] = bills_raw if isinstance(bills_raw, dict) else {}
        edges = bills.get("edges") or []
        total_balance = bills.get("totalBalance", "")
        total = str(total_balance)
        table = Table(title=f"Monthly bills (total balance: {total})")
        table.add_column("Payment due")
        table.add_column("Child")
        table.add_column("Full amount")
        table.add_column("Paid amount")
        table.add_column("Balance")
        for item in edges:
            node_raw = item.get("node", {})
            node: dict[str, Any] = node_raw if isinstance(node_raw, dict) else {}
            child_raw = node.get("child") or {}
            child_info: dict[str, Any] = child_raw if isinstance(child_raw, dict) else {}
            table.add_row(
                str(node.get("paymentDueTo", "")),
                f"{child_info.get('name','')} {child_info.get('surname','')}".strip(),
                str(node.get("fullAmount", "")),
                str(node.get("paidAmount", "")),
                str(node.get("balance", "")),
            )
        console.print(table)


@app.command()
def galleries(  # noqa: PLR0913
    group_id: str | None = typer.Option(None, help="Group ID filter."),
    first: int = typer.Option(3, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    search: str = typer.Option("", help="Search phrase."),
    order: str | None = typer.Option(None, help="Order string."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch galleries."""
    settings = Settings()
    tokens = _load_tokens(settings)

    variables: dict[str, object] = {
        "groupId": group_id,
        "first": first,
        "after": after,
        "search": search,
        "order": order,
    }
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.GALLERIES, variables, context, label="galleries"
    )
    payload = {"galleries": data.get("galleries")}
    if json_output:
        console.print_json(data=payload)
    else:
        edges = (payload.get("galleries") or {}).get("edges") or []
        if not edges:
            console.print("No galleries.")
            return
        table = Table(title="Galleries", show_lines=True)
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Created")
        table.add_column("Images")
        for item in edges:
            node = item.get("node", {})
            table.add_row(
                str(node.get("id", "")),
                str(node.get("name", "")),
                str(node.get("created", "")),
                str(node.get("imagesCount", "")),
            )
        console.print(table)


@app.command()
def gallery_download(  # noqa: B008
    ids: str = typer.Option("", "--ids", help="Comma-separated gallery IDs."),
    all_: bool = typer.Option(False, "--all", help="Download all galleries not yet downloaded."),
    output_dir: Path = typer.Option("galleries", help="Output directory for downloads."),
) -> None:
    """Download gallery images."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    dest = Path(output_dir).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not all_ and not id_list:
        console.print("[red]Provide at least one --id or use --all.[/red]")
        raise typer.Exit(code=1)

    try:
        downloaded = _run(
            download_all(
                settings=settings,
                tokens=tokens,
                context=context,
                gallery_ids=id_list,
                output_dir=dest,
                skip_downloaded=all_,
            )
        )
    except Exception as exc:  # pragma: no cover - network/file errors
        console.print(f"[red]Download failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not downloaded:
        console.print("No galleries downloaded (all already present?).")
        return

    console.print("Downloaded galleries:")
    for path in downloaded:
        console.print(f"- {path}")


@app.command()
def active_child(
    detailed: bool = typer.Option(False, "--detailed/--summary", help="Return detailed data."),
    date_from: str | None = typer.Option(
        None, help="Start date (YYYY-MM-DD) for daily activities."
    ),
    date_to: str | None = typer.Option(None, help="End date (YYYY-MM-DD) for daily activities."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch active child summary or detailed info (requires date range)."""
    settings = Settings()
    tokens = SessionStore(settings.session_file).load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)

    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    if detailed:
        if not date_from or not date_to:
            console.print("[red]date_from and date_to are required for detailed view.[/red]")
            raise typer.Exit(code=1)
        variables = {"dateFrom": date_from, "dateTo": date_to}
        query = queries.ACTIVE_CHILD_DETAIL
    else:
        variables = {}
        query = queries.ACTIVE_CHILD_SUMMARY

    try:
        data = asyncio.run(client.execute(query, variables))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"activeChild": data.get("activeChild")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def chat_users(
    user_types: str = typer.Option("", help="Comma-separated user types; empty for all."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch users available for chat."""
    settings = Settings()
    tokens = SessionStore(settings.session_file).load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)

    types_list = [u for u in user_types.split(",") if u] if user_types else []
    variables = {"userTypes": types_list}
    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.USERS_FOR_CHAT, variables))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"usersForChat": data.get("usersForChat")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def chat_search(
    search: str = typer.Option("", help="Search phrase for chat groups/children/parents."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Search chat groups and parents (groupsForChat)."""
    settings = Settings()
    tokens = SessionStore(settings.session_file).load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)

    variables = {"search": search or None}
    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.GROUPS_FOR_CHAT, variables))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"groupsForChat": data.get("groupsForChat")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def chat_send(
    recipients: str = typer.Option(
        ..., help="Comma-separated recipient IDs (e.g., S2lkc1ZpZXdCYXNlVXNlck5vZGU6Nzc5MzI=)."
    ),
    text: str = typer.Option(..., help="Message text."),
    name: str | None = typer.Option(None, help="Optional thread name."),
    parents_mutual_visibility: bool = typer.Option(
        False, "--parents-visible/--parents-hidden", help="Parents mutual visibility flag."
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Send a chat message (creates a thread)."""
    settings = Settings()
    tokens = SessionStore(settings.session_file).load()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)

    recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
    variables = {
        "input": {
            "message": {"text": text, "attachment": None},
            "recipients": recipient_list,
            "name": name,
            "parentsMutualVisibility": parents_mutual_visibility,
        }
    }
    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.CREATE_THREAD, variables))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"createThread": data.get("createThread")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def meals(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    """Fetch current diet info for active child."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(settings, tokens, queries.CURRENT_DIET, {}, context, label="meals")
    payload = {"currentDietForChild": data.get("currentDietForChild")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def observations(
    child_id: str | None = typer.Option(None, help="Child ID; defaults to context child."),
    activity_id: str | None = typer.Option(None, help="Additional activity ID filter."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch observations for additional activities for a child."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    effective_child = child_id or (context.child_id if context else None)
    if not effective_child:
        console.print("[red]Child ID is required (set via --child-id or context).[/red]")
        raise typer.Exit(code=1)

    variables: dict[str, object] = {
        "childId": effective_child,
        "id": activity_id,
    }
    data = _execute_graphql(
        settings, tokens, queries.ADDITIONAL_ACTIVITY_OBS, variables, context, label="observations"
    )
    payload = {
        "additionalActivities": data.get("additionalActivities"),
        "child": data.get("child"),
    }
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def notifications(
    first: int = typer.Option(20, help="Number of notifications to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    pending: bool | None = typer.Option(None, help="Pending filter (true/false)."),
    type_filter: str | None = typer.Option(
        None, "--type", help="Notification type (e.g., NEW_GALLERY, UPCOMING_EVENT, NEW_EVENT)."
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch notifications."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "pending": pending,
    }
    data = _execute_graphql(
        settings, tokens, queries.NOTIFICATIONS, variables, context, label="notifications"
    )
    notif = data.get("notifications") or {}
    edges = notif.get("edges") or []
    if type_filter:
        type_value = type_filter.upper()
        edges = [item for item in edges if (item.get("node") or {}).get("type") == type_value]
        notif = {**notif, "edges": edges}
    payload = {"notifications": notif}
    if json_output:
        console.print_json(data=payload)
    else:
        edges = (payload.get("notifications") or {}).get("edges") or []
        if not edges:
            console.print("No notifications.")
            return
        table = Table(title="Notifications")
        table.add_column("Text")
        table.add_column("Type")
        table.add_column("Date")
        table.add_column("Read")
        table.add_column("On date")
        for item in edges:
            node = item.get("node", {})
            data_json = node.get("data")
            data_date = None
            if isinstance(data_json, str):
                with suppress(Exception):
                    parsed = json.loads(data_json)
                    data_date = parsed.get("date")
            table.add_row(
                str(node.get("text", "")),
                str(node.get("type", "")),
                str(node.get("notifyOn", "")),
                "yes" if node.get("isRead") else "no",
                str(data_date) if data_date else "-",
            )
        console.print(table)


@app.command()
def applications(
    phrase: str = typer.Option("", help="Search phrase."),
    status: str | None = typer.Option(None, help="Application status filter."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch applications (wnioski)."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {"phrase": phrase or None, "status": status}
    data = _execute_graphql(
        settings, tokens, queries.APPLICATIONS, variables, context, label="applications"
    )
    payload = {"applications": data.get("applications")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def me(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    """Fetch current user profile and context."""
    settings = Settings()
    tokens = _load_tokens(settings)

    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.ME))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"me": data.get("me")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def colors(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    """Fetch available preschools and color scheme."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.COLORS))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"colors": data}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def unread(json_output: bool = typer.Option(True, "--json/--no-json")) -> None:
    """Fetch unread notification/message counts."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    client = GraphQLClient(settings, tokens, context=context)
    try:
        data = asyncio.run(client.execute(queries.UNREAD_COUNTS))
    except ApiError as exc:
        console.print(f"[red]GraphQL error:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    payload = {"unreadCounts": data.get("me")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def calendar(  # noqa: PLR0913
    date_from: str = typer.Option(
        "today", help="Start date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    date_to: str = typer.Option(
        "today", help="End date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    groups_ids: str = typer.Option("", help="Comma-separated group IDs."),
    activity_types: str = typer.Option("0,1,5,9", help="Comma-separated activity type ints."),
    show_canceled: bool | None = typer.Option(None, help="Include canceled activities."),
    for_schedule: bool | None = typer.Option(None, help="For schedule flag."),
    activity_id: str | None = typer.Option(None, help="Specific activity ID."),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Fetch calendar entries."""
    settings = Settings()
    tokens = _load_tokens(settings)

    groups_list = [g for g in groups_ids.split(",") if g] if groups_ids else []
    activity_type_list = (
        [int(x) for x in activity_types.split(",") if x.strip()] if activity_types else None
    )

    def _normalize_date(value: str) -> str:
        value = value.strip().lower()
        if value == "today":
            return date.today().isoformat()
        if value == "tomorrow":
            return (date.today() + timedelta(days=1)).isoformat()
        if value == "yesterday":
            return (date.today() - timedelta(days=1)).isoformat()
        return value

    variables: dict[str, object] = {
        "groupsIds": groups_list or None,
        "dateFrom": _normalize_date(date_from),
        "dateTo": _normalize_date(date_to),
        "activityTypes": activity_type_list,
        "showCanceledActivities": show_canceled,
        "forSchedule": for_schedule,
        "activityId": activity_id,
    }
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.CALENDAR, variables, context, label="calendar"
    )
    payload = {"calendar": data.get("calendar")}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


@app.command()
def context(  # noqa: PLR0913, PLR0912, PLR0915
    child_id: str | None = typer.Option(None, help="Child ID (active_child)."),
    preschool_id: str | None = typer.Option(None, help="Preschool ID (preschool)."),
    year_id: str | None = typer.Option(None, help="Year ID (years query)."),
    auto: bool = typer.Option(False, "--auto", help="Pick first available context values."),
    clear: bool = typer.Option(False, "--clear", help="Clear saved context."),
    interactive: bool = typer.Option(
        True, "--interactive/--no-interactive", help="Interactive selection with prompts."
    ),
    json_output: bool = typer.Option(True, "--json/--no-json"),
) -> None:
    """Set/show context (preschool, child, year) used to build cookies automatically."""
    settings = Settings()
    store = SessionStore(settings.session_file)
    tokens = store.load()
    ctx_store = ContextStore(settings.context_file)

    if clear:
        ctx_store.delete()
        console.print("[green]Context cleared.[/green]")
        return

    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login`.[/red]")
        raise typer.Exit(code=1)

    ctx = ctx_store.load() or Context()

    if auto:
        try:
            me_data = _fetch_me(settings, tokens, ctx)
        except ApiError as exc:
            console.print(f"[red]GraphQL error (auto context / me):[/red] {exc}")
            raise typer.Exit(code=1) from exc
        me_payload: dict[str, Any] = me_data.get("me", {}) if isinstance(me_data, dict) else {}
        children = me_payload.get("children") or []
        preschools = me_payload.get("availablePreschools") or []
        if children and ctx.child_id is None:
            ctx.child_id = (
                _prompt_choice(children, "Children", "name")
                if interactive
                else children[0].get("id")
            )
        if preschools and ctx.preschool_id is None:
            ctx.preschool_id = (
                _prompt_choice(preschools, "Preschools", "name")
                if interactive
                else preschools[0].get("id")
            )

        # Fetch years after preschool is chosen (backend wymaga preschool w sesji).
        try:
            years_data = _fetch_years(settings, tokens, ctx)
        except ApiError as exc:
            console.print(f"[red]GraphQL error (auto context / years):[/red] {exc}")
            raise typer.Exit(code=1) from exc
        years_payload: dict[str, Any] = years_data if isinstance(years_data, dict) else {}
        years_list = years_payload.get("years") or []
        if years_list and ctx.year_id is None:
            ctx.year_id = (
                _prompt_choice(years_list, "Lata", "displayName")
                if interactive
                else years_list[0].get("id")
            )

    # Manual overrides
    if child_id:
        ctx.child_id = child_id
    if preschool_id:
        ctx.preschool_id = preschool_id
    if year_id:
        ctx.year_id = year_id

    ctx_store.save(ctx)
    payload = {"context": ctx.model_dump()}
    if json_output:
        console.print_json(data=payload)
    else:
        console.print(Pretty(payload))


if __name__ == "__main__":
    app()
