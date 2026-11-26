from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from intelligent_memory import IntelligentMemoryProvider
from intelligent_memory.core.models import FactInput, FactStatus
from intelligent_memory.core.store import MemoryStore


def _provider(tmp_path: Path) -> IntelligentMemoryProvider:
    provider = IntelligentMemoryProvider({"cloud_mode": "off"})
    provider.initialize(
        "session-1",
        hermes_home=str(tmp_path),
        platform="cli",
        agent_context="primary",
        agent_identity="default",
    )
    return provider


def test_provenance_quote_and_offsets_roundtrip(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    result = store.remember(
        FactInput(
            content="عبدالله يفضل Bun لإدارة الحزم",
            kind="preference",
            target="user",
            source="user",
            source_ref="session:1",
            quote="أفضل Bun لإدارة الحزم",
            quote_start=12,
            quote_end=34,
        )
    )

    provenance = store.list_provenance(result.fact_id)

    assert len(provenance) == 1
    assert provenance[0].quote == "أفضل Bun لإدارة الحزم"
    assert provenance[0].quote_start == 12
    assert provenance[0].quote_end == 34
    store.close()


def test_recall_tool_includes_verbatim_sources(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    provider.on_memory_write(
        "add",
        "memory",
        "المشروع يستخدم SQLite للتخزين المحلي",
        metadata={"session_id": "s1"},
    )

    payload = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_recall", {"query": "SQLite"}
        )
    )

    assert payload["success"] is True
    assert payload["facts"][0]["scope"] == "global"
    assert payload["facts"][0]["sources"][0]["quote"] == (
        "المشروع يستخدم SQLite للتخزين المحلي"
    )
    assert payload["facts"][0]["sources"][0]["quote_start"] == 0
    provider.shutdown()


def test_revoke_restore_and_audit_lifecycle(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    fact = store.remember(FactInput(content="قرار مؤقت", source="user"))

    revoked = store.revoke(fact.fact_id, reason="user asked")

    assert revoked.status is FactStatus.REVOKED
    assert store.search("قرار مؤقت") == []

    restored = store.restore(fact.fact_id, reason="undo")

    assert restored.status is FactStatus.ACTIVE
    assert store.search("قرار مؤقت")[0].fact_id == fact.fact_id
    assert [entry.action for entry in store.list_audit(fact_id=fact.fact_id)] == [
        "restore",
        "revoke",
    ]
    store.close()


def test_erase_removes_text_and_provenance_but_keeps_audit_hash(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    fact = store.remember(
        FactInput(
            content="سر خاص يجب حذفه",
            source="user",
            quote="سر خاص يجب حذفه",
            quote_start=0,
            quote_end=16,
        )
    )

    erased = store.erase(fact.fact_id, reason="erasure request")

    assert erased.status is FactStatus.ERASED
    assert erased.content == "[erased]"
    assert erased.normalized_content == ""
    assert store.list_provenance(fact.fact_id) == []
    assert store.search("سر خاص") == []
    audit = store.list_audit(fact_id=fact.fact_id)
    assert len(audit) == 1
    assert audit[0].action == "erase"
    assert audit[0].reason == "erasure request"
    assert len(audit[0].content_hash) == 64
    store.close()


def test_scope_is_a_filter_not_a_profile_boundary(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    global_fact = store.remember(
        FactInput(content="Global deployment note", scope="global", source="user")
    )
    team_fact = store.remember(
        FactInput(content="Team deployment note", scope="team-a", source="user")
    )

    assert {fact.fact_id for fact in store.search("deployment")} == {
        global_fact.fact_id,
        team_fact.fact_id,
    }
    assert [fact.fact_id for fact in store.search("deployment", scope="global")] == [
        global_fact.fact_id
    ]
    assert [fact.fact_id for fact in store.search("deployment", scope="team-a")] == [
        team_fact.fact_id
    ]
    other_profile = MemoryStore(tmp_path / "memory.db", profile="other")
    assert other_profile.search("deployment") == []
    other_profile.close()
    store.close()


def test_forget_modes_and_restore_through_provider(tmp_path: Path) -> None:
    provider = _provider(tmp_path)
    first = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_remember", {"content": "first memory"}
        )
    )
    second = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_remember", {"content": "second memory"}
        )
    )
    third = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_remember", {"content": "third memory"}
        )
    )

    revoked = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_forget",
            {"fact_id": first["fact_id"], "mode": "revoke", "reason": "temporary"},
        )
    )
    erased = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_forget",
            {"fact_id": second["fact_id"], "mode": "erase"},
        )
    )
    provider.handle_tool_call(
        "intelligent_memory_forget",
        {"fact_id": third["fact_id"], "reason": "cleanup"},
    )

    assert revoked["status"] == "revoked"
    assert erased["status"] == "erased"
    assert provider.store.get_fact(third["fact_id"]).status is FactStatus.ARCHIVED
    assert provider.store.get_fact(second["fact_id"]).content == "[erased]"
    assert provider.store.search("second memory") == []

    restored = json.loads(
        provider.handle_tool_call(
            "intelligent_memory_restore", {"fact_id": first["fact_id"]}
        )
    )
    assert restored["status"] == "active"
    assert provider.store.search("first memory")[0].fact_id == first["fact_id"]
    provider.shutdown()


def test_private_defaults_are_off_and_bounded() -> None:
    provider = IntelligentMemoryProvider()

    assert provider.cloud_mode == "off"
    assert provider.max_recall_facts == 6
    assert provider.max_recall_chars == 1800

def test_old_provenance_schema_upgrades_in_place(tmp_path: Path) -> None:
    database = tmp_path / "memory.db"
    store = MemoryStore(database, profile="default")
    fact = store.remember(FactInput(content="schema upgrade fact", source="user"))
    store.close()

    connection = sqlite3.connect(database)
    connection.execute("ALTER TABLE fact_provenance DROP COLUMN quote")
    connection.execute("ALTER TABLE fact_provenance DROP COLUMN quote_start")
    connection.execute("ALTER TABLE fact_provenance DROP COLUMN quote_end")
    connection.commit()
    connection.close()

    upgraded = MemoryStore(database, profile="default")
    provenance = upgraded.list_provenance(fact.fact_id)

    assert provenance[0].quote == ""
    assert provenance[0].quote_start == -1
    assert provenance[0].quote_end == -1
    assert upgraded.list_audit() == []
    upgraded.close()


def test_scope_isolation_prevents_cross_scope_supersession(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    global_fact = store.remember(
        FactInput(
            content="يوم النشر هو الجمعة",
            subject="النشر",
            predicate="اليوم",
            value="الجمعة",
            scope="global",
            source="user",
        )
    )
    team_fact = store.remember(
        FactInput(
            content="يوم النشر هو الاثنين",
            subject="النشر",
            predicate="اليوم",
            value="الاثنين",
            scope="team-a",
            source="user",
        )
    )

    assert store.get_fact(global_fact.fact_id).status is FactStatus.ACTIVE
    assert store.get_fact(team_fact.fact_id).status is FactStatus.ACTIVE
    assert store.get_fact(team_fact.fact_id).supersedes_id is None
    store.close()
