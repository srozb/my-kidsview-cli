from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import typer

from .. import queries
from ..helpers import run_query_table


def register_payments(app: typer.Typer) -> None:  # noqa: PLR0915
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
            filtered = edges
            status_l = status.lower() if status else None
            if status_l:
                filtered = [
                    e
                    for e in filtered
                    if str((e.get("node") or {}).get("bluemediaPaymentStatus", "")).lower()
                    == status_l
                ]
            if created_from:
                filtered = [
                    e
                    for e in filtered
                    if str((e.get("node") or {}).get("created", "")) >= created_from
                ]
            if created_to:
                filtered = [
                    e
                    for e in filtered
                    if str((e.get("node") or {}).get("created", "")) <= created_to
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
            headers=["ID", "Name", "Type"],
            title="💸 Payment components",
            rows_fn=lambda payload: [
                (
                    str((edge.get("node") or {}).get("id", "")),
                    str((edge.get("node") or {}).get("name", "")),
                    str((edge.get("node") or {}).get("type", "")),
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
            title="🧾 Billing periods",
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
            title="🧾 Employee billing periods",
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
    def tuition_discounts(
        first: int = typer.Option(20, help="Number of discounts."),
        after: str | None = typer.Option(None, help="Cursor for pagination."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """List tuition discounts (if available)."""
        variables = {"first": first, "after": after}
        run_query_table(
            query=queries.TUITION_DISCOUNTS,
            variables=variables,
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
                    str(d.get("valueType", "")) if "valueType" in d else str(d.get("type", "")),
                    "yes" if d.get("active") else "no",
                )
                for d in (payload.get("tuitionDiscounts") or [])
            ],
        )

    @app.command("employee-roles")
    def employee_roles(
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
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
                    str(role.get("id", "")),
                    str(role.get("name", "")),
                    ", ".join(role.get("permissions", []) or []),
                )
                for role in payload.get("employeeRoles") or []
            ],
        )

    @app.command("employees")
    def employees(  # noqa: PLR0913
        first: int = typer.Option(20, help="Number of employees."),
        after: str | None = typer.Option(None, help="Cursor after."),
        search: str = typer.Option("", help="Search phrase."),
        json_output: bool = typer.Option(False, "--json/--no-json"),
    ) -> None:
        """List employees (basic fields)."""
        variables = {"first": first, "after": after, "search": search or None}

        def _rows(payload: dict[str, Any]) -> list[Sequence[str]]:
            edges = (payload.get("employees") or {}).get("edges") or []
            rows_local: list[Sequence[str]] = []
            for edge in edges:
                node = edge.get("node") or {}
                rows_local.append(
                    (
                        str(node.get("id", "")),
                        f"{node.get('firstName','')} {node.get('lastName','')}".strip(),
                        str(node.get("email", "")),
                        str(node.get("phone", "")),
                        str(node.get("position", "")),
                        str((node.get("role") or {}).get("name", "")),
                    )
                )
            return rows_local

        run_query_table(
            query=queries.EMPLOYEES,
            variables=variables,
            label="employees",
            json_output=json_output,
            empty_msg="No employees.",
            headers=["ID", "Name", "Email", "Phone", "Position", "Role"],
            title="👥 Employees",
            rows_fn=_rows,
        )
