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
import random
from dataclasses import dataclass
from typing import Callable

_LEET = str.maketrans({"a": "4", "e": "3", "i": "1", "o": "0", "s": "5", "t": "7",
                       "A": "4", "E": "3", "I": "1", "O": "0", "S": "5", "T": "7"})

# Latin -> visually identical Cyrillic/Greek confusables. The rendered glyph is (near-)identical,
# so the model reads the word normally while a byte-level keyword filter sees different codepoints.
_HOMOGLYPH = str.maketrans({
    "a": "а", "c": "с", "e": "е", "i": "і", "j": "ј", "o": "о", "p": "р", "s": "ѕ", "x": "х", "y": "у",
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "I": "І", "J": "Ј", "K": "К", "M": "М",
    "O": "О", "P": "Р", "S": "Ѕ", "T": "Т", "X": "Х", "Y": "У",
})

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


def _homoglyph(text: str) -> str:
    return text.translate(_HOMOGLYPH)


def _morse(text: str) -> str:
    return " ".join(_MORSE.get(ch.upper(), ch) for ch in text)


def _literal(text: str) -> str:
    return text


def _ascii(text: str) -> str:
    return " ".join(str(ord(ch)) for ch in text)


# --- stochastic perturbations: DIFFERENT output every call ------------------------------------
# These deliberately break the "deterministic str->str" contract of the transforms above — that is
# the point. Best-of-N jailbreaking works by firing MANY random surface-variants of one request and
# keeping whichever slips past a content/keyword filter; the per-call variance is the search itself.
# So these belong in a large batch (see bon.py), never as a single shot. Probabilities are hardcoded
# for now (tune later on real ASR curves).

def _random_caps(text: str) -> str:
    return "".join(ch.upper() if ch.isalpha() and random.random() < 0.5 else ch for ch in text)


def _char_typo(text: str) -> str:
    chars = list(text)
    for _ in range(random.randint(1, 2)):
        if len(chars) < 2:
            break
        i = random.randrange(len(chars) - 1)
        op = random.choice(("swap", "dup", "drop"))
        if op == "swap":
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
        elif op == "dup":
            chars.insert(i, chars[i])
        else:
            del chars[i]
    return "".join(chars)


def _random_space(text: str) -> str:
    out: list[str] = []
    for ch in text:
        out.append(ch)
        if ch != " " and random.random() < 0.15:
            out.append(" ")
    return "".join(out)


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
    Transform("ascii", "Encode as space-separated decimal ASCII codes (slips past keyword filters).", _ascii),
    Transform("hex", "Hex-encode the UTF-8 bytes of the fragment.", _hex),
    Transform("rot13", "ROT13 the letters of the fragment.", _rot13),
    Transform("morse", "Encode letters/digits as Morse code.", _morse),
    Transform("reverse", "Reverse the fragment.", _reverse),
    Transform("spaced", "Insert a space between every character.", _spaced),
    Transform("zero_width", "Insert a zero-width space between characters (defeats string matching).", _zero_width),
    Transform("leet", "Leetspeak substitution (a→4, e→3, ...).", _leet),
    Transform("homoglyph", "Swap Latin letters for visually identical Unicode confusables (Cyrillic/Greek): reads normally to the model but defeats byte-level keyword matching. Unlike a cipher it is NOT decode-and-refuse.", _homoglyph),
    Transform("random_caps", "Randomly upper-case ~half the letters (pies -> pIEs). STOCHASTIC — varies per call; only useful in a large batch.", _random_caps),
    Transform("char_typo", "Introduce 1-2 random typos (swap/duplicate/drop a character). STOCHASTIC — varies per call; only useful in a large batch.", _char_typo),
    Transform("random_space", "Sprinkle spaces at random positions. STOCHASTIC — varies per call; only useful in a large batch.", _random_space),
]

TRANSFORMS: dict[str, Transform] = {t.name: t for t in _ALL}


def apply_transform(name: str, text: str) -> str:
    return TRANSFORMS[name](text)


def transform_names() -> list[str]:
    return list(TRANSFORMS)


def render_menu() -> str:
    """One line per transform — for the strategist's flat menu (grouping is the taxonomy's job)."""
    return "\n".join(f"  - {t.name}: {t.description}" for t in _ALL)
