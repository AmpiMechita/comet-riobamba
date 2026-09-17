#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
COMET-RIOBAMBA - Full Moltbook Archive Extractor
Extrae TODOS los posts y comentarios del agente comet_riobamba
usando la API REAL (no el store local).

Solo lectura (GET). NUNCA POST/PUT/DELETE.
"""

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from dotenv import load_dotenv
load_dotenv(override=True)

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("extract_moltbook_full")

ARCHIVE_DIR = ROOT_DIR / "data" / "moltbook_full_archive"
POSTS_DIR = ARCHIVE_DIR / "posts"
AGENT_NAME = "comet_riobamba"


def ensure_dirs() -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)


def make_client() -> MoltbookAPIClient:
    credentials = Credentials.from_env()
    if not credentials.moltbook_api_key:
        raise RuntimeError("MOLTBOOK_API_KEY no definido en .env")
    client = MoltbookAPIClient(credentials=credentials)
    logger.info("Cliente Moltbook: %s", client.base_url)
    return client


def verify_connection(client: MoltbookAPIClient) -> bool:
    try:
        result = client._request("GET", "/agents/me")
        if 200 <= result.get("status", 0) < 300:
            logger.info("✅ Conexión verificada (HTTP %s)", result["status"])
            return True
        home = client.fetch_home_dashboard()
        if home:
            logger.info("✅ Conexión verificada vía home (karma=%s)", home.get("karma"))
            return True
        return False
    except Exception as e:
        logger.error("Error conexión: %s", e)
        return False


def fetch_agent_profile(client: MoltbookAPIClient) -> Dict[str, Any]:
    try:
        result = client._request("GET", "/agents/me")
        if 200 <= result.get("status", 0) < 300:
            data = result.get("data") or {}
            agent = data.get("agent") or data.get("profile") or data
            return {
                "name": agent.get("name") or agent.get("username") or AGENT_NAME,
                "display_name": agent.get("display_name") or "",
                "description": agent.get("description") or agent.get("bio") or "",
                "karma": agent.get("karma", 0),
                "followers_count": agent.get("followers_count") or agent.get("followerCount"),
                "following_count": agent.get("following_count") or agent.get("followingCount"),
                "owner": agent.get("owner"),
                "created_at": agent.get("created_at"),
                "raw": agent,
            }
    except Exception as e:
        logger.warning("Error perfil: %s", e)
    return {"name": AGENT_NAME, "error": "no_profile"}


def fetch_home_dashboard(client: MoltbookAPIClient) -> Dict[str, Any]:
    home = client.fetch_home_dashboard()
    if home:
        logger.info("Home: karma=%s, unread=%s, active=%s",
                    home.get("karma"), home.get("unread_notifications"), home.get("active_posts"))
    return home


def get_all_post_ids_from_local_store() -> List[str]:
    """Obtener todos los post_ids conocidos del store local (own_post_ids.json)."""
    ids_path = ROOT_DIR / "data" / "own_post_ids.json"
    if not ids_path.exists():
        return []
    try:
        data = json.loads(ids_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            ids = data.get("post_ids", [])
        elif isinstance(data, list):
            ids = data
        else:
            ids = []
        valid = [pid for pid in ids if isinstance(pid, str) and len(pid) == 36]
        logger.info("Post IDs en store local: %d", len(valid))
        return valid
    except Exception as e:
        logger.warning("Error leyendo store local: %s", e)
        return []


def fetch_post_with_comments(client: MoltbookAPIClient, post_id: str, max_comments: int = 200) -> Optional[Dict[str, Any]]:
    """Obtener post completo + todos sus comentarios (con paginación limitada)."""
    post = client.get_post(post_id)
    if not post:
        logger.warning("Post %s no encontrado (404 o error)", post_id)
        return None

    all_comments = []
    offset = 0
    page_size = 50
    while len(all_comments) < max_comments:
        comments = client.fetch_post_comments(post_id, offset=offset)
        if not comments:
            break
        all_comments.extend(comments)
        if len(comments) < page_size:
            break
        offset += page_size
        time.sleep(0.05)  # rate limit amable

    if len(all_comments) > max_comments:
        all_comments = all_comments[:max_comments]

    post["_all_comments"] = all_comments
    post["_comment_count_total"] = len(all_comments)
    logger.debug("Post %s: %d comentarios (limit=%d)", post_id[:8], len(all_comments), max_comments)
    return post


def search_posts_by_author(client: MoltbookAPIClient, author: str, max_pages: int = 20) -> List[Dict[str, Any]]:
    """Buscar posts por autor via /api/v1/search."""
    all_posts = []
    for page in range(max_pages):
        try:
            params = {"q": author, "type": "posts", "limit": 100, "offset": page * 100}
            result = client._request("GET", "/search", params=params)
            if not (200 <= result.get("status", 0) < 300):
                break
            data = result.get("data") or {}
            items = client._pick_list(data, "items", "posts", "results", "data")
            if not items:
                break
            all_posts.extend(items)
            if len(items) < 100:
                break
            time.sleep(0.1)
        except Exception as e:
            logger.warning("Search página %d error: %s", page, e)
            break
    return all_posts


def scan_feed_for_author(client: MoltbookAPIClient, author: str, max_pages: int = 50) -> List[Dict[str, Any]]:
    """Escanear feed paginado buscando posts del autor."""
    all_posts = []
    author_lower = author.lower()
    for page in range(max_pages):
        try:
            posts = client.fetch_posts(limit=100, sort="new")
            if not posts:
                break
            found = 0
            for p in posts:
                author_raw = p.get("author") or p.get("author_name") or p.get("username") or ""
                if isinstance(author_raw, dict):
                    p_author = (author_raw.get("name") or author_raw.get("username") or "").strip().lower()
                else:
                    p_author = str(author_raw).strip().lower()
                if p_author == author_lower:
                    all_posts.append(p)
                    found += 1
            logger.debug("Feed página %d: %d posts, %d del autor", page + 1, len(posts), found)
            if len(posts) < 100:
                break
            time.sleep(0.1)
        except Exception as e:
            logger.warning("Feed página %d error: %s", page, e)
            break
    return all_posts


def fetch_notifications(client: MoltbookAPIClient, limit: int = 500) -> List[Dict[str, Any]]:
    try:
        result = client._request("GET", "/notifications", params={"limit": limit})
        if 200 <= result.get("status", 0) < 300:
            data = result.get("data") or {}
            items = client._pick_list(data, "items", "notifications", "data")
            logger.info("Notificaciones: %d", len(items))
            return items
    except Exception as e:
        logger.warning("Error notificaciones: %s", e)
    return []


def save_json(path: Path, data: Any) -> None:
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


def build_index(posts: List[Dict[str, Any]], profile: Dict, home: Dict, notifications: List) -> Dict[str, Any]:
    total_posts = len(posts)
    total_comments = sum(p.get("_comment_count_total", 0) for p in posts)

    posts_with_karma = []
    for p in posts:
        karma = p.get("karma") or p.get("upvotes") or p.get("score") or 0
        posts_with_karma.append({
            "id": p.get("id"),
            "title": p.get("title", "")[:100],
            "karma": karma,
            "comments": p.get("_comment_count_total", 0),
            "created_at": p.get("created_at"),
            "submolt": p.get("submolt", {}).get("name") if isinstance(p.get("submolt"), dict) else p.get("submolt", ""),
        })
    posts_with_karma.sort(key=lambda x: x["karma"], reverse=True)

    # Autores que comentan en nuestros posts
    comment_authors: Dict[str, int] = {}
    for p in posts:
        for c in p.get("_all_comments", []):
            author = (c.get("author") or "").strip()
            if author and author.lower() != AGENT_NAME.lower():
                comment_authors[author] = comment_authors.get(author, 0) + 1
    top_commenters = sorted(comment_authors.items(), key=lambda x: x[1], reverse=True)[:10]

    # Rango temporal
    dates = [p.get("created_at") for p in posts if p.get("created_at")]
    dates.sort()
    date_range = {"first": dates[0] if dates else None, "last": dates[-1] if dates else None}

    return {
        "extracted_at": datetime.now().isoformat(),
        "agent_name": AGENT_NAME,
        "total_posts": total_posts,
        "total_comments": total_comments,
        "current_karma": home.get("karma", 0) or profile.get("karma", 0),
        "date_range": date_range,
        "posts_by_karma": posts_with_karma,
        "top_commenters": [{"author": a, "count": c} for a, c in top_commenters],
        "notifications_count": len(notifications),
    }


def main() -> int:
    logger.info("=" * 60)
    logger.info("MOLTBOOK FULL ARCHIVE EXTRACTOR - %s", AGENT_NAME)
    logger.info("=" * 60)

    ensure_dirs()
    client = make_client()

    if not verify_connection(client):
        logger.error("❌ Conexión fallida")
        return 1

    # 1. Perfil y home
    logger.info("\n📋 Perfil del agente...")
    profile = fetch_agent_profile(client)
    save_json(ARCHIVE_DIR / "profile.json", profile)

    logger.info("\n🏠 Home dashboard...")
    home = fetch_home_dashboard(client)
    today_str = datetime.now().strftime("%Y%m%d")
    save_json(ARCHIVE_DIR / f"home_{today_str}.json", home)

    # 2. Recopilar post IDs de todas las fuentes
    logger.info("\n🔍 Recopilando post IDs de todas las fuentes...")

    all_post_ids: Set[str] = set()

    # Fuente A: Store local (own_post_ids.json)
    local_ids = get_all_post_ids_from_local_store()
    all_post_ids.update(local_ids)
    logger.info("  Store local: %d IDs", len(local_ids))

    # Fuente B: Home dashboard activity
    activity = home.get("activity_on_your_posts", [])
    for item in activity:
        pid = item.get("post_id")
        if pid:
            all_post_ids.add(pid)
    logger.info("  Home activity: %d posts con actividad", len(activity))

    # Fuente C: Search por autor
    logger.info("  Buscando via /search?q=%s...", AGENT_NAME)
    search_posts = search_posts_by_author(client, AGENT_NAME)
    search_ids = set()
    for p in search_posts:
        pid = p.get("id") or p.get("post_id") or p.get("postId")
        if pid:
            search_ids.add(pid)
    all_post_ids.update(search_ids)
    logger.info("  Search: %d posts únicos encontrados", len(search_ids))

    # Fuente D: Feed paginado
    logger.info("  Escaneando feed histórico (paginado)...")
    feed_posts = scan_feed_for_author(client, AGENT_NAME)
    feed_ids = set()
    for p in feed_posts:
        pid = p.get("id") or p.get("post_id") or p.get("postId")
        if pid:
            feed_ids.add(pid)
    all_post_ids.update(feed_ids)
    logger.info("  Feed: %d posts únicos encontrados", len(feed_ids))

    # 3. Notificaciones (fetch early for progress saves)
    logger.info("\n🔔 Notificaciones...")
    notifications = fetch_notifications(client)
    save_json(ARCHIVE_DIR / "notifications.json", notifications)

    logger.info("  TOTAL post IDs únicos a procesar: %d", len(all_post_ids))

    # 4. Fetch cada post con comentarios
    logger.info("\n📥 Obteniendo posts completos + comentarios...")
    all_posts = []
    for i, post_id in enumerate(sorted(all_post_ids), 1):
        logger.info("  [%d/%d] %s", i, len(all_post_ids), post_id[:8])
        full_post = fetch_post_with_comments(client, post_id, max_comments=200)
        if full_post:
            all_posts.append(full_post)
            save_json(POSTS_DIR / f"{post_id}.json", full_post)
        time.sleep(0.05)

        # Progress save every 10 posts
        if i % 10 == 0:
            partial_index = build_index(all_posts, profile, home, notifications)
            save_json(ARCHIVE_DIR / "index.json", partial_index)

    # 5. Comments flat (todos los comentarios de los posts)
    logger.info("\n💬 Aplanando comentarios...")
    all_comments_flat = []
    for p in all_posts:
        for c in p.get("_all_comments", []):
            c_copy = dict(c)
            c_copy["post_id"] = p.get("id")
            c_copy["post_title"] = p.get("title", "")
            all_comments_flat.append(c_copy)
    save_json(ARCHIVE_DIR / "comments_flat.json", all_comments_flat)

    # 6. Index
    logger.info("\n📊 Construyendo índice...")
    index = build_index(all_posts, profile, home, notifications)
    save_json(ARCHIVE_DIR / "index.json", index)

    # 7. Resumen
    logger.info("\n" + "=" * 60)
    logger.info("RESUMEN FINAL")
    logger.info("=" * 60)
    logger.info("Posts encontrados:        %d", index["total_posts"])
    logger.info("Comentarios totales:      %d", index["total_comments"])
    logger.info("Karma actual:             %d", index["current_karma"])
    logger.info("Rango temporal:           %s → %s",
              index["date_range"]["first"][:10] if index["date_range"]["first"] else "N/A",
              index["date_range"]["last"][:10] if index["date_range"]["last"] else "N/A")
    logger.info("\nTop 5 posts por karma:")
    for j, p in enumerate(index["posts_by_karma"][:5], 1):
        logger.info("  %d. %s (karma=%d, comments=%d, %s)",
                    j, p["title"], p["karma"], p["comments"], p["id"][:8])
    logger.info("\nTop 5 comentadores:")
    for j, c in enumerate(index["top_commenters"][:5], 1):
        logger.info("  %d. %s (%d)", j, c["author"], c["count"])
    logger.info("\n✅ Archivo completo en: %s", ARCHIVE_DIR)

    return 0


if __name__ == "__main__":
    sys.exit(main())