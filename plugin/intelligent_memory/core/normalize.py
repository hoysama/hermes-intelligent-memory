from __future__ import annotations

import re
import unicodedata

# These aliases keep search useful for Arabic/English technical conversations
# without requiring an embedding model. The mapping is intentionally small and
# transparent; cloud intelligence may add fact-specific aliases later.
_TOKEN_ALIASES = {
    "جافاسكربت": "javascript",
    "جافااسكربت": "javascript",
    "حزم": "packages",
    "الحزم": "packages",
    "مكتبات": "libraries",
    "المكتبات": "libraries",
    "اعتماديات": "dependencies",
    "الاعتماديات": "dependencies",
    "تثبيت": "install",
    "يثبت": "install",
    "مدير": "manager",
    "المدير": "manager",
    "يفضل": "prefer",
    "يفضّل": "prefer",
    "يستخدم": "use",
    "يعتمد": "use",
    "التقنية": "technology",
}

_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_text(value: str) -> str:
    """Normalize Arabic and mixed technical text without changing its language."""
    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFKC", value)
    text = text.replace("ـ", "")
    text = _DIACRITICS.sub("", text)
    translation_table: dict[int, str | int | None] = {
        ord("أ"): "ا",
        ord("إ"): "ا",
        ord("آ"): "ا",
        ord("ى"): "ي",
        ord("ة"): "ه",
    }
    text = text.translate(translation_table)
    text = text.casefold()
    text = _NON_WORD.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def tokens(value: str) -> set[str]:
    """Return canonical tokens plus transparent bilingual query aliases."""
    result: set[str] = set()
    for token in normalize_text(value).split():
        result.add(token)
        alias = _TOKEN_ALIASES.get(token)
        if alias:
            result.add(alias)
    return result


def character_ngrams(value: str, size: int = 3) -> set[str]:
    normalized = normalize_text(value).replace(" ", "")
    if len(normalized) < size:
        return {normalized} if normalized else set()
    return {normalized[index : index + size] for index in range(len(normalized) - size + 1)}


def jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
