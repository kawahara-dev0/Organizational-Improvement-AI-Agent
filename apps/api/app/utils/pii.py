"""PII (Personally Identifiable Information) masking utilities.

These patterns are applied to chat content *before* it is sent to the
external LLM API.  The original text is preserved in the database; only
the copy sent to the AI provider is masked.

Covered patterns
----------------
- Email addresses          →  [EMAIL]
- Japanese mobile numbers  →  [PHONE]  (070/080/090-XXXX-XXXX)
- General JP landlines     →  [PHONE]  (0X-XXXX-XXXX, 0XX-XXX-XXXX …)
- International numbers    →  [PHONE]  (+XX-…)

Intentionally NOT masked
------------------------
- Personal names  — unreliable without NLP; risk of false positives on
                    Japanese common nouns is too high.
- Postal codes, addresses — too broad; would mask meaningful context.
"""

from __future__ import annotations

import re

_RULES: list[tuple[re.Pattern[str], str]] = [
    # Email addresses (RFC-5321 local part + domain)
    (
        re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.]+", re.ASCII),
        "[EMAIL]",
    ),
    # Japanese mobile: 070/080/090-NNNN-NNNN (with dash or en-dash)
    (
        re.compile(r"0[789]0[-\u2013]\d{4}[-\u2013]\d{4}"),
        "[PHONE]",
    ),
    # General Japanese landline / free-dial: 0X(X)(X)-NNN(N)-NNN(N)
    # Covers:  03-XXXX-XXXX, 0120-XXX-XXXX, 0120-XXX-XXX, etc.
    (
        re.compile(r"0\d{1,4}[-\u2013]\d{2,4}[-\u2013]\d{3,4}"),
        "[PHONE]",
    ),
    # International format: +CC[-. ]N{1,4}[-. ]NNNN[-. ]NNNN  (e.g. +81-3-1234-5678)
    (
        re.compile(r"\+\d{1,3}[\-.\s]\d{1,4}[\-.\s]\d{3,4}[\-.\s]\d{4}"),
        "[PHONE]",
    ),
]


def mask_pii(text: str) -> str:
    """Return *text* with PII patterns replaced by placeholder tokens."""
    for pattern, replacement in _RULES:
        text = pattern.sub(replacement, text)
    return text
