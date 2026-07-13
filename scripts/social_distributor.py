import os
import glob
import tkinter as tk
from tkinter import messagebox

def distribute_content():
    export_dir = os.path.join(os.path.dirname(__file__), '..', 'exports', 'social_content')
    files = glob.glob(os.path.join(export_dir, "*.md"))
    
    if not files:
        print("❌ No hay contenido generado en exports/social_content/. Corre harvest_insights.py primero.")
        return

    latest_file = max(files, key=os.path.getctime)
    print(f"📄 Cargando último contenido: {os.path.basename(latest_file)}")
    
    with open(latest_file, "r", encoding="utf-8") as f:
        content = f.read()

    try:
        # Extraer el hilo de Twitter
        tw_start = content.find("## 🧵 Twitter Thread")
        li_start = content.find("## 💼 LinkedIn Post")
        
        twitter_section = content[tw_start:li_start]
        
        # Formatear tuits
        tweets = [line.strip("- ").strip() for line in twitter_section.split("\n") if line.strip().startswith("- ")]
        
        formatted_thread = "=== HILO PARA TWITTER (Copia y pega) ===\n\n"
        for i, tweet in enumerate(tweets, 1):
            formatted_thread += f"[Tuit {i}/{len(tweets)}]\n{tweet}\n\n"
            
        # Extraer LinkedIn
        li_end = content.find("## 📄") if "## 📄" in content else len(content)
        linkedin_section = content[li_start:li_end].replace("## 💼 LinkedIn Post\n\n", "")
        
        formatted_thread += "=== POST PARA LINKEDIN (Copia y pega) ===\n\n"
        formatted_thread += linkedin_section.strip() + "\n"

        # Copiar al portapapeles automáticamente
        root = tk.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(formatted_thread)
        
        print("\n✅ ¡ÉXITO! El contenido ha sido copiado a tu portapapeles.")
        print("Ve a Twitter o LinkedIn, haz clic en 'Crear Post' y presiona Ctrl+V.")
        
        messagebox.showinfo("COMET Distributor", "¡Contenido copiado al portapapeles!\nVe a Twitter/LinkedIn y presiona Ctrl+V.")
        
    except Exception as e:
        print(f"❌ Error parseando el archivo: {e}")

if __name__ == "__main__":
    distribute_content()
