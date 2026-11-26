# Retrieval Evaluations

This directory contains an offline evaluation harness for the intelligent memory
provider. It measures lexical retrieval quality without cloud calls, model
downloads, or network access.

## Built-in Arabic and mixed-language suite

```bash
python -m evals.runner
# or:
python -m evals.runner --suite evals/arabic_suite.json --k 3 --verbose
```

The suite contains dated facts and queries in Arabic, English, and mixed
technical Arabic/English. It exercises Arabic normalization (alef variants,
tashkeel, ta marbuta), prefix stripping, aliases, character trigrams, tags, and
project fields.

Reported metrics:

- `recall_at_1` and `recall_at_k`: share of queries whose relevant fact appears
  in the top 1 or top k results.
- `mrr`: mean reciprocal rank of the first relevant fact.
- `failures`: queries with no relevant fact in the top k.

The suite is intentionally small and deterministic. It is a regression guard,
not a substitute for a large public benchmark.

## External datasets (LoCoMo, LongMemEval, or your own)

Official LoCoMo and LongMemEval datasets are not bundled here. Download them
under their own licenses, convert each question to the JSONL format below, and
run the harness against the converted file.

```jsonl
{"query": "Which city does the user live in?", "corpus": [{"id": "d1", "content": "I moved to Lisbon in May."}, {"id": "d2", "content": "The deploy runs on Fridays."}], "relevant": ["d1"]}
```

```bash
python -m evals.runner --dataset path/to/converted.jsonl --k 5
```

Each line is independent: the harness builds a fresh store for its corpus, so
converted conversation-level datasets can include only the turns that belong to
that question. Do not publish benchmark numbers until the conversion and the
run are reproducible and the dataset license permits it.

## Interpreting results

This provider stores canonical facts, not raw transcripts. A benchmark that
expects verbatim passage retrieval (for example, exact dialogue spans) measures
a different task. Compare results only against the same fact-extraction and
retrieval setup, and report the conversion method alongside the numbers.