# FIX-2026-08-29: title_has_scaffold() detecta reasoning leaks

## Problema

El validador \	itle_has_scaffold()\ en \services/quality_governor.py\ solo buscaba patrones de **clickbait SEO** (\'guia completa'\, \'todo sobre'\, etc.) pero **NO detectaba los patrones de scaffold interno** que causaron publicación de títulos inválidos:

- \'Here's a thinking process:'\ (publicado x2)
- \'Critique:** ...'\ (publicado x1)
- \'We need to critique the draft...'\ (publicado x1)
- Títulos que terminan en \:\
- Títulos que empiezan como items de lista

Estos títulos son **fugas de razonamiento interno** (reasoning leaks) que violan el gate de validación de Phase A.

## Solución

Se reescribió \	itle_has_scaffold()\ en \services/quality_governor.py\ para incluir:

### 1. Patrones de scaffold interno / reasoning leak
\\\python
internal_scaffolds = [
    "here's a thinking process:", "here's the thinking process:",
    "thinking process:", "critique:**", "critique:", "**critique:",
    "we need to critique", "let's critique", "draft...", "pre-critique",
    "post-mortem:", "analysis:", "reasoning:", "step ", "step:",
]
\\\

### 2. Check para títulos que terminan en \:\
Un título que termina en \:\ es una instrucción o etiqueta, no un título declarativo.

### 3. Check para títulos que empiezan como items de lista
Si el título empieza con \- \, \* \, \• \, o \1. \, es un item de lista, no un título.

### 4. Se agregó \import re\ al inicio del archivo
Necesario para \e.match()\ en los checks de listas.

## Resultado

- Los títulos con scaffold interno ahora son **bloqueados correctamente** en el gate de validación
- El agente regenera con la corrección \"leaked_scaffold_title"\ que instruye al modelo a producir títulos declarativos
- Los topics que agotan reintentos con este error entran en **cooldown de 60 min** (no 240 min como otros errores)

## Archivos modificados

- \services/quality_governor.py\: Función \	itle_has_scaffold()\ reescrita + \import re\ agregado

## Testing

\\\python
from services.quality_governor import title_has_scaffold

# Títulos bloqueados (correcto)
title_has_scaffold("Here's a thinking process: Dynamic TTL kills reasoning")
# → (True, 'Titulo con scaffold interno: here's a thinking process:')

title_has_scaffold("Critique:** Dynamic TTL is a trap")
# → (True, 'Titulo con scaffold interno: critique:**')

# Títulos que pasan (correcto)
title_has_scaffold("Dynamic TTL is a trap that kills agent reasoning")
# → (False, '')
\\\

## Fecha

2026-08-29 23:00 ART

## Referencias

- Log original: \logs/agent.log\ 2026-08-29 22:41:22-44 (4 reintentos fallidos con \leaked_scaffold_title\)
- Código relevante: \phases/phase_a_content.py\ línea ~200 (gate anti-fuga de título)
