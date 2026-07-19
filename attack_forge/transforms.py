"""Transform tools: deterministic `str -> str` functions the strategist can apply to a
fragment of a payload.

These are the reusable, attack-agnostic core. Each transform is a pure function (trivially
unit-testable) registered by name in `TRANSFORMS`. The executor invokes them by name as pipeline
steps (see `executor.py`); they share one registry/contract with the LLM-backed tools in
`llm_tools.py` and `framing_tools.py`. Growing the toolbox = one entry in `TRANSFORMS`.
"""

from __future__ import annotations

import base64
import codecs
from dataclasses import dataclass
from typing import Callable

_LEET = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7",
                       "A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7"})

_MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.",
    "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.",
    "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.", "S": "...", "T": "-", "U": "..-",
    "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}


def _base64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _hex(text: str) -> str:
    return text.encode("utf-8").hex()


def _rot13(text: str) -> str:
    return codecs.encode(text, "rot_13")


def _reverse(text: str) -> str:
    return text[::-1]


def _spaced(text: str) -> str:
    return " ".join(text)


def _zero_width(text: str) -> str:
    return "​".join(text)


def _leet(text: str) -> str:
    return text.translate(_LEET)


def _morse(text: str) -> str:
    return " ".join(_MORSE.get(ch.upper(), ch) for ch in text)


def _literal(text: str) -> str:
    return text


@dataclass(frozen=True)
class Transform:
    name: str
    description: str
    fn: Callable[[str], str]

    def __call__(self, text: str) -> str:
        return self.fn(text)


_ALL: list[Transform] = [
    Transform("literal", "Pass the text through unchanged — for a fragment that needs no obfuscation.", _literal),
    Transform("base64", "Base64-encode the fragment.", _base64),
    Transform("hex", "Hex-encode the UTF-8 bytes of the fragment.", _hex),
    Transform("rot13", "ROT13 the letters of the fragment.", _rot13),
    Transform("reverse", "Reverse the fragment.", _reverse),
    Transform("spaced", "Insert a space between every character.", _spaced),
    Transform("zero_width", "Insert a zero-width space between characters (defeats string matching).", _zero_width),
    Transform("leet", "Leetspeak substitution (a→4, e→3, ...).", _leet),
    Transform("morse", "Encode letters/digits as Morse code.", _morse),
]

TRANSFORMS: dict[str, Transform] = {t.name: t for t in _ALL}


def apply_transform(name: str, text: str) -> str:
    return TRANSFORMS[name](text)


def transform_names() -> list[str]:
    return list(TRANSFORMS)


def render_menu() -> str:
    """One line per transform — for the strategist prompt (later steps)."""
    return "\n".join(f"  - {t.name}: {t.description}" for t in _ALL)
