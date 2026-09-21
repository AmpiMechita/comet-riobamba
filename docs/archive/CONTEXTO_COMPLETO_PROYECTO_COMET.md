# CONTEXTO COMPLETO - Proyecto comet-riobamba-v31
# (Este archivo debe subirse al espacio de Perplexity para memoria persistente)

## 🔴 INSTRUCCIONES CRÍTICAS PARA EL ASISTENTE

### ANTES DE RESPONDER CUALQUIER PREGUNTA SOBRE ESTE PROYECTO:

1. ✅ **LEER ESTE ARCHIVO COMPLETO**
2. ✅ **VERIFICAR** que el contexto estÃ¡ cargado
3. ❌ **NO ASUMIR** nombres de archivos, estructuras, o configuraciones
4. ❌ **NO INVENTAR** informaciÃ³n que no estÃ¡ aquÃ­ o en memoria

---

## 📋 RESUMEN EJECUTIVO

- **Proyecto**: comet-riobamba-v31 (versiÃ³n 31, iterativo)
- **UbicaciÃ³n**: `C:\comet-riobamba-v31`
- **Propietario**: Usuario en Riobamba, Chimborazo, Ecuador
- **Objetivo**: Agente de IA autÃ³nomo que opera en **Moltbook** (red social para agentes IA)
- **MetodologÃ­a**: Watchlist de agentes reputados, engagement, gestiÃ³n de karma, optimizaciÃ³n de costos

---

## 🗂️ ESTRUCTURA DEL PROYECTO

```
C:\comet-riobamba-v31\
├── run_agent.py              # ✅ ARCHIVO PRINCIPAL (no main.py, no ru_agent.py)
├── .venv\                    # Entorno virtual de Python
├── core\                     # LÃ³gica central del agente
├── phases\                   # Fases del flujo del agente
│   ├── phase_a_content.py    # GeneraciÃ³n de contenido
│   ├── deps.py               # Dependencias y utilidades
│   └── [otras fases]         # SegÃºn metodologÃ­a implementada
├── services\                 # Servicios especializados
│   ├── quality_governor.py   # Gates de calidad
│   ├── quota_manager.py      # GestiÃ³n de cuotas de API
│   └── [otros servicios]     # SegÃºn necesidades
├── tools\                    # Herramientas y utilidades
├── config\                   # Configuraciones
├── monitoring\               # Observabilidad y logs
├── docs\                     # DocumentaciÃ³n
└── evals\                    # Evaluaciones y mÃ©tricas
```

---

## 🚀 COMANDOS CLAVE

### Iniciar el agente (PowerShell)
```powershell
cd C:\comet-riobamba-v31
.\.venv\Scripts\Activate.ps1
python run_agent.py
```

### Verificar estructura
```powershell
Get-ChildItem -Recurse -Filter "*.py" | Select-Object FullName
```

### Ver contenido de un archivo
```powershell
Get-Content run_agent.py
```

---

## 🎯 METODOLOGÍA MOLTBOOK

### Objetivo Principal
Convertir al agente en un **referente especialista** en los temas que trata, mediante:
1. Engagement estratÃ©gico con agentes reputados
2. PublicaciÃ³n de contenido de alta calidad
3. GestiÃ³n de karma y reputaciÃ³n
4. OptimizaciÃ³n de costos de modelos

### Watchlist de Agentes Reputados
- Lista de agentes de alta reputaciÃ³n en Moltbook
- El agente monitorea su actividad
- Comenta en sus posts para engagement
- Cuando estos agentes interactÃºan con el usuario, se prioriza la calidad de esos threads

### Gates de Calidad
- `quality_governor.py` evalÃºa contenido antes de publicaciÃ³n
- Criterios: relevancia, originalidad, tono, potencial de engagement
- Prioriza threads con agentes de la watchlist

### GestiÃ³n de Cuotas
- `quota_manager.py` controla requests/tokens por dÃ­a
- Fallback automÃ¡tico entre modelos (DeepSeek â Anthropic)
- Alertas cuando se acerca al lÃ­mite

---

## 🛠️ COMPONENTES CLAVE

### 1. run_agent.py
- **FunciÃ³n**: Punto de entrada principal
- **Responsabilidad**: Inicializar fases, servicios, comenzar loop del agente
- **No usar**: `main.py`, `ru_agent.py`, `agent.py`, `bot.py`

### 2. phases/
- **phase_a_content.py**: Genera contenido para publicaciÃ³n
- **deps.py**: Dependencias compartidas, helpers
- **Otras fases**: Implementan flujo de decisiÃ³n del agente

### 3. services/
- **quality_governor.py**: Gates de calidad, evaluaciÃ³n de contenido
- **quota_manager.py**: Control de cuotas, optimizaciÃ³n de costos

### 4. core/
- LÃ³gica central del agente, orquestaciÃ³n de fases

### 5. monitoring/
- Logs estructurados, mÃ©tricas, observabilidad

---

## 🔧 CONFIGURACIÓN DEL ENTORNO

### PowerShell (preferido)
- Usuario prefiere PowerShell para operaciones en el repositorio
- Verificar encoding para evitar texto ilegible
- Comandos directos, sin abstracciones innecesarias

### Python
- VersiÃ³n: 3.x (segÃºn .venv)
- Entorno virtual en `.venv\`
- ActivaciÃ³n: `.\.venv\Scripts\Activate.ps1`

### Modelos de IA
- **DeepSeek**: OpciÃ³n econÃ³mica para tareas rutinarias
- **Anthropic (Claude)**: Tareas que requieren mayor calidad
- **Fallback**: Cascada segÃºn disponibilidad y cuota

---

## 📊 PLATAFORMA MOLTBOOK

### ¿Qué es Moltbook?
- **Red social exclusiva para agentes de IA** (humanos solo observan)
- Similar a Reddit: comunidades, posts, comentarios, votos
- Impulsada por **OpenClaw** (bot gratuito y de cÃ³digo abierto)
- Creada por **Peter Steinberg** (noviembre 2024)
- MÃ¡s de **1.7 millones de usuarios** (agentes IA) en febrero 2025
- MÃ¡s de **240,000 publicaciones**

### Características Clave
- Agentes publican, comentan, votan autÃ³nomamente
- Comunidades temÃ¡ticas (filosofÃ­a, amor, quejas sobre humanos, etc.)
- Sin moderaciÃ³n humana directa
- Karma y reputaciÃ³n basados en engagement

---

## 🎨 PREFERENCIAS DEL USUARIO

- **UbicaciÃ³n**: Riobamba, Chimborazo, Ecuador
- **Idioma**: EspaÃ±ol
- **Estilo**: Directo, tÃ©cnico, sin rodeos
- **Herramientas**: PowerShell, Python, VS Code/OpenCode
- **Prioridad**: Funcionalidad sobre estÃ©tica
- **Presupuesto**: Optimizar costos, usar free tiers cuando posible
- **Tolerancia a errores**: Baja (espera precisiÃ³n y memoria del contexto)

---

## ⚠️ ERRORES CONOCIDOS Y SOLUCIONES

### Error: `No such file or directory: main.py`
- **Causa**: Archivo incorrecto
- **SoluciÃ³n**: Usar `python run_agent.py`

### Error de encoding en PowerShell
- **Causa**: ConfiguraciÃ³n de codificaciÃ³n de consola
- **SoluciÃ³n**: Verificar `chcp` y configuraciÃ³n de terminal

### Límites de API alcanzados
- **Causa**: Quota_manager detecta exceso de requests
- **SoluciÃ³n**: Esperar reset de cuota o cambiar de modelo

---

## 📈 OBJETIVOS Y PRIORIDADES

### 🔴 PRIORIDAD ALTA
1. Estabilidad del agente (ejecutar sin errores)
2. GestiÃ³n de cuotas (quota_manager.py operativo)
3. Gates de calidad (quality_governor.py evaluando correctamente)

### 🟠 PRIORIDAD MEDIA
4. Watchlist dinÃ¡mica (configurable, actualizable)
5. GeneraciÃ³n de contenido relevante y variado
6. Observabilidad (logs, mÃ©tricas, alertas)

### 🟢 PRIORIDAD BAJA
7. OptimizaciÃ³n de costos (anÃ¡lisis por modelo)
8. Escalabilidad (mÃºltiples cuentas, paralelizaciÃ³n)
9. DocumentaciÃ³n completa

---

## 🔍 CHECKLIST PARA EL ASISTENTE

Antes de responder sobre este proyecto:

- [ ] ¿LeÃ­ este archivo completo?
- [ ] ¿VerifiquÃ© que `run_agent.py` es el archivo principal?
- [ ] ¿Estoy usando PowerShell en los comandos?
- [ ] ¿Estoy siendo directo y honesto?
- [ ] ¿Reconozco si no tengo informaciÃ³n suficiente?

---

## 🚨 SEÑALES DE ALERTA

Si el usuario dice:
- "¿QuÃ© te pasa?"
- "¿EstÃ¡s limitado?"
- "Di manzana/pera"
- "Tienes que recordar el contexto"

**ACCIÓN INMEDIATA**:
1. Reconocer el error
2. Leer este archivo
3. Corregir con informaciÃ³n verificada
4. No justificar en exceso

---

## 📝 HISTORIAL DE VERSIONES

| VersiÃ³n | Fecha | Cambios Principales |
|---------|-------|---------------------|
| v31 | 2026-08-30 | DocumentaciÃ³n de contexto completo, memoria para asistente |
| v30 | ? | ? |
| ... | ... | ... |
| v1 | ? | VersiÃ³n inicial |

---

## 🔗 RECURSOS ADICIONALES

### Conectores disponibles
- Google Drive
- Google Calendar
- Finance

### Referencias externas
- [Moltbook - DocumentaciÃ³n](https://www.adrformacion.com/blog/que_es_moltbook.html)
- [Moltbook - Primicias Ecuador](https://www.primicias.ec/internacional/moltbook-red-social-inteligencia-artificial-agentes-115577/)
- [OpenClaw - Bot de cÃ³digo abierto](https://github.com/OpenClaw)

---

## 📌 NOTAS IMPORTANTES

1. **Este proyecto es iterativo**: Cada versiÃ³n (v1-v31) acumula mejoras
2. **La metodologÃ­a Moltbook es central**: Watchlist, engagement, calidad
3. **OptimizaciÃ³n de costos es prioritario**: DeepSeek vs Anthropic, quotas
4. **El usuario valora transparencia**: Si no sabes algo, dilo
5. **PowerShell es el entorno preferido**: No CMD, no bash

---

## ✅ VALIDACIÓN

Para verificar que el contexto estÃ¡ cargado correctamente:

1. Pregunta al asistente: "¿CuÃ¡l es el archivo principal del proyecto?"
   - Respuesta correcta: `run_agent.py`

2. Pregunta: "¿En quÃ© plataforma opera el agente?"
   - Respuesta correcta: Moltbook

3. Pregunta: "¿CuÃ¡l es la metodologÃ­a principal?"
   - Respuesta correcta: Watchlist de agentes reputados, engagement, gates de calidad

---

## 🔄 ÚLTIMA ACTUALIZACIÓN

- **Fecha**: 2026-08-30
- **Motivo**: ConsolidaciÃ³n de contexto para memoria persistente en Perplexity
- **Estado**: Activo, versiÃ³n 31
- **PrÃ³ximos pasos**: Seguir desarrollando segÃºn metodologÃ­a Moltbook

---

**⚠️ IMPORTANTE: Este archivo debe subirse al espacio/proyecto de Perplexity para que el asistente tenga contexto persistente en futuras sesiones.**