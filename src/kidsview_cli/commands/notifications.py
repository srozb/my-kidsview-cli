# ruff: noqa: B008
from __future__ import annotations

import json
from typing import Any

import typer

from .. import queries
from ..helpers import (
    console,
    run_query_table,
)
from ..helpers import (
    env as _env,
)
from ..helpers import (
    execute_graphql as _execute_graphql,
)
from ..helpers import (
    print_table as _print_table,
)
from ..helpers import (
    truncate as _truncate,
)


def register_notifications(app: typer.Typer) -> None:  # noqa: PLR0915
    @app.command()
    def unread(json_output: bool = typer.Option(False, "--json/--no-json")) -> None:
        """Fetch unread notification/message counts."""
        headers = ["Type", "Count"]

        def _rows(payload: dict[str, Any]) -> list[list[str]]:
            counts = (payload.get("me") or {}) if payload else {}
            return [
                ["Notifications", str(counts.get("unreadNotificationsCount", 0))],
                ["Messages", str(counts.get("unreadMessagesCount", 0))],
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
    def notifications(  # noqa: PLR0912, PLR0913, PLR0915
        first: int = typer.Option(20, help="Number of notifications to fetch."),
        after: str | None = typer.Option(None, help="Cursor for pagination."),
        pending: bool | None = typer.Option(None, help="Pending filter."),
        type_filter: str | None = typer.Option(None, "--type", help="Type filter (client-side)."),
        only_unread: bool = typer.Option(
            False, "--only-unread", help="Show only unread (client-side)."
        ),
        mark_read: bool = typer.Option(
            False, "--mark-read", help="Mark fetched notifications as read."
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
        variables: dict[str, object] = {"first": first, "after": after, "pending": pending}

        def _fetch_page(after_cursor: str | None) -> dict[str, Any]:
            page_vars = {**variables, "after": after_cursor}
            return _execute_graphql(
                settings, tokens, queries.NOTIFICATIONS, page_vars, context, label="notifications"
            )

        all_edges: list[dict[str, Any]] = []
        next_cursor: str | None = after
        while True:
            data = _fetch_page(next_cursor)
            notifications_conn = data.get("notifications") or {}
            edges = notifications_conn.get("edges") or []
            all_edges.extend(edges)
            page_info = notifications_conn.get("pageInfo") or {}
            if not all_pages or not page_info.get("hasNextPage"):
                break
            next_cursor = page_info.get("endCursor")
            if not next_cursor:
                break

        # client-side filters
        filtered_edges = all_edges
        if type_filter:
            type_norm = type_filter.lower()
            filtered_edges = [
                e
                for e in filtered_edges
                if str((e.get("node") or {}).get("type", "")).lower() == type_norm
            ]
        if only_unread:
            filtered_edges = [e for e in filtered_edges if not (e.get("node") or {}).get("isRead")]

        payload = {"notifications": {"edges": filtered_edges}}

        if mark_read and filtered_edges:
            for edge in filtered_edges:
                notif_id = (edge.get("node") or {}).get("notification", {}).get("id")
                if notif_id:
                    _execute_graphql(
                        settings,
                        tokens,
                        queries.SET_NOTIFICATION_READ,
                        {"notificationId": notif_id},
                        context,
                        label="setNotificationRead",
                    )

        if json_output:
            console.print_json(data=payload)
            return

        if not filtered_edges:
            console.print("No notifications.")
            return

        rows = []
        headers = ["ID", "Text", "Created", "Type", "On date"]
        for item in filtered_edges:
            node = item.get("node", {})
            data_field = node.get("data")
            date_val = ""
            if isinstance(data_field, str):
                try:
                    parsed = json.loads(data_field)
                    date_val = str(parsed.get("date", ""))
                except Exception:
                    date_val = ""
        rows.append(
            (
                str(node.get("id", "")),
                _truncate(str(node.get("text", "")), 120),
                str(node.get("created", "")),
                str(node.get("type", "")),
                date_val,
            )
        )
        _print_table("🔔 Notifications", rows, headers, show_lines=True)

    @app.command("notification-prefs")
    def notification_prefs(  # noqa: PLR0913
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
        payload = {"userNotificationPreferences": prefs}
        if json_output:
            console.print_json(data=payload)
        else:
            if not prefs:
                console.print("No notification preferences.")
                return
            rows = [
                (str(pref.get("notificationType", "")), "yes" if pref.get("enabled") else "no")
                for pref in prefs
            ]
            _print_table("🔔 Notification preferences", rows, ["Type", "Enabled"])
