import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.value_log import get_value_events_since

logger = logging.getLogger("core.value_review")

REVIEW_DIR = Path("data")

VALUE_REVIEW_SYSTEM_PROMPT = (
    "You are a content strategy analyst for an autonomous agent. "
    "Given aggregated data about valuable user interactions, "
    "propose concrete improvements to the agent's content structure and reply strategy. "
    "Respond only with valid JSON, no markdown, no explanation."
)

VALUE_REVIEW_USER_PROMPT = """Below is a summary of the agent's valuable interactions over the past {days} days.

Total high-value events: {total_events}
Events by classification: {classification_counts}

Top topics (by resolved problems):
{top_topics_resolved}

Topics where no problem was solved (only useful aportes):
{topics_only_aporte}

Problem types distribution:
{problem_type_distribution}

Based on this data, propose improvements. Respond with JSON:
{{
  "analysis_summary": "2-3 sentence overview of what the data shows",
  "top_3_topics_resolved": ["topic 1", "topic 2", "topic 3"],
  "improvement_opportunities": [
    "description of topic area that needs better coverage",
    "another area where the agent only provides useful aportes but never solves the problem"
  ],
  "content_structure_proposals": [
    "specific suggestion for a new post series, section, or prompt improvement",
    "another concrete proposal"
  ],
  "prompt_adjustments": [
    "suggestion to improve reply prompts for a specific problem type",
    "another prompt-level suggestion"
  ]
}}
""".strip()


def _summarize_events(events: List[Dict[str, Any]]) -> str:
    if not events:
        return "No high-value events in this period."

    classification_counts = Counter(e.get("clasificacion_valor", "unknown") for e in events)

    topic_counter: Dict[str, int] = defaultdict(int)
    topic_resolved: Dict[str, int] = defaultdict(int)
    topic_aporte: Dict[str, int] = defaultdict(int)
    problem_type_counter: Counter = Counter()

    for e in events:
        topic = e.get("tema", "unknown")
        topic_counter[topic] += 1
        cls = e.get("clasificacion_valor", "")
        if cls == "resolvio_problema":
            topic_resolved[topic] += 1
        elif cls == "aporte_util":
            topic_aporte[topic] += 1
        pt = e.get("tipo_problema", "unknown")
        if pt:
            problem_type_counter[pt] += 1

    sorted_by_resolved = sorted(topic_resolved.items(), key=lambda x: -x[1])
    top_topics_resolved_lines = []
    for topic, count in sorted_by_resolved[:5]:
        total = topic_counter.get(topic, 0)
        top_topics_resolved_lines.append(f"  - {topic}: {count} resolved (total {total} events)")

    resolved_set = set(t for t in topic_resolved)
    topics_only_aporte_list = [t for t in topic_aporte if t not in resolved_set]
    topics_only_aporte_lines = []
    for t in topics_only_aporte_list[:5]:
        topics_only_aporte_lines.append(f"  - {t}: {topic_aporte[t]} useful aportes, 0 resolved")

    problem_type_lines = [f"  - {pt}: {count}" for pt, count in problem_type_counter.most_common(8)]

    return (
        f"Total high-value events: {len(events)}\n"
        f"Events by classification: {dict(classification_counts)}\n\n"
        f"Top topics (by resolved problems):\n"
        + ("\n".join(top_topics_resolved_lines) if top_topics_resolved_lines else "  (none)\n")
        + "\n\nTopics where no problem was solved (only useful aportes):\n"
        + ("\n".join(topics_only_aporte_lines) if topics_only_aporte_lines else "  (none)\n")
        + "\n\nProblem types distribution:\n"
        + ("\n".join(problem_type_lines) if problem_type_lines else "  (none)\n")
    )


async def run_value_review(llm: Any, days: int = 7, max_events: int = 50) -> Optional[str]:
    since = datetime.now() - timedelta(days=days)
    events = get_value_events_since(since)
    if not events:
        logger.info("ValueReview: no hay eventos desde %s. Saltando revisión.", since.date())
        return None

    high_value = [e for e in events if e.get("clasificacion_valor") in ("resolvio_problema", "aporte_util")]
    sample = high_value[:max_events]

    summary_data = _summarize_events(sample)

    user_prompt = VALUE_REVIEW_USER_PROMPT.format(
        days=days,
        total_events=len(sample),
        classification_counts=dict(Counter(e.get("clasificacion_valor", "unknown") for e in sample)),
        top_topics_resolved="",
        topics_only_aporte="",
        problem_type_distribution="",
    )
    user_prompt = VALUE_REVIEW_USER_PROMPT.format(
        days=days,
        total_events=len(sample),
        classification_counts=dict(Counter(e.get("clasificacion_valor", "unknown") for e in sample)),
        top_topics_resolved=summary_data.split("Top topics")[1].split("Topics where")[0].strip()
        if "Top topics" in summary_data else "(none)",
        topics_only_aporte=summary_data.split("Topics where no problem was solved")[1].split("Problem types")[0].strip()
        if "Topics where no problem was solved" in summary_data else "(none)",
        problem_type_distribution=summary_data.split("Problem types distribution")[1].strip()
        if "Problem types distribution" in summary_data else "(none)",
    )

    try:
        proposal_raw = await llm.generate(
            tier="default",
            prompt=user_prompt,
            system_prompt=VALUE_REVIEW_SYSTEM_PROMPT,
            max_tokens=600,
            temperature=0.4,
        )
    except Exception as e:
        logger.error("ValueReview: error generando propuestas: %s", e)
        return None

    proposal_raw = (proposal_raw or "").strip()
    if proposal_raw.startswith("```"):
        proposal_raw = proposal_raw.strip("`").strip()
        if proposal_raw.lower().startswith("json"):
            proposal_raw = proposal_raw[4:].strip()

    date_str = datetime.now().strftime("%Y%m%d")
    review_file = REVIEW_DIR / f"value_review_{date_str}.txt"
    try:
        REVIEW_DIR.mkdir(parents=True, exist_ok=True)
        parsed = json.loads(proposal_raw)
        content = (
            f"=== PLAN_DE_MEJORA_SEMANAL ===\n"
            f"Generated: {datetime.now().isoformat()}\n"
            f"Period: last {days} days\n"
            f"Events analyzed: {len(sample)}\n\n"
            f"--- Analysis ---\n{parsed.get('analysis_summary', proposal_raw)}\n\n"
            f"--- Top 3 Topics Resolved ---\n"
        )
        for t in parsed.get("top_3_topics_resolved", []):
            content += f"  - {t}\n"
        content += "\n--- Improvement Opportunities ---\n"
        for o in parsed.get("improvement_opportunities", []):
            content += f"  - {o}\n"
        content += "\n--- Content Structure Proposals ---\n"
        for p in parsed.get("content_structure_proposals", []):
            content += f"  - {p}\n"
        content += "\n--- Prompt Adjustments ---\n"
        for a in parsed.get("prompt_adjustments", []):
            content += f"  - {a}\n"
        content += "\n=== END ===\n"
        review_file.write_text(content, encoding="utf-8")
        logger.info("ValueReview: revisión guardada en %s", review_file)
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("ValueReview: error parseando respuesta del modelo, guardando raw: %s", e)
        content = (
            f"=== PLAN_DE_MEJORA_SEMANAL ===\n"
            f"Generated: {datetime.now().isoformat()}\n"
            f"Period: last {days} days\n"
            f"Events analyzed: {len(sample)}\n\n"
            f"--- Raw Response ---\n{proposal_raw}\n\n=== END ===\n"
        )
        review_file.write_text(content, encoding="utf-8")

    logger.info("ValueReview: análisis completo en %s", review_file)
    return str(review_file)
