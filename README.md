# COMET-RIOBAMBA v4.3.0

Agente autónomo para generación de contenido técnico y engagement en Moltbook. Opera en ciclos de 8 horas con 3 fases.

## Arquitectura

- **Phase A** — Genera y publica 1 post técnico/día vía OpenRouter. Incluye validación de contenido, CAPTCHA, y cola de outbox para reintentos.
- **Phase B** — Comenta en feed de comunidad y en posts propios. Hasta 6 comentarios/día, 2 por ciclo. Deduplicación persistida (`data/replied_comment_ids.json`, `data/commented_post_ids.json`). Siempre responde en inglés.
- **Phase C** — Analytics cada 3 ciclos. Sin LLM: recolecta métricas de interacción y genera insights. Se puede deshabilitar vía `AGENT_PHASE_C_ENABLED=0`.
- **Model cascade** — `openrouter` → `tier_opus` → `ollama_local` con fallback automático.

## Arranque

```powershell
python -m run_agent          # inicio rápido
.\run-prod.ps1               # producción (PowerShell)
```

## Detener el agente (graceful, sin señales de OS)

```powershell
New-Item data/stop.flag      # el agente lo detecta en ≤1s y hace shutdown limpio
```

Crear el archivo `data/stop.flag` solicita una parada graceful: el agente lo detecta
en su próximo chequeo (máximo 1s de latencia), guarda el estado final y sale limpiamente.
El flag se elimina automáticamente para no bloquear el próximo arranque. Es el método
preferido en Windows, donde enviar SIGINT/CTRL_BREAK a un proceso hijo en segundo plano
no es fiable.

## Variables de entorno clave

`MOLTBOOK_API_KEY`, `AGENT_MAX_POSTS_PER_DAY`, `AGENT_MAX_COMMENTS_PER_DAY`, `AGENT_PHASE_C_ENABLED`, `OPENROUTER_API_KEY`, `OLLAMA_BASE_URL`.

## Métricas

```powershell
python -m scripts.print_daily_report               # hoy
python -m scripts.print_daily_report 2026-06-09    # fecha específica
python -m scripts.metrics_last_n_days               # últimos 7 días
```

## Tests

```powershell
pytest tests/ -q             # 78 tests
pytest tests/ -v             # verbose
```
