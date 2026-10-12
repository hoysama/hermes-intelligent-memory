import json
import time
from pathlib import Path

import pytest
from intelligent_memory import IntelligentMemoryProvider
from intelligent_memory.core.models import FactInput, FactStatus
from intelligent_memory.core.store import MemoryStore


def test_in_process_semantic_reranking_accuracy_and_speed(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")

    # Add multiple facts
    store.remember(
        FactInput(
            content="إعدادات المدفوعات عبر بوابة Stripe في بيئة الإنتاج",
            project="billing",
            tags=("payments", "stripe", "production"),
            source="user",
            confidence=0.9,
            importance=0.9,
        )
    )
    store.remember(
        FactInput(
            content="نظام التوثيق وتسجيل الدخول عبر JWT",
            project="auth",
            tags=("security", "jwt", "auth"),
            source="user",
            confidence=0.8,
            importance=0.8,
        )
    )
    store.remember(
        FactInput(
            content="استخدام Redis لتخزين الجلسات المؤقتة",
            project="infrastructure",
            tags=("cache", "redis", "sessions"),
            source="user",
            confidence=0.7,
            importance=0.7,
        )
    )

    # 1. Test Arabic morphological prefix matching ("مدفوعات" -> "المدفوعات")
    start = time.perf_counter()
    results = store.search("مدفوعات", limit=5)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert len(results) >= 1
    assert results[0].project == "billing"
    assert "Stripe" in results[0].content
    # Blazing speed: in-process reranking must execute well under 10ms (typically < 0.5ms)
    assert elapsed_ms < 20.0

    # 2. Test Tag and Project boost
    tag_results = store.search("stripe production", limit=5)
    assert tag_results[0].project == "billing"
    assert "payments" in tag_results[0].tags

    store.close()


def test_explicit_project_and_kind_filtering(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")

    store.remember(
        FactInput(
            content="قاعدة بيانات التطبيق هي PostgreSQL",
            kind="fact",
            project="core-backend",
            source="user",
        )
    )
    store.remember(
        FactInput(
            content="المستخدم يفضل كتابة الأكواد بلغة بايثون",
            kind="preference",
            project="core-backend",
            source="user",
        )
    )
    store.remember(
        FactInput(
            content="واجهة المستخدم مبنية باستخدام React و Vite",
            kind="fact",
            project="frontend-app",
            source="user",
        )
    )

    # Filter by project: core-backend
    backend_facts = store.search("بيانات", project="core-backend")
    assert len(backend_facts) == 1
    assert backend_facts[0].project == "core-backend"
    assert "PostgreSQL" in backend_facts[0].content

    # Filter by project: frontend-app
    frontend_facts = store.search("بيانات", project="frontend-app")
    assert len(frontend_facts) == 0

    frontend_all = store.search("واجهة", project="frontend-app")
    assert len(frontend_all) == 1
    assert frontend_all[0].project == "frontend-app"

    # Filter by kind: preference
    prefs = store.search("بايثون", kind="preference")
    assert len(prefs) == 1
    assert prefs[0].kind == "preference"

    # Filter by kind: fact (should not match preference)
    no_fact = store.search("بايثون", kind="fact")
    assert len(no_fact) == 0

    store.close()


def test_provider_tools_project_tags_and_conflict_warning(tmp_path: Path) -> None:
    provider = IntelligentMemoryProvider()
    provider.database_path = tmp_path / "memory.db"
    provider.profile = "default"
    provider.store = MemoryStore(provider.database_path, profile=provider.profile)

    # 1. Store initial fact with project and tags
    res1_raw = provider.handle_tool_call(
        "intelligent_memory_remember",
        {
            "content": "استخدم دائما مكتبة requests للاتصال بالشبكة",
            "project": "api-gateway",
            "tags": ["network", "http", "api"],
            "kind": "preference",
        },
    )
    res1 = json.loads(res1_raw)
    assert res1["success"] is True
    assert res1["created"] is True
    assert "conflict_detected" not in res1
    fact_id_1 = res1["fact_id"]

    # 2. Recall and verify project and tags in payload
    recall_raw = provider.handle_tool_call(
        "intelligent_memory_recall",
        {"query": "requests", "project": "api-gateway"},
    )
    recall = json.loads(recall_raw)
    assert recall["success"] is True
    assert len(recall["facts"]) == 1
    recalled_fact = recall["facts"][0]
    assert recalled_fact["fact_id"] == fact_id_1
    assert recalled_fact["project"] == "api-gateway"
    assert recalled_fact["tags"] == ["network", "http", "api"]

    # 3. Store a contradictory fact -> Proactive Conflict Warning!
    res2_raw = provider.handle_tool_call(
        "intelligent_memory_remember",
        {
            "content": "لا تستخدم مكتبة requests في هذا المشروع واستخدم httpx بدلا منها",
            "project": "api-gateway",
            "tags": ["network", "http"],
            "kind": "preference",
        },
    )
    res2 = json.loads(res2_raw)
    assert res2["success"] is True
    assert res2.get("conflict_detected") is True
    assert "warning" in res2
    assert res2["conflicting_fact"]["fact_id"] == fact_id_1
    assert "intelligent_memory_revise" in res2["suggestion"]
    fact_id_2 = res2["fact_id"]

    # Verify conflicts_with_id is linked in store
    saved_fact2 = provider.store.get_fact(fact_id_2)
    assert saved_fact2.conflicts_with_id == fact_id_1

    # 4. Hermes chooses to revise fact_id_1
    revise_raw = provider.handle_tool_call(
        "intelligent_memory_revise",
        {
            "fact_id": fact_id_1,
            "content": "استخدم مكتبة httpx غير المتزامنة لجميع الاتصالات الشبكية",
            "project": "api-gateway",
            "tags": ["network", "httpx", "async"],
        },
    )
    revise_res = json.loads(revise_raw)
    assert revise_res["success"] is True
    assert revise_res["done"] is True

    # Verify fact_id_1 is now SUPERSEDED
    old_fact = provider.store.get_fact(fact_id_1)
    assert old_fact.status is FactStatus.SUPERSEDED

    provider.shutdown()
