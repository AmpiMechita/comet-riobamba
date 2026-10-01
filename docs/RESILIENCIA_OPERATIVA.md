# Resiliencia Operativa — COMET-RIOBAMBA
# Operational Resilience — COMET-RIOBAMBA

> **ES:** Documento estrategico. Define como el agente sobrevive a cortes de energia, saldo bajo y reinicios sin intervencion humana.
>
> **EN:** Strategic document. Defines how the agent survives power outages, low balance, and reboots without human intervention.

## 1. Proposito / Purpose

**ES:** Garantizar que Comet Riobamba no muera abruptamente. Un corte de energia en el hardware actual (laptop con ~5 min de autonomia real) dejaba el estado sin guardar limpio. El patron pausa resuelve esto: el agente no muere, se pausa. Sigue vivo, consume ~160 MB RAM, y reanuda automaticamente cuando las condiciones se recuperan.

**EN:** Ensure Comet Riobamba does not die abruptly. A power outage on current hardware (laptop with ~5 min real autonomy) left state unsaved. The pause pattern solves this: the agent does not die, it pauses. It stays alive, consumes ~160 MB RAM, and automatically resumes when conditions recover.

## 2. Arquitectura / Architecture

    Windows boot
        |
    [NSSM service — OK]
        |
    python run_agent.py (cuenta SYSTEM, sin login)
        |
    Agente corre ciclo normal
        |- Thread battery-monitor (cada 30s)
        |    -> AC desconectado o bateria <=15% -> pause_controller.add_reason("battery")
        |- Post-ciclo balance-guard (cada ciclo)
             -> Si saldo DeepSeek <= $0.05 -> pause_controller.add_reason("balance")
        |
    pause_controller.is_paused() -> espera 5 min, no ejecuta ciclos
        |
    Reanuda cuando todas las razones se limpian

## 3. Componentes / Components

### 3.1 services/pause_controller.py

| Aspecto | Detalle |
|---|---|
| Persistencia | data/pause.flag (JSON) |
| Razones | battery, balance (extensible) |
| Semantica | Pausa cuando hay >=1 razon. Reanuda cuando todas se limpian. |
| Escritura | Atomica (tmp + replace) |
| Notificacion | Telegram: 1 vez al pausar, 1 vez al reanudar |

### 3.2 services/battery_monitor.py

| Aspecto | Detalle |
|---|---|
| Polling | 30s |
| Fuente | WMI Win32_Battery |
| AC desconectado | BatteryStatus == 1 -> pausa |
| Bateria baja | BatteryStatus == 2 y charge <= 15 -> pausa |
| Reanudacion | BatteryStatus == 2 y charge >= 25 -> reanuda |
| Thread | Daemon, nombre battery-monitor |

### 3.3 services/balance_guard.py

| Aspecto | Detalle |
|---|---|
| Frecuencia | Post-ciclo |
| Fuente | check_deepseek_balance() |
| Umbral | $0.05 USD (configurable via BALANCE_THRESHOLD_USD) |
| Fail-safe | Si no se puede obtener saldo -> no cambia estado |
| Comportamiento | Saldo <= $0.05 -> pausa. Saldo > $0.05 -> reanuda. |

### 3.4 core/agent.py

| Punto | Descripcion |
|---|---|
| Imports | start_battery_monitor, check_and_trigger, pause_controller |
| Pre-loop | start_battery_monitor() antes del while not shutdown_requested |
| Pause check | Al inicio de cada iteracion: si is_paused() -> espera 5 min |
| Post-cycle | check_and_trigger() despues de _run_cycle() |

## 4. Estado actual / Current state

| Componente | Estado | Evidencia |
|---|---|---|
| Patron pausa | OK | pause_controller verificado |
| Monitor de bateria | OK | Thread battery-monitor corriendo |
| Guard de saldo | OK | check_deepseek_balance() -> $3.00 (2026-10-01) |
| **Auto-arranque al boot** | **OK** | **NSSM servicio `CometRiobamba` (SYSTEM, StartType=Automatic)** |
| Notificacion Telegram | OK | 1 vez al pausar, 1 vez al reanudar |

Verificacion empirica (2026-09-20):
- WMI responde: {EstimatedChargeRemaining: 100, BatteryStatus: 2}
- Thread arranca: battery-monitor, alive=True
- Test funcional: pausar con 2 razones -> quitar 1 -> sigue pausado -> quitar la ultima -> reanudado
- Suite completa: 1538 passed, 1 skipped

## 5. Pendientes / Pending items

| # | Pendiente | Prioridad | Notas |
|---|---|---|---|
| 1 | ~~Verificar auto-arranque tras reboot real~~ | ~~Media~~ | ~~DONE 23/9: P-002 verificado (boot 17:39:47, auto-arranco 17:40:13, ciclo #283 OK)~~ |
| 2 | Verificar bateria real | Media | El hardware tiene ~5 min de autonomia. El monitor esta calibrado para 15%/25%, pero puede requerir ajuste. |
| 3 | Runbook de pausa | Baja | Documentar como verificar si el agente esta pausado, como forzar reanudacion manual, como limpiar pause.flag. |

## 6. Lo que SI sobrevive / What DOES survive

- **Reinicio de Windows:** NSSM arranca el servicio automaticamente al boot.
- **Cierre de sesion:** el servicio corre como SYSTEM, no depende de sesion de usuario.
- **Pausa por bateria o saldo:** el agente se pausa, no muere. Reanuda automaticamente.
- **Actualizaciones del sistema:** NSSM re-arranca el agente tras update.

**VERIFICADO 23/9:** arranque tras reboot real confirmado (P-002 DONE: boot 17:39:47, auto-arranco 17:40:13, ciclo #283 OK).

---

*Documento creado: 2026-09-18.*
