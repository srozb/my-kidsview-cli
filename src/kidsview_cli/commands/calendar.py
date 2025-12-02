from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

import typer

from .. import queries
from ..helpers import normalize_date as _normalize_date
from ..helpers import run_query_table

MONTH_LAST = 12


def _compute_range(
    date_from: str, date_to: str, week: bool, month: bool, days: int | None
) -> tuple[str, str]:
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


def register_calendar(app: typer.Typer) -> None:
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
        range_from, range_to = _compute_range(date_from, date_to, week, month, days)
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
        range_from, range_to = _compute_range(date_from, date_to, week, month, days)

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
