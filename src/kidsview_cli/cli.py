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
from .download import download_all, fetch_galleries, make_progress
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
    json_output: bool = typer.Option(False, "--json/--no-json", help="Print response as JSON."),
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
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
        table = Table(title="📢 Announcements", show_lines=True)
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
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
        table = Table(title=f"💰 Monthly bills (total balance: {total})")
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {
        "dateFrom": date_from,
        "dateTo": date_to,
        "child": child_id,
        "type": type_filter,
        "isBooked": is_booked,
        "first": first,
        "after": after,
    }
    data = _execute_graphql(
        settings, tokens, queries.PAYMENTS, variables, context, label="payments"
    )
    payload = {"payments": data.get("payments")}
    if json_output:
        console.print_json(data=payload)
        return
    edges = (payload.get("payments") or {}).get("edges") or []
    if not edges:
        console.print("No payments.")
        return
    table = Table(title="💳 Payments")
    table.add_column("Title")
    table.add_column("Amount")
    table.add_column("Date")
    table.add_column("Type")
    table.add_column("Booked")
    table.add_column("Child")
    for item in edges:
        node = item.get("node", {})
        child = node.get("child") or {}
        child_name = f"{child.get('name','')} {child.get('surname','')}".strip()
        table.add_row(
            str(node.get("title", "")),
            str(node.get("amount", "")),
            str(node.get("paymentDate", "")),
            str(node.get("type", "")),
            "yes" if node.get("isBooked") else "no",
            child_name or "-",
        )
    console.print(table)


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
        table = Table(title="🖼️ Galleries", show_lines=True)
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


@app.command("gallery-like")
def gallery_like(
    gallery_id: str = typer.Option(..., "--id", help="Gallery ID to like/unlike."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Toggle like for a gallery."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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


@app.command("application-submit")
def application_submit(
    form_id: str = typer.Option(..., "--form-id", help="Application form ID."),
    comment: str = typer.Option("", "--comment", help="Parent comment."),
    accept_contract: bool = typer.Option(True, "--accept-contract/--no-accept-contract"),
    months: int | None = typer.Option(None, "--months", help="Number of months (if required)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Submit an application (createApplication)."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    data = _execute_graphql(
        settings, tokens, queries.PAYMENTS_SUMMARY, variables, context, label="paymentsSummary"
    )
    payload = {"paymentsSummary": data.get("paymentsSummary")}
    if json_output:
        console.print_json(data=payload)
        return
    summary = payload.get("paymentsSummary") or {}
    children_conn = summary.get("children") or {}
    edges = children_conn.get("edges") or []
    if not edges:
        console.print("No payments summary entries.")
        return
    title = f"💳 Payments summary (full balance: {summary.get('fullBalance','')})"
    table = Table(title=title)
    table.add_column("Child")
    table.add_column("Amount")
    table.add_column("Paid")
    table.add_column("Balance")
    table.add_column("Paid bills")
    for item in edges:
        node = item.get("node", {}) or {}
        child_name = f"{node.get('name','')} {node.get('surname','')}".strip()
        table.add_row(
            child_name or "-",
            str(node.get("amount", "")),
            str(node.get("paidAmount", "")),
            str(node.get("balance", "")),
            str(node.get("paidMonthlyBillsCount", "")),
        )
    console.print(table)


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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "before": before,
        "offset": offset,
    }
    data = _execute_graphql(
        settings, tokens, queries.PAYMENT_ORDERS, variables, context, label="paymentOrders"
    )
    orders = data.get("paymentOrders") or {}
    edges = orders.get("edges") or []
    # client-side filters
    if status:
        edges = [
            e
            for e in edges
            if str((e.get("node") or {}).get("bluemediaPaymentStatus", "")).lower()
            == status.lower()
        ]
    if created_from:
        edges = [
            e
            for e in edges
            if str((e.get("node") or {}).get("created", "")) >= _normalize_date(created_from)
        ]
    if created_to:
        edges = [
            e
            for e in edges
            if str((e.get("node") or {}).get("created", "")) <= _normalize_date(created_to)
        ]
    payload = {"paymentOrders": {**orders, "edges": edges}}
    if json_output:
        console.print_json(data=payload)
        return
    if not edges:
        console.print("No payment orders.")
        return
    table = Table(title="💸 Payment orders")
    table.add_column("ID")
    table.add_column("Created")
    table.add_column("Amount")
    table.add_column("Status")
    table.add_column("Booking date")
    for item in edges:
        node = item.get("node", {}) or {}
        table.add_row(
            str(node.get("id", "")),
            str(node.get("created", "")),
            str(node.get("amount", "")),
            str(node.get("bluemediaPaymentStatus", "")),
            str(node.get("bookingDate", "")),
        )
    console.print(table)


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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
        child = payload.get("activeChild") or {}
        if not child:
            console.print("No active child.")
            return
        _print_active_child(child)


@app.command()
def chat_users(
    user_types: str = typer.Option("", "--type", help="Comma-separated user types; empty for all."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch users available for chat."""
    settings = Settings()
    tokens = _load_tokens(settings)
    types_list = [u for u in user_types.split(",") if u] if user_types else []
    variables = {"userTypes": types_list}
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.USERS_FOR_CHAT, variables, context, label="chat_users"
    )
    payload = {"usersForChat": data.get("usersForChat")}
    if json_output:
        console.print_json(data=payload)
    else:
        users = payload.get("usersForChat") or []
        if not users:
            console.print("No chat users.")
            return
        table = Table(title="💬 Chat users")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Position")
        table.add_column("Role")
        for user in users:
            table.add_row(
                str(user.get("chatDisplayName", "")),
                str(user.get("userType", "")),
                str(user.get("chatUserPosition", "")),
                str(user.get("roleName", "")),
            )
        console.print(table)


@app.command()
def chat_search(
    search: str = typer.Option("", help="Search phrase for chat groups/children/parents."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "type": type_filter,
        "child": child_id,
        "preschool": preschool_id,
        "search": search or None,
    }
    data = _execute_graphql(
        settings, tokens, queries.CHAT_THREADS, variables, context, label="threads"
    )
    payload = {"threads": data.get("threads")}
    if json_output:
        console.print_json(data=payload)
        return
    edges = (payload.get("threads") or {}).get("edges") or []
    if not edges:
        console.print("No threads.")
        return
    console.print(_render_threads_table(edges))


@app.command("chat-messages")
def chat_messages(
    thread_id: str | None = typer.Option(None, "--thread-id", help="Thread ID (optional)."),
    first: int = typer.Option(20, help="Number of messages."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """List messages in a thread."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    data = _execute_graphql(
        settings, tokens, queries.CHAT_MESSAGES, variables, context, label="thread"
    )
    payload = {"thread": data.get("thread")}
    if json_output:
        console.print_json(data=payload)
        return
    thread = payload.get("thread") or {}
    messages = (thread.get("messages") or {}).get("edges") or []
    if not messages:
        console.print("No messages.")
        return
    title = f"💬 Messages in {thread.get('name','')}"
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Created")
    table.add_column("Sender")
    table.add_column("Read")
    table.add_column("Type")
    table.add_column("Modified")
    table.add_column("Recipients")
    table.add_column("Last message")
    table.add_column("Text")
    for item in messages:
        node = item.get("node", {})
        sender = (node.get("sender") or {}).get("fullName", "")
        text = str(node.get("text", ""))
        preview = text if len(text) <= TEXT_PREVIEW else text[: (TEXT_PREVIEW - 3)] + "..."
        table.add_row(
            str(node.get("id", "")),
            str(node.get("created", "")),
            str(sender),
            "yes" if node.get("read") else "no",
            str(thread.get("type", "")),
            str(thread.get("modified", "")),
            ", ".join(r.get("fullName", "") for r in (thread.get("recipients") or [])),
            str(thread.get("lastMessage", "")[:LAST_MSG_PREVIEW])
            + ("..." if len(str(thread.get("lastMessage", ""))) > LAST_MSG_PREVIEW else ""),
            preview,
        )
    console.print(table)


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
def meals(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
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
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
        table = Table(title="🔔 Notifications")
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()

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
    data = _execute_graphql(
        settings, tokens, queries.QUICK_CALENDAR, variables, context, label="quickCalendar"
    )
    payload = {"quickCalendar": data.get("quickCalendar")}
    if json_output:
        console.print_json(data=payload)
        return
    items = payload.get("quickCalendar") or []
    if not items:
        console.print("No quick calendar entries.")
        return
    table = Table(title="📅 Quick calendar")
    table.add_column("Date")
    table.add_column("Has events")
    table.add_column("New events")
    table.add_column("Holiday")
    table.add_column("Absent")
    table.add_column("Meals modified")
    for node in items:
        table.add_row(
            str(node.get("date", "")),
            "yes" if node.get("hasEvents") else "no",
            "yes" if node.get("hasNewEvents") else "no",
            "yes" if node.get("holiday") else "no",
            "yes" if node.get("absent") else "no",
            "yes" if node.get("mealsModified") else "no",
        )
    console.print(table)


@app.command()
def schedule(
    group_id: str = typer.Option(..., "--group-id", help="Group ID for schedule (required)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch schedule for a group."""
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
    variables: dict[str, object] = {"group": group_id}
    data = _execute_graphql(
        settings, tokens, queries.SCHEDULE, variables, context, label="schedule"
    )
    payload = {"schedule": data.get("schedule")}
    if json_output:
        console.print_json(data=payload)
        return
    items = payload.get("schedule") or []
    if not items:
        console.print("No schedule entries.")
        return
    table = Table(title="🗓️ Schedule")
    table.add_column("Title")
    table.add_column("Start")
    table.add_column("End")
    table.add_column("All day")
    table.add_column("Type")
    table.add_column("Groups")
    for node in items:
        table.add_row(
            str(node.get("title", "")),
            str(node.get("startDate", "")),
            str(node.get("endDate", "")),
            "yes" if node.get("allDay") else "no",
            str(node.get("type", "")),
            ", ".join(node.get("groupsNames") or [])
            if isinstance(node.get("groupsNames"), list)
            else str(node.get("groupsNames", "")),
        )
    console.print(table)


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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()
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
    settings = Settings()
    tokens = _load_tokens(settings)
    context = ContextStore(settings.context_file).load()

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


@app.command()
def applications(
    phrase: str = typer.Option("", help="Search phrase."),
    status: str | None = typer.Option(None, help="Application status filter."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
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
        edges = (payload.get("applications") or {}).get("edges") or []
        if not edges:
            console.print("No applications.")
            return
        table = Table(title="📝 Applications", show_lines=True)
        table.add_column("ID")
        table.add_column("Created")
        table.add_column("Form name")
        table.add_column("Form status")
        table.add_column("Status")
        table.add_column("Director comment")
        for item in edges:
            node = item.get("node", {})
            form = node.get("applicationForm") or {}
            table.add_row(
                str(node.get("id", "")),
                str(node.get("created", "")),
                str(form.get("name", "")),
                str(form.get("status", "")),
                str(node.get("status", "")),
                str(node.get("commentDirector", "")),
            )
        console.print(table)


@app.command()
def me(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:  # noqa: PLR0915
    """Fetch current user profile and context."""
    settings = Settings()
    tokens = _load_tokens(settings)

    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(settings, tokens, queries.ME, {}, context, label="me")
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

    # Optional: show available years for current preschool context
    if context and context.preschool_id:
        try:
            years_data = _fetch_years(settings, tokens, context)
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
def colors(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
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
def unread(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
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
        counts = payload.get("unreadCounts") or {}
        table = Table(title="🔔 Unread")
        table.add_column("Type")
        table.add_column("Count")
        table.add_row("Notifications", str(counts.get("unreadNotificationsCount", 0)))
        table.add_row("Messages", str(counts.get("unreadMessagesCount", 0)))
        console.print(table)


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
    settings = Settings()
    tokens = _load_tokens(settings)

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
    context = ContextStore(settings.context_file).load()
    data = _execute_graphql(
        settings, tokens, queries.CALENDAR, variables, context, label="calendar"
    )
    payload = {"calendar": data.get("calendar")}
    if json_output:
        console.print_json(data=payload)
    else:
        items = payload.get("calendar") or []
        if not items:
            console.print("No calendar entries.")
            return
        table = Table(
            title=f"Calendar {variables['dateFrom']} to {variables['dateTo']}",
            show_lines=True,
        )
        table.add_column("Title")
        table.add_column("Start")
        table.add_column("End")
        table.add_column("Type")
        table.add_column("All day")
        table.add_column("Reported by")
        for node in items:
            reporter = (node.get("absenceReportedBy") or {}).get("fullName", "")
            table.add_row(
                str(node.get("title", "")),
                str(node.get("startDate", "")),
                str(node.get("endDate", "")),
                str(node.get("type", "")),
                "yes" if node.get("allDay") else "no",
                str(reporter),
            )
        console.print(table)


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
