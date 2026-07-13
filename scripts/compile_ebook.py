import json
import os
from datetime import datetime, timedelta

def compile_weekly_ebook():
    # LA RUTA REAL: Donde el agente guarda el registro de lo publicado
    posts_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'published_posts.json')
    export_dir = os.path.join(os.path.dirname(__file__), '..', 'exports')
    os.makedirs(export_dir, exist_ok=True)
    
    if not os.path.exists(posts_path):
        print("❌ No existe data/published_posts.json todavía.")
        return

    with open(posts_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except Exception as e:
            print(f"❌ Error leyendo el JSON: {e}")
            return

    # Asegurarnos de que es una lista (el agente a veces guarda dicts envueltos)
    if isinstance(data, dict):
        posts = data.get("posts", data.get("data", list(data.values())))
    elif isinstance(data, list):
        posts = data
    else:
        posts = []

    if not posts:
        print("❌ El archivo está vacío o no tiene posts.")
        return

    # Filtrar últimos 7 días (si hay timestamp)
    week_ago = datetime.now() - timedelta(days=7)
    recent_posts = []
    
    for p in posts:
        ts_str = p.get("timestamp", p.get("created_at", p.get("date")))
        if ts_str:
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00").split("+")[0])
                if ts > week_ago:
                    recent_posts.append(p)
                continue
            except:
                pass
        recent_posts.append(p) # Si no tiene fecha, lo incluimos

    if not recent_posts:
        print("❌ No hay posts en los últimos 7 días.")
        return

    # Generar el E-book
    ebook_title = f"COMET Weekly Insights: {datetime.now().strftime('%d %b %Y')}"
    filepath = os.path.join(export_dir, f"ebook_{datetime.now().strftime('%Y%m%d')}.md")

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# {ebook_title}\n\n")
        f.write("**Patrones de Resiliencia para Agentes Autónomos**\n")
        f.write("*Extraído directamente de producción por el agente COMET-RIOBAMBA.*\n\n")
        f.write("---\n\n")

        for post in recent_posts:
            title = post.get("title", "Sin Título")
            content = post.get("content", post.get("text", "Contenido no disponible."))
            ts = post.get("timestamp", post.get("created_at", "Fecha no registrada"))
            
            f.write(f"## {title}\n\n")
            f.write(f"*Publicado: {ts}*\n\n")
            f.write(f"{content}\n\n")
            f.write("---\n\n")

    print(f"✅ ¡ÉXITO! E-book semanal compilado.")
    print(f"📄 Ruta: {filepath}")
    print(f"📊 Capítulos procesados: {len(recent_posts)} posts.")
    print("🚀 ¡Listo para subir a Gumroad!")

if __name__ == "__main__":
    compile_weekly_ebook()