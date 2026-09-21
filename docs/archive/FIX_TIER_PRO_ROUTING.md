# Fix: tier_pro Discount + Routing - 2026-09-02

## Cambios Aplicados

### 1. Routing tier_pro (línea 175 + 672)
- Agregado "pro": "tier_pro" en TIER_MAPPING
- Cambiado PRO-TIER-ONLY: tier = "pro" (antes "fallback")

### 2. Descuento 50% para tier_pro (línea 93)
- tier_pro ahora recibe descuento en horas valle
- Mismo comportamiento que tier_fallback

## Costos Actualizados (hora valle)

| Componente | Tokens | Costo USD |
|------------|--------|-----------|
| Post Phase A | ~1,000 | $0.0007-0.0010 |
| Comentario Phase B | ~2,000 | $0.0013-0.0020 |
| Mensual (20+100/día) | - | $8-12 USD |

## Archivos Modificados
- services/model_cascade.py: TIER_MAPPING, PRO-TIER-ONLY, _estimate_cost_usd
- docs/FIX_TIER_PRO_ROUTING.md: Documentación

## Verificación
```text
Phase A: tier de generación = pro (Escenario B: DeepSeek V4 Pro)
ModelCascade: intentando tier_pro (deepseek-v4-pro)...
```
