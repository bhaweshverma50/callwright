"""Custom-tuned wordmarks and lockups for the four logo concepts.

Each wordmark starts from Unbounded or Geist outlines and replaces one letter (or pair) with a
construction that carries the symbol's idea, so the name is ownable rather than typed.
`INK` in a fragment is replaced with the lockup's text colour.
"""

from __future__ import annotations

from marks import CONCEPTS, INK, PAPER, f
from type import Face, Setting, set_line

TEXT_DARK = "#EEF0FB"


# --- custom letters -------------------------------------------------------------------------


def stepped_c(uid: str, step_em: float = 0.085, gap_em: float = 0.05):
    """Unbounded's C cut at the waist; the lower half steps forward (Handoff)."""

    def fn(face: Face, x: float, baseline: float):
        d, adv = face.glyph("C", x, baseline)
        cap = face.metric("cap")
        mid = baseline - cap / 2
        step, gap = step_em * face.size, gap_em * face.size
        defs = [
            f'<clipPath id="{uid}u"><rect x="{f(x - 10)}" y="{f(mid - cap)}" width="{f(adv + 20)}" height="{f(cap - gap / 2)}"/></clipPath>',
            f'<clipPath id="{uid}l"><rect x="{f(x - 10)}" y="{f(mid + gap / 2)}" width="{f(adv + 20)}" height="{f(cap)}"/></clipPath>',
        ]
        # On hover the symbol splits while this C closes: the halves slide back over the glyph's
        # own position (wc-u, wc-l) and the uncut glyph (wc-full) fades in to fill the waist.
        svg = (
            f'<g class="wc-u"><path d="{d}" fill="INK" clip-path="url(#{uid}u)" transform="translate({f(-step / 2)} 0)"/></g>'
            f'<g class="wc-l"><g transform="translate({f(step / 2)} 0)"><path d="{d}" fill="INK" clip-path="url(#{uid}l)"/></g></g>'
            f'<path class="wc-full" d="{d}" fill="INK" opacity="0"/>'
        )
        return svg, adv + step / 2, defs

    return fn


def dovetail_w(uid: str):
    """W drawn as the dovetail profile: flat valleys, a flat-topped middle tail (Dovetail)."""

    def fn(face: Face, x: float, baseline: float):
        cap = face.metric("cap")
        sw = face.stem() * 0.98
        w = 1.02 * face.glyph("W", 0, 0)[1]
        lsb = 0.02 * face.size
        top = baseline - cap
        mid = baseline - cap * 0.66
        x0 = x + lsb + sw * 0.4
        x6 = x + w - lsb - sw * 0.4
        span = x6 - x0
        # x positions along the profile (fractions of the span)
        xs = [0.0, 0.17, 0.33, 0.43, 0.57, 0.67, 0.83, 1.0]
        p = [x0 + span * t for t in xs]
        yb = baseline - sw / 2
        ym = mid + sw / 2
        yt = top - sw  # arms run past the cap line, the clip squares them off
        pts = [(p[0] - span * 0.03, yt), (p[1], yb), (p[2], yb), (p[3], ym), (p[4], ym), (p[5], yb), (p[6], yb), (p[7] + span * 0.03, yt)]
        d = "M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts)
        cid = f"{uid}d"
        defs = [f'<clipPath id="{cid}"><rect x="{f(x - 5)}" y="{f(top)}" width="{f(w + 10)}" height="{f(cap)}"/></clipPath>']
        svg = f'<path d="{d}" fill="none" stroke="INK" stroke-width="{f(sw)}" stroke-linejoin="miter" stroke-miterlimit="6" clip-path="url(#{cid})"/>'
        return svg, w, defs

    return fn


def thread_w():
    """w as one round-jointed stroke whose last upstroke rises past the x-height, as in the
    symbol (Thread)."""

    def fn(face: Face, x: float, baseline: float):
        sw = face.stem() * 0.96
        xh = face.metric("x")
        _, _, _, asc = face.bounds("l")
        adv = face.glyph("w", 0, 0)[1] * 1.04
        l, r = x + sw * 0.75, x + adv - sw * 0.6
        span = r - l
        top = baseline - xh + sw / 2
        bot = baseline - sw / 2
        mid = baseline - xh * 0.66
        pts = [(l, top), (l + span * 0.24, bot), (l + span * 0.5, mid), (l + span * 0.74, bot), (r + span * 0.06, baseline - asc + sw / 2)]
        d = "M" + "L".join(f"{f(a)} {f(b)}" for a, b in pts)
        svg = f'<path d="{d}" fill="none" stroke="INK" stroke-width="{f(sw)}" stroke-linecap="round" stroke-linejoin="round"/>'
        return svg, adv, []

    return fn


def crossed_w(uid: str):
    """w as two v's that cross; the overlap is cut out (Two voices)."""

    def fn(face: Face, x: float, baseline: float):
        xh = face.metric("x")
        sw = face.stem() * 0.9
        adv = face.glyph("w", 0, 0)[1] * 1.04
        top = baseline - xh
        h = adv * 0.25
        off = adv * 0.4
        a = x + adv * 0.02 + sw * 0.35
        b = a + off
        ext = sw  # run arms past the x-height; the clip cuts them square

        def v(x0: float) -> str:
            k = (xh + ext) / xh
            return f"M{f(x0 + h - h * k)} {f(baseline - xh - ext)}L{f(x0 + h)} {f(baseline + sw * 0.2)}L{f(x0 + h + h * k)} {f(baseline - xh - ext)}"

        va, vb = v(a), v(b)
        attrs = f'fill="none" stroke-width="{f(sw)}" stroke-linejoin="miter" stroke-miterlimit="10"'
        defs = [f'<clipPath id="{uid}k"><rect x="{f(x - 5)}" y="{f(top)}" width="{f(adv + 10)}" height="{f(xh)}"/></clipPath>']
        svg = f'<g clip-path="url(#{uid}k)"><path d="{va}" stroke="INK" {attrs}/><path d="{vb}" stroke="INK" {attrs}/></g>'
        return svg, adv, defs

    return fn


# --- per-concept wordmark settings -------------------------------------------------------------


def wordmark(key: str, uid: str, size: float, baseline: float) -> Setting:
    if key == "handoff":
        face = Face("unbounded", 600, size)
        return set_line(face, "Callwright", -0.025, baseline, {0: stepped_c(uid)})
    if key == "dovetail":
        face = Face("unbounded", 500, size)
        return set_line(face, "CALLWRIGHT", 0.035, baseline, {4: dovetail_w(uid)}, kern={1: -0.05 * size, 3: -0.02 * size})
    if key == "thread":
        face = Face("geist", 500, size)
        return set_line(face, "callwright", -0.012, baseline, {4: thread_w()})
    if key == "two-voices":
        face = Face("unbounded", 600, size)
        return set_line(face, "callwright", -0.025, baseline, {4: crossed_w(uid)})
    raise KeyError(key)


# Lockup proportions: wordmark em size and gap as fractions of the symbol height.
LOCKUP = {
    "handoff": {"em": 0.56, "gap": 0.16},
    "dovetail": {"em": 0.5, "gap": 0.26},
    "thread": {"em": 0.74, "gap": 0.16},
    "two-voices": {"em": 0.58, "gap": 0.2},
}

CAP_FRAC = {"handoff": 0.75, "dovetail": 0.75, "thread": 0.71, "two-voices": 0.75}


def concept(key: str):
    return next(c for c in CONCEPTS if c.key == key)


def wordmark_svg(key: str, uid: str, size: float, ink: str) -> tuple[str, float, float]:
    """Wordmark alone, with its own box: returns (svg inner, width, height). Height spans the cap
    line to the baseline plus descender room."""
    cap = CAP_FRAC[key] * size
    st = wordmark(key, uid, size, cap)
    inner = "".join(f'<path d="{d}" fill="{ink}"/>' for d in st.paths) + "".join(st.extras).replace("INK", ink)
    defs = "".join(st.defs)
    return (f"<defs>{defs}</defs>" if defs else "") + inner, st.width, cap


def lockup(key: str, uid: str, mode: str, height: float = 48) -> tuple[str, float, float]:
    """Symbol plus wordmark. mode: light, dark or mono. Returns (svg inner, width, height)."""
    c = concept(key)
    p = LOCKUP[key]
    size = p["em"] * height
    ink = {"light": INK, "dark": TEXT_DARK, "mono": "currentColor"}[mode]
    sym = c.mark(mode if mode != "mono" else "mono", uid + "s")
    k = height / 48
    cap = CAP_FRAC[key] * size
    baseline = height / 2 + cap / 2
    st = wordmark(key, uid + "w", size, baseline)
    x0 = height + p["gap"] * height
    words = "".join(f'<path d="{d}" fill="{ink}"/>' for d in st.paths) + "".join(st.extras).replace("INK", ink)
    defs = "".join(st.defs)
    inner = (
        f'<g transform="scale({f(k)})">{sym}</g>'
        + (f"<defs>{defs}</defs>" if defs else "")
        + f'<g transform="translate({f(x0)} 0)">{words}</g>'
    )
    return inner, x0 + st.width, height


__all__ = ["lockup", "wordmark_svg", "LOCKUP", "PAPER"]
