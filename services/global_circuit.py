# -*- coding: utf-8 -*-
"""
Global Circuit Breaker para COMET-RIOBAMBA
Controla fallos consecutivos y aumenta intervalo entre ciclos
"""

import json
import os
from datetime import datetime, timedelta

CIRCUIT_FILE = "data/state/global_circuit.json"

class GlobalCircuitBreaker:
    def __init__(self):
        self.failures = 0
        self.max_failures = 3
        self.base_interval = 300
        self.current_interval = self.base_interval
        self.last_failure = None
        self._load()
    
    def _load(self):
        if os.path.exists(CIRCUIT_FILE):
            try:
                with open(CIRCUIT_FILE, 'r') as f:
                    data = json.load(f)
                    self.failures = data.get('failures', 0)
                    self.current_interval = data.get('current_interval', self.base_interval)
                    self.last_failure = data.get('last_failure')
            except:
                pass
    
    def _save(self):
        os.makedirs(os.path.dirname(CIRCUIT_FILE), exist_ok=True)
        with open(CIRCUIT_FILE, 'w') as f:
            json.dump({
                'failures': self.failures,
                'current_interval': self.current_interval,
                'last_failure': self.last_failure
            }, f)
    
    def record_failure(self):
        self.failures += 1
        self.last_failure = datetime.now().isoformat()
        if self.failures >= 1:
            self.current_interval = int(self.current_interval * 1.5)
        self._save()
    
    def record_success(self):
        self.failures = 0
        self.current_interval = self.base_interval
        self._save()
    
    def is_open(self):
        return self.failures >= self.max_failures
    
    def get_interval(self):
        return self.current_interval

# Instancia global
global_circuit = GlobalCircuitBreaker()

# Funciones exportadas
def should_skip_cycle():
    """Retorna (skip: bool, reason: str|None)"""
    if global_circuit.is_open():
        return True, "global_circuit_open"
    return False, None

def get_current_interval(base_interval: int = 300) -> int:
    """Retorna el intervalo actual entre ciclos"""
    return max(base_interval, global_circuit.get_interval())

def register_cycle_result(success: bool, base_interval: int = 300) -> int:
    """Registra resultado del ciclo y retorna el intervalo a usar"""
    if success:
        global_circuit.record_success()
    else:
        global_circuit.record_failure()
    return get_current_interval(base_interval)
