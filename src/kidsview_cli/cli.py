# ruff: noqa: B008
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from rich.pretty import Pretty
from rich.table import Table

from . import queries
from .auth import AuthClient, AuthError
from .client import ApiError
from .commands.calendar import register_calendar
from .commands.chat import register_chat
from .commands.galleries import register_galleries
from .commands.notifications import register_notifications
from .commands.payments import register_payments
from .config import Settings
from .context import Context, ContextStore
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
    normalize_date as _normalize_date,
)
from .helpers import (
    prompt_choice as _prompt_choice,
)
from .helpers import (
    run as _run,
)
from .helpers import (
    truncate as _truncate,
)
from .session import SessionStore

app = typer.Typer(help="Kidsview CLI for humans and automation.")
register_calendar(app)
register_chat(app)
register_galleries(app)
register_notifications(app)
register_payments(app)


@app.command()
def login(
    username: str = typer.Option(..., prompt=True, help="Kidsview username (email)."),
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, help="Kidsview password (hidden)."
    ),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist tokens to the session file."),
    json_output: bool = typer.Option(False, "--json", help="Print tokens as JSON."),
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
    json_output: bool = typer.Option(False, "--json/--no-json", help="Print tokens as JSON."),
) -> None:
    """Refresh tokens using cached refresh token."""
    settings = Settings()
    store = SessionStore(settings.session_file)
    tokens = store.load()
    if not tokens or not tokens.refresh_token:
        console.print("[red]No refresh token found. Login first.[/red]")
        raise typer.Exit(code=1)
    try:
        new_tokens = _run(AuthClient(settings).refresh(tokens.refresh_token))
    except AuthError as exc:  # pragma: no cover - network/auth errors
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
    if detailed and (not date_from or not date_to):
        console.print("[red]date_from and date_to are required for detailed view.[/red]")
        raise typer.Exit(code=1)

    variables: dict[str, object] = {}
    query = queries.ACTIVE_CHILD_SUMMARY
    if detailed:
        variables = {"dateFrom": date_from, "dateTo": date_to}
        query = queries.ACTIVE_CHILD_DETAIL

    data = _execute_graphql(settings, tokens, query, variables, context, label="activeChild")
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
def announcements(
    first: int = typer.Option(10, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    status: str = typer.Option("ACTIVE", help="AnnouncementStatus."),
    phrase: str = typer.Option("", help="Search phrase."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch announcements."""
    variables: dict[str, object] = {
        "first": first,
        "after": after,
        "status": status,
        "phrase": phrase,
    }
    headers = ["Title", "Created", "Author", "Text"]

    def _rows(payload: dict[str, Any]) -> list[list[str]]:
        conn = payload.get("announcements") or {}
        edges = conn.get("edges") or []
        rows_local: list[list[str]] = []
        for item in edges:
            node = item.get("node", {}) or {}
            rows_local.append(
                [
                    str(node.get("title", "")),
                    str(node.get("created", "")),
                    str((node.get("createdBy") or {}).get("fullName", "")),
                    _truncate(str(node.get("text", "")), 120),
                ]
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


@app.command()
def monthly_bills(  # noqa: PLR0913
    year: str = typer.Option("", help="Year node ID (e.g., WWVhck5vZGU6MjM4OA==)."),
    child: str | None = typer.Option(None, help="Child ID."),
    unpaid: bool = typer.Option(False, "--unpaid", help="Show only unpaid bills."),
    first: int = typer.Option(10, help="Items to fetch."),
    after: str | None = typer.Option(None, help="Cursor for pagination."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch monthly bills."""
    variables = {
        "year": year,
        "child": child,
        "isPaid": False if unpaid else None,
        "first": first,
        "after": after,
    }
    headers = ["Payment due", "Child", "Full amount", "Paid amount", "Balance"]

    def _rows(payload: dict[str, Any]) -> list[list[str]]:
        bills_raw = payload.get("monthlyBills") or {}
        bills: dict[str, Any] = bills_raw if isinstance(bills_raw, dict) else {}
        edges = bills.get("edges") or []
        rows_local: list[list[str]] = []
        for item in edges:
            node_raw = item.get("node", {})
            node: dict[str, Any] = node_raw if isinstance(node_raw, dict) else {}
            child_raw = node.get("child") or {}
            child_info: dict[str, Any] = child_raw if isinstance(child_raw, dict) else {}
            rows_local.append(
                [
                    str(node.get("paymentDueTo", "")),
                    f"{child_info.get('name','')} {child_info.get('surname','')}".strip(),
                    str(node.get("fullAmount", "")),
                    str(node.get("paidAmount", "")),
                    str(node.get("balance", "")),
                ]
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
def meals(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """Fetch current diet info for active child."""
    settings, tokens, context = _env()
    data = _execute_graphql(
        settings, tokens, queries.CURRENT_DIET, {}, context, label="currentDiet"
    )
    payload = {"currentDietForChild": data.get("currentDietForChild")}
    if json_output:
        console.print_json(data=payload)
        return
    diet = payload.get("currentDietForChild") or {}
    if not diet:
        console.print("No diet info.")
        return
    table = Table(title="🍽️ Diet")
    table.add_column("ID")
    table.add_column("Body")
    table.add_column("Category")
    table.add_row(
        str(diet.get("id", "")),
        _truncate(str(diet.get("body", "")), 120),
        str((diet.get("category") or {}).get("id", "")),
    )
    console.print(table)


@app.command()
def observations(
    child_id: str = typer.Option(..., help="Child ID."),
    activity_id: str | None = typer.Option(None, help="Additional activity ID."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch observations for additional activities for a child."""
    settings, tokens, context = _env()
    variables = {"childId": child_id, "id": activity_id}
    data = _execute_graphql(
        settings,
        tokens,
        queries.ADDITIONAL_ACTIVITY_OBS,
        variables,
        context,
        label="observations",
    )
    if json_output:
        console.print_json(data=data)
        return
    obs = data.get("additionalActivities") or {}
    edges = obs.get("edges") or []
    if not edges:
        console.print("No observations.")
        return
    table = Table(title="👀 Observations")
    table.add_column("Activity")
    table.add_column("Observation IDs")
    for edge in edges:
        node = edge.get("node") or {}
        obs_edges = (node.get("observations") or {}).get("edges") or []
        ids = ", ".join((o.get("node") or {}).get("id", "") for o in obs_edges)
        table.add_row(str(node.get("name", "")), ids)
    console.print(table)


@app.command("application-submit")
def application_submit(
    form_id: str = typer.Option(..., help="Application form ID."),
    child_id: str | None = typer.Option(None, help="Child ID (optional)."),
    comment: str | None = typer.Option(None, help="Optional director comment."),
    months: int | None = typer.Option(None, help="Number of months (if applicable)."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Submit an application (createApplication)."""
    settings, tokens, context = _env()
    variables: dict[str, object] = {
        "applicationFormId": form_id,
        "commentParent": comment,
        "months": months,
    }
    if child_id:
        variables["childId"] = child_id
    data = _execute_graphql(
        settings, tokens, queries.CREATE_APPLICATION, variables, context, label="createApplication"
    )
    if json_output:
        console.print_json(data=data)
        return
    success = (data.get("createApplication") or {}).get("success")
    if success:
        console.print("[green]Application submitted.[/green]")
    else:
        console.print(f"[red]Submit failed:[/red] {data}")


@app.command()
def applications(
    status: str | None = typer.Option(None, help="Status filter."),
    phrase: str | None = typer.Option(None, help="Search phrase."),
    json_output: bool = typer.Option(False, "--json/--no-json"),
) -> None:
    """Fetch applications (wnioski)."""
    variables = {"status": status, "phrase": phrase}
    headers = ["ID", "Created", "Form", "Form status", "Status", "Comment"]

    def _rows(payload: dict[str, Any]) -> list[list[str]]:
        edges = (payload.get("applications") or {}).get("edges") or []
        rows_local: list[list[str]] = []
        for item in edges:
            node = item.get("node") or {}
            form = node.get("applicationForm") or {}
            rows_local.append(
                [
                    str(node.get("id", "")),
                    str(node.get("created", "")),
                    str(form.get("name", "")),
                    str(form.get("status", "")),
                    str(node.get("status", "")),
                    str(node.get("commentDirector", "")),
                ]
            )
        return rows_local

    run_query_table(
        query=queries.APPLICATIONS,
        variables=variables,
        label="applications",
        json_output=json_output,
        empty_msg="No applications.",
        headers=headers,
        title="📄 Applications",
        rows_fn=_rows,
    )


@app.command()
def colors(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
    """Fetch available preschools and color scheme."""
    headers = ["ID", "Name", "Header", "Background", "Accent"]

    def _rows(payload: dict[str, Any]) -> list[list[str]]:
        me_data = payload.get("me") or {}
        preschools = me_data.get("availablePreschools") or []
        rows_local: list[list[str]] = []
        for pre in preschools:
            color = (pre.get("usercolorSet") or {}) or {}
            rows_local.append(
                [
                    str(pre.get("id", "")),
                    str(pre.get("name", "")),
                    str(color.get("headerColor", "")),
                    str(color.get("backgroundColor", "")),
                    str(color.get("accentColor", "")),
                ]
            )
        return rows_local

    run_query_table(
        query=queries.COLORS,
        variables={},
        label="me",
        json_output=json_output,
        empty_msg="No preschools/colors.",
        headers=headers,
        title="🎨 Colors",
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
        console.print(
            f"[yellow]Confirm absence for child {effective_child} on {date_from_norm}"
            f"{' to ' + date_to_norm if date_to_norm else ''}[/yellow]"
        )
        if not typer.confirm("Proceed?"):
            console.print("Aborted.")
            return

    variables: dict[str, object] = {
        "childId": effective_child,
        "date": date_from_norm,
        "dateTo": date_to_norm,
        "input": {
            "child": effective_child,
            "date": date_from_norm,
            "dateTo": date_to_norm,
            "onTime": on_time,
            "partiallyRefundMeals": partial_meal_refund,
            "forcePartiallyRefundMeals": force_partial_refund,
        },
    }
    data = _execute_graphql(
        settings, tokens, queries.SET_CHILD_ABSENCE, variables, context, label="setChildAbsence"
    )
    if json_output:
        console.print_json(data=data)
        return
    success = (data.get("setChildAbsence") or {}).get("success")
    if success:
        console.print("[green]Absence reported.[/green]")
    else:
        console.print(f"[red]Failed to report absence:[/red] {data}")


if __name__ == "__main__":
    app()
