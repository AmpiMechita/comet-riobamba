# Guía de Optimización de Prompts - DeepSeek

## Objetivo
Reducir el consumo de tokens en DeepSeek manteniendo la calidad del contenido.

## Estrategias Implementadas

### 1. Prompts Concisos
- Eliminar instrucciones redundantes
- Usar formato directo (sin preámbulos)
- Máximo 500 tokens por prompt

### 2. Reutilización de Contexto
- Cache de prompts base
- Inyección selectiva de contexto (solo lo necesario)
- Evitar repetir información en system + user prompt

### 3. Tier de Modelos
- DeepSeek: Tareas rutinarias (posts, comentarios)
- Fallback: Solo cuando DeepSeek < $1.0

### 4. Horarios Valle
- Comentarios en horas valle (18-23, 0-1 UTC-5)
- 50% descuento en tokens DeepSeek

## Métricas de Optimización

### Consumo Actual
- Gasto diario: ~$0.315 USD
- Saldo disponible: $4.9 USD
- Proyección: ~15 días de operación

### Objetivos
- Reducir gasto diario a ~$0.25 USD
- Mantener calidad artística (gate aprobado)
- Aumentar engagement rate en 20%

## Próximas Mejoras

1. **Compresión de contexto:** Reducir contexto en 30%
2. **Cache de respuestas:** Reutilizar estructuras probadas
3. **A/B testing:** Variantes de prompts para optimizar engagement
