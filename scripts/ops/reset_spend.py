import json
from datetime import datetime, timezone

# Resetear deepseek_spend_tracker.json manualmente
today = datetime.now(timezone.utc).date().isoformat()
data = {"date": today, "total_usd": 0.0}

with open('data/deepseek_spend_tracker.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print(f"✅ deepseek_spend_tracker.json reseteado")
print(f"   • Nueva fecha: {today}")
print(f"   • Nuevo total: $0.00")
print(f"   • Límite diario: $2.00")
print(f"   • Reset manual completado exitosamente")