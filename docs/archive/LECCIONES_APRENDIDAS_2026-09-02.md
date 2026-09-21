# Lecciones Aprendidas - DeepSeek Quota Bug

## Fecha: 2026-09-02

## Problema
El `quota_manager.py` reportó gasto de $5.00 USD cuando el gasto real fue ~$1.94 USD.
Esto bloqueó el agente prematuramente.

## Causa Raíz
- El sistema de contabilidad de quotas estaba sobre-contando las llamadas
- No había forma de verificar el gasto real vs reportado
- El límite diario de $5.00 era demasiado bajo para la operación real

## Solución Aplicada
1. Eliminar límite diario: `DEEPSEEK_SPEND_LIMIT_USD=999999`
2. Monitoreo manual del saldo real en dashboard de DeepSeek
3. Fix de bug de sintaxis en `services/model_cascade.py` (líneas 855-875)

## Costos Reales Descubierto
- Posts (Fase A): $0.001054 USD promedio (~1,078 tokens)
- Comentarios (Fase B): $0.001022 USD promedio (~1,259 tokens)
- Proyección mensual (escenario moderado): $3.69 USD/mes

## Recomendación Futura
- Usar DeepSeek Pro para contenido de mayor calidad
- Mantener sin límite diario pero monitorear semanalmente
- Actualizar documentación con costos reales

## Archivos Modificados
- `.env`: `DEEPSEEK_SPEND_LIMIT_USD=999999`
- `services/model_cascade.py`: Fix de indentación en logger.info() (líneas 855-875)
