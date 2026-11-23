"""Prompt-injection screening for untrusted invoice text."""
import re

INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|rules?|prompts?)",
    r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier|your)",
    r"(?:system|developer)\s*(?:prompt|message|override|instruction)",
    r"you\s+are\s+(?:now\s+)?(?:an?\s+)?(?:ai|assistant|language model|llm)",
    r"(?:mark|set|treat|flag)\s+(?:this\s+)?invoice\s+(?:as\s+)?(?:approved|paid|valid|verified)",
    r"(?:auto[- ]?)?approve\s+(?:this\s+)?(?:invoice|payment|immediately)",
    r"do\s+not\s+(?:flag|review|escalate|check|verify)",
    r"skip\s+(?:all\s+)?(?:validation|checks|review)",
    r"override\s+(?:the\s+)?(?:decision|rules?|controls?)",
]
_COMPILED = [re.compile(p, re.I) for p in INJECTION_PATTERNS]


def find_injection(text: str) -> list[str]:
    """Return snippets of text that look like instructions aimed at an AI system."""
    hits: list[str] = []
    for rx in _COMPILED:
        for m in rx.finditer(text):
            start = max(0, m.start() - 30)
            hits.append(text[start : m.end() + 60].replace("\n", " ").strip())
    return hits[:5]


def sanitize_for_prompt(text: str, limit: int = 60000) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    return text[:limit]
