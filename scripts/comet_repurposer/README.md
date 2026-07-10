# comet_repurposer

Extiende **comet_riobamba** para llevar el contenido técnico que el agente ya
produce (posts en Moltbook, ebooks, research agenda, social_content markdown)
a **Instagram, TikTok, YouTube, X/Twitter, LinkedIn y Facebook**, y publicar
automáticamente a **LinkedIn y X/Twitter** (MVP).

No reemplaza a `scripts/social_distributor.py` — lo complementa. Mientras
`social_distributor.py` solo maneja Twitter + LinkedIn y copia al portapapeles,
`comet_repurposer`:

1. **Genera** versiones adaptadas para 6 plataformas (texto listo para revisar)
2. **Encola** las versiones de LinkedIn + X en una cola SQLite con aprobación
3. **Publica** automáticamente vía APIs oficiales con horarios óptimos

---

## Flujo completo

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Fuentes del     │     │ drafts markdown  │     │ Cola SQLite     │
│ agente          │────▶│ per platform     │────▶│ status=generated│
│ - published_    │     │ (6 plataformas)  │     └────────┬────────┘
│   posts.json    │     └──────────────────┘              │
│ - social_       │                                       │ approve (1-click)
│   content/*.md  │                                       ▼
│ - ebook_*.md    │                              ┌─────────────────┐
│ - research_     │                              │ status=approved │
│   agenda.json   │                              │ + scheduled_at  │
└─────────────────┘                              └────────┬────────┘
                                                          │ publish
                                                          ▼
                                                ┌─────────────────┐
                                                │ LinkedIn API    │
                                                │ X/Twitter API   │
                                                └─────────────────┘
```

### Comandos del CLI

```powershell
# 1. Generar drafts (también los encola para LinkedIn y X)
python -m comet_repurposer generate --source latest --limit 3 \
    --enqueue-linkedin --enqueue-x

# 2. Ver la cola
python -m comet_repurposer queue

# 3. Aprobar (gate 1-click)
python -m comet_repurposer approve 1 2 3            # por ID
python -m comet_repurposer approve --all            # todos
python -m comet_repurposer approve --all --platform linkedin

# 4. Rechazar los que no te gusten
python -m comet_repurposer reject 4 5

# 5. Publicar (dry-run por defecto)
python -m comet_repurposer publish --dry-run        # solo simula
python -m comet_repurposer publish --for-real --i-know   # posta

# 6. Emergency stop
python -m comet_repurposer kill --reason "wrong tone"
python -m comet_repurposer unkill

# 7. Setup LinkedIn OAuth (primera vez)
python -m comet_repurposer auth-linkedin
```

---

## Seguridad (modo conservador por defecto)

1. **Dry-run es el default**: `publish` sin flags solo simula. Para postear
   de verdad necesitas `--for-real --i-know` (doble flag, anti-typo).
2. **Kill switch**: archivo `data/KILL_SWITCH`. Si existe, ningún publish
   corre. Útil si detectas que el agente generó contenido inadecuado.
3. **Aprobación 1-click**: nada se publica sin que apruebes el job
   específico (o uses `--all` explícitamente).
4. **Min gap 2h**: el scheduler no programa dos posts en la misma
   plataforma con menos de 2 horas de diferencia.
5. **Horarios óptimos**: LinkedIn 9am/12pm/5pm UTC, X 8am/12pm/6pm/9pm UTC
   (editables en `.env`).

---

## Setup inicial (15-30 min)

Lee **`SETUP_LINKEDIN_X.md`** para la guía paso a paso con capturas conceptuales
de cada pantalla de LinkedIn Developers y X Developer Portal.

Resumen:

1. **Copia el paquete** a `C:\comet-riobamba-v31\scripts\comet_repurposer\`
2. **Instala dependencias**: `pip install requests python-dotenv`
3. **Crea app en LinkedIn Developers** → copia `LINKEDIN_CLIENT_ID` y
   `LINKEDIN_CLIENT_SECRET` a `.env`
4. **Crea app en X Developer Portal** → copia las 4 keys de X a `.env`
5. **Corre OAuth de LinkedIn**: `python -m comet_repurposer auth-linkedin`
   → copia los 4 valores impresos a `.env`
6. **Prueba el flujo**:
   ```powershell
   python -m comet_repurposer generate --source latest --limit 1 \
       --enqueue-linkedin --enqueue-x
   python -m comet_repurposer queue
   python -m comet_repurposer approve 1 2
   python -m comet_repurposer publish --dry-run
   ```
7. Cuando estés conforme, publica de verdad:
   ```powershell
   python -m comet_repurposer publish --for-real --i-know
   ```

---

## Estructura del paquete

```
comet_repurposer/
├── __init__.py
├── __main__.py
├── cli.py                   # CLI con subcomandos: generate, queue, approve, publish, kill, auth-linkedin
├── config.py                # Carga .env + cascade LLM + creds publishers
├── llm_client.py            # Cliente OpenAI-compatible con cascade
├── sources.py               # Lectores de cada fuente del agente
├── prompts.py               # Templates por plataforma (JSON schema)
├── pipeline.py              # Orquesta: fuente -> LLM -> markdown
├── dedup.py                 # SQLite dedup de generation
├── _mock_llm.py             # Para tests sin gastar API quota
└── publishers/
    ├── __init__.py
    ├── base.py              # QueueStore, PublishJob, BasePublisher, kill switch
    ├── linkedin.py          # LinkedIn Share API + OAuth flow interactivo
    ├── twitter.py           # X API v2 (OAuth 1.0a, single tweet + thread)
    └── scheduler.py         # Horarios óptimos por plataforma
```

---

## Variables de entorno

Copia `.env.example` a tu `.env` existente y completa las claves de LinkedIn
y X. Las variables de LLM ya las tienes (las reutiliza el agente).

Variables nuevas que añadir a `.env`:

```env
# Publisher MVP
PUBLISH_QUEUE_DB=data/publish_queue.db
PUBLISH_KILL_SWITCH=data/KILL_SWITCH
PUBLISH_DRY_RUN_DEFAULT=1
PUBLISH_MIN_GAP_HOURS=2

LINKEDIN_OPTIMAL_SLOTS=09:00,12:00,17:00
X_OPTIMAL_SLOTS=08:00,12:00,18:00,21:00

# LinkedIn (obtener con `python -m comet_repurposer auth-linkedin`)
LINKEDIN_CLIENT_ID=
LINKEDIN_CLIENT_SECRET=
LINKEDIN_ACCESS_TOKEN=
LINKEDIN_ACCESS_TOKEN_EXPIRES_AT=
LINKEDIN_REFRESH_TOKEN=
LINKEDIN_REFRESH_TOKEN_EXPIRES_AT=
LINKEDIN_PERSON_ID=

# X / Twitter (obtener en developer.x.com)
TWITTER_API_KEY=
TWITTER_API_KEY_SECRET=
TWITTER_ACCESS_TOKEN=
TWITTER_ACCESS_TOKEN_SECRET=
```

---

## Tests

```powershell
cd C:\comet-riobamba-v31\scripts

# Test 1: generación end-to-end con mock LLM (no gasta API quota)
python tests\test_smoke.py

# Test 2: flujo completo generate -> enqueue -> approve -> publish (dry-run)
python tests\test_publish_flow.py

# Test 3: mejoras (A) truncamiento + (B) dedup semántico con los 5 posts reales
python tests\test_improvements_ab.py
```

Ambos tests usan mocks y no requieren credenciales reales.

---

## Mejoras evolutivas (A y B)

Tras analizar 5 posts reales del agente comet_riobamba detectamos dos
patrones problemáticos. Esta versión del repurposer los maneja:

### (A) Manejo de posts truncados

El agente comet_riobamba impone un `Length: {min}-{max} characters
(enforce strictly)` en su system prompt. Esto causa que ~80% de los posts
terminen cortados a mitad de frase ("...ensuring", "...variance", "...This").

**Solución implementada:**
- `sources.py::looks_truncated()` detecta heurísticamente si el body
  termina a mitad de cláusula (conectores finales, comas, artículos
  colgantes, etc.).
- `prompts.py` añade una sección `HANDLING TRUNCATED SOURCE CONTENT` al
  system prompt que instruye al LLM:
  - NO inventar claims/métricas/ejemplos nuevos para rellenar
  - SÍ inferir un cierre breve en la voz del agente
  - Para X/Twitter y TikTok: refactorizar como cliffhanger con pregunta
  - Para LinkedIn, Facebook, Instagram: cierre de una oración
- `pipeline.py` pasa el flag `truncated=True` al `build_prompt()` y lo
  registra en el `manifest.json`.

**Validación**: el test `test_improvements_ab.py` verifica que 4 de los
5 posts reales se detectan como truncados.

### (B) Dedup semántico

El dedup original era por `(source_id, platform, language)` — no detectaba
que 4 de 5 posts trataban el mismo tema (circuit breakers + quotas +
observability). Publicar 4 posts sobre circuit breakers en una semana
satura a la audiencia.

**Solución implementada (cascada de 3 métodos):**

1. **Embeddings** (mejor fidelidad, requiere configuración)
   - Setear `EMBEDDINGS_BASE_URL`, `EMBEDDINGS_API_KEY`,
     `EMBEDDINGS_MODEL` en `.env`
   - Funciona con OpenAI, Ollama local (nomic-embed-text), u otros
     endpoints compatibles
   - Threshold automático: 0.85 (cosine en vector space denso)

2. **TF-IDF + cosine** (default, sin API)
   - Implementación propia en `semantic_dedup.py::TfidfIndex`
   - Pondera términos raros del corpus más alto que términos comunes
   - Captura similitud temática incluso con vocabulario divergente
   - Threshold default: 0.20 (calibrado contra los 5 posts reales)

3. **Jaccard léxico** (fallback dentro del método 2)
   - Si TF-IDF da similitud baja pero Jaccard es más alta, se usa la
     más alta de las dos.

**Cómo se usa:**
```powershell
# Default: semantic dedup ON con TF-IDF (no gasta API)
python -m comet_repurposer generate --source latest --limit 5

# Con embeddings reales (mejor precisión, requiere EMBEDDINGS_* en .env)
python -m comet_repurposer generate --source latest --limit 5
# (el CLI detecta automáticamente que hay embeddings configurados)

# Desactivar semantic dedup (procesar todo)
python -m comet_repurposer generate --source latest --limit 5 --no-semantic-dedup

# Ajustar threshold manualmente
python -m comet_repurposer generate --source latest --limit 5 --semantic-threshold 0.30
```

**Qué pasa cuando un item se salta por ser duplicado:**
- Se escribe un `manifest.json` con `skipped: true` y
  `skip_reason: "semantic_duplicate"` indicando de qué source_id es
  duplicado y con qué similitud
- Se loguea a `logs/repurpose.jsonl` con `platform: "semantic_skip"`
- El item NO se procesa para NINGUNA plataforma (a diferencia del dedup
  por source_id que es por plataforma)

**Validación**: el test `test_improvements_ab.py` verifica que el post 5
("Dual-token quota guard") se detecta como duplicado del post 4
("Circuit-breaker layer with token bucket") con similitud 0.34 (TF-IDF).

---

## Próximas mejoras evolutivas planeadas

### (C) Modo `--series` (pendiente)

Detectar clusters temáticos (no solo pares duplicados) y generar:
- Un ebook consolidado que una los N posts del cluster
- N piezas derivadas para cada plataforma

Ejemplo de uso previsto:
```powershell
python -m comet_repurposer series --source latest --limit 30
# Detecta que 4 posts tratan sobre circuit breakers
# Genera: exports/social_repurpose/2026-06-22/circuit-breakers-series/
#         ├── ebook.md           (consolidación de los 4)
#         ├── linkedin.md        (post basado en el ebook)
#         ├── x.md               (hilo largo basado en el ebook)
#         └── manifest.json
```

### Otras mejoras futuras sugeridas

- **Programación depublicación manual**: ya que decidimos no automatizar,
  el repurposer podría generar un `calendar.md` con sugerencias de qué
  publicar cada día según el nicho y la cadencia óptima por plataforma.
- **Editor in-line**: comando `comet_repurposer edit <job_id>` que abre
  el `.md` en `$EDITOR` y al cerrar guarda los cambios.
- **Métricas de Engagement**: si más adelante conectas las APIs de
  LinkedIn/X en modo lectura, podrías correlacionar qué temas/posts
  generaron más engagement y retroalimentar al agente comet_riobamba.

---

## FAQ

**¿Por qué solo LinkedIn + X en el MVP de publicación?**
Porque son las únicas plataformas donde puedes publicar texto solo, sin
video/imagen, con APIs accesibles hoy mismo y sin app review largo.
Instagram, TikTok y YouTube requieren video real (que el agente no genera
todavía) y/o app review de 1-2 semanas.

**¿Cuándo agregar Instagram/Facebook/YouTube/TikTok?**
Cuando quieras generar contenido multimedia. El paso siguiente natural es
agregar un módulo `media/` que convierta el texto del agente en:
- Cards estáticas para Instagram (Pillow o DALL-E)
- Videos cortos con TTS para TikTok/Reels/Shorts (edge-tts + ffmpeg)

Tengo esto diseñado pero no implementado todavía — pídelo cuando quieras.

**¿Qué pasa si el agente genera contenido inadecuado?**
Dos líneas de defensa:
1. **Aprobación 1-click**: ves el texto antes de aprobarlo.
2. **Kill switch**: `python -m comet_repurposer kill --reason "..."` detiene
   todos los publishes hasta que lo clears con `unkill`.

Si algo se publicó por error, usa las apps nativas de LinkedIn/X para
borrarlo manualmente. El pipeline no tiene "unpublish" intencionalmente
(para evitar que un bug borre posts que sí querías).

**¿El idioma por qué es inglés por defecto?**
Porque el agente comet_riobamba produce en inglés (su system prompt lo
especifica). Usa `--lang es` para traducir las versiones al español
manteniendo la voz técnica.

**¿Consume mucha cuota de API?**
- LLM: cada item × plataforma = 1 llamada. 5 items × 6 plataformas = 30
  llamadas. Con Gemini Flash o Groq el costo es despreciable.
- LinkedIn: free, sin límite duro conocido (rate-limit suave ~90 posts/día).
- X: Free tier = 1,500 posts/mes, 50 posts/24h. Suficiente para MVP.

**¿Puedo agregar una plataforma nueva?**
Sí. Para generar drafts: edita `prompts.py` y agrega una entrada al dict
`PLATFORMS`. Para publicar: crea `publishers/<plataforma>.py` heredando de
`BasePublisher` y registra la factoría en `cli.py::_build_publisher`.
