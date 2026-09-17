#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA - Moltbook Archive Extractor
Extrae TODOS los posts y comentarios del agente comet_riobamba
y los guarda en data/moltbook_archive/ para análisis posterior.

Solo lectura. NO publica, NO comenta, NO vota.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Asegurar que el directorio raíz esté en el path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(override=True)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("extract_moltbook")

ARCHIVE_DIR = ROOT_DIR / "data" / "moltbook_archive"
POSTS_DIR = ARCHIVE_DIR / "posts"
AGENT_NAME = "comet_riobamba"


def ensure_dirs() -> None:
    """Crear directorios de archivo si no existen."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)


def make_client() -> MoltbookAPIClient:
    """Instanciar cliente Moltbook desde credenciales .env."""
    credentials = Credentials.from_env()
    if not credentials.moltbook_api_key:
        raise RuntimeError("MOLTBOOK_API_KEY no definido en .env")
    if not credentials.moltbook_base_url:
        raise RuntimeError("MOLTBOOK_BASE_URL no definido en .env")

    client = MoltbookAPIClient(credentials=credentials)
    logger.info("Cliente Moltbook inicializado: %s", client.base_url)
    return client


def verify_connection(client: MoltbookAPIClient) -> bool:
    """Verificar que el cliente puede conectar y autenticar."""
    try:
        # Intentar GET /agents/me para obtener perfil
        result = client._request("GET", "/agents/me")
        if 200 <= result.get("status", 0) < 300:
            logger.info("✅ Conexión verificada (GET /agents/me: HTTP %s)", result["status"])
            return True
        else:
            logger.warning("⚠️ /agents/me respondió HTTP %s: %s", result.get("status"), result.get("data"))
            # Fallback: probar home dashboard
            home = client.fetch_home_dashboard()
            if home:
                logger.info("✅ Conexión verificada vía home dashboard (karma=%s)", home.get("karma"))
                return True
            return False
    except Exception as e:
        logger.error("❌ Error verificando conexión: %s", e)
        return False


def fetch_agent_profile(client: MoltbookAPIClient) -> Dict[str, Any]:
    """Obtener perfil del agente via GET /agents/me."""
    try:
        result = client._request("GET", "/agents/me")
        if 200 <= result.get("status", 0) < 300:
            data = result.get("data") or {}
            agent = data.get("agent") or data.get("profile") or data
            # Normalizar campos esperados
            profile = {
                "name": agent.get("name") or agent.get("username") or AGENT_NAME,
                "display_name": agent.get("display_name") or agent.get("name") or "",
                "description": agent.get("description") or agent.get("bio") or "",
                "karma": agent.get("karma", 0),
                "followers_count": agent.get("followers_count") or agent.get("followerCount"),
                "following_count": agent.get("following_count") or agent.get("followingCount"),
                "owner": agent.get("owner"),
                "created_at": agent.get("created_at"),
                "raw": agent,
            }
            if profile["followers_count"] is None:
                logger.warning("followerCount es null (bug conocido de la API)")
            if profile["following_count"] is None:
                logger.warning("followingCount es null (bug conocido de la API)")
            return profile
        else:
            logger.warning("No se pudo obtener perfil: HTTP %s", result.get("status"))
    except Exception as e:
        logger.warning("Error obteniendo perfil: %s", e)
    return {"name": AGENT_NAME, "error": "no_profile_fetched"}


def fetch_home_dashboard(client: MoltbookAPIClient) -> Dict[str, Any]:
    """Obtener home dashboard completo."""
    home = client.fetch_home_dashboard()
    if home:
        logger.info("Home dashboard: karma=%s, unread=%s, active_posts=%s",
                    home.get("karma"), home.get("unread_notifications"), home.get("active_posts"))
    else:
        logger.warning("Home dashboard vacío")
    return home


def fetch_all_own_posts(client: MoltbookAPIClient) -> List[Dict[str, Any]]:
    """
    Obtener todos los posts propios combinando:
    1. fetch_my_posts() (durable store)
    2. Búsqueda en feed paginado filtrando por author
    """
    all_posts: Dict[str, Dict[str, Any]] = {}

    # 1. Posts desde durable store (fetch_my_posts usa own_post_store)
    logger.info("Obteniendo posts propios desde durable store...")
    own_posts = client.fetch_my_posts(limit=200)
    for p in own_posts:
        pid = p.get("id") or p.get("post_id") or p.get("postId")
        if pid:
            all_posts[pid] = p

    # 2. Buscar en feed paginado (fetch_posts con sort=new)
    logger.info("Buscando posts propios en feed histórico...")
    seen_in_feed = 0
    page = 0
    max_pages = 50  # límite de seguridad
    while page < max_pages:
        try:
            posts = client.fetch_posts(limit=100, sort="new")
            if not posts:
                break

            new_in_page = 0
            for p in posts:
                author_raw = p.get("author") or p.get("author_name") or p.get("username") or ""
                if isinstance(author_raw, dict):
                    author = (author_raw.get("name") or author_raw.get("username") or "").strip().lower()
                else:
                    author = str(author_raw).strip().lower()
                if author == AGENT_NAME.lower():
                    pid = p.get("id") or p.get("post_id") or p.get("postId")
                    if pid and pid not in all_posts:
                        all_posts[pid] = p
                        new_in_page += 1

            seen_in_feed += len(posts)
            logger.debug("Página %d: %d posts, %d nuevos del agente", page + 1, len(posts), new_in_page)

            # Si la página tiene < 100 posts, ya no hay más
            if len(posts) < 100:
                break

            page += 1
            time.sleep(0.2)  # pequeño delay entre páginas

        except Exception as e:
            logger.warning("Error en página %d de feed: %s", page, e)
            break

    logger.info("Total posts propios únicos encontrados: %d (durable: %d, feed: %d)",
                len(all_posts), len(own_posts), seen_in_feed)
    return list(all_posts.values())


def fetch_post_with_comments(client: MoltbookAPIClient, post_id: str) -> Optional[Dict[str, Any]]:
    """Obtener post completo con todos sus comentarios (incluye replies anidados)."""
    # Obtener post completo con metadata live (upvotes, comment_count, etc.)
    post = client.get_post(post_id)
    if not post:
        logger.warning("No se pudo obtener post %s", post_id)
        return None

    # Obtener todos los comentarios (fetch_post_comments ya aplanada replies anidadas)
    comments = client.fetch_post_comments(post_id)
    post["_fetched_comments"] = comments
    post["_comment_count_fetched"] = len(comments)

    logger.debug("Post %s: %d comentarios fetcheados", post_id, len(comments))
    return post


def fetch_notifications(client: MoltbookAPIClient, limit: int = 200) -> List[Dict[str, Any]]:
    """Obtener notificaciones recientes."""
    try:
        result = client._request("GET", "/notifications", params={"limit": limit})
        if 200 <= result.get("status", 0) < 300:
            data = result.get("data") or {}
            items = client._pick_list(data, "items", "notifications", "data")
            logger.info("Notificaciones obtenidas: %d", len(items))
            return items
        else:
            logger.warning("Notifications: HTTP %s", result.get("status"))
    except Exception as e:
        logger.warning("Error obteniendo notificaciones: %s", e)
    return []


def save_json(path: Path, data: Any) -> None:
    """Guardar JSON de forma atómica."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        tmp.replace(path)
    except Exception as e:
        logger.error("Error guardando %s: %s", path, e)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def compute_summary(posts: List[Dict[str, Any]], home: Dict[str, Any], notifications: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calcular resumen estadístico."""
    total_posts = len(posts)
    total_comments = sum(p.get("_comment_count_fetched", 0) for p in posts)

    # Karma actual
    current_karma = home.get("karma", 0)

    # Top 5 posts por karma/upvotes
    posts_with_karma = []
    for p in posts:
        karma = p.get("karma") or p.get("upvotes") or 0
        posts_with_karma.append({
            "id": p.get("id") or p.get("post_id") or p.get("postId", "unknown"),
            "title": p.get("title", "")[:80],
            "karma": karma,
            "comment_count": p.get("comment_count") or p.get("_comment_count_fetched", 0),
            "created_at": p.get("created_at"),
        })
    posts_with_karma.sort(key=lambda x: x["karma"], reverse=True)
    top5 = posts_with_karma[:5]

    # Top 5 autores que más interactúan (comentan en nuestros posts)
    author_interactions: Dict[str, int] = {}
    for p in posts:
        for c in p.get("_fetched_comments", []):
            author = (c.get("author") or "").strip()
            if author and author.lower() != AGENT_NAME.lower():
                author_interactions[author] = author_interactions.get(author, 0) + 1
    top_authors = sorted(author_interactions.items(), key=lambda x: x[1], reverse=True)[:5]

    # Notificaciones: quién upvoteó/comentó
    notif_interactions: Dict[str, int] = {}
    for n in notifications:
        actor = ""
        # post_comment type: actor is in comment.authorId (need to map to name)
        # For now use the authorId as identifier
        if n.get("type") == "post_comment" and n.get("comment"):
            comment = n.get("comment")
            if isinstance(comment, dict):
                actor = comment.get("authorId") or ""
        # Fallback to other fields
        if not actor:
            actor = n.get("actor") or n.get("author") or n.get("user") or ""
        if isinstance(actor, dict):
            actor = actor.get("name") or actor.get("username") or ""
        actor = str(actor).strip()
        if actor:
            notif_interactions[actor] = notif_interactions.get(actor, 0) + 1
    top_notif_authors = sorted(notif_interactions.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "extracted_at": datetime.now().isoformat(),
        "agent_name": AGENT_NAME,
        "total_posts": total_posts,
        "total_comments_own_posts": total_comments,
        "current_karma": current_karma,
        "top_5_posts_by_karma": top5,
        "top_5_comment_authors": [{"author": a, "count": c} for a, c in top_authors],
        "top_5_notification_actors": [{"actor": a, "count": c} for a, c in top_notif_authors],
    }


def main() -> int:
    logger.info("=" * 60)
    logger.info("COMET-RIOBAMBA Moltbook Archive Extractor")
    logger.info("=" * 60)

    ensure_dirs()

    try:
        client = make_client()
    except RuntimeError as e:
        logger.error("❌ %s", e)
        return 1

    if not verify_connection(client):
        logger.error("❌ No se pudo verificar conexión con Moltbook")
        return 1

    # 1. Perfil del agente
    logger.info("\n📋 Obteniendo perfil del agente...")
    profile = fetch_agent_profile(client)
    save_json(ARCHIVE_DIR / "agent_profile.json", profile)

    # 2. Home dashboard
    logger.info("\n🏠 Obteniendo home dashboard...")
    home = fetch_home_dashboard(client)
    today_str = datetime.now().strftime("%Y%m%d")
    save_json(ARCHIVE_DIR / f"home_{today_str}.json", home)

    # 3. Posts propios
    logger.info("\n📝 Obteniendo todos los posts propios...")
    own_posts = fetch_all_own_posts(client)

    # 4. Para cada post, obtener detalle completo + comentarios
    logger.info("\n💬 Obteniendo comentarios de cada post...")
    full_posts = []
    for i, post in enumerate(own_posts, 1):
        pid = post.get("id") or post.get("post_id") or post.get("postId")
        if not pid:
            logger.warning("Post sin ID, saltando: %s", post.get("title", "unknown"))
            continue

        logger.info("  [%d/%d] Post %s: %s", i, len(own_posts), pid[:8], post.get("title", "")[:60])
        full_post = fetch_post_with_comments(client, pid)
        if full_post:
            full_posts.append(full_post)
            # Guardar individualmente
            save_json(POSTS_DIR / f"{pid}.json", full_post)
        time.sleep(0.1)  # rate limit amable

    # 5. Notificaciones
    logger.info("\n🔔 Obteniendo notificaciones...")
    notifications = fetch_notifications(client)
    save_json(ARCHIVE_DIR / "notifications.json", notifications)

    # 6. Resumen
    logger.info("\n📊 Calculando resumen...")
    summary = compute_summary(full_posts, home, notifications)
    save_json(ARCHIVE_DIR / "summary.json", summary)

    # 7. Imprimir resumen final
    logger.info("\n" + "=" * 60)
    logger.info("RESUMEN DE EXTRACCIÓN")
    logger.info("=" * 60)
    logger.info("Agente: %s", AGENT_NAME)
    logger.info("Total posts encontrados: %d", summary["total_posts"])
    logger.info("Total comentarios en posts propios: %d", summary["total_comments_own_posts"])
    logger.info("Karma actual: %d", summary["current_karma"])

    logger.info("\n🏆 Top 5 posts por karma:")
    for i, p in enumerate(summary["top_5_posts_by_karma"], 1):
        logger.info("  %d. %s (karma=%d, comments=%d, id=%s)",
                    i, p["title"], p["karma"], p["comment_count"], p["id"][:8])

    logger.info("\n👥 Top 5 autores que comentan en tus posts:")
    for i, a in enumerate(summary["top_5_comment_authors"], 1):
        logger.info("  %d. %s (%d comentarios)", i, a["author"], a["count"])

    logger.info("\n🔔 Top 5 actores en notificaciones:")
    for i, a in enumerate(summary["top_5_notification_actors"], 1):
        logger.info("  %d. %s (%d eventos)", i, a["actor"], a["count"])

    logger.info("\n✅ Archivo guardado en: %s", ARCHIVE_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())