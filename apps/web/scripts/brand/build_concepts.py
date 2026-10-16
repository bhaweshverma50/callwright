"""Build the Callwright logo concept files and the review page.

    uv run --with fonttools --with brotli python apps/web/scripts/brand/build_concepts.py

Writes public/brand/concepts/<key>/{symbol,symbol-dark,app-icon,lockup-light,lockup-dark,mono}.svg
and docs/brand/logo-options.html (self-contained: inline SVG, fonts embedded). Set CW_FONTS to the
@fontsource-variable folder if node_modules is not installed in apps/web.
"""

from __future__ import annotations

import base64
import itertools
import os

from marks import CONCEPTS, INK, f
from type import fonts_dir
from wordmarks import lockup

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.normpath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(WEB, "public", "brand", "concepts")
DOCS = os.path.join(WEB, "docs", "brand")

_ids = itertools.count(1)


def uid() -> str:
    return f"k{next(_ids)}"


def sym(c, mode: str, size: float, label: str | None = None) -> str:
    aria = f' role="img" aria-label="{label}"' if label else ' aria-hidden="true"'
    return f'<svg width="{f(size)}" height="{f(size)}" viewBox="0 0 48 48"{aria}>{c.mark(mode, uid())}</svg>'


def lock(c, mode: str, height: float, cls: str = "") -> str:
    inner, w, h = lockup(c.key, uid(), mode, 48)
    width = w * height / 48
    return f'<svg class="{cls}" width="{f(width)}" height="{f(height)}" viewBox="0 0 {f(w)} 48" role="img" aria-label="Callwright">{inner}</svg>'


# ---------------------------------------------------------------------------------------------
# Files


def svg_file(inner: str, w: float, h: float, extra: str = "") -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {f(w)} {f(h)}" width="{f(w * 4)}" height="{f(h * 4)}"{extra}>{inner}</svg>\n'


def write_files() -> None:
    for c in CONCEPTS:
        d = os.path.join(OUT, c.key)
        os.makedirs(d, exist_ok=True)
        files = {
            "symbol.svg": svg_file(c.mark("light", "a"), 48, 48),
            "symbol-dark.svg": svg_file(c.mark("dark", "a"), 48, 48),
            "app-icon.svg": svg_file(c.mark("tile", "a"), 48, 48),
        }
        for mode, name in (("light", "lockup-light.svg"), ("dark", "lockup-dark.svg"), ("mono", "mono.svg")):
            inner, w, h = lockup(c.key, "a", mode, 48)
            extra = f' color="{INK}"' if mode == "mono" else ""
            files[name] = svg_file(inner, w, h, extra)
        for name, body in files.items():
            with open(os.path.join(d, name), "w") as fh:
                fh.write(body)


# ---------------------------------------------------------------------------------------------
# Review page

COPY = {
    "handoff": {
        "line": "A C cut at the waist, its lower half stepped forward.",
        "why": [
            "The top half is the caller, the bottom half the agent. One speaks, the other picks up the turn a beat later. Turn-taking is the hardest thing a voice agent does, and it is the moment Callwright times and scores.",
            "The wordmark carries the same cut in its C, so the name and the mark are one idea.",
        ],
        "motion": "On hover the halves slide level and step apart again: a turn changing hands.",
        "risk": "The most conventional of the four. The step is what makes it ours; without it, it is a plain C.",
    },
    "dovetail": {
        "line": "Two blocks locked by a dovetail joint.",
        "why": [
            "A dovetail is the joint a wright cuts so two pieces hold without glue. Tails and pins alternate like turns in a call, and the seam between them is a trapezoid wave: a signal.",
            "The W in the wordmark is cut on the same profile, flat valleys and a flat-topped tail, set in Unbounded capitals like a maker's stamp.",
        ],
        "motion": "On load the lower block slides up into the tails and locks.",
        "risk": "Abstract: it needs the name beside it until people learn it, and the seam closes up below 16px.",
    },
    "thread": {
        "line": "One stroke, never lifted, writes c and w.",
        "why": [
            "A call is one continuous path from the caller through the chain and back. The last upstroke rises above the rest: the agent answering.",
            "The wordmark keeps Geist's plain letters and swaps in the same w, so the lift shows wherever the name does.",
        ],
        "motion": "The stroke draws itself in once, end to end, then rests.",
        "risk": "A monogram, so it says cw rather than a picture. Gradient strokes need care on light surfaces.",
    },
    "two-voices": {
        "line": "W is a double v: one v per voice.",
        "why": [
            "The caller is cobalt, the agent violet. Where they cross the overlap turns heat pink: both talking at once, which a good agent handles and Callwright shows you. In one colour the overlap is cut out.",
            "The wordmark uses the same crossed w in Unbounded, the app's display face.",
        ],
        "motion": "The two v's slide in from either side and the overlap lights as they meet.",
        "risk": "The crossed w in the lowercase wordmark is subtle under 14px; the symbol carries it.",
    },
}

NAV = ["Agents", "Knowledge", "Channels"]
NAV2 = ["Dashboard", "Calls"]


def browser_tabs(c, theme: str) -> str:
    return f"""
<div class="browser {theme}">
  <div class="tabs">
    <div class="tab active">{sym(c, "tile", 16)}<span>Agents</span><i></i></div>
    <div class="tab">{sym(c, "tile", 16)}<span>Calls</span><i></i></div>
    <div class="tab"><b></b><span>Inbox</span><i></i></div>
  </div>
  <div class="omni"><span>app.callwright.com/agents</span></div>
</div>"""


def sidebar(c, theme: str) -> str:
    mode = "light" if theme == "light" else "dark"
    items = "".join(f'<li class="{"on" if n == "Agents" else ""}"><b></b>{n}</li>' for n in NAV)
    items2 = "".join(f"<li><b></b>{n}</li>" for n in NAV2)
    return f"""
<div class="side {theme}">
  <div class="side-head">{lock(c, mode, 30)}</div>
  <p>Build</p><ul>{items}</ul>
  <p>Observe</p><ul>{items2}</ul>
</div>"""


def rail(c, theme: str) -> str:
    mode = "light" if theme == "light" else "dark"
    cells = "".join(f'<li class="{"on" if i == 0 else ""}"><b></b></li>' for i in range(5))
    return f"""
<div class="rail {theme}">
  <div class="rail-head">{sym(c, mode, 32, "Callwright")}</div>
  <ul>{cells}</ul>
</div>"""


def hero(c, theme: str = "light") -> str:
    return f"""
<div class="hero {theme}">
  <div class="hero-nav">{lock(c, theme, 28)}<span>Pricing</span><span>Enterprise</span><em>Sign in</em><strong>Create account</strong></div>
  <div class="hero-body">
    <h4>Phone agents fast enough that callers keep talking.</h4>
    <p>Choose the speech recognition, model and voice. Callwright runs the call, times every turn and prices every second.</p>
  </div>
</div>"""


def section(i: int, c) -> str:
    t = COPY[c.key]
    why = "".join(f"<p>{p}</p>" for p in t["why"])
    sizes = "".join(
        f'<figure class="sz"><div class="sz-box">{sym(c, "light", s)}</div><figcaption>{s}px</figcaption></figure>'
        for s in (16, 32, 64)
    )
    return f"""
<section class="concept" id="{c.key}">
  <header class="c-head">
    <span class="c-letter">{"ABCD"[i]}</span>
    <div>
      <h2>{c.name}</h2>
      <p class="lede">{t["line"]}</p>
    </div>
  </header>
  <div class="c-grid">
    <div class="c-copy">
      {why}
      <dl>
        <dt>Motion</dt><dd>{t["motion"]}</dd>
        <dt>Watch out</dt><dd>{t["risk"]}</dd>
      </dl>
    </div>
    <div class="c-plates">
      <div class="plate big light">{sym(c, "light", 180, c.name + " symbol")}<span class="cap">180px on paper</span></div>
      <div class="plate big dark">{sym(c, "dark", 180)}<span class="cap">180px on ink</span></div>
      <div class="plate sizes">{sizes}<figure class="sz"><div class="sz-box">{sym(c, "tile", 32)}</div><figcaption>App icon</figcaption></figure><figure class="sz mono"><div class="sz-box">{sym(c, "mono", 32)}</div><figcaption>One colour</figcaption></figure></div>
      <div class="plate lock light">{lock(c, "light", 52)}</div>
      <div class="plate lock dark">{lock(c, "dark", 52)}</div>
      <div class="plate lock mono">{lock(c, "mono", 40)}<span class="cap">One colour lockup</span></div>
    </div>
  </div>
  <div class="c-context">
    <figure><div class="ctx stack">{browser_tabs(c, "light")}{browser_tabs(c, "dark")}</div><figcaption>Favicon in browser tabs, 16px</figcaption></figure>
    <figure><div class="ctx pair">{sidebar(c, "light")}{sidebar(c, "dark")}</div><figcaption>App sidebar at its real 248px, light and dark</figcaption></figure>
    <figure><div class="ctx pair">{rail(c, "light")}{rail(c, "dark")}</div><figcaption>Collapsed rail, 72px</figcaption></figure>
    <figure class="wide"><div class="hero-pair"><div class="ctx hero-ctx">{hero(c)}</div><div class="ctx hero-ctx">{hero(c, "dark")}</div></div><figcaption>Home page header and hero, light and dark</figcaption></figure>
  </div>
</section>"""


def font_face(name: str, rel: str) -> str:
    with open(os.path.join(fonts_dir(), rel), "rb") as fh:
        b = base64.b64encode(fh.read()).decode()
    return f"@font-face{{font-family:'{name}';src:url(data:font/woff2;base64,{b}) format('woff2');font-weight:100 900;font-display:block}}"


CSS = """
:root{--ink:#171A3D;--deep:#0E1030;--paper:#F4F5FA;--white:#fff;--line:#DCDFEB;--line-2:#C3C7DA;--text-2:#474B70;--text-3:#5E6287;--cobalt:#3346E8;--surface-d:#161A42;--line-d:#262B5E}
*{box-sizing:border-box}
html{background:var(--paper)}
body{margin:0;color:var(--ink);font:15px/1.6 Geist,ui-sans-serif,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
.page{max-width:1360px;margin:0 auto;padding:56px 40px 80px}
h1,h2,h4{font-family:Unbounded,ui-sans-serif,sans-serif;font-weight:600;letter-spacing:-0.025em;margin:0}
h1{font-size:44px;line-height:1.08;max-width:15ch}
.intro{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:48px;align-items:end;padding-bottom:40px;border-bottom:1px solid var(--line)}
.intro p{margin:0;color:var(--text-2);max-width:60ch}
.lineup{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:0;margin:32px 0 8px}
.lineup a{display:flex;align-items:center;gap:16px;padding:18px 20px;color:inherit;text-decoration:none;border-right:1px solid var(--line)}
.lineup a:last-child{border-right:0}
.lineup a:hover{background:var(--white)}
.lineup a:focus-visible{outline:2px solid var(--cobalt);outline-offset:2px}
.lineup span{font-family:Unbounded;font-weight:500;font-size:15px;letter-spacing:-0.02em}
.lineup small{display:block;color:var(--text-3);font-size:13px}
.concept{padding:64px 0 56px;border-top:1px solid var(--line)}
.lineup + .concept{border-top:0}
.c-head{display:flex;gap:20px;align-items:baseline;margin-bottom:28px}
.c-letter{font-family:Unbounded;font-size:15px;font-weight:500;color:var(--text-3);width:28px}
h2{font-size:32px;line-height:1.1}
.lede{margin:6px 0 0;color:var(--text-2);font-size:17px}
.c-grid{display:grid;grid-template-columns:minmax(0,320px) minmax(0,1fr);gap:40px;padding-left:48px}
.c-copy p{margin:0 0 14px;max-width:46ch}
.c-copy dl{margin:22px 0 0;display:grid;grid-template-columns:minmax(0,1fr);gap:2px}
.c-copy dt{font-weight:600;font-size:13px;margin-top:10px}
.c-copy dd{margin:0;color:var(--text-2);font-size:14px}
.c-plates{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:12px}
.plate{position:relative;border-radius:14px;display:flex;align-items:center;justify-content:center;min-height:120px;padding:20px}
.plate.light{background:var(--white);border:1px solid var(--line)}
.plate.dark{background:var(--deep)}
.plate.big{grid-column:span 2;grid-row:span 2;min-height:260px}
.plate.sizes{grid-column:span 2;grid-row:span 2;background:var(--white);border:1px solid var(--line);display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-content:center;gap:18px 8px}
.plate.lock{grid-column:span 2;min-height:110px}
.plate.lock.mono{background:var(--paper);border:1px dashed var(--line-2);color:var(--ink)}
.cap{position:absolute;left:14px;bottom:10px;font-size:12px;color:var(--text-3)}
.dark .cap{color:#8F94BE}
.sz{margin:0;display:flex;flex-direction:column;align-items:center;gap:8px}
.sz-box{height:64px;display:flex;align-items:center;justify-content:center}
.sz.mono{color:var(--ink)}
.sz figcaption{font-size:12px;color:var(--text-3)}
.plate svg{max-width:100%;height:auto}
.plate.big svg{width:180px;height:180px}
.c-context{display:grid;grid-template-columns:minmax(0,1fr) 498px 146px;gap:14px;margin-top:22px;padding-left:48px}
.c-context .wide{grid-column:1/-1}
.c-context figure{margin:0}
.c-context figcaption{font-size:12px;color:var(--text-3);margin-top:8px}
.ctx{border-radius:14px;overflow:hidden;border:1px solid var(--line);background:var(--white);height:250px;display:flex;flex-direction:column}
.ctx.hero-ctx{height:auto}
.hero-pair{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.ctx.pair{flex-direction:row}
/* browser tabs */
.browser{flex:1;display:flex;flex-direction:column;font:12px/1 system-ui,-apple-system,sans-serif}
.browser.light{background:#DEE1E6;color:#3C4043}
.browser.dark{background:#202124;color:#E8EAED}
.tabs{display:flex;align-items:flex-end;gap:2px;padding:12px 10px 0}
.omni{flex:1;display:flex;align-items:center;padding:0 10px}
.omni span{flex:1;height:28px;border-radius:14px;display:flex;align-items:center;padding:0 14px;font-size:12px}
.browser.light .omni{background:#fff}
.browser.light .omni span{background:#F1F3F4;color:#5F6368}
.browser.dark .omni{background:#35363A}
.browser.dark .omni span{background:#202124;color:#BDC1C6}
.tab{display:flex;align-items:center;gap:8px;height:34px;padding:0 10px;border-radius:9px 9px 0 0;flex:0 1 150px;min-width:0;white-space:nowrap;overflow:hidden}
.tab span{flex:1;overflow:hidden;text-overflow:ellipsis}
.tab i{width:8px;height:8px;position:relative;opacity:.6}
.tab i::before,.tab i::after{content:"";position:absolute;left:3.5px;top:-1px;width:1.2px;height:10px;background:currentColor;transform:rotate(45deg)}
.tab i::after{transform:rotate(-45deg)}
.tab b{width:16px;height:16px;border-radius:50%;background:#9AA0A6;flex:none}
.browser.light .tab.active{background:#fff}
.browser.dark .tab.active{background:#35363A}
.tab svg{flex:none}
/* sidebar */
.side{flex:0 0 248px;padding:0 12px;font-size:13.5px;min-width:0}
.side.light{background:#ECEEF6;color:var(--ink)}
.side.dark{background:#12153A;color:#EEF0FB}
.side-head{flex:none;height:60px;display:flex;align-items:center;padding-left:4px}
.side-head svg{max-width:100%}
.side p{margin:6px 0 4px 10px;font-size:11.5px;color:var(--text-3);font-weight:500}
.side.dark p{color:#8F94BE}
.side ul,.rail ul{list-style:none;margin:0;padding:0}
.side li{display:flex;align-items:center;gap:10px;height:32px;padding:0 10px;border-radius:8px}
.side li b{width:15px;height:15px;border-radius:4px;border:1.6px solid currentColor;opacity:.55}
.side.light li.on{background:#E6E9FD;color:#2B3CD0}
.side.dark li.on{background:#222A6E;color:#A3ADFF}
.side li.on b{opacity:1}
/* rail */
.rail{flex:0 0 72px;display:flex;flex-direction:column;align-items:center}
.rail.light{background:#ECEEF6;color:var(--ink);border-right:1px solid var(--line)}
.rail.dark{background:#12153A;color:#EEF0FB}
.rail-head{flex:none;height:60px;display:flex;align-items:center;justify-content:center}
.rail ul{display:flex;flex-direction:column;gap:6px}
.rail li{width:40px;height:40px;border-radius:9px;display:grid;place-items:center}
.rail li b{width:16px;height:16px;border-radius:4px;border:1.6px solid currentColor;opacity:.55}
.rail.light li.on{background:#E6E9FD;color:#2B3CD0}
.rail.dark li.on{background:#222A6E;color:#A3ADFF}
/* hero */
.hero{flex:1;background:radial-gradient(60% 80% at 85% 20%,rgba(122,60,255,.12),transparent 70%),radial-gradient(50% 60% at 10% 90%,rgba(51,70,232,.10),transparent 70%),var(--paper);display:flex;flex-direction:column}
.hero-nav{display:flex;align-items:center;gap:20px;height:56px;padding:0 24px;border-bottom:1px solid var(--line);font-size:13px;color:var(--text-2);white-space:nowrap}
.hero-nav svg{margin-right:6px}
.hero-nav em{font-style:normal;margin-left:auto}
.hero-nav strong{font-weight:500;color:#fff;background:linear-gradient(120deg,#3346e8,#5a3cf4 55%,#7a3cff);padding:6px 11px;border-radius:7px}
.hero-body{padding:32px 24px 36px}
.hero h4{font-size:34px;line-height:1.05;letter-spacing:-0.035em;max-width:15ch;color:var(--ink)}
.hero.dark{background:radial-gradient(60% 80% at 85% 20%,rgba(122,60,255,.22),transparent 70%),var(--deep)}
.hero.dark h4{color:#EEF0FB}
.hero.dark p,.hero.dark .hero-nav{color:#B7BBDA}
.hero.dark .hero-nav{border-color:var(--line-d)}
.ctx.hero-ctx:has(.dark){border-color:var(--deep)}
.hero p{margin:14px 0 0;font-size:14px;color:var(--text-2);max-width:52ch;line-height:1.55}
.compare{padding:56px 0 0;border-top:1px solid var(--line)}
.compare h2{font-size:24px;margin-bottom:6px}
.compare > p{margin:0 0 20px;color:var(--text-2)}
.cmp-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}
.cmp-grid .ctx{height:auto}
.cmp-tabs{display:flex;align-items:flex-end;gap:2px;padding:10px 10px 0;font:12px/1 system-ui,-apple-system,sans-serif}
.cmp-tabs.light{background:#DEE1E6;color:#3C4043}
.cmp-tabs.dark{background:#202124;color:#E8EAED}
.cmp-tabs.light .tab{background:#fff}
.cmp-tabs.dark .tab{background:#35363A}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--line);font-size:13px;color:var(--text-3)}
footer code{font:12.5px 'Geist Mono',ui-monospace,monospace;color:var(--text-2)}
@media (max-width:1100px){.c-grid,.c-context{padding-left:0}.c-grid{grid-template-columns:minmax(0,1fr)}.c-context{grid-template-columns:minmax(0,1fr)}.ctx.pair{overflow-x:auto}.intro{grid-template-columns:minmax(0,1fr)}.lineup{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media (max-width:640px){.page{padding:32px 16px 56px}h1{font-size:32px}.c-plates{grid-template-columns:repeat(2,minmax(0,1fr))}.plate.big,.plate.sizes,.plate.lock{grid-column:span 2}.c-context,.cmp-grid,.hero-pair{grid-template-columns:minmax(0,1fr)}.lineup{grid-template-columns:minmax(0,1fr)}.lineup a{border-right:0;border-bottom:1px solid var(--line)}}
"""


def page() -> str:
    fonts = font_face("Unbounded", "unbounded/files/unbounded-latin-wght-normal.woff2") + font_face(
        "Geist", "geist/files/geist-latin-wght-normal.woff2"
    )
    lineup = "".join(
        f'<a href="#{c.key}">{sym(c, "light", 44)}<div><span>{c.name}</span><small>{COPY[c.key]["line"]}</small></div></a>'
        for c in CONCEPTS
    )
    sections = "".join(section(i, c) for i, c in enumerate(CONCEPTS))
    tabs_l = "".join(f'<div class="tab">{sym(c, "tile", 16)}<span>{c.name}</span><i></i></div>' for c in CONCEPTS)
    tabs_d = tabs_l.replace("", "")
    compare = f"""
<section class="compare">
  <h2>Side by side at 16px</h2>
  <p>The size that decides most logos: the favicon among other tabs.</p>
  <div class="cmp-grid">
    <div class="ctx"><div class="cmp-tabs light">{tabs_l}</div></div>
    <div class="ctx"><div class="cmp-tabs dark">{"".join(f'<div class="tab">{sym(c, "tile", 16)}<span>{c.name}</span><i></i></div>' for c in CONCEPTS)}</div></div>
  </div>
</section>"""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Callwright logo options</title>
<style>{fonts}{CSS}</style>
</head>
<body>
<main class="page">
  <div class="intro">
    <h1>Four directions for the Callwright mark</h1>
    <p>A wright is a maker: shipwright, playwright. Callwright makes voice agents, so each direction draws on one of three ideas: turn-taking between two voices, the signal chain a call runs through, and the craft of making. Every symbol is built from circles, arcs and straight lines on a 48 unit grid, then tested at 16px, in the sidebar, the collapsed rail and the home page, light and dark.</p>
  </div>
  <nav class="lineup" aria-label="Concepts">{lineup}</nav>
  {sections}
  {compare}
  <footer>Source files: <code>apps/web/public/brand/concepts/&lt;name&gt;/</code>. Rebuild with <code>uv run --with fonttools --with brotli python apps/web/scripts/brand/build_concepts.py</code>.</footer>
</main>
</body>
</html>
"""


def main() -> None:
    write_files()
    os.makedirs(DOCS, exist_ok=True)
    with open(os.path.join(DOCS, "logo-options.html"), "w") as fh:
        fh.write(page())
    print("wrote", OUT, "and", os.path.join(DOCS, "logo-options.html"))


if __name__ == "__main__":
    main()
