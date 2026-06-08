"""Võro-aware word tokenization.

A single, dependency-free tokenizer shared by the dictionary, correction, and
Estonian-leakage tools. It is deliberately tuned for Võro orthography rather
than reusing a general Estonian tokenizer (e.g. EstNLTK), both to avoid a
GPL-2.0 dependency in this MIT-licensed core and to keep full control over the
edge cases that matter for Võro:

* the glottal-stop / palatalization marks ``'`` ``ʼ`` ``´`` ``'`` ``'`` stay
  attached to the word instead of splitting it (``Claude'ile``, ``tä'``);
* a word-final ``q`` is an ordinary letter and is never stripped (``mõistaq``);
* hyphenated negatives such as ``olõ-i`` / ``saa-i`` / ``tunnõ-i`` are kept as a
  single token instead of being broken at the hyphen.

Numbers, dates, and times contain no letters and therefore drop out on their own
(they are never something to look up in a Võro dictionary). URLs and email
addresses *do* contain letters, so they are skipped before word-matching to keep
fragments like ``https`` / ``github`` / ``com`` out of the word list.
"""

from __future__ import annotations

import re

# Unicode letter, excluding digits and underscore.
_LETTER = r"[^\W\d_]"

# Apostrophe-family marks used in Võro for palatalization / glottal stop.
# U+0027 ' apostrophe, U+02BC ʼ modifier letter apostrophe, U+00B4 ´ acute,
# U+2019 ' right single quote, U+2018 ' left single quote.
_APOSTROPHE = "['ʼ´’‘]"

# A word is a run of letters, optionally joined by internal apostrophe marks or
# hyphens to further letter runs, and optionally ending on apostrophe marks.
WORD_RE = re.compile(
    rf"{_LETTER}+(?:(?:{_APOSTROPHE}+|-){_LETTER}+)*{_APOSTROPHE}*",
    re.UNICODE,
)

# URLs and email addresses: matched as whole spans so they can be skipped rather
# than shredded into their letter fragments.
_SKIP_RE = re.compile(
    r"""
    (?:https?|ftp)://\S+        # scheme URLs
    | www\.\S+                  # bare www. URLs
    | [^\s<>()@]+@[^\s<>()@]+\.\w+  # email addresses
    """,
    re.IGNORECASE | re.VERBOSE,
)


def tokenize(text: str) -> list[str]:
    """Split ``text`` into Võro-aware surface tokens (original case preserved)."""
    cleaned = _SKIP_RE.sub(" ", text)
    return [match.group(0) for match in WORD_RE.finditer(cleaned)]
