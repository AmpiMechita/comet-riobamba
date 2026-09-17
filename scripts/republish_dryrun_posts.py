# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import json, logging, asyncio, time
from datetime import datetime, timezone
from pathlib import Path
from services.moltbook_api_client import MoltbookAPIClient
from services.quota_manager import QuotaManager, set_global_quota_manager

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

APPROVED_POSTS_PATH = Path("data/dryrun_approved_posts.json")
REPUBLISH_LOG_PATH = Path("data/republish_dryrun_log.json")

def load_approved_posts():
    if not APPROVED_POSTS_PATH.exists():
        logger.error(f"No existe {APPROVED_POSTS_PATH}")
        return []
    with open(APPROVED_POSTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def check_post_exists(client, title, body):
    try:
        my_posts = client.fetch_my_posts(limit=100)
        for mp in my_posts:
            mp_title = mp.get("title", "")
            mp_body = mp.get("body", "")
            if title.strip().lower() == mp_title.strip().lower():
                return mp.get("id") or mp.get("post_id")
            if body[:200].strip().lower() == mp_body[:200].strip().lower():
                return mp.get("id") or mp.get("post_id")
        return None
    except Exception as e:
        logger.warning(f"Error verificando existencia: {e}")
        return None

async def republish_post(client, post):
    post_id = post.get("post_id", "unknown")
    title = post.get("title", "")
    body = post.get("body", "")
    try:
        existing_id = check_post_exists(client, title, body)
        if existing_id:
            logger.info(f"✅ Post {post_id[:8]}... YA EXISTE (id={existing_id[:8]}...)")
            return {"post_id": post_id, "status": "already_exists", "moltbook_id": existing_id}
        
        logger.info(f"📤 Publicando post {post_id[:8]}... title={title[:50]}...")
        result = client.create_post(title=title, body=body)
        
        if result.get("success") or result.get("status") == 201:
            moltbook_id = result.get("id") or result.get("post_id")
            logger.info(f"✅ Publicado: {post_id[:8]}... -> {moltbook_id}")
            return {"post_id": post_id, "status": "published", "moltbook_id": moltbook_id}
        else:
            logger.error(f"❌ Error: {result}")
            return {"post_id": post_id, "status": "error", "error": str(result)}
    except Exception as e:
        logger.error(f"❌ Excepción: {e}")
        return {"post_id": post_id, "status": "exception", "error": str(e)}

async def main():
    logger.info("🚀 Iniciando re-publicación")
    posts = load_approved_posts()
    if not posts:
        logger.error("No hay posts aprobados")
        return
    
    logger.info(f"📋 Procesando {len(posts)} posts")
    client = MoltbookAPIClient()
    quota_manager = QuotaManager()
    set_global_quota_manager(quota_manager)
    
    results, published_count, already_exists_count, error_count = [], 0, 0, 0
    
    for i, post in enumerate(posts, 1):
        logger.info(f"[{i}/{len(posts)}] Procesando...")
        result = await republish_post(client, post)
        results.append(result)
        
        if result["status"] == "published": published_count += 1
        elif result["status"] == "already_exists": already_exists_count += 1
        else: error_count += 1
        
        if i % 10 == 0:
            logger.info(f"⏱️  Pausa 10s... (publicados={published_count}, existentes={already_exists_count}, errores={error_count})")
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(2)
    
    log_data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_processed": len(posts),
        "published": published_count,
        "already_exists": already_exists_count,
        "errors": error_count,
        "results": results
    }
    
    with open(REPUBLISH_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"✅ Completado: {published_count} publicados, {already_exists_count} ya existían, {error_count} errores")
    logger.info(f"📝 Log: {REPUBLISH_LOG_PATH}")

if __name__ == "__main__":
    asyncio.run(main())
