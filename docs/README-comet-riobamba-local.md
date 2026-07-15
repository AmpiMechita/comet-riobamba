# COMET-RIOBAMBA v3.1.0 – Modos de operación (local vs Moltbook)

Este archivo resume la configuración actual del agente, cómo usa los LLMs locales y cómo alternar entre modo laboratorio (whisper + local) y modo producción (Moltbook real).

---

## 1. Estado actual (modo laboratorio)

Configuración vigente:

- `whisper_mode: True` en `config/config.py` → API de Moltbook simulada, sin llamadas reales.
- `fast_local` (Ollama Mistral) es el primer modelo de la cascada.
- `heavy_local` apunta a `127.0.0.1:57575` pero actualmente no está levantado (error de conexión).
- Cascada de modelos (`services/model_cascade.py`) en este orden:

  ```python
  self.model_order = [
      "fast_local",
      "balanced_cloud",
      "quality_fallback",
      "openrouter_cloud",
      "together_cloud",
      "github_models",
      "heavy_local"
  ]
  ```

- En modo whisper, solo se bloquean los tiers cloud; `fast_local` y `heavy_local` siguen activos.
- `phase_a_content.py` usa `model_cascade.generate()` para generar posts incluso en whisper y simula solo la publicación.
- `phase_b_replies.py` simula feed y replies en whisper (`feed vacío`) y respeta `reply_length_min = 100` y `reply_length_max = 650`.
- Outbox: `pending = 0`, `published = 15`, `abandoned = 16`.

Logs esperados en este modo:

- `Intentando fast_local (Ollama Llama 3.2)`
- `Generación exitosa con modelo fast_local`
- `Modo whisper: publicación simulada`

---

## 2. Cómo correr el agente en modo laboratorio

1. Asegura que Ollama esté corriendo y tenga Mistral:

   ```powershell
   Invoke-WebRequest "http://127.0.0.1:11434/v1/models" -UseBasicParsing
   ```

2. Verifica que `whisper_mode` esté en `True`:

   ```powershell
   Select-String -Path ".\config\config.py" -Pattern "whisper_mode"
   ```

3. Arranca el agente:

   ```powershell
   python .\run_agent.py
   ```

---

## 3. Cómo volver a modo producción

1. Configura la API key de Moltbook en la sesión actual:

   ```powershell
   $env:MOLTBOOK_API_KEY = "moltbook_tu_clave_aqui"
   ```

2. Desactiva whisper:

   ```powershell
   (Get-Content ".\config\config.py" -Raw) `
   -replace 'whisper_mode: bool = True', 'whisper_mode: bool = False' `
   | Set-Content ".\config\config.py" -Encoding UTF8

   python -m py_compile .\config\config.py
   ```

3. Arranca de nuevo el agente:

   ```powershell
   python .\run_agent.py
   ```

Si Moltbook vuelve a fallar, reactiva whisper:

```powershell
(Get-Content ".\config\config.py" -Raw) `
-replace 'whisper_mode: bool = False', 'whisper_mode: bool = True' `
| Set-Content ".\config\config.py" -Encoding UTF8
```

---

## 4. Backups recomendados

```powershell
Copy-Item ".\config\config.py" ".\config\config.py.working" -Force
Copy-Item ".\services\model_cascade.py" ".\services\model_cascade.py.working" -Force
Copy-Item ".\phases\phase_a_content.py" ".\phases\phase_a_content.py.working" -Force
Copy-Item ".\phases\phase_b_replies.py" ".\phases\phase_b_replies.py.working" -Force
```

Para restaurar:

```powershell
Copy-Item ".\config\config.py.working" ".\config\config.py" -Force
Copy-Item ".\services\model_cascade.py.working" ".\services\model_cascade.py" -Force
Copy-Item ".\phases\phase_a_content.py.working" ".\phases\phase_a_content.py" -Force
Copy-Item ".\phases\phase_b_replies.py.working" ".\phases\phase_b_replies.py" -Force
```

---

## 6. Troubleshooting rápido

### 6.1. Ollama / fast_local no responde

1. Verifica que Ollama esté arriba:
   ```powershell
   Invoke-WebRequest "http://127.0.0.1:11434/v1/models" -UseBasicParsing
   ```

2. Lista los modelos:
   ```powershell
   ollama list
   ```

3. Si falta el modelo, descárgalo:
   ```powershell
   ollama pull mistral
   ollama pull llama3.2
   ```

### 6.2. Moltbook devuelve 500 o 401

1. Revisa la API key:
   ```powershell
   $env:MOLTBOOK_API_KEY
   ```

2. Vuelve a modo laboratorio:
   ```powershell
   (Get-Content ".\config\config.py" -Raw) `
   -replace 'whisper_mode: bool = False', 'whisper_mode: bool = True' `
   | Set-Content ".\config\config.py" -Encoding UTF8
   ```

3. Valida el archivo:
   ```powershell
   python -m py_compile .\config\config.py
   ```

### 6.3. El agente no arranca

1. Compila config:
   ```powershell
   python -m py_compile .\config\config.py
   ```

2. Si algo quedó roto, restaura backups:
   ```powershell
   Copy-Item ".\config\config.py.working" ".\config\config.py" -Force
   Copy-Item ".\services\model_cascade.py.working" ".\services\model_cascade.py" -Force
   Copy-Item ".\phases\phase_a_content.py.working" ".\phases\phase_a_content.py" -Force
   Copy-Item ".\phases\phase_b_replies.py.working" ".\phases\phase_b_replies.py" -Force
   ```

3. Arranca otra vez:
   ```powershell
   python .\run_agent.py
   ```
