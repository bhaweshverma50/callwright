"""Outline type for the wordmarks: glyphs from Unbounded and Geist, set and then hand-tuned.

The fonts are the variable woff2 files the app already ships (@fontsource-variable). Glyph outlines
are converted to SVG paths so the lockups need no web font; individual letters are replaced by the
custom constructions in `wordmarks.py`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

FONT_FILES = {
    "unbounded": "unbounded/files/unbounded-latin-wght-normal.woff2",
    "geist": "geist/files/geist-latin-wght-normal.woff2",
}


def fonts_dir() -> str:
    env = os.environ.get("CW_FONTS")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", "node_modules", "@fontsource-variable"))


@lru_cache(maxsize=None)
def font(family: str, wght: int) -> TTFont:
    f = TTFont(os.path.join(fonts_dir(), FONT_FILES[family]))
    return instancer.instantiateVariableFont(f, {"wght": wght})


@dataclass
class Face:
    family: str
    wght: int
    size: float  # px per em

    @property
    def tt(self) -> TTFont:
        return font(self.family, self.wght)

    @property
    def scale(self) -> float:
        return self.size / self.tt["head"].unitsPerEm

    def metric(self, name: str) -> float:
        os2 = self.tt["OS/2"]
        return {"cap": os2.sCapHeight, "x": os2.sxHeight}[name] * self.scale

    def glyph(self, ch: str, x: float, baseline: float) -> tuple[str, float]:
        gs = self.tt.getGlyphSet()
        name = self.tt.getBestCmap()[ord(ch)]
        pen = SVGPathPen(gs)
        s = self.scale
        gs[name].draw(TransformPen(pen, (s, 0, 0, -s, x, baseline)))
        return pen.getCommands(), gs[name].width * s

    def bounds(self, ch: str) -> tuple[float, float, float, float]:
        """Glyph ink box in px, y up from the baseline: xmin, ymin, xmax, ymax."""
        gs = self.tt.getGlyphSet()
        name = self.tt.getBestCmap()[ord(ch)]
        bp = BoundsPen(gs)
        gs[name].draw(bp)
        return tuple(v * self.scale for v in bp.bounds)  # type: ignore[return-value]

    def stem(self) -> float:
        """Vertical stem width, measured from I (Geist's l has a tail)."""
        x0, _, x1, _ = self.bounds("I")
        return x1 - x0


@dataclass
class Setting:
    """A set line of type: plain glyph paths plus custom SVG fragments, all in one coordinate box."""

    paths: list[str] = field(default_factory=list)  # filled path data (font glyphs)
    extras: list[str] = field(default_factory=list)  # SVG elements using fill/stroke="{ink}"
    defs: list[str] = field(default_factory=list)
    width: float = 0.0


def set_line(face: Face, text: str, tracking: float, baseline: float, custom=None, kern=None) -> Setting:
    """Set `text`; `custom[i]` may replace glyph i with fn(face, x, baseline) -> (svg, advance, defs).
    `kern[i]` adds px after glyph i. Tracking is in em."""
    out = Setting()
    x = 0.0
    custom = custom or {}
    kern = kern or {}
    for i, ch in enumerate(text):
        if i in custom:
            svg, adv, defs = custom[i](face, x, baseline)
            out.extras.append(svg)
            out.defs.extend(defs)
        else:
            d, adv = face.glyph(ch, x, baseline)
            out.paths.append(d)
        x += adv + tracking * face.size + kern.get(i, 0.0)
    out.width = x - tracking * face.size
    return out
