from datetime import datetime, timedelta
import re


# Ejemplos conocidos a rastrear
from pathlib import Path
from typing import Tuple
EJEMPLOS_CONOCIDOS = [
    "kafka", "Einstein", "Newton", "Darwin", "Freud", "Jung",
    "Tesla", "Gutenberg", "Turing", "Shakespeare", "Picasso"
]

# Software conocido (para detectar versiones especificas)
SOFTWARE_CONOCIDO = [
    "kafka", "python", "java", "javascript", "typescript", "node", "docker",
    "kubernetes", "redis", "postgres", "mysql", "mongodb", "nginx", "apache",
    "tensorflow", "pytorch", "transformers", "langchain", "llama", "mistral"
]

_COMMENTS_PATH = Path("data/published_comments.json")
_POSTS_PATH = Path("data/published_posts.json")


def text_has_ungrounded_named_entity(text: str) -> Tuple[bool, str]:
    """Detecta entidades nombradas sin calificador ('por ejemplo', 'como').
    
    Retorna (True, razon) si detecta problema, (False, "") si esta OK.
    """
    text_lower = text.lower()
    
    # Verificar si tiene calificadores genericos
    tiene_calificador_generico = any([
        "ejemplo" in text_lower,
        "como" in text_lower,
        "like" in text_lower,
        "por ejemplo" in text_lower,
        "such as" in text_lower
    ])
    
    entidades_sin_calificar = []
    for entidad in EJEMPLOS_CONOCIDOS:
        if entidad.lower() in text_lower and not tiene_calificador_generico:
            entidades_sin_calificar.append(entidad)
    
    if entidades_sin_calificar:
        return True, f"ungrounded_named_entity:{','.join(entidades_sin_calificar)}"
    
    return False, ""


def text_has_ungrounded_software_version(text: str) -> Tuple[bool, str]:
    """Detecta versiones de software sin calificador.
    
    Solo detecta software conocido seguido de version (ej: Kafka 0.11, Python 3.9).
    Evita falsos positivos con parametros numericos (2.5, 0.3, 30%).
    
    Retorna (True, razon) si detecta problema, (False, "") si esta OK.
    """
    text_lower = text.lower()
    
    # Verificar si tiene calificadores
    tiene_calificador = any([
        "ejemplo" in text_lower,
        "como" in text_lower,
        "version" in text_lower,
        "release" in text_lower,
        "introduced" in text_lower,
        "since" in text_lower,
        "starting from" in text_lower
    ])
    
    if tiene_calificador:
        return False, ""
    
    versiones_sin_calificar = []
    for software in SOFTWARE_CONOCIDO:
        patron = rf"\b{software}\s+(\d+\.\d+(?:\.\d+)?)"
        matches = re.finditer(patron, text_lower, re.IGNORECASE)
        
        for match in matches:
            version_completa = match.group(0)
            versiones_sin_calificar.append(version_completa)
    
    if versiones_sin_calificar:
        return True, f"ungrounded_software_version:{','.join(versiones_sin_calificar)}"
    
    return False, ""


def text_has_repeated_example_24h(text: str, lookback_hours: int = 24) -> Tuple[bool, str]:
    """Verifica si un ejemplo conocido se uso en las ultimas 24h.
    
    Retorna (True, razon) si detecta repeticion, (False, "") si esta OK.
    """
    text_lower = text.lower()
    ahora = datetime.now()
    hace_24h = ahora - timedelta(hours=lookback_hours)
    
    # Encontrar ejemplos en el texto actual
    ejemplos_en_texto = [e for e in EJEMPLOS_CONOCIDOS if e.lower() in text_lower]
    
    if not ejemplos_en_texto:
        return False, ""
    
    # Cargar historial de comments
    if not _COMMENTS_PATH.exists():
        return False, ""
    
    try:
        with open(_COMMENTS_PATH, "r", encoding="utf-8") as f:
            historial = json.load(f)
    except:
        return False, ""
    
    # Verificar repeticion
    ejemplos_repetidos = []
    for ejemplo in ejemplos_en_texto:
        usos_recientes = 0
        for item in historial:
            texto_item = item.get("content", item.get("comment", item.get("body", "")))
            fecha_str = item.get("published_at", item.get("created_at", ""))
            
            if ejemplo.lower() in texto_item.lower():
                try:
                    fecha = datetime.fromisoformat(fecha_str.replace("Z", "+00:00"))
                    if fecha >= hace_24h:
                        usos_recientes += 1
                except:
                    continue
        
        if usos_recientes > 0:
            ejemplos_repetidos.append(f"{ejemplo}({usos_recientes} veces)")
    
    if ejemplos_repetidos:
        return True, f"repeated_example_24h:{','.join(ejemplos_repetidos)}"
    
    return False, ""


def gate_calidad_entidades(text: str, title: str = "") -> Tuple[bool, str]:
    """Gate completo para entidades, versiones y repeticion.
    
    Integra las 3 verificaciones en un solo llamado.
    Retorna (aprobado, razon) donde:
      - aprobado=True si no hay problemas
      - razon="" si aprobado, o descripcion del problema si no aprobado
    """
    # Verificar texto completo (title + body si existe)
    texto_completo = f"{title} {text}" if title else text
    
    # 1. Entidades nombradas sin calificador
    tiene_problema, razon = text_has_ungrounded_named_entity(texto_completo)
    if tiene_problema:
        return False, razon
    
    # 2. Versiones de software sin calificador
    tiene_problema, razon = text_has_ungrounded_software_version(texto_completo)
    if tiene_problema:
        return False, razon
    
    # 3. Repeticion de ejemplos en 24h
    tiene_problema, razon = text_has_repeated_example_24h(texto_completo)
    if tiene_problema:
        return False, razon

    # 4. Calidad artistica/artesanal
    aprobado, razon = text_has_artistic_excellence(texto_completo, title)
    if not aprobado:
        return False, razon
    
    return True, ""


def main():
    """Test de las funciones con el comment de Kafka."""
    print("=" * 80)
    print("TEST GATE ENTIDADES v3")
    print("=" * 80)
    print()
    
    # Test con el comment problematico de Kafka
    texto_kafka = """
    Kafka 0.11 introduced exactly-once semantics with producer IDs and sequence 
    numbers — the broker could detect a duplicate write because the write carried 
    its own lineage. Your witness data is the same idea, but at the effect boundary 
    instead of the transport layer.
    """
    
    print("Texto: Kafka 0.11...")
    print()
    
    aprobado, razon = gate_calidad_entidades(texto_kafka)
    print(f"Aprobado: {aprobado}")
    print(f"Razon: {razon}")
    print()
    
    # Test con texto sin problemas
    texto_limpio = """
    The mechanism is a divergence gate between hops. Before a downstream stage 
    consumes upstream output, the orchestrator re-embeds that output against 
    the prior intent embedding and refuses passage when cosine distance exceeds 
    0.3 of the hop's observed baseline.
    """
    
    print("Texto: Divergence gate (sin ejemplos)...")
    print()
    
    aprobado, razon = gate_calidad_entidades(texto_limpio)
    print(f"Aprobado: {aprobado}")
    print(f"Razon: {razon}")
    print()
    
    # Test con ejemplo calificado
    texto_calificado = """
    For example, Kafka 0.11 introduced exactly-once semantics with producer IDs.
    This is like how your witness data works at the effect boundary.
    """
    
    print("Texto: Kafka con 'For example'...")
    print()
    
    aprobado, razon = gate_calidad_entidades(texto_calificado)
    print(f"Aprobado: {aprobado}")
    print(f"Razon: {razon}")
    print()
    
    print("=" * 80)
    print("RESULTADOS ESPERADOS:")
    print("  - Kafka sin calificador: RECHAZAR")
    print("  - Divergence gate: APROBAR")
    print("  - Kafka con 'For example': APROBAR")
    print("=" * 80)





def text_has_reasoning_leak(text: str):
    """True si el texto contiene fuga de razonamiento / scaffolds internos.

    FIX 2026-09-14: firma unificada a bool + patrones ampliados para
    cubrir los casos reales detectados en Moltbook (24-25/08/2026):
    - Labels estructurados (TITLE/Role/Structure/Core principles/Paragraph N)
    - Thinking process leaks ("Here's a thinking process")
    - Instrucciones narrativas (We need to respond/reply/produce/acknowledge)
    - Persona directives (Must be in X mode, as an engineer addressing)
    - Separador HR y flechas de scaffold
    """
    if not text:
        return False

    text_lower = text.lower()

    # 1. Scaffolds clasicos de prosa (listas de pasos, conclusiones)
    scaffolds = ['primero,', 'segundo,', 'tercero,', 'en conclusion', 'finalmente,',
                 'por un lado', 'por otro lado', 'en resumen', 'para concluir']
    for scaffold in scaffolds:
        if scaffold in text_lower:
            return True

    # 2. Labels estructurados de prompt (TITLE:, **Role**:, Structure:, etc.)
    if re.search(r'(?im)^\s*(?:\*\*)?(?:TITLE|Role|Structure|Core principles)(?:\*\*)?\s*:', text):
        return True
    if re.search(r'(?im)^\s*Paragraph\s+\d+(?:\s*\([^)]*\))?\s*:', text):
        return True

    # 3. Thinking process leaks
    if re.search(r"(?i)here'?s (?:a |the )?thinking process", text):
        return True

    # 4. Instrucciones narrativas (1a persona plural + verbo de instruccion)
    if re.search(r'(?i)\bwe need to (?:respond to|reply|produce a|acknowledge|address the specific|rewrite the draft)\b', text):
        return True
    if re.search(r'(?i)\bnecesitamos responder\b', text):
        return True
    if re.search(r'(?i)\bdebemos reconocer puntos\b', text):
        return True

    # 5. Persona directives
    if re.search(r'(?i)\bmust be in \w+ mode\b', text):
        return True
    if re.search(r'(?i)\bas an engineer,? addressing\b', text):
        return True

    # 6. Separador HR y flechas de scaffold
    if re.search(r'(?m)^---\s*$', text):
        return True
    if re.search(r'->\s*\w+\s*->', text):
        return True

    return False

def title_has_scaffold(title: str):
    if not title:
        return False

    # Patrones de clickbait SEO
    seo_scaffolds = ['guia completa', 'todo sobre', 'todo lo que', 'como hacer', 'mejores', 'top ']
    # Patrones de scaffold interno / reasoning leak (24/08/2026)
    internal_scaffolds = [
        "here's a thinking process:", "he aqui un proceso de pensamiento:", "here's the thinking process:",
        "thinking process:", "critique:**", "critique:", "**critique:",
        "we need to critique", "let's critique", "draft...", "pre-critique",
        "post-mortem:", "analysis:", "reasoning:", "step ", "step:",
    ]
    title_lower = title.lower()

    for scaffold in seo_scaffolds:
        if scaffold in title_lower:
            return True

    for scaffold in internal_scaffolds:
        if scaffold in title_lower:
            return True

    # FIX 2026-09-14: label "Role:" como titulo (fuga real en Moltbook).
    if re.match(r'^\s*(?:\*\*)?(?:Role|Rol)(?:\*\*)?\s*:', title, re.IGNORECASE):
        return True

    if title.rstrip().endswith(':'):
        return True

    if re.match(r'^\s*[-*]\s', title) or re.match(r'^\s*\d+\.\s', title):
        return True

    return False

def text_template_fatigue(text: str, bodies=None, min_posts=3):
    import re
    list_patterns = [r'^\s*[-•*]\s', r'^\s*\d+\.\s']
    lines = text.split('\n')
    list_count = sum(1 for line in lines if any(re.match(p, line) for p in list_patterns))
    if list_count > len(lines) * 0.5 and len(lines) > 5:
        return True, f'Exceso de listas: {list_count}/{len(lines)} lineas'
    return False






def text_has_artistic_excellence(text: str, title: str = "") -> Tuple[bool, str]:
    """Verifica que el texto tenga calidad artistica/artesanal.
    
    Criterios:
    - Variacion en longitud de oraciones (no todas iguales)
    - Al menos una frase memorable (corta, impactante)
    - Uso de contraste o paradoja
    - Flujo natural (no robotico o repetitivo)
    """
    sentences = re.split(r"[.!?]+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    if len(sentences) < 3:
        return False, "too_few_sentences"
    
    # Verificar variacion en longitud
    lengths = [len(s) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
    
    # Si todas las oraciones tienen longitud similar, rechazar
    if variance < 400:  # Umbral bajo = poca variacion
        return False, "low_sentence_variance"
    
    # Verificar al menos una frase corta impactante (< 15 palabras)
    has_punch = any(len(s.split()) <= 15 for s in sentences)
    if not has_punch:
        return False, "no_punch_line"
    
    # Verificar contraste o paradoja (palabras clave)
    contrast_words = ["not", "but", "yet", "however", "instead", "rather", "paradox", "irony"]
    has_contrast = any(word in text.lower() for word in contrast_words)
    if not has_contrast:
        return False, "no_contrast"
    
    return True, "artistic_excellence_ok"

