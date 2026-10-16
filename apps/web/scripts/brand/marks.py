"""Callwright logo concepts: hand-built symbol geometry on a 48 unit grid.

Every symbol is constructed from circles, arcs and polylines here; no font outlines are used for a
symbol. Each concept exposes `mark(mode, uid)` returning SVG markup for viewBox 0 0 48 48, where
mode is one of:

  light  full colour, for paper and white surfaces
  dark   full colour, for ink surfaces
  mono   one colour (currentColor)
  tile   the app icon / favicon: the mark on its own ink tile
"""

from __future__ import annotations

import math

INK = "#171A3D"
INK_DEEP = "#0E1030"
PAPER = "#F4F5FA"
COBALT = "#3346E8"
VIOLET = "#7A3CFF"
PINK = "#E0457B"
AMBER = "#FFB347"
# Lifted brand hues for ink surfaces (cobalt and violet are too dark to read on ink).
COBALT_LIFT = "#6E7DFF"
VIOLET_LIFT = "#A47BFF"


def f(v: float) -> str:
    s = f"{v:.3f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def pt(cx: float, cy: float, r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def annulus(cx: float, cy: float, ro: float, ri: float, a0: float, a1: float) -> str:
    """Ring segment from a0 to a1 (degrees, SVG convention: 0 is +x, angles grow clockwise)."""
    span = (a1 - a0) % 360
    large = 1 if span > 180 else 0
    x0, y0 = pt(cx, cy, ro, a0)
    x1, y1 = pt(cx, cy, ro, a1)
    x2, y2 = pt(cx, cy, ri, a1)
    x3, y3 = pt(cx, cy, ri, a0)
    return (
        f"M{f(x0)} {f(y0)}A{f(ro)} {f(ro)} 0 {large} 1 {f(x1)} {f(y1)}"
        f"L{f(x2)} {f(y2)}A{f(ri)} {f(ri)} 0 {large} 0 {f(x3)} {f(y3)}Z"
    )


def grad(uid: str, stops: list[tuple[float, str]], x1=0, y1=0, x2=48, y2=48) -> str:
    s = "".join(f'<stop offset="{f(o)}" stop-color="{c}"/>' for o, c in stops)
    return (
        f'<linearGradient id="{uid}" gradientUnits="userSpaceOnUse" x1="{f(x1)}" y1="{f(y1)}" '
        f'x2="{f(x2)}" y2="{f(y2)}">{s}</linearGradient>'
    )


def tile(inner: str, fill: str = INK, r: float = 11) -> str:
    return f'<rect width="48" height="48" rx="{f(r)}" fill="{fill}"/>{inner}'


def scaled(inner: str, k: float) -> str:
    """Scale content about the centre of the 48 grid (used to inset a mark inside its tile)."""
    o = 24 * (1 - k)
    return f'<g transform="translate({f(o)} {f(o)}) scale({f(k)})">{inner}</g>'


# ---------------------------------------------------------------------------------------------
# A. Handoff: a C cut at its waist; the lower half steps forward. Two voices, one turn passed on.


class Handoff:
    key = "handoff"
    name = "Handoff"
    # Geometry: ring centre, radii, mouth half-angle, step and waist gap.
    CX, CY, RO, RI, MOUTH, STEP, GAP = 24, 24, 19, 10.2, 40, 7, 3.2

    def pieces(self) -> tuple[str, str]:
        cx, cy, ro, ri, m, s, g = self.CX, self.CY, self.RO, self.RI, self.MOUTH, self.STEP, self.GAP
        upper = annulus(cx - s / 2, cy - g / 2, ro, ri, 180, 360 - m)
        lower = annulus(cx + s / 2, cy + g / 2, ro, ri, m, 180)
        return upper, lower

    def mark(self, mode: str, uid: str) -> str:
        up, lo = self.pieces()
        if mode == "mono":
            return f'<path class="lg-a" d="{up}" fill="currentColor"/><path class="lg-b" d="{lo}" fill="currentColor"/>'
        if mode == "light":
            top, bot = INK, f"url(#{uid}g)"
            defs = grad(f"{uid}g", [(0, COBALT), (1, VIOLET)], 4, 30, 44, 44)
        elif mode == "dark":
            top, bot = PAPER, f"url(#{uid}g)"
            defs = grad(f"{uid}g", [(0, COBALT_LIFT), (1, VIOLET_LIFT)], 4, 30, 44, 44)
        else:  # tile
            top, bot = PAPER, f"url(#{uid}g)"
            defs = grad(f"{uid}g", [(0, COBALT_LIFT), (1, VIOLET_LIFT)], 4, 30, 44, 44)
        body = f'<defs>{defs}</defs><path class="lg-a" d="{up}" fill="{top}"/><path class="lg-b" d="{lo}" fill="{bot}"/>'
        return tile(scaled(body, 0.74)) if mode == "tile" else body


# ---------------------------------------------------------------------------------------------
# B. Dovetail: two blocks locked by a dovetail joint. Tails and pins alternate like turns, and the
# seam is a trapezoid wave: a carpenter's joint that is also a signal.


class Dovetail:
    key = "dovetail"
    name = "Dovetail"
    R = 7  # block corner radius
    SEAM = [  # seam from left to right edge; tails hang from the upper block and flare downward
        (0, 19), (10, 19), (6.2, 30), (20.8, 30), (17, 19),
        (31, 19), (27.2, 30), (41.8, 30), (38, 19), (48, 19),
    ]
    CUT = 3.0  # seam width

    def seam_d(self) -> str:
        return "M" + "L".join(f"{f(x)} {f(y)}" for x, y in self.SEAM)

    def above(self) -> str:
        return "M0 0L48 0L48 19" + "".join(f"L{f(x)} {f(y)}" for x, y in reversed(self.SEAM)) + "Z"

    def mark(self, mode: str, uid: str) -> str:
        if mode == "tile":
            # The blocks are already a tile: full bleed, ink above, gradient below.
            box = '<rect width="48" height="48" rx="10"/>'
        else:
            box = f'<rect x="2" y="2" width="44" height="44" rx="{self.R}"/>'
        mask = (
            f'<mask id="{uid}m" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">'
            f'<rect width="48" height="48" fill="#fff"/>'
            f'<path d="{self.seam_d()}" fill="none" stroke="#000" stroke-width="{self.CUT}" '
            f'stroke-linejoin="miter" stroke-miterlimit="8"/></mask>'
            f'<clipPath id="{uid}c">{box}</clipPath>'
            f'<clipPath id="{uid}a"><path d="{self.above()}"/></clipPath>'
        )
        if mode == "mono":
            top = bot = "currentColor"
            extra = ""
        elif mode in ("light", "tile"):
            top, bot = INK, f"url(#{uid}g)"
            lo, hi = (COBALT, VIOLET) if mode == "light" else (COBALT_LIFT, VIOLET_LIFT)
            extra = grad(f"{uid}g", [(0, lo), (1, hi)], 2, 20, 46, 46)
        else:
            top, bot = PAPER, f"url(#{uid}g)"
            extra = grad(f"{uid}g", [(0, COBALT_LIFT), (1, VIOLET_LIFT)], 2, 20, 46, 46)
        body = (
            f"<defs>{mask}{extra}</defs>"
            f'<g mask="url(#{uid}m)" clip-path="url(#{uid}c)">'
            f'<rect class="lg-b" width="48" height="48" fill="{bot}"/>'
            f'<rect class="lg-a" width="48" height="48" fill="{top}" clip-path="url(#{uid}a)"/></g>'
        )
        return body


# ---------------------------------------------------------------------------------------------
# C. Thread: one unbroken stroke writes c and w: the path a call takes, out and back, never lifted.


class Thread:
    key = "thread"
    name = "Thread"
    SW = 5.4

    def d(self) -> str:
        # c: three quarter turn round (13.5, 27) r 8.5, starting top right, anticlockwise.
        cx, cy, r = 13.5, 27.5, 8.5
        sx, sy = pt(cx, cy, r, -62)
        ex, ey = pt(cx, cy, r, 62)
        # then a hairpin up into the w, two valleys, final upstroke higher than the first (a rise:
        # the agent answering).
        return (
            f"M{f(sx)} {f(sy)}A{f(r)} {f(r)} 0 1 0 {f(ex)} {f(ey)}"
            f"C{f(ex + 3)} {f(ey + 1.2)} {f(22.6)} {f(31)} {f(24.4)} {f(18.5)}"
            f"L{f(29.4)} {f(36)}L{f(34.6)} {f(21.5)}L{f(39.8)} {f(36)}L{f(45)} {f(14)}"
        )

    def mark(self, mode: str, uid: str) -> str:
        stroke_attrs = f'fill="none" stroke-width="{self.SW}" stroke-linecap="round" stroke-linejoin="round"'
        if mode == "mono":
            return f'<path class="lg-a" pathLength="1" d="{self.d()}" stroke="currentColor" {stroke_attrs}/>'
        if mode == "light":
            defs = grad(f"{uid}g", [(0, INK), (0.42, COBALT), (1, VIOLET)], 4, 0, 46, 0)
        else:
            defs = grad(f"{uid}g", [(0, PAPER), (0.42, COBALT_LIFT), (1, VIOLET_LIFT)], 4, 0, 46, 0)
        body = f'<defs>{defs}</defs><path class="lg-a" pathLength="1" d="{self.d()}" stroke="url(#{uid}g)" {stroke_attrs}/>'
        return tile(scaled(body, 0.92)) if mode == "tile" else body


# ---------------------------------------------------------------------------------------------
# D. Two voices: w is a double v. Two chevrons, one per speaker; where they cross, both are
# talking at once, and the overlap takes the heat colour (cut out in one colour).


class TwoVoices:
    key = "two-voices"
    name = "Two voices"
    SW = 7.6
    TOP, BASE = 9, 39
    H = 10.6  # half width of one chevron
    OFF = 13.2  # second chevron offset
    X0 = 4.4

    def v(self, x: float) -> str:
        t, b, h = self.TOP - 6, self.BASE, self.H
        # extend the arms above the cap line; the clip squares them off
        k = (self.BASE - t) / (self.BASE - self.TOP)
        return f"M{f(x + h - h * k)} {f(t)}L{f(x + h)} {f(b)}L{f(x + h + h * k)} {f(t)}"

    def mark(self, mode: str, uid: str) -> str:
        a, b = self.X0, self.X0 + self.OFF
        sw = self.SW
        attrs = f'fill="none" stroke-width="{f(sw)}" stroke-linejoin="miter" stroke-miterlimit="10"'

        def m(mid: str, keep: str | None, cut: str | None, w: float) -> str:
            body = '<rect width="48" height="48" fill="#fff"/>' if keep is None else ""
            if keep is not None:
                body += f'<path d="{keep}" stroke="#fff" fill="none" stroke-width="{f(w)}" stroke-linejoin="miter" stroke-miterlimit="10"/>'
            if cut is not None:
                body += f'<path d="{cut}" stroke="#000" fill="none" stroke-width="{f(w)}" stroke-linejoin="miter" stroke-miterlimit="10"/>'
            return f'<mask id="{mid}" maskUnits="userSpaceOnUse" x="0" y="0" width="48" height="48">{body}</mask>'

        va, vb = self.v(a), self.v(b)
        defs = f'<clipPath id="{uid}k"><rect x="0" y="{self.TOP}" width="48" height="{self.BASE - self.TOP + 0.01}"/></clipPath>'
        if mode == "mono":
            # The overlap is knocked out: where both voices talk at once there is a gap.
            g = sw + 2.6
            defs += m(f"{uid}a", None, vb, g) + m(f"{uid}b", None, va, g)
            body = (
                f"<defs>{defs}</defs><g clip-path=\"url(#{uid}k)\">"
                f'<path class="lg-a" d="{va}" stroke="currentColor" {attrs} mask="url(#{uid}a)"/>'
                f'<path class="lg-b" d="{vb}" stroke="currentColor" {attrs} mask="url(#{uid}b)"/></g>'
            )
            return body
        if mode == "light":
            c1, c2, c3 = COBALT, VIOLET, PINK
        else:
            c1, c2, c3 = COBALT_LIFT, VIOLET_LIFT, "#F06A97"
        # Each voice keeps its colour; the stretch where they overlap turns heat pink.
        defs += m(f"{uid}x", vb, None, sw)
        body = (
            f"<defs>{defs}</defs><g clip-path=\"url(#{uid}k)\">"
            f'<path class="lg-b" d="{vb}" stroke="{c2}" {attrs}/>'
            f'<path class="lg-a" d="{va}" stroke="{c1}" {attrs}/>'
            f'<path class="lg-c" d="{va}" stroke="{c3}" {attrs} mask="url(#{uid}x)"/></g>'
        )
        if mode == "tile":
            return tile(scaled(body, 0.78))
        return body


CONCEPTS = [Handoff(), Dovetail(), Thread(), TwoVoices()]
