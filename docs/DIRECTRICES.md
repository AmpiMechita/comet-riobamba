# DIRECTRICES — COMET-RIOBAMBA

> Reglas operativas obligatorias. Aplican a cada sesion, sin excepcion.
> Creado: 2026-09-21

## Principios (Rafael, 2026-09-21)

1. No mentir.
2. No suponer. No asumir. No alucinar.
3. No piratear recompensas (no atribuirse logros no hechos).
4. No divagar.
5. Ser explicito.
6. Paso a paso, sin cometer fallas.
7. Abarcar todos los pendientes sin olvidar.
7b. No ser condescendiente.

## Operativas

8. Los pendientes se resuelven inmediatamente al encontrarlos, o se anotan en PENDING.md.
9. No dejar nada solo anotado: cada pendiente termina en DONE/DECIDE/BLOCKED/WONTFIX.
10. Nunca borrar archivos sin: (a) listar que hay, (b) mostrar contenido, (c) pedir confirmacion explicita.
11. Para archivar: mover a backups/ o archive/, nunca Remove-Item -Recurse sin backup previo.
12. Antes de afirmar algo, verificar con comando. Si no se verifico, decirlo.
12b. Diagnóstico de causa raíz exige reproducir el fallo antes de proponer fix. Lectura estática de código NO es verificación.

## Encoding

13. #40: no usar here-strings de PowerShell para escribir codigo con non-ASCII.
14. #41: al editar archivos con non-ASCII, preferir reemplazo por indice de linea.
15. #42: antes de archivar/trackear, verificar .gitignore con git check-ignore -v.
16. #43: toda metrica persistida debe tener run_id.
17. #44: codigo con non-ASCII solo en VS Code. PowerShell solo para ASCII puro.
18. #45: todo .py se lee/escribe con encoding="utf-8" explicito.
19. #46: Git Bash o Python para tareas de archivo con non-ASCII. PowerShell solo ASCII.
20. #47: nunca pegar codigo fuente directamente en el prompt de una shell.

## Tiempo

21. No tengo reloj interno. Uso solo la hora que Rafael confirma, literal.
22. No invento horas, no sumo minutos, no interpolo.
23. Si pasan >3 mensajes sin timestamp, pido hora antes de asumir.

## Cierre de sesion

24. Al cerrar sesion, SIEMPRE culminar con el prompt de apertura del siguiente hilo/modelo. No es opcional.
25. El prompt de apertura vive en docs/PROMPT_APERTURA.md. Se actualiza al cierre si cambio el estado del proyecto.
26. El prompt debe incluir: contexto del operador, lecturas obligatorias con verificacion, metodo no negociable, anti-patrones conocidos, protocolo de verificacion, confirmacion obligatoria.

34. Al cierre de sesion, verificar coherencia HANDOFF vs PENDING:
    extraer IDs mencionados en HANDOFF seccion 8, buscar cada uno en PENDING.md,
    comparar estado (OPEN/DONE). Si hay discrepancia, corregir PENDING.md
    antes de cerrar. Documentar la verificacion en HANDOFF seccion 8.

## Operaciones destructivas — protocolo obligatorio (incidente 21/9)

27. Antes de cualquier operacion destructiva (Remove-Item, rm -rf, git clean -fdx,
    git reset --hard, DROP TABLE): listar -> mostrar tamanos/fechas -> copiar a
    backups/trash-<timestamp>/ -> confirmar con Rafael -> recien entonces ejecutar.
28. Nunca Remove-Item -Recurse sin backup previo. Aplica SIEMPRE, aunque el
    directorio "parezca basura".
29. Si el directorio no esta en git y no tiene backup: PARAR. Preguntar. No asumir.

## Recuperacion via VSS (probado 21/9)

Si se borra algo por error:
1. vssadmin list shadows                    (requiere admin)
2. cmd /c mklink /d C:\shadowN "\\?\GLOBALROOT\Device\HarddiskVolumeShadowCopyN\"
3. Explorar C:\shadowN\...\path\perdido
4. Copiar a backups/recovered-<nombre>-<timestamp>/
5. Remove-Item C:\shadowN -Force            (limpiar symlink)

Los snapshots suelen estar cada 3-12h. Ventana util: ~48-72h.

## Anotacion de pendientes (2026-09-22)

30. Todo pendiente detectado durante una sesion se anota INMEDIATAMENTE en PENDING.md.
    No se acumula para el cierre. Si surge un pendiente, se anota en el momento.
31. No basta con mencionar un pendiente en el chat o en un informe:
    si no esta en PENDING.md, no existe.
32. Al cierre de sesion, verificar que TODO pendiente mencionado durante la sesion
    este en PENDING.md con ID, estado, fecha y descripcion. Si falta, anadirlo antes de cerrar.

## Encoding de parches (2026-09-22)

33. Parches de archivos de texto via Python: usar read_bytes/write_bytes, nunca read_text/write_text (colapsan CRLF y traducen LF->CRLF). Preservar el terminador de cada linea. Con core.autocrlf=true, read_text/write_text renormalizan blobs con CRLF y generan diffs fantasma (incidente CHANGELOG 22/9: numstat 152/139 por solo EOL). Tras cada commit, verificar git show --numstat HEAD.


## Artefactos de sesion (2026-09-26)

35. Borrar artefactos de sesion (scripts/patch_*.py, scripts/_tmp_*.py, y similares)
    ANTES de git add -A, no despues del commit. Si se cuelan en staging:
    git restore --staged del path antes de commitear. Origen: p083b (amend
    a5ea345->5658073 por patch_*.py stageado).


## Rigor de verificacion (2026-09-27, auditoria p079-p119)

36. (A1 fuerte) Todo grep que decida un veredicto (bug/no-bug, existe/no-existe,
    DONE/no-DONE) debe pasar por DOS mecanismos independientes antes de concluir.
    Ejemplo: Select-String + python -c "import re; ...". Si los dos no coinciden,
    el resultado NO se usa. Un solo grep no decide nada estructural.
    Origen: 3 falsos negativos el 27/9 (patron track_action\( con -SimpleMatch;
    "a|b" con -SimpleMatch; nombre ADR-004 inventado por analogia).

37. (A1b) Nunca usar -SimpleMatch con patrones que contengan metacaracteres
    (\( \) \[ \] \* \. \| \?). -SimpleMatch desactiva regex PERO toma los
    escapes y el pipe como literales -> falso negativo silencioso. Si el patron
    tiene metacaracter, usar -Pattern sin -SimpleMatch (regex real).

38. (A2) Antes de concluir "no hay X", ejecutar el grep sobre un archivo donde
    se sabe que X existe. Si no hay match ahi, el patron esta mal, no el codigo.
    Falso negativo != ausencia.

39. (A3) Cuando docs citan archivo, DB o path, verificar con Test-Path/glob
    ANTES de operar sobre el. Si no existe, corregir el doc en la misma sesion.
    No inferir paths por analogia (incidente 27/9: se asumio
    ADR-004-jsonl-retirement.md; el real es ADR-004-jsonl-obsolete-sqlite-canonical.md).

40. (A4) Al diagnosticar, escribir la hipotesis explicita en texto y luego el
    comando que la confirmaria/refutaria. Prohibido encadenar dos fixes sobre
    hipotesis no confirmadas.

41. (A5) Al operador no programador no se le ofrecen opciones tecnicas ambiguas.
    Cuando Rafael pide "solucionar", investigar hasta tener UNA propuesta
    justificada. Alternativas solo cuando la decision es de negocio (dinero,
    narrativa, riesgo), nunca de ingenieria.

42. (A6) Toda accion externa (post/comment/reply) debe persistir en append-only
    los campos suficientes para reconstruir sin depender de la API:
    timestamp ISO con microsegundos, id devuelto por API, post_id, parent_id,
    autor target, status HTTP, y score/upvotes del momento. Origen: paginacion
    por cursor demostro que un dato "irrecuperable" puede serlo solo si la API
    cambia el contrato.

43. (A7) En cada cierre, Select-String de todo path citado en el HANDOFF y
    confirmar existencia. Errores de path en docs son deuda silenciosa que
    reaparece como P-115 (premisa falsa durante 2 sesiones).

44. (A8) Cuando una salida de PowerShell llegue vacia o truncada, pedir la
    salida cruda (| Out-String -Width 400, -Raw, o -Tail/-First) antes de
    concluir. Las lineas largas se truncan y simulan ausencia.
