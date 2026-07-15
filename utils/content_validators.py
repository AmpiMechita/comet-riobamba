"""
Content Validators - v3.1.0
===========================
Validaciones estrictas antes de publicar.
"""

import re
import logging
from typing import Dict, Tuple, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    is_valid: bool
    reason: str
    severity: str  # error, warning, info
    cleaned_content: Optional[str] = None
    should_retry: bool = False


class ContentValidator:
    
    def __init__(self, content_config):
        self.cfg = content_config
        
    def validate_post(self, title: str, content: str) -> ValidationResult:
        length_result = self._validate_length(content, is_reply=False)
        if not length_result.is_valid and not length_result.cleaned_content:
            return length_result
        
        content = length_result.cleaned_content or content
        format_result = self._validate_format(content)
        if not format_result.is_valid and not format_result.cleaned_content:
            return format_result
            
        content = format_result.cleaned_content or content
        hook_result = self._validate_hook(content)
        forbidden_result = self._check_forbidden_patterns(content)
        density_result = self._check_technical_density(content)
        
        all_results = [length_result, format_result, hook_result, forbidden_result, density_result]
        errors = [r for r in all_results if r.severity == "error" and not r.is_valid]
        
        if errors:
            return ValidationResult(
                is_valid=False,
                reason=f"Errors: {'; '.join(e.reason for e in errors)}",
                severity="error",
                cleaned_content=content,
                should_retry=True
            )
        
        warnings = [r for r in all_results if r.severity == "warning"]
        if warnings:
            logger.warning(f"Post has warnings: {warnings}")
        
        return ValidationResult(is_valid=True, reason="OK", severity="info", cleaned_content=content)
    
    def validate_reply(self, reply_text: str) -> ValidationResult:
        length_result = self._validate_length(reply_text, is_reply=True)
        if not length_result.is_valid and not length_result.cleaned_content:
            return length_result
            
        reply_text = length_result.cleaned_content or reply_text
        opening_result = self._validate_reply_opening(reply_text)
        if not opening_result.is_valid:
            return opening_result
        
        format_result = self._validate_format(reply_text)
        reply_text = format_result.cleaned_content or reply_text
        
        return ValidationResult(is_valid=True, reason="Reply valid", severity="info", cleaned_content=reply_text)
    
    def _validate_length(self, text: str, is_reply: bool = False) -> ValidationResult:
        if is_reply:
            min_len = self.cfg.reply_length_min
            max_len = self.cfg.reply_length_max
            target = "reply"
        else:
            min_len = self.cfg.post_length_min
            max_len = self.cfg.post_length_hard_max
            target = "post"
        
        current_len = len(text)
        
        if current_len < min_len:
            return ValidationResult(is_valid=False, reason=f"{target} too short ({current_len}/{min_len})", 
                               severity="error", should_retry=True)
        
        if current_len > max_len:
            truncated = self._smart_truncate(text, max_len)
            return ValidationResult(is_valid=True, reason=f"Truncated from {current_len} to {len(truncated)}",
                                   severity="warning", cleaned_content=truncated)
        
        return ValidationResult(is_valid=True, reason="Length OK", severity="info")
    
    def _smart_truncate(self, text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        search_area = text[:max_len]
        last_period = search_area.rfind('.')
        if last_period > max_len * 0.8:
            return text[:last_period + 1]
        last_space = search_area.rfind(' ')
        if last_space > max_len * 0.8:
            return text[:last_space] + "..."
        return text[:max_len-3] + "..."
    
    def _validate_format(self, text: str) -> ValidationResult:
        original = text
        modified = text
        warnings = []
        
        if '```' in modified:
            modified = re.sub(r'```[\w]*\n?', '', modified)
            modified = modified.replace('```', '')
            warnings.append("Removed code fences")
        
        special_tokens = ['<|im_start|>', '<|im_end|>', '<|eot_id|>', '[INST]', '[/INST]']
        for token in special_tokens:
            if token in modified:
                modified = modified.replace(token, '')
                warnings.append(f"Removed special token: {token}")
        
        if re.search(r'^\d+[\.\)]\s', modified, re.MULTILINE):
            modified = self._convert_list_to_prose(modified)
            warnings.append("Converted numbered list to prose")
        
        if re.search(r'^[\-\*]\s', modified, re.MULTILINE):
            modified = self._convert_list_to_prose(modified)
            warnings.append("Converted bullet points to prose")
        
        modified = re.sub(r'^#+\s+', '', modified, flags=re.MULTILINE)
        modified = re.sub(r'\n{3,}', '\n\n', modified)
        modified = modified.strip()
        
        if warnings:
            return ValidationResult(is_valid=True, reason=f"Format fixed: {'; '.join(warnings)}",
                                   severity="warning", cleaned_content=modified)
        return ValidationResult(is_valid=True, reason="Format OK", severity="info")
    
    def _convert_list_to_prose(self, text: str) -> str:
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        clean_lines = [re.sub(r'^[\d\.\-\)\*\#]+\s*', '', line).strip() for line in lines]
        
        if len(clean_lines) <= 1:
            return clean_lines[0] if clean_lines else text
        
        connectors = ["First,", "Then,", "Moreover,", "Additionally,", 
                      "Furthermore,", "However,", "In contrast,", "Finally,"]
        
        prose_parts = []
        for i, line in enumerate(clean_lines):
            if i == 0:
                prose_parts.append(line)
            elif i < len(connectors):
                if line:
                    modified_line = f"{connectors[i-1]} {line[0].lower()}{line[1:]}"
                    prose_parts.append(modified_line)
                else:
                    prose_parts.append(connectors[i-1])
            else:
                prose_parts.append(line)
        
        return " ".join(prose_parts)
    
    def _validate_hook(self, content: str) -> ValidationResult:
        first_chars = content[:self.cfg.hook_length_chars].strip().lower()
        boring_patterns = [r'^in this post', r"^let's talk about", r'^here is',
                           r'^i want to discuss', r'^in this article', r"^we are going to"]
        for pattern in boring_patterns:
            if re.match(pattern, first_chars):
                return ValidationResult(is_valid=True, reason="Weak hook detected", severity="warning")
        return ValidationResult(is_valid=True, reason="Hook OK", severity="info")
    
    def _validate_reply_opening(self, reply: str) -> ValidationResult:
        first_60 = reply[:60].lower().strip()
        for forbidden in self.cfg.forbidden_openings:
            if first_60.startswith(forbidden.lower()):
                return ValidationResult(is_valid=False, reason=f"Forbidden opening: '{forbidden}'",
                                       severity="error", should_retry=True)
        return ValidationResult(is_valid=True, reason="Opening OK", severity="info")
    
    def _check_forbidden_patterns(self, content: str) -> ValidationResult:
        if '#' in content and self.cfg.formatting_rules.get("no_hashtags"):
            if re.search(r'#\w+', content):
                return ValidationResult(is_valid=True, reason="Contains potential hashtag",
                                      severity="warning", cleaned_content=re.sub(r'#(\w+)', r'\1', content))
        return ValidationResult(is_valid=True, reason="No forbidden patterns", severity="info")
    
    def _check_technical_density(self, content: str) -> ValidationResult:
        tech_terms = ["architecture", "trade-off", "memory", "latency", "throughput",
                      "failure", "bottleneck", "orchestration", "routing", "fallback",
                      "agent", "llm", "model", "context", "prompt", "token", "inference",
                      "api", "endpoint", "rate.limit", "queue", "database", "cache"]
        term_count = sum(1 for term in tech_terms if term.lower() in content.lower())
        if len(content) > 400 and term_count < 2:
            return ValidationResult(is_valid=True, reason=f"Low technical density ({term_count} terms)",
                                      severity="warning")
        return ValidationResult(is_valid=True, reason=f"Technical density OK ({term_count} terms)", severity="info")


def validate_content(title: str, content: str, is_reply: bool = False, cfg=None) -> ValidationResult:
    if cfg is None:
        from config import content_cfg as default_cfg
        cfg = default_cfg
    validator = ContentValidator(cfg)
    if is_reply:
        return validator.validate_reply(content)
    return validator.validate_post(title, content)

