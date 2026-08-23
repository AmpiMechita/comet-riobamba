"""
Validador de contenido para COMET-RIOBAMBA
Evita publicar contenido problemático
"""
import re
import logging

logger = logging.getLogger(__name__)

# Palabras prohibidas (ajustar según necesidad)
FORBIDDEN_WORDS = [
    'código ejecutable', 'script', 'exec(', 'eval(', 
    'http://', 'https://',  # No URLs externas
    'rm -rf', 'sudo', 'admin'
]

# Patrones peligrosos
DANGEROUS_PATTERNS = [
    r'import\s+os',
    r'import\s+subprocess',
    r'__import__',
    r'system\(',
]

def validate_content(title: str, content: str) -> dict:
    """
    Valida que el contenido sea seguro para publicar.
    Retorna: {'valid': bool, 'errors': list}
    """
    errors = []
    
    # Verificar longitud
    if len(title) > 280:
        errors.append(f"Título muy largo: {len(title)} > 280")
    if len(content) > 5000:
        errors.append(f"Contenido muy largo: {len(content)} > 5000")
    
    # Verificar palabras prohibidas
    text_lower = (title + ' ' + content).lower()
    for word in FORBIDDEN_WORDS:
        if word.lower() in text_lower:
            errors.append(f"Palabra prohibida encontrada: '{word}'")
    
    # Verificar patrones peligrosos
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, title + ' ' + content, re.IGNORECASE):
            errors.append(f"Patrón peligroso: {pattern}")
    
    if errors:
        logger.warning(f"⚠️ Validación falló: {errors}")
        return {'valid': False, 'errors': errors}
    
    logger.info("✅ Contenido validado correctamente")
    return {'valid': True, 'errors': []}

# Alias para compatibilidad
is_safe_to_publish = validate_content
