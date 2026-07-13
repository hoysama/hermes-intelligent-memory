from __future__ import annotations

import json
from pathlib import Path

import pytest
from intelligent_memory import IntelligentMemoryProvider
from intelligent_memory.core.models import FactInput, FactStatus


@pytest.fixture
def provider(tmp_path: Path) -> IntelligentMemoryProvider:
    instance = IntelligentMemoryProvider(
        config={
            "cloud_mode": "off",
            "max_recall_facts": 4,
            "max_recall_chars": 500,
        }
    )
    instance.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_context="primary",
        agent_identity="default",
    )
    yield instance
    instance.shutdown()


def test_provider_uses_profile_scoped_database(provider, tmp_path) -> None:
    assert provider.database_path == tmp_path / "intelligent_memory" / "memory.db"
    assert provider.database_path.exists()


def test_prefetch_is_bounded_and_returns_only_relevant_active_facts(provider) -> None:
    for index in range(12):
        provider.store.remember(
            FactInput(
                content=f"قرار Cloudflare رقم {index} يستخدم Workers",
                kind="decision",
                source="user",
                importance=0.8,
            )
        )
    unrelated = provider.store.remember(
        FactInput(content="تفصيل عن Unreal Engine", source="user")
    )
    provider.store.archive(unrelated.fact_id)

    context = provider.prefetch("ما قرارات Cloudflare Workers؟")

    assert context.startswith("# Relevant memory")
    assert context.count("\n- [") <= 4
    assert len(context) <= 500
    assert "Unreal Engine" not in context


def test_builtin_add_replace_remove_are_mirrored_with_lifecycle(provider) -> None:
    provider.on_memory_write(
        "add",
        "user",
        "عبدالله يفضل npm لإدارة الحزم",
        metadata={"session_id": "s1", "tool_name": "memory"},
    )
    original = provider.store.search("npm عبدالله")[0]

    provider.on_memory_write(
        "replace",
        "user",
        "عبدالله يفضل Bun لإدارة الحزم",
        metadata={"old_text": "يفضل npm", "session_id": "s1"},
    )
    replacement = provider.store.search("Bun عبدالله")[0]

    assert provider.store.get_fact(original.fact_id).status is FactStatus.SUPERSEDED
    assert replacement.supersedes_id == original.fact_id

    provider.on_memory_write(
        "remove",
        "user",
        "",
        metadata={"old_text": "يفضل Bun", "session_id": "s1"},
    )

    assert provider.store.get_fact(replacement.fact_id).status is FactStatus.ARCHIVED
    assert provider.store.search("Bun عبدالله") == []


def test_provider_tools_have_stable_json_contract(provider) -> None:
    remember = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_remember",
            {
                "content": "المشروع يستخدم Cloudflare D1",
                "kind": "project",
                "target": "memory",
                "importance": 0.9,
            },
        )
    )
    recall = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_recall", {"query": "قاعدة بيانات Cloudflare"}
        )
    )
    status = json.loads(provider.handle_tool_call("intelligent_memory_status", {}))

    assert remember["success"] is True
    assert remember["created"] is True
    assert recall["success"] is True
    assert recall["facts"][0]["fact_id"] == remember["fact_id"]
    assert status["success"] is True
    assert status["active_facts"] == 1


def test_cloud_failure_never_breaks_session_end(tmp_path) -> None:
    def failing_analyzer(_messages):
        raise RuntimeError("provider unavailable")

    provider = IntelligentMemoryProvider(
        config={"cloud_mode": "selective"}, cloud_analyzer=failing_analyzer
    )
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_context="primary",
        agent_identity="default",
    )

    provider.on_session_end(
        [{"role": "user", "content": "من الآن استخدم Bun دائماً"}]
    )

    assert provider.store.active_count() == 0
    assert provider.last_cloud_error == "provider unavailable"
    provider.shutdown()


def test_non_primary_context_does_not_persist(provider) -> None:
    provider.agent_context = "subagent"
    provider.on_memory_write("add", "memory", "لا يجب حفظها")

    assert provider.store.active_count() == 0
