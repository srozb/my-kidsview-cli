from __future__ import annotations

import json
from pathlib import Path


def _load_schema() -> dict:
    schema_path = Path("docs/schema-introspection.json")
    if not schema_path.exists():
        raise FileNotFoundError("docs/schema-introspection.json not found; run introspection.")
    data = json.loads(schema_path.read_text())
    # console.print_json zapisuje bez klucza "data" – obsługujemy obie formy
    return data.get("data", data)


def _field_map(kind_name: str, root: dict) -> dict[str, set[str]]:
    types = {t["name"]: t for t in root["__schema"]["types"]}
    fields = {}
    for f in types[kind_name]["fields"]:
        fields[f["name"]] = {arg["name"] for arg in f.get("args", [])}
    return fields


def test_required_queries_exist_and_have_expected_args() -> None:
    root = _load_schema()
    query_name = root["__schema"]["queryType"]["name"]
    qfields = _field_map(query_name, root)

    expected_queries: dict[str, set[str]] = {
        "announcements": set(),
        "monthlyBills": {"isPaid", "year"},
        "galleries": {"first"},
        "activeChild": set(),
        "usersForChat": set(),
        "groupsForChat": {"search"},
        "me": set(),
        "notifications": {"pending", "first"},
        "applications": set(),
        "currentDietForChild": set(),
        "calendar": {"dateFrom", "dateTo"},
        "years": set(),
        "payments": {"dateFrom", "dateTo"},
        "paymentsSummary": {"search", "balanceGte", "balanceLte"},
        "paymentOrders": {"first"},
    }

    for name, expected_args in expected_queries.items():
        assert name in qfields, f"Query {name} missing in schema"
        assert expected_args.issubset(
            qfields[name]
        ), f"Query {name} missing args: {expected_args - qfields[name]}"


def test_required_mutations_exist_and_have_expected_args() -> None:
    root = _load_schema()
    mutation_name = root["__schema"]["mutationType"]["name"]
    mfields = _field_map(mutation_name, root)

    expected_mutations: dict[str, set[str]] = {
        "sendMessage": {"recipients", "text"},
        # Schema uses notificationId (not generic id)
        "setNotificationRead": {"notificationId"},
        "setChildAbsence": {"childId", "date"},
        "setGalleryLike": {"galleryId"},
        "createGalleryComment": {"input"},
        "createApplication": {"input"},
    }

    for name, expected_args in expected_mutations.items():
        assert name in mfields, f"Mutation {name} missing in schema"
        assert expected_args.issubset(
            mfields[name]
        ), f"Mutation {name} missing args: {expected_args - mfields[name]}"
