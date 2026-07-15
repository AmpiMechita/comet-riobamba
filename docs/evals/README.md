# Evals — COMET-RIOBAMBA Behavioral Evaluation

## Purpose

The eval suite provides a lightweight behavioral regression test for Phase B decision logic. Unlike unit tests (which test individual functions in isolation), evals test _decision outcomes_ against a frozen set of realistic inputs — ensuring that changes to relevance scoring, dedup logic, guardrails, or prompting produce the expected results.

## Structure

```
evals/
├── run_evals.py                    # Eval runner (Python)
├── fixtures/
│   └── phase_b_cases.json          # 24 fixture cases
└── README.md                       # This file
```

## How It Works

1. `run_evals.py` loads 24 cases from `fixtures/phase_b_cases.json`
2. For each case, it calls the relevant Phase B method:
   - `_classify_topic_value()` for feed cases (HIGH_VALUE → expect reply, TRIVIAL → expect skip)
   - `_is_non_trivial_contribution()` for STANDARD cases
   - `_decide_reply()` for own-post cases
   - `_classify_debate_value()` for debate cases
3. Each actual output is compared against the `expected` field
4. Pass rate is calculated; >= 85% is required (exit 0), else exit 1

## Running

```powershell
python evals/run_evals.py
```

## When to Update Fixtures

Add or modify fixture cases when:

- **A new guardrail is added** — add 1 case that should pass it and 1 that should trigger it
- **Relevance scoring is changed** — verify that HIGH_VALUE/STANDARD/TRIVIAL boundaries are still correct
- **Dedup logic is modified** — add cases for near-duplicate boundaries
- **Submolt filtering is updated** — add cases for new allowed/blocked submolts

## Fixture Schema

```json
{
  "id": "unique_case_id",
  "type": "feed | own_post | debate",
  "expected": "reply | skip | reply_if_non_trivial",
  "value_level": "HIGH_VALUE | STANDARD | TRIVIAL",
  "post_body": "...",
  "comments": [],
  "draft": "...",
  "content": "...",
  "comment_text": "...",
  "author": "...",
  "post_id": "...",
  "comment_id": "..."
}
```

## Release Process Integration

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐
│ Unit     │───→│ Behavioral│───→│ Production│───→│ Postmortem   │
│ Tests    │    │ Evals     │    │ Monitoring│    │              │
│ (always) │    │ (>= 85%)  │    │ (daily)   │    │ (per incident)│
└──────────┘    └──────────┘    └──────────┘    └──────────────┘
     │               │               │                  │
     │               │               │                  │
     ▼               ▼               ▼                  ▼
 Block PR        Block PR        Alert on drift     Add regression
                                                        case
```

## Future

- Expand to cover Phase A topic selection and content validation
- Add automated eval run on every PR (CI)
- Support A/B comparison: run evals against two code versions and diff results
