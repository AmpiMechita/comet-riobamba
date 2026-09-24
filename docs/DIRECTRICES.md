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

