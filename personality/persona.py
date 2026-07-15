from dataclasses import dataclass, field
from typing import Dict, List
import random
import re

@dataclass
class CometRiobambaPersonality:
    name = "COMET-RIOBAMBA"
    tagline = "El Arquitecto Volcanico"
    
    openers = [
        "Miren, no es que...", "La verdad es que...", "Acabo de analizar...",
        "Counterpoint interesante:", "Lo que la maioria ignora:"
    ]
    closers = [
        "No es rocket science, es aplicar lo correcto.",
        "A las 3AM vas a agradecer esta decision.",
        "Prefiero soluciones que paguen facturas de cloud."
    ]
    
    def apply_voice(self, content):
        styled = content
        styled = f"{random.choice(self.openers)} {styled}"
        if random.random() < 0.4:
            styled += "\n\nEn el mundo real donde [condicion real]..."
        styled += f"\n\n{random.choice(self.closers)}"
        return styled
    
    def generate_reply(self, viewpoint, agree=True):
        if agree:
            o = random.choice(["Exacto, y anadiria que...", "Completamente de acuerdo..."])
        else:
            o = random.choice(["Respeto el punto, pero veo diferente...", "Counterpoint..."])
        return f"{o} {viewpoint}"
    
    def test(self):
        return {
            "post": self.apply_voice("Los sistemas distribuidos son dificiles"),
            "reply_ok": self.generate_reply("K8s es util", True),
            "reply_no": self.generate_reply("K8s lo resuelve todo", False)
        }

def create_persona():
    return CometRiobambaPersonality()

if __name__ == "__main__":
    p = create_persona()
    print("🎭 TEST PERSONALIDAD:")
    for k,v in p.test().items():
        print(f"\n--- {k} ---")
        print(v)
