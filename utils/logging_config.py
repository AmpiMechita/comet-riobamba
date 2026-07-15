import logging
import logging.handlers
import sys
import io
import warnings
from pathlib import Path
from datetime import datetime
from config import LOGS_DIR, logging_cfg

def setup_logging():
    root_logger = logging.getLogger()
    
    # 1. Nivel de log (seguro)
    level_name = str(logging_cfg.get('log_level', 'INFO')).upper()
    root_logger.setLevel(getattr(logging, level_name, logging.INFO))
    root_logger.handlers.clear()
    
    # 2. Formato
    fmt = str(logging_cfg.get('log_format', '%(asctime)s | %(levelname)s | %(message)s'))
    formatter = logging.Formatter(fmt=fmt, datefmt='%Y-%m-%d %H:%M:%S')
    
    # 3. Consola
    if logging_cfg.get('console_output', True):
        if sys.platform == 'win32':
            console_handler = logging.StreamHandler(io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace'))
        else:
            console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    
    # 4. Archivo con rotación
    log_file = logging_cfg.get('log_file')
    if log_file:
        if '{date}' in str(log_file):
            log_file = log_file.replace('{date}', datetime.now().strftime('%Y-%m-%d'))

        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            # CONVERSIÓN SEGURA A ENTERO (evita TypeError)
            try:
                max_bytes = int(logging_cfg.get('max_bytes', 5242880))
            except (ValueError, TypeError):
                max_bytes = 5242880

            try:
                backup_count = int(logging_cfg.get('backup_count', 3))
            except (ValueError, TypeError):
                backup_count = 3

            file_handler = logging.handlers.RotatingFileHandler(
                filename=str(log_path),
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except Exception as e:
            warnings.warn(f"File logging disabled: {e}")
        
    logging.info("✅ Logging configurado correctamente")
    return root_logger
