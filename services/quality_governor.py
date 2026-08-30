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
    scaffolds = ['primero,', 'segundo,', 'tercero,', 'en conclusion', 'finalmente,', 
                 'por un lado', 'por otro lado', 'en resumen', 'para concluir']
    text_lower = text.lower()
    for scaffold in scaffolds:
        if scaffold in text_lower:
            return True, f'Contiene scaffold: {scaffold}'
    return False, ''


def title_has_scaffold(title: str):
    # Patrones de clickbait SEO
    seo_scaffolds = ['guia completa', 'todo sobre', 'todo lo que', 'como hacer', 'mejores', 'top ']
    # Patrones de scaffold interno / reasoning leak (24/08/2026)
    internal_scaffolds = [
        "here's a thinking process:", "here's the thinking process:",
        "thinking process:", "critique:**", "critique:", "**critique:",
        "we need to critique", "let's critique", "draft...", "pre-critique",
        "post-mortem:", "analysis:", "reasoning:", "step ", "step:",
    ]
    title_lower = title.lower()
    
    # Check SEO scaffolds
    for scaffold in seo_scaffolds:
        if scaffold in title_lower:
            return True, f'Titulo con scaffold SEO: {scaffold}'
    
    # Check internal scaffolds / reasoning leaks
    for scaffold in internal_scaffolds:
        if scaffold in title_lower:
            return True, f'Titulo con scaffold interno: {scaffold}'
    
    # Check si termina en ':' (instruccion, no titulo)
    if title.rstrip().endswith(':'):
        return True, 'Titulo termina en dos puntos (scaffold)'
    
    # Check si empieza como item de lista
    if re.match(r'^\s*[-•*]\s', title) or re.match(r'^\s*\d+\.\s', title):
        return True, 'Titulo es item de lista'
    
    return False, ''

def text_template_fatigue(text: str):
    import re
    list_patterns = [r'^\s*[-•*]\s', r'^\s*\d+\.\s']
    lines = text.split('\n')
    list_count = sum(1 for line in lines if any(re.match(p, line) for p in list_patterns))
    if list_count > len(lines) * 0.5 and len(lines) > 5:
        return True, f'Exceso de listas: {list_count}/{len(lines)} lineas'
    return False, ''


