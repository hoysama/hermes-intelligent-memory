from __future__ import annotations

from types import SimpleNamespace

from intelligent_memory.cloud import CloudMemoryAnalyzer, redact_sensitive_text


def test_redaction_removes_secret_like_values_and_private_blocks() -> None:
    raw = (
        "Use token sk-abcdefghijklmnopqrstuvwxyz123456 and "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz.123456789\n"
        "<private>do not transmit this</private>"
    )

    redacted = redact_sensitive_text(raw)

    assert "sk-" not in redacted
    assert "Bearer abc" not in redacted
    assert "do not transmit" not in redacted
    assert redacted.count("[REDACTED]") >= 2


def test_selective_analyzer_skips_conversation_without_memory_signal() -> None:
    calls = []
    analyzer = CloudMemoryAnalyzer(caller=lambda **kwargs: calls.append(kwargs))

    assert analyzer.extract([{"role": "user", "content": "كيف حالك؟"}]) == []
    assert calls == []


def test_analyzer_returns_validated_structured_facts() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=(
                        '{"facts":[{"content":"عبدالله يفضل Bun",'
                        '"kind":"preference","target":"user",'
                        '"aliases":["مدير الحزم"],"confidence":1.0,'
                        '"importance":0.95}]}'
                    )
                )
            )
        ]
    )
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        return response

    analyzer = CloudMemoryAnalyzer(caller=caller, max_input_chars=2000)
    facts = analyzer.extract(
        [{"role": "user", "content": "تذكر أني أفضل Bun لإدارة الحزم"}]
    )

    assert len(calls) == 1
    assert calls[0]["task"] == "intelligent_memory"
    assert len(facts) == 1
    assert facts[0].content == "عبدالله يفضل Bun"
    assert facts[0].aliases == ("مدير الحزم",)
    assert facts[0].confidence == 1.0


def test_analyzer_rejects_invalid_or_oversized_model_output() -> None:
    invalid = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"facts":[{"content":""}]}'))]
    )
    analyzer = CloudMemoryAnalyzer(caller=lambda **_kwargs: invalid)

    assert analyzer.extract([{"role": "user", "content": "تذكر هذه المعلومة"}]) == []
