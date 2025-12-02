# ruff: noqa: B008
from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from contextlib import suppress
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
from rich.pretty import Pretty
from rich.table import Table

from . import queries
from .auth import AuthClient, AuthError
from .client import ApiError, GraphQLClient
from .config import Settings
from .context import Context, ContextStore
from .download import download_all, fetch_galleries, make_progress
from .helpers import (
    console,
    run_query_table,
)
from .helpers import (
    env as _env,
)
from .helpers import (
    execute_graphql as _execute_graphql,
)
from .helpers import (
    fetch_me as _fetch_me,
)
from .helpers import (
    fetch_years as _fetch_years,
)
from .helpers import (
    print_table as _print_table,
)
from .helpers import (
    run as _run,
)
from .helpers import (
    truncate as _truncate,
)
from .session import SessionStore

app = typer.Typer(help="Kidsview CLI for humans and automation.")


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


def _prompt_multi_choice(options: list[dict[str, Any]], title: str, label_key: str) -> list[str]:
    """Prompt for one or more selections; returns list of IDs."""
    if not options:
        return []
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("ID")
    for idx, item in enumerate(options, start=1):
        table.add_row(str(idx), str(item.get(label_key, "")), str(item.get("id", "")))
    console.print(table)
    raw = typer.prompt(f"Choose numbers (comma-separated) 1-{len(options)}", type=str)
    picks: list[str] = []
    for raw_part in raw.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            num = int(part)
        except ValueError as err:
            console.print(f"[red]Invalid choice: {part}[/red]")
            raise typer.Exit(code=1) from err
        if 1 <= num <= len(options):
            picks.append(str(options[num - 1].get("id")))
        else:
            console.print(f"[red]Choice out of range: {num}[/red]")
            raise typer.Exit(code=1)
    return picks


LAST_MSG_PREVIEW = 50
TEXT_PREVIEW = 80


def _render_thread_row(node: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    recipients = ", ".join(r.get("fullName", "") for r in (node.get("recipients") or []))
    child = node.get("child") or {}
    child_name = f"{child.get('name','')} {child.get('surname','')}".strip()
    last_msg = str(node.get("lastMessage", "")[:LAST_MSG_PREVIEW])
    name = node.get("name") or last_msg or recipients or child_name or "(no name)"
    return (
        str(node.get("id", "")),
        str(name),
        child_name,
        recipients,
        last_msg + ("..." if len(str(node.get("lastMessage", ""))) > LAST_MSG_PREVIEW else ""),
        str(node.get("type", "")),
        str(node.get("modified", "")),
    )


def _render_threads_table(edges: list[dict[str, Any]], title: str = "💬 Chat threads") -> Table:
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Child")
    table.add_column("Recipients")
    table.add_column("Last message")
    table.add_column("Type")
    table.add_column("Modified")
    for item in edges:
        node = item.get("node", {})
        row = _render_thread_row(node)
        table.add_row(*row)
    return table


def _rows_for_threads(
    edges: list[dict[str, Any]], *, include_id: bool = True
) -> list[Sequence[str]]:
    rows: list[Sequence[str]] = []
    for idx, item in enumerate(edges, start=1):
        node = item.get("node", {}) or {}
        row = _render_thread_row(node)
        if include_id:
            rows.append(row)
        else:
            rows.append(row[1:])  # skip ID
        item["_resolved_id"] = row[0]
        item["_display_index"] = idx
    return rows


def _prompt_thread_selection(edges: list[dict[str, Any]]) -> str:
    """Prompt user to pick a thread from edges; returns thread ID or exits."""
    if not edges:
        console.print("No threads.")
        raise typer.Exit(code=1)
    table = Table(title="Threads")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Child")
    table.add_column("Recipients")
    table.add_column("Last message")
    table.add_column("Type")
    table.add_column("Modified")
    for idx, item in enumerate(edges, start=1):
        node = item.get("node", {}) or {}
        row = _render_thread_row(node)
        table.add_row(str(idx), *row[1:])  # skip ID in display
        item["_resolved_id"] = row[0]
    console.print(table)
    choice = typer.prompt(f"Choose a number 1-{len(edges)}", type=int)
    if 1 <= choice <= len(edges):
        return str(edges[choice - 1].get("_resolved_id", ""))
    console.print("[red]Invalid choice.[/red]")
    raise typer.Exit(code=1)


LAST_MSG_PREVIEW = 50
TEXT_PREVIEW = 80
MONTH_LAST = 12


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
    store = SessionStore(settings.session_file)
    client = AuthClient(settings)

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
def context(  # noqa: PLR0913, PLR0912, PLR0915
    child_id: str | None = typer.Option(None, help="Child ID (active_child)."),
    preschool_id: str | None = typer.Option(None, help="Preschool ID (preschool)."),
    year_id: str | None = typer.Option(None, help="Year ID (years query)."),
    auto: bool = typer.Option(False, "--auto", help="Pick first available context values."),
    clear: bool = typer.Option(False, "--clear", help="Clear saved context."),
    change: bool = typer.Option(
        False, "--change", help="Re-pick context interactively even if already set."
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
    if change:
        # force re-selection
        auto = True
        ctx = Context(locale=ctx.locale)

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
                children[0].get("id")
                if len(children) == 1
                else _prompt_choice(children, "Children", "name")
            )
        if preschools and ctx.preschool_id is None:
            ctx.preschool_id = (
                preschools[0].get("id")
                if len(preschools) == 1
                else _prompt_choice(preschools, "Preschools", "name")
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
                years_list[0].get("id")
                if len(years_list) == 1
                else _prompt_choice(years_list, "Lata", "displayName")
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
        ctx_table = Table(title="🧭 Context", show_header=False)
        ctx_table.add_row("Child ID", str(ctx.child_id or "-"))
        ctx_table.add_row("Preschool ID", str(ctx.preschool_id or "-"))
        ctx_table.add_row("Year ID", str(ctx.year_id or "-"))
        ctx_table.add_row("Locale", str(ctx.locale))
        console.print(ctx_table)


if __name__ == "__main__":
    app()


@app.command()
def me(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:  # noqa: PLR0912, PLR0915
    """Fetch current user profile and context."""
    settings, tokens, context = _env()
    data = _fetch_me(settings, tokens, context)
    payload = {"me": data.get("me")}
    if json_output:
        console.print_json(data=payload)
        return

    me_data: dict[str, Any] = payload.get("me") or {}
    summary = Table(title="🙋 Me", show_header=False)
    summary.add_row("ID", str(me_data.get("id", "")))
    summary.add_row("Full name", str(me_data.get("fullName", "")))
    summary.add_row("Email", str(me_data.get("email", "")))
    summary.add_row("Phone", str(me_data.get("phone", "")))
    summary.add_row("Position", str(me_data.get("userPosition", "")))
    summary.add_row("Type", str(me_data.get("userType", "")))
    unread = []
    if me_data.get("unreadNotificationsCount") is not None:
        unread.append(f"notifications: {me_data['unreadNotificationsCount']}")
    if me_data.get("unreadMessagesCount") is not None:
        unread.append(f"messages: {me_data['unreadMessagesCount']}")
    if unread:
        summary.add_row("Unread", ", ".join(unread))
    console.print(summary)

    children = me_data.get("children") or []
    if children:
        ctable = Table(title="👶 Children")
        ctable.add_column("ID")
        ctable.add_column("Name")
        ctable.add_column("Surname")
        ctable.add_column("Group")
        ctable.add_column("Balance")
        for child in children:
            group_name = (child.get("group") or {}).get("name", "")
            balance = child.get("balance", "")
            ctable.add_row(
                str(child.get("id", "")),
                str(child.get("name", "")),
                str(child.get("surname", "")),
                str(group_name),
                str(balance),
            )
        console.print(ctable)

    preschools = me_data.get("availablePreschools") or []
    if preschools:
        ptable = Table(title="🏫 Preschools")
        ptable.add_column("ID")
        ptable.add_column("Name")
        ptable.add_column("Phone")
        ptable.add_column("Email")
        ptable.add_column("Address")
        for pre in preschools:
            ptable.add_row(
                str(pre.get("id", "")),
                str(pre.get("name", "")),
                str(pre.get("phone", "")),
                str(pre.get("email", "")),
                str(pre.get("address", "")),
            )
        console.print(ptable)

    # Years: prefer data already returned in `me` under the matching preschool; fallback to query
    preschool_id = context.preschool_id if context else None
    if not preschool_id and preschools:
        preschool_id = str((preschools[0] or {}).get("id", "")) or None

    years_list: list[dict[str, Any]] | None = None
    if preschool_id:
        for pre in preschools:
            if str(pre.get("id", "")) == preschool_id:
                edges = (pre.get("years") or {}).get("edges") or []
                years_list = [e.get("node", {}) for e in edges if e.get("node")]
                break
        if not years_list:
            years_ctx = context or Context(preschool_id=preschool_id)
            if years_ctx.preschool_id != preschool_id:
                years_ctx = Context(
                    child_id=years_ctx.child_id,
                    preschool_id=preschool_id,
                    year_id=years_ctx.year_id,
                    locale=years_ctx.locale,
                )
            try:
                years_data = _fetch_years(settings, tokens, years_ctx)
                years_list = years_data.get("years") if isinstance(years_data, dict) else None
            except ApiError:
                years_list = None
    if years_list:
        ytable = Table(title="📆 Years")
        ytable.add_column("ID")
        ytable.add_column("Display")
        ytable.add_column("Start")
        ytable.add_column("End")
        for y in years_list:
            ytable.add_row(
                str(y.get("id", "")),
                str(y.get("displayName", "")),
                str(y.get("startDate", "")),
                str(y.get("endDate", "")),
            )
        console.print(ytable)


def _print_active_child(child: dict[str, Any]) -> None:
    summary = Table(title="👧 Active child", show_header=False)
    preschool = (child.get("preschool") or {}).get("name", "")
    group = (child.get("group") or {}).get("name", "")
    summary.add_row("ID", str(child.get("id", "")))
    summary.add_row("Full name", f"{child.get('name','')} {child.get('surname','')}".strip())
    summary.add_row("Status", str(child.get("status", "")))
    summary.add_row("Preschool", str(preschool))
    summary.add_row("Group", str(group))
    summary.add_row("Balance", str(child.get("balance", "")))
    summary.add_row("Technical account", str(child.get("technicalAccount", "")))
    summary.add_row("Individual number", str(child.get("individualNumber", "")))
    summary.add_row(
        "Contract",
        f"{child.get('contractStartDate','')} → {child.get('contractEndDate','')}".strip(),
    )
    summary.add_row("Diet", str((child.get("dietCategory") or {}).get("name", "")))
    exclusions = ", ".join(e.get("name", "") for e in (child.get("exclusions") or []))
    summary.add_row("Exclusions", exclusions or "-")
    summary.add_row("PIN", str(child.get("pinCode", "")))
    console.print(summary)

    parents = (child.get("parents") or {}).get("edges") or []
    if parents:
        ptable = Table(title="👨‍👩‍👧 Parents/guardians")
        ptable.add_column("Name")
        ptable.add_column("Phone")
        ptable.add_column("Email")
        ptable.add_column("Can pick up")
        ptable.add_column("Legal guardian")
        ptable.add_column("App access")
        ptable.add_column("Limited")
        for edge in parents:
            node = edge.get("node") or {}
            full = f"{node.get('firstName','')} {node.get('lastName','')}".strip()
            ptable.add_row(
                full,
                str(node.get("phone", "")),
                str(node.get("email", "")),
                "yes" if node.get("canPickupChild") else "no",
                "yes" if node.get("isLegalGuardian") else "no",
                "yes" if node.get("hasAppAccess") else "no",
                "yes" if node.get("limitedAccess") else "no",
            )
        console.print(ptable)


@app.command()
def active_child(
    detailed: bool = typer.Option(False, "--detailed/--summary", help="Return detailed data."),
    date_from: str | None = typer.Option(
        None, help="Start date (YYYY-MM-DD) for daily activities."
    ),
    date_to: str | None = typer.Option(None, help="End date (YYYY-MM-DD) for daily activities."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch active child summary or detailed info (requires date range)."""
    settings, tokens, context = _env()
    if not tokens:
        console.print("[red]No session found. Run `kidsview-cli login` first.[/red]")
        raise typer.Exit(code=1)

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
        child = payload.get("activeChild") or {}
        if not child:
            console.print("No active child.")
            return
        _print_active_child(child)


@app.command()
def graphql(
    query: str = typer.Option(..., "--query", "-q", help="GraphQL query string or @file path."),
    variables: str | None = typer.Option(
        None, "--vars", "-v", help="Variables as JSON string (e.g. '{\"id\":1}')."
    ),
    json_output: bool = typer.Option(False, "--json/--no-json", help="Print response as JSON."),
) -> None:
    """Execute a GraphQL query against Kidsview backend using cached tokens."""
    settings, tokens, context = _env()

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

    result = _execute_graphql(settings, tokens, query_text, variables_payload, context)

    if json_output:
        console.print_json(data=result)
    else:
        console.print(Pretty(result))


@app.command()
def notifications(  # noqa: PLR0913, PLR0915
    first: int = typer.Option(20, help="Number of notifications to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    pending: bool | None = typer.Option(None, help="Pending filter (true/false)."),
    type_filter: str | None = typer.Option(
        None, "--type", help="Notification type (e.g., NEW_GALLERY, UPCOMING_EVENT, NEW_EVENT)."
    ),
    only_unread: bool = typer.Option(
        False, "--only-unread", help="Filter to unread notifications (client-side)."
    ),
    mark_read: bool = typer.Option(
        False, "--mark-read", help="Mark fetched notifications as read (uses notificationId)."
    ),
    all_pages: bool = typer.Option(
        False,
        "--all-pages",
        help="Fetch all pages (honors type/pending filters) when marking read.",
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch notifications."""
    settings, tokens, context = _env()
    collected_edges: list[dict[str, Any]] = []
    cursor = after

    def _fetch_page(cur: str | None) -> dict[str, Any]:
        variables: dict[str, object] = {
            "first": first,
            "after": cur,
            "pending": pending,
        }
        return _execute_graphql(
            settings, tokens, queries.NOTIFICATIONS, variables, context, label="notifications"
        )

    # paginate if requested
    while True:
        data = _fetch_page(cursor)
        notif = data.get("notifications") or {}
        edges = notif.get("edges") or []
        if type_filter:
            type_value = type_filter.upper()
            edges = [item for item in edges if (item.get("node") or {}).get("type") == type_value]
        if only_unread:
            edges = [item for item in edges if not (item.get("node") or {}).get("isRead")]
        collected_edges.extend(edges)
        page_info = notif.get("pageInfo") or {}
        if not all_pages or not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")

    payload = {"notifications": {"edges": collected_edges}}
    if json_output:
        console.print_json(data=payload)
    else:
        edges = collected_edges
        if not edges:
            console.print("No notifications.")
            return
        rows = []
        for item in edges:
            node = item.get("node", {})
            data_json = node.get("data")
            data_date = None
            if isinstance(data_json, str):
                with suppress(Exception):
                    parsed = json.loads(data_json)
                    data_date = parsed.get("date")
            rows.append(
                (
                    str(node.get("text", "")),
                    str(node.get("type", "")),
                    str(node.get("notifyOn", "")),
                    "yes" if node.get("isRead") else "no",
                    str(data_date) if data_date else "-",
                )
            )
        headers = ["Text", "Type", "Date", "Read", "On date"]
        _print_table("🔔 Notifications", rows, headers)

    if mark_read and collected_edges:
        mutation = queries.SET_NOTIFICATION_READ
        marked = 0
        for item in collected_edges:
            node = item.get("node") or {}
            notif_id = (node.get("notification") or {}).get("id") or node.get("id")
            if not notif_id:
                continue
            _execute_graphql(
                settings,
                tokens,
                mutation,
                {"notificationId": notif_id},
                context,
                label="setNotificationRead",
            )
            marked += 1
        console.print(f"[green]Marked {marked} notifications as read.[/green]")


def _normalize_date(value: str) -> str:
    value = value.strip().lower()
    if value == "today":
        return date.today().isoformat()
    if value == "tomorrow":
        return (date.today() + timedelta(days=1)).isoformat()
    if value == "yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    return value


@app.command()
def announcements(
    first: int = typer.Option(10, help="Number of announcements to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    status: str = typer.Option("ACTIVE", help="AnnouncementStatus value."),
    phrase: str = typer.Option("", help="Search phrase."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch announcements."""
    variables = {"first": first, "after": after, "status": status, "phrase": phrase}
    headers = ["Title", "Text", "Created", "Author"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        edges = (payload.get("announcements") or {}).get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node = item.get("node", {})
            text = _truncate(str(node.get("text", "")), 120)
            rows_local.append(
                (
                    str(node.get("title", "")),
                    text,
                    str(node.get("created", "")),
                    str((node.get("createdBy") or {}).get("fullName", "")),
                )
            )
        return rows_local

    run_query_table(
        query=queries.ANNOUNCEMENTS,
        variables=variables,
        label="announcements",
        json_output=json_output,
        empty_msg="No announcements.",
        headers=headers,
        title="📢 Announcements",
        rows_fn=_rows,
        show_lines=True,
    )


@app.command("quick-calendar")
def quick_calendar(  # noqa: PLR0913
    date_from: str = typer.Option(
        "today", help="Start date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    date_to: str = typer.Option(
        "today", help="End date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    week: bool = typer.Option(False, "--week", help="Set range to current week."),
    month: bool = typer.Option(False, "--month", help="Set range to current month."),
    days: int | None = typer.Option(None, "--days", help="Set range to N days starting today."),
    groups_ids: str = typer.Option("", help="Comma-separated group IDs."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch quick calendar overview (has events/new/holiday/absent)."""

    def _compute_range() -> tuple[str, str]:
        if days:
            start = date.today()
            end = start + timedelta(days=days)
            return start.isoformat(), end.isoformat()
        if week:
            today = date.today()
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start.isoformat(), end.isoformat()
        if month:
            today = date.today()
            start = today.replace(day=1)
            if start.month == MONTH_LAST:
                end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
            return start.isoformat(), end.isoformat()
        return _normalize_date(date_from), _normalize_date(date_to)

    range_from, range_to = _compute_range()
    variables: dict[str, object] = {
        "groupsIds": [g for g in groups_ids.split(",") if g] or None,
        "dateFrom": range_from,
        "dateTo": range_to,
    }

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        items = payload.get("quickCalendar") or []
        return [
            (
                str(node.get("date", "")),
                "yes" if node.get("hasEvents") else "no",
                "yes" if node.get("hasNewEvents") else "no",
                "yes" if node.get("holiday") else "no",
                "yes" if node.get("absent") else "no",
                "yes" if node.get("mealsModified") else "no",
            )
            for node in items
        ]

    run_query_table(
        query=queries.QUICK_CALENDAR,
        variables=variables,
        label="quickCalendar",
        json_output=json_output,
        empty_msg="No quick calendar entries.",
        headers=["Date", "Has events", "New events", "Holiday", "Absent", "Meals modified"],
        title="📅 Quick calendar",
        rows_fn=_rows,
    )


@app.command()
def calendar(  # noqa: PLR0913
    date_from: str = typer.Option(
        "today", help="Start date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    date_to: str = typer.Option(
        "today", help="End date (YYYY-MM-DD) or 'today'/'tomorrow'/'yesterday'."
    ),
    week: bool = typer.Option(False, "--week", help="Set range to current week (Mon-Sun)."),
    month: bool = typer.Option(False, "--month", help="Set range to current month."),
    days: int | None = typer.Option(None, "--days", help="Set range to N days starting today."),
    groups_ids: str = typer.Option("", help="Comma-separated group IDs."),
    activity_types: str = typer.Option("0,1,5,9", help="Comma-separated activity type ints."),
    show_canceled: bool | None = typer.Option(None, help="Include canceled activities."),
    for_schedule: bool | None = typer.Option(None, help="For schedule flag."),
    activity_id: str | None = typer.Option(None, help="Specific activity ID."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch calendar entries."""
    groups_list = [g for g in groups_ids.split(",") if g] if groups_ids else []
    activity_type_list = (
        [int(x) for x in activity_types.split(",") if x.strip()] if activity_types else None
    )

    def _compute_range() -> tuple[str, str]:
        if days:
            start = date.today()
            end = start + timedelta(days=days)
            return start.isoformat(), end.isoformat()
        if week:
            today = date.today()
            start = today - timedelta(days=today.weekday())
            end = start + timedelta(days=6)
            return start.isoformat(), end.isoformat()
        if month:
            today = date.today()
            start = today.replace(day=1)
            if start.month == MONTH_LAST:
                end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
            return start.isoformat(), end.isoformat()
        return _normalize_date(date_from), _normalize_date(date_to)

    range_from, range_to = _compute_range()

    variables: dict[str, object] = {
        "groupsIds": groups_list or None,
        "dateFrom": range_from,
        "dateTo": range_to,
        "activityTypes": activity_type_list,
        "showCanceledActivities": show_canceled,
        "forSchedule": for_schedule,
        "activityId": activity_id,
    }

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        items = payload.get("calendar") or []
        rows_local: list[Sequence[str]] = []
        for node in items:
            reporter = (node.get("absenceReportedBy") or {}).get("fullName", "")
            rows_local.append(
                (
                    str(node.get("title", "")),
                    str(node.get("startDate", "")),
                    str(node.get("endDate", "")),
                    str(node.get("type", "")),
                    "yes" if node.get("allDay") else "no",
                    str(reporter),
                )
            )
        return rows_local

    run_query_table(
        query=queries.CALENDAR,
        variables=variables,
        label="calendar",
        json_output=json_output,
        empty_msg="No calendar entries.",
        headers=["Title", "Start", "End", "Type", "All day", "Reported by"],
        title=f"Calendar {range_from} to {range_to}",
        rows_fn=_rows,
        show_lines=True,
    )


@app.command()
def schedule(
    group_id: str = typer.Option(..., "--group-id", help="Group ID for schedule (required)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch schedule for a group."""
    variables: dict[str, object] = {"group": group_id}

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        items = payload.get("schedule") or []
        rows: list[Sequence[str]] = []
        for node in items:
            groups = node.get("groupsNames")
            groups_str = ", ".join(groups) if isinstance(groups, list) else str(groups or "")
            rows.append(
                (
                    str(node.get("title", "")),
                    str(node.get("startDate", "")),
                    str(node.get("endDate", "")),
                    "yes" if node.get("allDay") else "no",
                    str(node.get("type", "")),
                    groups_str,
                )
            )
        return rows

    run_query_table(
        query=queries.SCHEDULE,
        variables=variables,
        label="schedule",
        json_output=json_output,
        empty_msg="No schedule entries.",
        headers=["Title", "Start", "End", "All day", "Type", "Groups"],
        title="🗓️ Schedule",
        rows_fn=_rows,
    )


@app.command()
def absence(  # noqa: PLR0913
    child_id: str | None = typer.Option(None, help="Child ID (defaults to context child)."),
    date_val: str = typer.Option(
        "today", "--date", help="Date YYYY-MM-DD or today/tomorrow/yesterday"
    ),
    date_to: str | None = typer.Option(None, "--date-to", help="Optional end date."),
    on_time: bool = typer.Option(True, "--on-time/--not-on-time", help="Reported on time."),
    partial_meal_refund: bool = typer.Option(
        False, "--partial-meal-refund/--no-partial-meal-refund", help="Partial meal refund."
    ),
    force_partial_refund: bool = typer.Option(
        False,
        "--force-partial-meal-refund/--no-force-partial-meal-refund",
        help="Force partial meal refund.",
    ),
    yes: bool = typer.Option(
        False, "--yes", help="Do not prompt for confirmation (use with care)."
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Report child absence (setChildAbsence)."""
    settings, tokens, context = _env()
    effective_child = child_id or (context.child_id if context else None)
    if not effective_child:
        console.print("[red]Child ID required (pass --child-id or set context).[/red]")
        raise typer.Exit(code=1)
    date_from_norm = _normalize_date(date_val)
    date_to_norm = _normalize_date(date_to) if date_to else None
    if not yes:
        range_text = f"{date_from_norm}" + (f" to {date_to_norm}" if date_to_norm else "")
        prompt_msg = (
            f"Report absence for child {effective_child} on {range_text}? "
            f"(on_time={on_time}, partial_refund={partial_meal_refund})"
        )
        typer.confirm(prompt_msg, abort=True)
    variables: dict[str, object] = {
        "childId": effective_child,
        "date": date_from_norm,
        "dateTo": date_to_norm,
        "onTime": on_time,
        "partialMealRefund": partial_meal_refund,
        "forcePartialMealRefund": force_partial_refund,
    }
    data = _execute_graphql(
        settings, tokens, queries.SET_CHILD_ABSENCE, variables, context, label="setChildAbsence"
    )
    if json_output:
        console.print_json(data=data)
    else:
        range_text = f"{date_from_norm}" + (f" to {date_to_norm}" if date_to_norm else "")
        console.print(
            f"[green]Absence reported[/green] for child {effective_child} on {range_text}."
        )


@app.command()
def meals(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """Fetch current diet info for active child."""
    run_query_table(
        query=queries.CURRENT_DIET,
        variables={},
        label="meals",
        json_output=json_output,
        empty_msg="No diet data.",
        headers=["ID", "Body", "Category", "Attachments"],
        title="🍽️ Current diet",
        rows_fn=lambda payload: _rows_diet(payload),
    )


def _rows_diet(payload: dict[str, Any]) -> list[Sequence[str]]:
    diet = payload.get("currentDietForChild") or {}
    items = diet if isinstance(diet, list) else [diet] if diet else []
    rows: list[Sequence[str]] = []
    for item in items:
        attachments = item.get("attachments") or {}
        edges = attachments.get("edges") or []
        attach_ids = [str((edge.get("node") or {}).get("id", "")) for edge in edges]
        rows.append(
            (
                str(item.get("id", "")),
                str(item.get("body", "")),
                str((item.get("category") or {}).get("id", "")),
                ", ".join(attach_ids),
            )
        )
    return rows


@app.command()
def observations(
    child_id: str | None = typer.Option(None, help="Child ID; defaults to context child."),
    activity_id: str | None = typer.Option(None, help="Additional activity ID filter."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch observations for additional activities for a child."""
    settings, tokens, context = _env()
    effective_child = child_id or (context.child_id if context else None)
    if not effective_child:
        console.print("[red]Child ID is required (set via --child-id or context).[/red]")
        raise typer.Exit(code=1)

    variables: dict[str, object] = {
        "childId": effective_child,
        "id": activity_id,
    }

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        activities = payload.get("additionalActivities") or {}
        edges = activities.get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node = item.get("node", {}) or {}
            observations_nodes = (node.get("observations") or {}).get("edges") or []
            obs_public = ", ".join(
                str((obs.get("node") or {}).get("public", "")) for obs in observations_nodes
            )
            rows_local.append(
                (
                    str(node.get("id", "")),
                    str(node.get("name", "")),
                    obs_public,
                )
            )
        return rows_local

    run_query_table(
        query=queries.ADDITIONAL_ACTIVITY_OBS,
        variables=variables,
        label="observations",
        json_output=json_output,
        empty_msg="No observations.",
        headers=["ID", "Name", "Public observations"],
        title="👀 Observations",
        rows_fn=_rows,
    )


@app.command()
def applications(
    phrase: str = typer.Option("", help="Search phrase."),
    status: str | None = typer.Option(None, help="Application status filter."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch applications (wnioski)."""
    variables: dict[str, object] = {"phrase": phrase or None, "status": status}
    headers = ["ID", "Created", "Form name", "Form status", "Status", "Director comment"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        edges = (payload.get("applications") or {}).get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node = item.get("node", {})
            form = node.get("applicationForm") or {}
            rows_local.append(
                (
                    str(node.get("id", "")),
                    str(node.get("created", "")),
                    str(form.get("name", "")),
                    str(form.get("status", "")),
                    str(node.get("status", "")),
                    str(node.get("commentDirector", "")),
                )
            )
        return rows_local

    run_query_table(
        query=queries.APPLICATIONS,
        variables=variables,
        label="applications",
        json_output=json_output,
        empty_msg="No applications.",
        headers=headers,
        title="📝 Applications",
        rows_fn=_rows,
        show_lines=True,
    )


@app.command("application-submit")
def application_submit(
    form_id: str = typer.Option(..., "--form-id", help="Application form ID."),
    comment: str = typer.Option("", "--comment", help="Parent comment."),
    accept_contract: bool = typer.Option(True, "--accept-contract/--no-accept-contract"),
    months: int | None = typer.Option(None, "--months", help="Number of months (if required)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Submit an application (createApplication)."""
    settings, tokens, context = _env()
    variables: dict[str, object] = {
        "applicationFormId": form_id,
        "commentParent": comment or None,
        "acceptContract": accept_contract,
        "months": months,
    }
    data = _execute_graphql(
        settings,
        tokens,
        queries.CREATE_APPLICATION,
        variables,
        context,
        label="createApplication",
    )
    if json_output:
        console.print_json(data=data)
    else:
        result = data.get("createApplication") or {}
        if result.get("success"):
            console.print(f"[green]Application submitted (id={result.get('id')}).[/green]")
        else:
            console.print(f"[red]Submit failed:[/red] {result.get('error')}")


@app.command()
def unread(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """Fetch unread notification/message counts."""
    headers = ["Type", "Count"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        counts = (payload.get("me") or {}) if payload else {}
        return [
            ("Notifications", str(counts.get("unreadNotificationsCount", 0))),
            ("Messages", str(counts.get("unreadMessagesCount", 0))),
        ]

    run_query_table(
        query=queries.UNREAD_COUNTS,
        variables={},
        label="me",
        json_output=json_output,
        empty_msg="No unread counters.",
        headers=headers,
        title="🔔 Unread",
        rows_fn=_rows,
    )


@app.command()
def colors(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """Fetch available preschools and color scheme."""

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        me = payload.get("me") or {}
        preschools = me.get("availablePreschools") or []
        rows_local: list[Sequence[str]] = []
        for ps in preschools:
            colors_info = (ps.get("usercolorSet") or {}) if isinstance(ps, dict) else {}
            rows_local.append(
                (
                    str(ps.get("id", "")),
                    str(ps.get("name", "")),
                    str(colors_info.get("headerColor", "")),
                    str(colors_info.get("backgroundColor", "")),
                    str(colors_info.get("accentColor", "")),
                )
            )
        return rows_local

    run_query_table(
        query=queries.COLORS,
        variables={},
        label="me",
        json_output=json_output,
        empty_msg="No preschools/colors.",
        headers=["ID", "Name", "Header", "Background", "Accent"],
        title="🎨 Colors",
        rows_fn=_rows,
    )


@app.command()
def payments(  # noqa: PLR0913
    date_from: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)."),
    date_to: str | None = typer.Option(None, help="End date (YYYY-MM-DD)."),
    child_id: str | None = typer.Option(None, help="Child ID filter."),
    type_filter: str | None = typer.Option(None, "--type", help="Payment type filter."),
    is_booked: bool | None = typer.Option(None, "--booked/--not-booked", help="Booked flag."),
    first: int = typer.Option(20, help="Number of records."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch payments history."""
    variables: dict[str, object] = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "child": child_id,
        "type": type_filter,
        "isBooked": is_booked,
        "first": first,
        "after": after,
    }
    headers = ["Title", "Amount", "Date", "Type", "Booked", "Child"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        edges = (payload.get("payments") or {}).get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node = item.get("node", {})
            child = node.get("child") or {}
            child_name = f"{child.get('name','')} {child.get('surname','')}".strip()
            rows_local.append(
                (
                    str(node.get("title", "")),
                    str(node.get("amount", "")),
                    str(node.get("paymentDate", "")),
                    str(node.get("type", "")),
                    "yes" if node.get("isBooked") else "no",
                    child_name or "-",
                )
            )
        return rows_local

    run_query_table(
        query=queries.PAYMENTS,
        variables=variables,
        label="payments",
        json_output=json_output,
        empty_msg="No payments.",
        headers=headers,
        title="💳 Payments",
        rows_fn=_rows,
    )


@app.command("payments-summary")
def payments_summary(  # noqa: PLR0913
    search: str = typer.Option("", help="Search phrase."),
    groups_ids: str = typer.Option("", help="Comma-separated group IDs."),
    balance_gte: str | None = typer.Option(None, help="Min balance (Decimal)."),
    balance_lte: str | None = typer.Option(None, help="Max balance (Decimal)."),
    paid_count_gte: int | None = typer.Option(None, help="Min paid monthly bills count."),
    paid_count_lte: int | None = typer.Option(None, help="Max paid monthly bills count."),
    children_first: int = typer.Option(50, help="Number of children to fetch."),
    children_after: str | None = typer.Option(None, help="Cursor for children pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch payments summary (balances per child)."""
    variables: dict[str, object] = {
        "search": search or None,
        "groupsIds": [g for g in groups_ids.split(",") if g] or None,
        "balanceGte": balance_gte,
        "balanceLte": balance_lte,
        "paidMonthlyBillsCountGte": paid_count_gte,
        "paidMonthlyBillsCountLte": paid_count_lte,
        "childrenFirst": children_first,
        "childrenAfter": children_after,
    }

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        summary = payload.get("paymentsSummary") or {}
        children_conn = summary.get("children") or {}
        edges = children_conn.get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node = item.get("node", {}) or {}
            child_name = f"{node.get('name','')} {node.get('surname','')}".strip()
            rows_local.append(
                (
                    child_name or "-",
                    str(node.get("amount", "")),
                    str(node.get("paidAmount", "")),
                    str(node.get("balance", "")),
                    str(node.get("paidMonthlyBillsCount", "")),
                )
            )
        return rows_local

    def _title(payload: dict[str, Any]) -> str:
        summary = payload.get("paymentsSummary") or {}
        return f"💳 Payments summary (full balance: {summary.get('fullBalance','')})"

    run_query_table(
        query=queries.PAYMENTS_SUMMARY,
        variables=variables,
        label="paymentsSummary",
        json_output=json_output,
        empty_msg="No payments summary entries.",
        headers=["Child", "Amount", "Paid", "Balance", "Paid bills"],
        title=_title,
        rows_fn=_rows,
    )


@app.command("payment-orders")
def payment_orders(  # noqa: PLR0913
    first: int = typer.Option(20, help="Number of orders."),
    after: str | None = typer.Option(None, help="Cursor after."),
    before: str | None = typer.Option(None, help="Cursor before."),
    offset: int | None = typer.Option(None, help="Offset for pagination."),
    status: str | None = typer.Option(None, help="Filter by payment status (client-side)."),
    created_from: str | None = typer.Option(None, help="Filter created >= (YYYY-MM-DD)."),
    created_to: str | None = typer.Option(None, help="Filter created <= (YYYY-MM-DD)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch payment orders."""
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "before": before,
        "offset": offset,
    }

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        orders = payload.get("paymentOrders") or {}
        edges = orders.get("edges") or []
        # client-side filters
        filtered = edges
        status_l = status.lower() if status else None
        if status_l:
            filtered = [
                e
                for e in filtered
                if str((e.get("node") or {}).get("bluemediaPaymentStatus", "")).lower() == status_l
            ]
        if created_from:
            filtered = [
                e
                for e in filtered
                if str((e.get("node") or {}).get("created", "")) >= _normalize_date(created_from)
            ]
        if created_to:
            filtered = [
                e
                for e in filtered
                if str((e.get("node") or {}).get("created", "")) <= _normalize_date(created_to)
            ]
        rows_local: list[Sequence[str]] = []
        for item in filtered:
            node = item.get("node", {}) or {}
            rows_local.append(
                (
                    str(node.get("id", "")),
                    str(node.get("created", "")),
                    str(node.get("amount", "")),
                    str(node.get("bluemediaPaymentStatus", "")),
                    str(node.get("bookingDate", "")),
                )
            )
        # mutate payload edges for potential reuse in JSON path
        payload["paymentOrders"] = {**orders, "edges": filtered}
        return rows_local

    run_query_table(
        query=queries.PAYMENT_ORDERS,
        variables=variables,
        label="paymentOrders",
        json_output=json_output,
        empty_msg="No payment orders.",
        headers=["ID", "Created", "Amount", "Status", "Booking date"],
        title="💸 Payment orders",
        rows_fn=_rows,
    )


@app.command("payment-components")
def payment_components(
    first: int = typer.Option(20, help="Number of components."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List payment components."""
    variables = {"first": first, "after": after}
    run_query_table(
        query=queries.PAYMENT_COMPONENTS,
        variables=variables,
        label="paymentComponents",
        json_output=json_output,
        empty_msg="No payment components.",
        headers=["ID", "Name", "Type", "Fee", "Repeat", "Period"],
        title="🧾 Payment components",
        rows_fn=lambda payload: [
            (
                str((edge.get("node") or {}).get("id", "")),
                str((edge.get("node") or {}).get("name", "")),
                str((edge.get("node") or {}).get("typeName", "")),
                str((edge.get("node") or {}).get("fee", "")),
                str((edge.get("node") or {}).get("billingRepeatTypeName", "")),
                str((edge.get("node") or {}).get("feePeriodTypeName", "")),
            )
            for edge in (payload.get("paymentComponents") or {}).get("edges") or []
        ],
    )


@app.command("billing-periods")
def billing_periods(
    first: int = typer.Option(20, help="Number of periods."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List billing periods."""
    variables = {"first": first, "after": after}
    run_query_table(
        query=queries.BILLING_PERIODS,
        variables=variables,
        label="billingPeriods",
        json_output=json_output,
        empty_msg="No billing periods.",
        headers=["ID", "Start", "End", "Closed"],
        title="🗓 Billing periods",
        rows_fn=lambda payload: [
            (
                str((edge.get("node") or {}).get("id", "")),
                str(((edge.get("node") or {}).get("month") or {}).get("startDate", "")),
                str(((edge.get("node") or {}).get("month") or {}).get("endDate", "")),
                "yes" if (edge.get("node") or {}).get("isClosed") else "no",
            )
            for edge in (payload.get("billingPeriods") or {}).get("edges") or []
        ],
    )


@app.command("employee-billing-periods")
def employee_billing_periods(
    first: int = typer.Option(20, help="Number of periods."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List billing periods for employees (if permitted)."""
    variables = {"first": first, "after": after}
    run_query_table(
        query=queries.EMPLOYEE_BILLING_PERIODS,
        variables=variables,
        label="employeeBillingPeriods",
        json_output=json_output,
        empty_msg="No employee billing periods.",
        headers=["ID", "Start", "End", "Closed", "Total", "Paid"],
        title="🗓 Employee billing periods",
        rows_fn=lambda payload: [
            (
                str((edge.get("node") or {}).get("id", "")),
                str(((edge.get("node") or {}).get("month") or {}).get("startDate", "")),
                str(((edge.get("node") or {}).get("month") or {}).get("endDate", "")),
                "yes" if (edge.get("node") or {}).get("isClosed") else "no",
                str((edge.get("node") or {}).get("monthlyBillsTotalAmount", "")),
                str((edge.get("node") or {}).get("monthlyBillsTotalPaid", "")),
            )
            for edge in (payload.get("employeeBillingPeriods") or {}).get("edges") or []
        ],
    )


@app.command("tuition-discounts")
def tuition_discounts(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """List tuition discounts (if available)."""
    run_query_table(
        query=queries.TUITION_DISCOUNTS,
        variables={},
        label="tuitionDiscounts",
        json_output=json_output,
        empty_msg="No tuition discounts.",
        headers=["ID", "Name", "Value", "Type", "Active"],
        title="🏷 Tuition discounts",
        rows_fn=lambda payload: [
            (
                str(d.get("id", "")),
                str(d.get("name", "")),
                str(d.get("value", "")),
                str(d.get("valueType", "")),
                "yes" if d.get("active") else "no",
            )
            for d in (payload.get("tuitionDiscounts") or [])
        ],
    )


@app.command("employee-roles")
def employee_roles(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """List employee roles (if permitted)."""
    run_query_table(
        query=queries.EMPLOYEE_ROLES,
        variables={},
        label="employeeRoles",
        json_output=json_output,
        empty_msg="No employee roles.",
        headers=["ID", "Name", "Permissions"],
        title="👥 Employee roles",
        rows_fn=lambda payload: [
            (
                str(r.get("id", "")),
                str(r.get("name", "")),
                ", ".join(sorted([str(p) for p in (r.get("permissions") or [])])),
            )
            for r in (payload.get("employeeRoles") or [])
        ],
    )


@app.command("employees")
def employees(
    first: int = typer.Option(20, help="Number of employees."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List employees (basic fields)."""
    variables = {"first": first, "after": after}

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        edges = (payload.get("employees") or {}).get("edges") or []
        rows_local: list[Sequence[str]] = []
        for edge in edges:
            node = edge.get("node") or {}
            full_name = f"{node.get('firstName','')} {node.get('lastName','')}".strip()
            role = (node.get("role") or {}).get("name", "")
            rows_local.append(
                (
                    str(node.get("id", "")),
                    full_name,
                    str(node.get("email", "")),
                    str(node.get("phone", "")),
                    role,
                    str(node.get("position", "")),
                )
            )
        return rows_local

    run_query_table(
        query=queries.EMPLOYEES,
        variables=variables,
        label="employees",
        json_output=json_output,
        empty_msg="No employees.",
        headers=["ID", "Name", "Email", "Phone", "Role", "Position"],
        title="👤 Employees",
        rows_fn=_rows,
    )


@app.command()
def monthly_bills(  # noqa: PLR0913
    year: str = typer.Option("", help="Year node ID (e.g., WWVhck5vZGU6MjM4OA==)."),
    child: str | None = typer.Option(None, help="Child ID."),
    is_paid: bool | None = typer.Option(True, help="Filter by paid status."),
    first: int = typer.Option(10, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch monthly bills."""
    variables = {
        "year": year,
        "child": child,
        "isPaid": is_paid,
        "first": first,
        "after": after,
    }
    headers = ["Payment due", "Child", "Full amount", "Paid amount", "Balance"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        bills_raw = payload.get("monthlyBills") or {}
        bills: dict[str, Any] = bills_raw if isinstance(bills_raw, dict) else {}
        edges = bills.get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in edges:
            node_raw = item.get("node", {})
            node: dict[str, Any] = node_raw if isinstance(node_raw, dict) else {}
            child_raw = node.get("child") or {}
            child_info: dict[str, Any] = child_raw if isinstance(child_raw, dict) else {}
            rows_local.append(
                (
                    str(node.get("paymentDueTo", "")),
                    f"{child_info.get('name','')} {child_info.get('surname','')}".strip(),
                    str(node.get("fullAmount", "")),
                    str(node.get("paidAmount", "")),
                    str(node.get("balance", "")),
                )
            )
        return rows_local

    def _title(payload: dict[str, Any]) -> str:
        bills_raw = payload.get("monthlyBills") or {}
        total_balance = (bills_raw or {}).get("totalBalance", "")
        return f"💰 Monthly bills (total balance: {total_balance})"

    run_query_table(
        query=queries.MONTHLY_BILLS,
        variables=variables,
        label="monthlyBills",
        json_output=json_output,
        empty_msg="No monthly bills.",
        headers=headers,
        title=_title,
        rows_fn=_rows,
    )


@app.command()
def galleries(  # noqa: PLR0913
    group_id: str | None = typer.Option(None, help="Group ID filter."),
    first: int = typer.Option(3, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    search: str = typer.Option("", help="Search phrase."),
    order: str | None = typer.Option(None, help="Order string."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch galleries."""
    variables: dict[str, object] = {
        "groupId": group_id,
        "first": first,
        "after": after,
        "search": search,
        "order": order,
    }
    headers = ["ID", "Name", "Created", "Images"]

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        edges = (payload.get("galleries") or {}).get("edges") or []
        return [
            (
                str((item.get("node") or {}).get("id", "")),
                str((item.get("node") or {}).get("name", "")),
                str((item.get("node") or {}).get("created", "")),
                str((item.get("node") or {}).get("imagesCount", "")),
            )
            for item in edges
        ]

    run_query_table(
        query=queries.GALLERIES,
        variables=variables,
        label="galleries",
        json_output=json_output,
        empty_msg="No galleries.",
        headers=headers,
        title="🖼️ Galleries",
        rows_fn=_rows,
        show_lines=True,
    )


@app.command()
def gallery_download(  # noqa: B008
    ids: str = typer.Option("", "--id", "--ids", help="Comma-separated gallery IDs."),
    all_: bool = typer.Option(False, "--all", help="Download all galleries not yet downloaded."),
    output_dir: Path | None = typer.Option(
        None,
        help="Output dir (default KIDSVIEW_DOWNLOAD_DIR or ~/Pictures/Kidsview).",
    ),
) -> None:
    """Download gallery images."""
    settings, tokens, context = _env()

    # Resolve child name for subdirectory (if context has child_id)
    child_name: str | None = None
    if context and context.child_id:
        try:
            me_data = _fetch_me(settings, tokens, context)
            me_obj = me_data.get("me") or {}
            for child in me_obj.get("children") or []:
                if str(child.get("id")) == context.child_id:
                    child_name = f"{child.get('name','')} {child.get('surname','')}".strip() or None
                    break
        except ApiError:
            child_name = None
        if not child_name:
            child_name = context.child_id

    dest_base = output_dir or settings.download_dir
    dest = Path(dest_base).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    galleries_cache: list[dict[str, Any]] | None = None
    if not all_ and not id_list:
        # Interactive pick
        try:
            galleries_cache = _run(
                fetch_galleries(settings=settings, tokens=tokens, context=context)
            )
        except Exception as exc:  # pragma: no cover - network errors
            console.print(f"[red]Failed to list galleries:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        if not galleries_cache:
            console.print("[red]No galleries available to choose.[/red]")
            raise typer.Exit(code=1)
        id_list = _prompt_multi_choice(galleries_cache, "Select galleries", "name")
        if not id_list:
            console.print("[red]No galleries selected.[/red]")
            raise typer.Exit(code=1)

    try:
        with make_progress() as progress:
            downloaded = _run(
                download_all(
                    settings=settings,
                    tokens=tokens,
                    context=context,
                    gallery_ids=id_list,
                    output_dir=dest,
                    skip_downloaded=all_,
                    galleries=galleries_cache,
                    progress=progress,
                    concurrency=4,
                    child_name=child_name,
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


@app.command("gallery-like")
def gallery_like(
    gallery_id: str = typer.Option(..., "--id", help="Gallery ID to like/unlike."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Toggle like for a gallery."""
    settings, tokens, context = _env()
    data = _execute_graphql(
        settings,
        tokens,
        queries.SET_GALLERY_LIKE,
        {"galleryId": gallery_id},
        context,
        label="setGalleryLike",
    )
    if json_output:
        console.print_json(data=data)
    else:
        result = (data.get("setGalleryLike") or {}).get("isLiked")
        console.print(f"[green]Gallery like toggled. isLiked={result}[/green]")


@app.command("gallery-comment")
def gallery_comment(
    gallery_id: str = typer.Option(..., "--id", help="Gallery ID."),
    content: str = typer.Option(..., "--content", prompt=True, help="Comment text."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Add comment to a gallery."""
    settings, tokens, context = _env()
    data = _execute_graphql(
        settings,
        tokens,
        queries.CREATE_GALLERY_COMMENT,
        {"galleryId": gallery_id, "content": content},
        context,
        label="createGalleryComment",
    )
    if json_output:
        console.print_json(data=data)
    else:
        errors = (data.get("createGalleryComment") or {}).get("errors")
        if errors:
            console.print(f"[red]Error:[/red] {errors}")
        else:
            console.print("[green]Comment added.[/green]")


@app.command("chat-threads")
def chat_threads(  # noqa: PLR0913
    type_filter: str | None = typer.Option(None, "--type", help="Thread type filter."),
    child_id: str | None = typer.Option(None, "--child-id", help="Child ID filter."),
    preschool_id: str | None = typer.Option(None, "--preschool-id", help="Preschool ID filter."),
    search: str = typer.Option("", help="Search by name."),
    first: int = typer.Option(20, help="Number of threads."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List chat threads."""
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "type": type_filter,
        "child": child_id,
        "preschool": preschool_id,
        "search": search or None,
    }
    run_query_table(
        query=queries.CHAT_THREADS,
        variables=variables,
        label="threads",
        json_output=json_output,
        empty_msg="No threads.",
        headers=["Name", "Child", "Recipients", "Last message", "Type", "Modified"],
        title="💬 Threads",
        rows_fn=lambda payload: _rows_for_threads(
            (payload.get("threads") or {}).get("edges") or [], include_id=False
        ),
    )


@app.command("chat-messages")
def chat_messages(
    thread_id: str | None = typer.Option(None, "--thread-id", help="Thread ID (optional)."),
    first: int = typer.Option(20, help="Number of messages."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List messages in a thread."""
    settings, tokens, context = _env()
    chosen_thread = thread_id
    threads_cache: list[dict[str, Any]] | None = None

    if not chosen_thread:
        data_threads = _execute_graphql(
            settings,
            tokens,
            queries.CHAT_THREADS,
            {"first": 20},
            context,
            label="threads",
        )
        threads_cache = (data_threads.get("threads") or {}).get("edges") or []
        chosen_thread = _prompt_thread_selection(threads_cache)
        if not chosen_thread:
            console.print("[red]No thread selected.[/red]")
            raise typer.Exit(code=1)

    variables: dict[str, object] = {"id": chosen_thread, "first": first, "after": after}

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        thread = payload.get("thread") or {}
        messages = (thread.get("messages") or {}).get("edges") or []
        rows_local: list[Sequence[str]] = []
        for item in messages:
            node = item.get("node", {})
            sender = (node.get("sender") or {}).get("fullName", "")
            text = str(node.get("text", ""))
            rows_local.append(
                (
                    str(node.get("id", "")),
                    str(node.get("created", "")),
                    str(sender),
                    "yes" if node.get("read") else "no",
                    str(thread.get("type", "")),
                    str(thread.get("modified", "")),
                    ", ".join(r.get("fullName", "") for r in (thread.get("recipients") or [])),
                    _truncate(str(thread.get("lastMessage", "")), LAST_MSG_PREVIEW),
                    _truncate(text, TEXT_PREVIEW),
                )
            )
        return rows_local

    run_query_table(
        query=queries.CHAT_MESSAGES,
        variables=variables,
        label="thread",
        json_output=json_output,
        empty_msg="No messages.",
        headers=[
            "ID",
            "Created",
            "Sender",
            "Read",
            "Type",
            "Modified",
            "Recipients",
            "Last message",
            "Text",
        ],
        title=lambda payload: f"💬 Messages in {(payload.get('thread') or {}).get('name','')}",
        rows_fn=_rows,
    )


@app.command()
def chat_users(
    user_types: str = typer.Option("", "--type", help="Comma-separated user types; empty for all."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch users available for chat."""
    types_list = [u for u in user_types.split(",") if u] if user_types else []
    variables = {"userTypes": types_list}

    def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
        users = payload.get("usersForChat") or []
        rows_local: list[Sequence[str]] = []
        for user in users:
            rows_local.append(
                (
                    str(user.get("chatDisplayName", "")),
                    str(user.get("userType", "")),
                    str(user.get("chatUserPosition", "")),
                    str(user.get("roleName", "")),
                )
            )
        return rows_local

    run_query_table(
        query=queries.USERS_FOR_CHAT,
        variables=variables,
        label="usersForChat",
        json_output=json_output,
        empty_msg="No chat users.",
        headers=["Name", "Type", "Position", "Role"],
        title="💬 Chat users",
        rows_fn=_rows,
    )


@app.command()
def chat_search(
    search: str = typer.Option("", help="Search phrase for chat groups/children/parents."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Search chat groups and parents (groupsForChat)."""
    variables = {"search": search or None}
    run_query_table(
        query=queries.GROUPS_FOR_CHAT,
        variables=variables,
        label="groupsForChat",
        json_output=json_output,
        empty_msg="No chat groups found.",
        headers=["Name", "Children/Parents"],
        title="💬 Chat search",
        rows_fn=lambda payload: [
            (
                str(group.get("name", "")),
                ", ".join(child.get("fullName", "") for child in (group.get("children") or [])),
            )
            for group in (payload.get("groupsForChat") or [])
        ],
    )


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
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Send a chat message (creates a thread)."""
    settings, tokens, context = _env()
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


@app.command("notification-prefs")
def notification_prefs(
    enable: list[str] = typer.Option(
        None,
        "--enable",
        help="Enable notification types (repeatable, e.g., --enable NEW_EVENT).",
    ),
    disable: list[str] = typer.Option(
        None,
        "--disable",
        help="Disable notification types (repeatable, e.g., --disable NEW_GALLERY).",
    ),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Show or update notification preferences."""
    settings, tokens, context = _env()

    def _list_prefs() -> list[dict[str, Any]]:
        data = _execute_graphql(
            settings,
            tokens,
            queries.USER_NOTIFICATION_PREFERENCES,
            {},
            context,
            label="notification-prefs",
        )
        prefs = data.get("userNotificationPreferences") or []
        return prefs if isinstance(prefs, list) else []

    changes: list[dict[str, object]] = []
    for name in enable or []:
        changes.append({"notificationType": name.upper(), "enabled": True})
    for name in disable or []:
        changes.append({"notificationType": name.upper(), "enabled": False})

    if changes:
        _execute_graphql(
            settings,
            tokens,
            queries.SET_USER_NOTIFICATION_PREFERENCES,
            {"preferences": changes},
            context,
            label="setUserNotificationPreferences",
        )

    prefs = _list_prefs()
    if json_output:
        console.print_json(data={"notificationPreferences": prefs})
    else:
        if not prefs:
            console.print("No notification preferences found.")
            return
        table = Table(title="🔔 Notification preferences")
        table.add_column("Type")
        table.add_column("Name")
        table.add_column("Enabled")
        for pref in prefs:
            table.add_row(
                str(pref.get("type", "")),
                str(pref.get("name", "")),
                "yes" if pref.get("enabled") else "no",
            )
        console.print(table)
