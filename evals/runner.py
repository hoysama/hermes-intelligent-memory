from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = PROJECT_ROOT / "plugin"
for path in (PROJECT_ROOT, PLUGIN_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from intelligent_memory.core.models import FactInput  # noqa: E402
from intelligent_memory.core.store import MemoryStore  # noqa: E402

DEFAULT_SUITE = Path(__file__).with_name("arabic_suite.json")
EXTERNAL_FORMAT = (
    "JSONL with one object per line: "
    '{"query": str, "corpus": [{"id": str, "content": str}], "relevant": [str]}'
)


def load_suite(path: str | Path = DEFAULT_SUITE) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("suite must be a JSON object")
    facts = payload.get("facts")
    queries = payload.get("queries")
    if not isinstance(facts, list) or not isinstance(queries, list):
        raise ValueError("suite requires 'facts' and 'queries' lists")
    return payload


def evaluate_suite(
    suite: dict[str, Any], *, k: int = 3, verbose: bool = False
) -> dict[str, Any]:
    facts = suite["facts"]
    queries = suite["queries"]
    with tempfile.TemporaryDirectory(prefix="intelligent-memory-eval-") as tmp:
        store = MemoryStore(Path(tmp) / "eval.db", profile="eval")
        try:
            id_by_fact_id = _load_facts(store, facts)
            metrics = _score_queries(
                store, queries, id_by_fact_id, k=k, verbose=verbose
            )
        finally:
            store.close()
    metrics["suite"] = suite.get("name", "unnamed")
    return metrics


def evaluate_dataset(
    path: str | Path, *, k: int = 5, verbose: bool = False
) -> dict[str, Any]:
    cases = [
        json.loads(line)
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    total_queries = 0
    total_hits = 0
    total_hits_at_1 = 0
    total_rr = 0.0
    failures: list[dict[str, Any]] = []

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(EXTERNAL_FORMAT)
        query = str(case.get("query") or "")
        corpus = case.get("corpus")
        relevant = case.get("relevant")
        if not query or not isinstance(corpus, list) or not isinstance(relevant, list):
            raise ValueError(EXTERNAL_FORMAT)
        facts = [
            {
                **item,
                "id": str(item.get("id") or f"case-{index}-doc-{position}"),
                "content": str(item.get("content") or ""),
            }
            for position, item in enumerate(corpus)
            if isinstance(item, dict)
        ]
        with tempfile.TemporaryDirectory(
            prefix="intelligent-memory-eval-dataset-"
        ) as tmp:
            store = MemoryStore(Path(tmp) / "eval.db", profile="eval")
            try:
                id_by_fact_id = _load_facts(store, facts)
                metrics = _score_queries(
                    store,
                    [{"query": query, "relevant": relevant}],
                    id_by_fact_id,
                    k=k,
                    verbose=verbose,
                )
            finally:
                store.close()
        total_queries += 1
        total_hits += 1 if metrics["recall_at_k"] else 0
        total_hits_at_1 += 1 if metrics["recall_at_1"] else 0
        total_rr += metrics["mrr"]
        failures.extend(metrics["failures"])

    return {
        "dataset": str(path),
        "queries": total_queries,
        "k": k,
        "recall_at_1": round(total_hits_at_1 / total_queries, 4)
        if total_queries
        else 0.0,
        "recall_at_k": round(total_hits / total_queries, 4) if total_queries else 0.0,
        "mrr": round(total_rr / total_queries, 4) if total_queries else 0.0,
        "failures": failures,
    }


def _load_facts(store: MemoryStore, facts: list[dict[str, Any]]) -> dict[int, str]:
    id_by_fact_id: dict[int, str] = {}
    for fact in facts:
        fact_id = str(fact.get("id") or "")
        content = str(fact.get("content") or "")
        if not fact_id or not content:
            continue
        result = store.remember(
            FactInput(
                content=content,
                kind=str(fact.get("kind") or "general"),
                target=str(fact.get("target") or "memory"),
                project=str(fact.get("project") or ""),
                tags=tuple(str(tag) for tag in fact.get("tags", [])),
                aliases=tuple(str(alias) for alias in fact.get("aliases", [])),
                source="eval",
                profile="eval",
                confidence=float(fact.get("confidence", 0.9)),
                importance=float(fact.get("importance", 0.8)),
            )
        )
        id_by_fact_id[result.fact_id] = fact_id
    return id_by_fact_id


def _score_queries(
    store: MemoryStore,
    queries: list[dict[str, Any]],
    id_by_fact_id: dict[int, str],
    *,
    k: int,
    verbose: bool,
) -> dict[str, Any]:
    hits = 0
    hits_at_1 = 0
    reciprocal_rank = 0.0
    failures: list[dict[str, Any]] = []
    for case in queries:
        query = str(case.get("query") or "")
        relevant = {str(item) for item in case.get("relevant", [])}
        if not query or not relevant:
            continue
        results = store.search(query, limit=max(k, 5))
        ranked = [id_by_fact_id.get(fact.fact_id, "") for fact in results]
        rank = next(
            (
                position
                for position, fact_id in enumerate(ranked, start=1)
                if fact_id in relevant
            ),
            None,
        )
        if rank is not None and rank <= k:
            hits += 1
        if rank == 1:
            hits_at_1 += 1
        if rank is not None:
            reciprocal_rank += 1.0 / rank
        else:
            failures.append(
                {
                    "query": query,
                    "relevant": sorted(relevant),
                    "top": ranked[:k],
                }
            )
        if verbose:
            print(
                json.dumps(
                    {
                        "query": query,
                        "relevant": sorted(relevant),
                        "rank": rank,
                        "top": ranked[:k],
                    },
                    ensure_ascii=False,
                )
            )
    total = sum(1 for case in queries if case.get("query") and case.get("relevant"))
    return {
        "queries": total,
        "k": k,
        "recall_at_1": round(hits_at_1 / total, 4) if total else 0.0,
        "recall_at_k": round(hits / total, 4) if total else 0.0,
        "mrr": round(reciprocal_rank / total, 4) if total else 0.0,
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evaluate-memory",
        description="Offline retrieval evaluation for intelligent memory.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--suite",
        type=Path,
        default=DEFAULT_SUITE,
        help=f"Built-in suite JSON (default: {DEFAULT_SUITE.name})",
    )
    source.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help=f"External JSONL dataset. Format: {EXTERNAL_FORMAT}",
    )
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.dataset is not None:
        metrics = evaluate_dataset(args.dataset, k=args.k, verbose=args.verbose)
    else:
        metrics = evaluate_suite(
            load_suite(args.suite), k=args.k, verbose=args.verbose
        )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())