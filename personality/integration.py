"""Integracion de personalidad"""
from personality.persona import create_persona

_p = None

def get_persona():
    global _p
    if _p is None:
        _p = create_persona()
    return _p

def style_post(c):
    return get_persona().apply_voice(c)
