from __future__ import annotations

import json

from evals.runner import evaluate_dataset, evaluate_suite, load_suite


def test_builtin_arabic_suite_meets_retrieval_baseline() -> None:
    metrics = evaluate_suite(load_suite(), k=3)

    assert metrics["queries"] >= 15
    assert metrics["recall_at_k"] >= 0.85
    assert metrics["mrr"] >= 0.6
    assert metrics["failures"] == []


def test_external_dataset_adapter_reports_metrics(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "query": "بوابة الدفع",
                        "corpus": [
                            {"id": "billing", "content": "بوابة الدفع هي Stripe لمعالجة المدفوعات"},
                            {"id": "cache", "content": "نستخدم Redis للجلسات"},
                        ],
                        "relevant": ["billing"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "query": "session cache",
                        "corpus": [
                            {"id": "billing", "content": "بوابة الدفع هي Stripe لمعالجة المدفوعات"},
                            {
                                "id": "cache",
                                "content": "Redis يُستخدم لتخزين الجلسات المؤقتة",
                                "aliases": ["session cache"],
                            },
                        ],
                        "relevant": ["cache"],
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    metrics = evaluate_dataset(dataset, k=1)

    assert metrics["queries"] == 2
    assert metrics["recall_at_1"] == 1.0
    assert metrics["mrr"] == 1.0
    assert metrics["failures"] == []