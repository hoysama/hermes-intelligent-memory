from __future__ import annotations

from intelligent_memory.core.models import FactInput, FactStatus
from intelligent_memory.core.normalize import normalize_text
from intelligent_memory.core.store import MemoryStore


def test_normalize_arabic_and_mixed_technical_terms() -> None:
    assert normalize_text("  عَبْدُالله يُفَضِّل BUN لإدارة الحُزَمـ!  ") == (
        "عبدالله يفضل bun لاداره الحزم"
    )


def test_exact_normalized_duplicate_reuses_fact_and_adds_provenance(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    first = store.remember(
        FactInput(
            content="عبدالله يفضل Bun لإدارة الحزم",
            kind="preference",
            target="user",
            source="user",
            source_ref="session:a",
        )
    )
    second = store.remember(
        FactInput(
            content="عَبْدُالله يفضل bun لإدارة الحزم!",
            kind="preference",
            target="user",
            source="builtin",
            source_ref="USER.md:1",
        )
    )

    assert second.fact_id == first.fact_id
    assert second.created is False
    assert store.provenance_count(first.fact_id) == 2


def test_correction_supersedes_old_fact_without_destroying_history(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    old = store.remember(
        FactInput(
            content="عبدالله يفضل npm لإدارة الحزم",
            kind="preference",
            target="user",
            subject="عبدالله",
            predicate="package_manager",
            value="npm",
            source="user",
        )
    )
    new = store.remember(
        FactInput(
            content="عبدالله يفضل Bun لإدارة الحزم",
            kind="preference",
            target="user",
            subject="عبدالله",
            predicate="package_manager",
            value="Bun",
            source="user",
            supersedes_id=old.fact_id,
        )
    )

    assert store.get_fact(old.fact_id).status is FactStatus.SUPERSEDED
    assert store.get_fact(new.fact_id).status is FactStatus.ACTIVE
    assert [fact.fact_id for fact in store.search("مدير الحزم عبدالله")] == [new.fact_id]


def test_arabic_recall_uses_aliases_and_character_trigrams(tmp_path) -> None:
    store = MemoryStore(tmp_path / "memory.db", profile="default")
    remembered = store.remember(
        FactInput(
            content="عبدالله يعتمد Bun لإدارة dependencies",
            kind="preference",
            target="user",
            aliases=("مدير الحزم", "package manager", "تثبيت مكتبات JavaScript"),
            source="user",
            importance=0.95,
            confidence=1.0,
        )
    )

    results = store.search("وش التقنية المفضلة لتثبيت مكتبات جافاسكربت؟")

    assert results
    assert results[0].fact_id == remembered.fact_id


def test_archived_and_cross_profile_facts_are_not_recalled(tmp_path) -> None:
    db = tmp_path / "memory.db"
    default_store = MemoryStore(db, profile="default")
    other_store = MemoryStore(db, profile="other")
    archived = default_store.remember(
        FactInput(content="معلومة قديمة", source="user", profile="default")
    )
    default_store.archive(archived.fact_id)
    other_store.remember(
        FactInput(content="مشروع سري في profile آخر", source="user", profile="other")
    )

    assert default_store.search("معلومة قديمة") == []
    assert default_store.search("مشروع سري") == []
