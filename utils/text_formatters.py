"""
Text Formatters - v3.1.0
========================
Limpieza de texto generado por LLMs.
"""

import re
import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class JSONResponseParser:
    
    @staticmethod
    def extract_json(raw_response: str) -> Tuple[Optional[dict], Optional[str]]:
        if not raw_response:
            return None, "Empty response"
        text = raw_response.strip()
        
        json_match = JSONResponseParser._find_balanced_json(text)
        if json_match:
            try:
                parsed = json.loads(json_match)
                return parsed, None
            except json.JSONDecodeError as e:
                logger.debug(f"JSON found but invalid: {e}")
                repaired = JSONResponseParser._attempt_repair(json_match)
                if repaired:
                    try:
                        return json.loads(repaired), None
                    except:
                        pass
        
        title_match = re.search(r'"title"\s*:\s*["\']([^"\']*)["\']', text)
        content_match = re.search(r'"content"\s*:\s*["\']((?:[^"\\]|\\.)*)["\']', text, re.DOTALL)
        
        if title_match and content_match:
            return {"title": title_match.group(1), "content": content_match.group(1)}, None
        
        try:
            return json.loads(text), None
        except:
            pass
        return None, f"Could not extract valid JSON (length: {len(text)})"
    
    @staticmethod
    def _find_balanced_json(text: str) -> Optional[str]:
        start = text.find('{')
        if start == -1:
            return None
        depth = 0
        in_string = False
        escape_next = False
        json_start = -1
        for i in range(start, len(text)):
            char = text[i]
            if escape_next:
                escape_next = False
                continue
            if char == '\\' and in_string:
                escape_next = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == '{':
                if depth == 0:
                    json_start = i
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0 and json_start != -1:
                    candidate = text[json_start:i+1]
                    if '"title"' in candidate or '"content"' in candidate:
                        return candidate
        return None
    
    @staticmethod
    def _attempt_repair(json_str: str) -> Optional[str]:
        repaired = json_str.replace("'", '"')
        repaired = re.sub(r':\s*([^",\[\]{}\s][^,}]*?)\s*([}])', r': "\1"\2', repaired)
        repaired = re.sub(r',\s*}', '}', repaired)
        repaired = re.sub(r',\s*]', ']', repaired)
        return repaired


class TextCleaner:
    
    @staticmethod
    def clean_llm_output(text: str, max_double_newlines: int = 1) -> str:
        if not text:
            return ""
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        while '\n\n\n' in text:
            text = text.replace('\n\n\n', '\n\n')
        if max_double_newlines == 1:
            parts = text.split('\n\n', 1)
            text = parts[0].strip()
        text = re.sub(r' {2,}', ' ', text)
        return text.strip()
    
    @staticmethod
    def remove_disclaimers(text: str) -> str:
        patterns = [
            r'\n?\n?(Note|Disclaimer|Important|Remember):.*$',
            r'\n?\n?\(Note:.*?\)',
            r'\n?\n?\[.*?disclaimer.*?\]',
            r'\n?\n?---.*$',
            r'\n?\n?$$.*$$',
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
        return text.strip()


class ReplyPostprocessor:
    
    @staticmethod
    def process(reply_text: str, max_length: int = 650) -> str:
        clean = TextCleaner.clean_llm_output(reply_text, max_double_newlines=1)
        clean = TextCleaner.remove_disclaimers(clean)
        if len(clean) > max_length:
            clean = clean[:max_length]
            last_period = clean.rfind('.')
            if last_period > max_length * 0.8:
                clean = clean[:last_period + 1]
            else:
                clean = clean.rsplit(' ', 1)[0] + '...'
        return clean.lstrip()
