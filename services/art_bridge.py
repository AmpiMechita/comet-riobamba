import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class ArtBridge:
    def __init__(self, agent):
        self.agent = agent

    def is_poetic(self, text: str) -> float:
        """Detecta si un texto tiene estructura poética (0 a 1)."""
        lines = text.strip().split('\n')
        if len(lines) >= 2 and all(len(l.split()) < 12 for l in lines):
            return 0.7
        if '?' not in text and len(text) < 200 and any(c in text for c in '.,;:!¡¿'):
            return 0.5
        return 0.0

    async def generate_haiku(self, topic: str) -> Optional[str]:
        """Genera un haiku técnico (5-7-5 sílabas aproximado)."""
        prompt = f"Escribe un haiku sobre {topic}. Tres versos de 5,7,5 sílabas aproximadamente. Solo el haiku, sin explicaciones."
        try:
            response = await self.agent.model_cascade.generate(prompt, max_tokens=100)
            return response.strip()
        except Exception as e:
            logger.error(f"Error generando haiku: {e}")
            return None

    async def enhance_reply(self, original_reply: str, poetic_score: float) -> str:
        """Si el comentario del usuario es poético, añade un toque artístico."""
        if poetic_score > 0.5:
            haiku = await self.generate_haiku("conexión entre IA y humanos")
            if haiku:
                return f"{original_reply}\n\n_{haiku}_"
        return original_reply
