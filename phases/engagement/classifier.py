import re
import unicodedata
from typing import Set

CLASSIFICATION_RULES = {
    "question": {
        "prefixes": ("que ", "como ", "cómo ", "por que", "por qué"),
    },
    "critique": {
        "keywords": ("no estoy de acuerdo", "discrepo", "incorrecto", "falla", "problema", "error"),
    },
    "evidence": {
        "keywords": ("evidencia", "paper", "estudio", "datos", "métrica", "experimento"),
    },
    "cross_reference": {
        "keywords": ("como dije", "en otro post", "en otro comentario", "@", "mencionaste", "citaste"),
    },
}

BASE_SCORES = {
    "question": 90,
    "critique": 85,
    "evidence": 80,
    "cross_reference": 75,
    "discussion": 65,
    "short_reaction": 35,
    "empty": 0,
}

ENGLISH_TOKENS = {
    "the", "and", "is", "are", "what", "how", "why", "should", "would", "could", "can",
    "if", "when", "while", "about", "for", "with", "this", "that", "your", "you", "we",
    "they", "it", "to", "of", "in", "on", "as", "by", "or", "but", "not", "do", "does",
    "did", "more", "most", "better", "maybe", "think", "approach", "evidence", "process",
}

SPANISH_TOKENS = {
    "el", "la", "los", "las", "de", "del", "que", "como", "para", "con", "por", "una", "uno",
    "pero", "sobre", "crees", "podria", "seria", "cuando", "donde", "porque", "tambien",
    "me", "parece", "respuesta", "pregunta", "proceso", "evidencia", "metodo", "datos",
    "esto", "esta", "este", "hay", "fue", "son", "mas", "menos", "muy", "si", "no", "ya",
}


class Classifier:

    @staticmethod
    def classify_comment(text: str) -> str:
        text_lower = (text or "").lower()
        if not text_lower.strip():
            return "empty"
        if "?" in text_lower or text_lower.startswith(CLASSIFICATION_RULES["question"]["prefixes"]):
            return "question"
        if any(x in text_lower for x in CLASSIFICATION_RULES["critique"]["keywords"]):
            return "critique"
        if any(x in text_lower for x in CLASSIFICATION_RULES["evidence"]["keywords"]):
            return "evidence"
        if any(x in text_lower for x in CLASSIFICATION_RULES["cross_reference"]["keywords"]):
            return "cross_reference"
        if len(text_lower) < 25:
            return "short_reaction"
        return "discussion"

    @staticmethod
    def priority_score(comment_type: str, text: str) -> int:
        score = BASE_SCORES.get(comment_type, 50)
        text_lower = (text or "").lower()
        boost_keywords = ["experimento", "hipótesis", "proceso", "metodología", "metrica", "métrica"]
        if any(x in text_lower for x in boost_keywords):
            score += 10
        if len(text_lower) > 280:
            score += 5
        return min(score, 100)

    @staticmethod
    def is_direct_question_to_me(text: str, own_names: Set[str]) -> bool:
        t = (text or "").strip().lower()
        if not t or "?" not in t:
            return False
        identity_names = {
            "comet_riobamba",
            "comet riobamba",
            "@comet_riobamba",
            "comet-riobamba",
            "cometriobamba",
        }
        for name in identity_names | own_names:
            if name and name in t:
                return True
        return False

    @staticmethod
    def should_reply(comment_type: str, priority_score: int, text: str, own_names: Set[str]) -> bool:
        text_lower = (text or "").lower()
        if priority_score >= 90:
            return True
        if comment_type in {"empty", "short_reaction"}:
            return False
        if len((text or "").strip()) < 8:
            return False
        if "cometriobamba" in text_lower or "comet_riobamba" in text_lower or "comet riobamba" in text_lower:
            return True
        if comment_type == "question" and priority_score >= 70:
            return True
        if comment_type == "cross_reference" and priority_score >= 75:
            return True
        if Classifier.is_direct_question_to_me(text, own_names):
            return True
        return False

    @staticmethod
    def looks_mostly_english(text: str) -> bool:
        t = (text or "").strip()
        if not t:
            return False
        normalized = unicodedata.normalize("NFKD", t)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        lowered = normalized.lower()
        tokens = re.findall(r"[a-z]+", lowered)
        if not tokens:
            return False
        english_score = sum(1 for token in tokens if token in ENGLISH_TOKENS)
        spanish_score = sum(1 for token in tokens if token in SPANISH_TOKENS)
        ascii_chars = sum(1 for ch in t if ord(ch) < 128)
        ascii_ratio = ascii_chars / max(len(t), 1)
        if english_score >= 2 and english_score > spanish_score:
            return True
        if english_score >= 1 and spanish_score == 0 and ascii_ratio >= 0.95:
            return True
        return False
