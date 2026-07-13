import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.credentials import Credentials
from services.moltbook_api_client import MoltbookAPIClient


def main():
    outbox_path = PROJECT_ROOT / "data" / "failed_posts_outbox.jsonl"
    if not outbox_path.exists():
        print("No hay outbox de posts fallidos.")
        return

    api = MoltbookAPIClient(credentials=Credentials.from_env())

    remaining = []
    reintentos_ok = 0
    total = 0

    with open(outbox_path, "r", encoding="utf-8-sig") as f:
        for line in f:
            if not line.strip():
                continue

            try:
                item = json.loads(line)
            except Exception as exc:
                print(f"Línea inválida en outbox, se conserva sin procesar: {exc}")
                continue

            total += 1
            title = item.get("title", "Post recuperado")
            content = item.get("content", "")
            submolt = item.get("submolt", "general")
            submolt_name = item.get("submolt_name", "General")

            print(f"Reintentando post {total}: {title!r} -> {submolt}")

            resp = api.create_post(
                title=title,
                content=content,
                submolt=submolt,
                submolt_name=submolt_name,
            )

            print(f"Respuesta: {resp}")

            if resp.get("success") and resp.get("id"):
                print(f"OK reintento, id={resp.get('id')}")
                reintentos_ok += 1
            else:
                item["last_retry_response"] = resp
                remaining.append(item)

    if remaining:
        with open(outbox_path, "w", encoding="utf-8") as f:
            for item in remaining:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Quedan {len(remaining)} posts en outbox tras reintentos.")
    else:
        outbox_path.unlink()
        print("Outbox vacío: todos los posts pendientes se reintentaron con éxito.")

    print(f"Reintentos OK: {reintentos_ok}/{total}")


if __name__ == "__main__":
    main()


