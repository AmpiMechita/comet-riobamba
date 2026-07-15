VALUE_CLASSIFIER_SYSTEM_PROMPT = (
    "You are a value analysis assistant for an autonomous agent. "
    "Analyze the interaction between a user comment and the agent's reply, "
    "and classify whether the agent provided meaningful value. "
    "Respond only with valid JSON, no markdown, no explanation."
)

VALUE_CLASSIFIER_USER_PROMPT = """Analyze this interaction and classify the agent's contribution.

Original post:
{post}

User comment:
{comment}

Agent's reply:
{reply}

{follow_up_section}

Classify the value according to these categories:
- "resolvio_problema": The agent solved a specific problem or provided a working solution.
- "aporte_util": The agent provided genuinely useful information, insight, or guidance.
- "baja_relevancia": The reply was generic, off-topic, or added little value.

Respond with JSON only:
{{
  "clasificacion_valor": "resolvio_problema" | "aporte_util" | "baja_relevancia",
  "tema": "short topic label (e.g. 'model latency', 'prompt injection', 'agent memory')",
  "tipo_problema": "short problem type (e.g. 'procastination', 'creative block', 'technical doubt', 'architecture question')",
  "senales_usuario": ["list of signals like 'agradecimiento_explicito', 'confirmacion_solucion', 'pregunta_seguimiento', 'critica_constructiva'"],
  "resumen_problema": "1-2 sentence summary of the user's issue or question",
  "resumen_solucion": "1-2 sentence summary of how the agent addressed it"
}}
""".strip()


def build_classifier_prompt(post: str, comment: str, reply: str, follow_up: str = "") -> tuple:
    follow_up_section = ""
    if follow_up:
        follow_up_section = f"User follow-up:\n{follow_up}\n"
    user_prompt = VALUE_CLASSIFIER_USER_PROMPT.format(
        post=post[:1200],
        comment=comment[:800],
        reply=reply[:800],
        follow_up_section=follow_up_section,
    )
    return VALUE_CLASSIFIER_SYSTEM_PROMPT, user_prompt
