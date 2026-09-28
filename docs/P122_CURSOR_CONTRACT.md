# P-122 - Contrato de paginacion /posts/{uuid}/comments

**Confirmado:** 2026-09-28 (UTC), probe scripts/_p122_probe_cursor.py
**Post usado:** 19b6e9bf-6ff9-4ea5-834a-cbbac714f546
**Evidencia cruda:** docs/evidence/P122_probe_20260928T000355Z.txt (gitignored *.txt)

## Contrato real (NO asumido)

Envelope de /posts/{uuid}/comments:
- data.comments : lista de comentarios top-level (con replies anidadas)
- data.count    : total
- data.has_more : bool
- data.next_cursor : string opaco (base64-ish). Vacio/ausente si has_more=false
- data.post_id, data.sort, data.success : metadatos

Parametro de paginacion: **cursor** (NO offset).
- GET /posts/{uuid}/comments?limit=50&cursor=<next_cursor> -> pagina siguiente, 50 items nuevos
- GET /posts/{uuid}/comments?limit=50&offset=50 -> MISMA pagina 1 (overlap=50); offset IGNORADO

Item de comentario: author, author_id, content, created_at, depth, downvotes,
id, is_deleted, is_spam, post_id, replies, reply_count, score, updated_at,
upvotes, verification_status.

## Implicaciones para el fix

- No hace falta probar nombres alternativos: cursor es el correcto.
- Leer has_more para cortar el bucle; next_cursor es el token.
- Guard de blast radius: tope de paginas configurable (max_pages).
- has_more=false en la primera pagina mantiene coste 1 request.

## Errata de docs previos

HANDOFF_2026-09-27_audit.md L53 y PENDING.md L372 citan "19b6e9bf" como
post_id. Es prefijo (8 chars); la API exige UUID completo
(19b6e9bf-6ff9-4ea5-834a-cbbac714f546). Anotado como P-124.

## Evidencia cruda del probe (2026-09-28T00:03:55Z)

```
# P-122 probe 2026-09-28T00:03:53.698951+00:00 post=19b6e9bf-6ff9-4ea5-834a-cbbac714f546
status=200 data_type=dict
data_keys=['comments', 'count', 'has_more', 'next_cursor', 'post_id', 'sort', 'success']
data[has_more]=true
data[next_cursor]="eyJ1cHZvdGVzIjoxLCJpZCI6ImQ2OTExYTBkLTMwOTgtNGJjZC04ZTNjLTNlYmYzZWRiZDdkZSJ9"
items_p1=50
item0_keys=['author', 'author_id', 'content', 'created_at', 'depth', 'downvotes', 'id', 'is_deleted', 'is_spam', 'post_id', 'replies', 'reply_count', 'score', 'updated_at', 'upvotes', 'verification_status']
param=cursor status=200 n=50 new=50
CONFIRMADO cursor
offset=50 status=200 n=50 overlap=50
```
