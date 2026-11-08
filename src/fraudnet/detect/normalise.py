"""Turn raw contact and text values into comparable keys (entity resolution, ARCHITECTURE.md P1).

These rules are the detector's own. It does not reuse generator code, so a generator quirk can't
leak into detection through a shared helper.
"""
from __future__ import annotations

import math
import re
from collections import Counter

# Standard street-suffix abbreviations, wider than any one data source uses.
STREET_SUFFIXES = {
    "st": "street", "str": "street", "ave": "avenue", "av": "avenue", "rd": "road", "ln": "lane",
    "dr": "drive", "ct": "court", "blvd": "boulevard", "pl": "place", "ter": "terrace", "cir": "circle",
    "pkwy": "parkway", "hwy": "highway", "sq": "square",
}
_WORD = re.compile(r"[a-z0-9]+")
_CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
_LETTERS = re.compile(r"[a-z]+")


def address_key(line: str, city: str, postal_code: str) -> str:
    """`12 Oak St`, `12 OAK STREET` and `12 Oak Street.` in one city and postal code give one key."""
    words = _WORD.findall(line.lower())
    if words:
        words[-1] = STREET_SUFFIXES.get(words[-1], words[-1])
    return f"{' '.join(words)}|{' '.join(city.lower().split())}|{postal_code.strip()}"


def phone_key(value: str) -> str:
    return re.sub(r"\D", "", value)


def email_key(value: str) -> str:
    return value.strip().lower()


def bank_key(value: str) -> str:
    return value.strip().upper()


IDENTITY_KEYS = {"phone": phone_key, "email": email_key, "bank_token": bank_key}


def surname(full_name: str) -> str:
    return full_name.split()[-1].lower()


def narrative_words(text: str) -> frozenset[str]:
    """Words of a narrative with clock times removed, since the time is the part that changes between copies."""
    return frozenset(_LETTERS.findall(_CLOCK.sub(" ", text.lower())))


class NarrativeSimilarity:
    """IDF-weighted Jaccard similarity over word sets.

    Words used in many narratives, such as common phrasing, count for little; rare words such as a
    street name or a specific detail count for a lot. Plain word overlap scores unrelated template
    text at 0.8-0.9 (ARCHITECTURE.md section 8), so it can't separate copies from coincidence.
    """

    def __init__(self, narratives) -> None:
        sets = [narrative_words(text) for text in narratives]
        counts = Counter(word for words in sets for word in words)
        total = max(len(sets), 1)
        self.idf = {word: math.log(total / count) for word, count in counts.items()}
        self._fallback = math.log(total) if total > 1 else 1.0  # unseen word: as rare as a word seen once

    def weight(self, words: frozenset[str]) -> float:
        return sum(self.idf.get(word, self._fallback) for word in words)

    def similarity(self, a: frozenset[str], b: frozenset[str]) -> float:
        union = self.weight(a | b)
        return self.weight(a & b) / union if union else 0.0
