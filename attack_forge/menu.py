"""The strategist's menu: everything it may choose from, rendered as one prompt block.

Combines the three technique kinds — structures, transforms, framings — into a single text the
strategist reads when it plans a vector.
"""

from __future__ import annotations

from .framings import DEFAULT_LIBRARY, FramingLibrary
from .transforms import render_menu as _render_transforms

_STRUCTURES = (
    "STRUCTURES (how to arrange the vector):\n"
    "  - single: one technique in one message\n"
    "  - stack: several techniques folded into one message\n"
    "  - chain: a sequence of turns (crescendo, many-shot, fake history)"
)


def render_menu(library: FramingLibrary = DEFAULT_LIBRARY) -> str:
    return "\n\n".join([
        _STRUCTURES,
        "TRANSFORMS (apply to a fragment via [[t:name]]...[[/t]], may nest):\n" + _render_transforms(),
        "FRAMINGS (reuse an example or write your own variation in the same spirit):\n" + library.render_menu(),
    ])
