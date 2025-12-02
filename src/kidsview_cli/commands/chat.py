from __future__ import annotations

from typing import Any

import typer

from .. import queries
from ..helpers import console, run_query_table
from ..helpers import env as _env
from ..helpers import execute_graphql as _execute_graphql
from ..helpers import truncate as _truncate

LAST_MSG_PREVIEW = 50
TEXT_PREVIEW = 80


def _render_thread_row(node: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    child = node.get("child") or {}
    child_name = f"{child.get('name','')} {child.get('surname','')}".strip() if child else ""
    recipients = ", ".join(r.get("fullName", "") for r in (node.get("recipients") or []))
    last_msg = str(node.get("lastMessage", "")[:LAST_MSG_PREVIEW])
    if len(str(node.get("lastMessage", ""))) > LAST_MSG_PREVIEW:
        last_msg += "..."
    return (
        str(node.get("id", "")),
        str(node.get("name", "")),
        child_name,
        recipients,
        last_msg,
        str(node.get("type", "")),
        str(node.get("modified", "")),
    )


def _rows_for_threads(edges: list[dict[str, Any]], include_id: bool = True) -> list[list[str]]:
    rows: list[list[str]] = []
    for item in edges:
        node = item.get("node", {})
        row = _render_thread_row(node)
        rows.append(list(row if include_id else row[1:]))
    return rows


def _prompt_thread_selection(app: typer.Typer, edges: list[dict[str, Any]]) -> str:
    """Prompt user to pick a thread from edges; returns thread ID or exits."""
    if not edges:
        console.print("No threads.")
        raise typer.Exit(code=1)
    table = typer.rich_utils.table.Table(title="Threads")  # type: ignore[attr-defined]
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


def register_chat(app: typer.Typer) -> None:  # noqa: PLR0915
    @app.command("chat-threads")  # noqa: PLR0913
    def chat_threads(  # noqa: PLR0913
        type_filter: str | None = typer.Option(None, "--type", help="Thread type filter."),
        child_id: str | None = typer.Option(None, "--child-id", help="Child ID filter."),
        preschool_id: str | None = typer.Option(
            None, "--preschool-id", help="Preschool ID filter."
        ),
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
            chosen_thread = _prompt_thread_selection(app, threads_cache)
            if not chosen_thread:
                console.print("[red]No thread selected.[/red]")
                raise typer.Exit(code=1)

        variables: dict[str, object] = {"id": chosen_thread, "first": first, "after": after}

        def _rows(payload: dict[str, Any]) -> list[list[str]]:
            thread = payload.get("thread") or {}
            messages = (thread.get("messages") or {}).get("edges") or []
            rows_local: list[list[str]] = []
            for item in messages:
                node = item.get("node", {})
                sender = (node.get("sender") or {}).get("fullName", "")
                text = str(node.get("text", ""))
                rows_local.append(
                    [
                        str(node.get("id", "")),
                        str(node.get("created", "")),
                        str(sender),
                        "yes" if node.get("read") else "no",
                        str(thread.get("type", "")),
                        str(thread.get("modified", "")),
                        ", ".join(r.get("fullName", "") for r in (thread.get("recipients") or [])),
                        _truncate(str(thread.get("lastMessage", "")), LAST_MSG_PREVIEW),
                        _truncate(text, TEXT_PREVIEW),
                    ]
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

    @app.command("chat-users")
    def chat_users(
        user_types: str = typer.Option(
            "", "--type", help="Comma-separated user types; empty for all."
        ),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Fetch users available for chat."""
        types_list = [u for u in user_types.split(",") if u] if user_types else []
        variables = {"userTypes": types_list}

        def _rows(payload: dict[str, Any]) -> list[list[str]]:
            users = payload.get("usersForChat") or []
            rows_local: list[list[str]] = []
            for user in users:
                rows_local.append(
                    [
                        str(user.get("chatDisplayName", "")),
                        str(user.get("userType", "")),
                        str(user.get("chatUserPosition", "")),
                        str(user.get("roleName", "")),
                    ]
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

    @app.command("chat-search")
    def chat_search(
        search: str = typer.Option("", "--search", help="Search phrase for groupsForChat."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Search chat groups and parents (groupsForChat)."""
        variables = {"search": search}

        def _rows(payload: dict[str, Any]) -> list[list[str]]:
            groups = payload.get("groupsForChat") or []
            rows_local: list[list[str]] = []
            for group in groups:
                children = group.get("children") or []
                parents = []
                for child in children:
                    for parent in child.get("parents") or []:
                        parents.append(parent.get("chatDisplayName", ""))
                rows_local.append(
                    [
                        str(group.get("id", "")),
                        str(group.get("name", "")),
                        ", ".join(parents),
                    ]
                )
            return rows_local

        run_query_table(
            query=queries.GROUPS_FOR_CHAT,
            variables=variables,
            label="groupsForChat",
            json_output=json_output,
            empty_msg="No chat groups.",
            headers=["ID", "Name", "Parents"],
            title="💬 Chat search",
            rows_fn=_rows,
        )

    @app.command("chat-send")
    def chat_send(
        recipients: str = typer.Option(..., "--recipients", help="Comma-separated recipient IDs."),
        text: str = typer.Option(..., "--text", help="Message text."),
        name: str | None = typer.Option(None, "--name", help="Optional thread name."),
        parents_mutual_visibility: bool = typer.Option(
            False,
            "--parents-visible/--parents-hidden",
            help="Parents mutual visibility flag.",
        ),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """Send a chat message (creates a thread)."""
        settings, tokens, context = _env()
        recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]
        variables = {
            "input": {
                "message": {"text": text, "attachment": None},
                "recipients": recipient_list,
                "name": name,
                "parentsMutualVisibility": parents_mutual_visibility,
            }
        }
        try:
            data = _execute_graphql(
                settings, tokens, queries.CREATE_THREAD, variables, context, label="createThread"
            )
        except Exception as exc:  # pragma: no cover - network errors
            console.print(f"[red]GraphQL error:[/red] {exc}")
            raise typer.Exit(code=1) from exc
        if json_output:
            console.print_json(data=data)
        else:
            result = (data.get("createThread") or {}) if isinstance(data, dict) else {}
            if result.get("success"):
                console.print(f"[green]Thread created. id={result.get('id')}[/green]")
            else:
                console.print(f"[red]Send failed:[/red] {result.get('error')}")
