import { useId, type CSSProperties } from "react";
import { cn } from "./cn";
import { SYMBOL } from "./logo-data.generated";

/*
  Geometry of the Handoff symbol, read from the generated art so the loader follows the logo if it
  is ever regenerated. Each half is an annulus segment whose path opens with its outer arc; one end
  of that arc is the half's leftmost point, on the waist, where the centre is (x + r, y).

  The loader turns both halves about the midpoint of the two centres. A half turn about that point
  moves one centre exactly onto the other, so after half a turn the halves have traded places and
  lock into a true mark, upside down.
*/
const pathOf = (cls: string) => new RegExp(`class="${cls}" d="([^"]+)"`).exec(SYMBOL.markup)?.[1] ?? "";
const A_PATH = pathOf("lg-a");
const B_PATH = pathOf("lg-b");
function centreOf(d: string): [number, number, number] {
  const m = /^M([\d.]+) ([\d.]+)A([\d.]+) [\d.]+ \d \d \d ([\d.]+) ([\d.]+)/.exec(d);
  if (!m) return [24, 24, 19];
  const [x0, y0, r, x1, y1] = m.slice(1).map(Number) as [number, number, number, number, number];
  return x0 <= x1 ? [x0 + r, y0, r] : [x1 + r, y1, r];
}
const [AX, AY, R] = centreOf(A_PATH);
const [BX, BY] = centreOf(B_PATH);
const MX = (AX + BX) / 2;
const MY = (AY + BY) / 2;
/** Mid radius of the ring (outer radius R, inner 10.2), where the comet trails run. */
const RT = R - (R - 10.2) / 2;

interface Trail {
  d: string;
  /** Gradient runs from the faint far end to the bright end at the half's tail. */
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}
/** A comet on the trail radius around a half's centre, from `far` to `tail` (degrees, y down). */
function comet([cx, cy]: [number, number], far: number, tail: number): Trail {
  const at = (deg: number) => [cx + RT * Math.cos((deg * Math.PI) / 180), cy + RT * Math.sin((deg * Math.PI) / 180)] as const;
  const [x1, y1] = at(far);
  const [x2, y2] = at(tail);
  const sweep = tail > far ? 1 : 0;
  const f = (n: number) => n.toFixed(3);
  return { d: `M${f(x1)} ${f(y1)}A${f(RT)} ${f(RT)} 0 0 ${sweep} ${f(x2)} ${f(y2)}`, x1, y1, x2, y2 };
}
const A_C: [number, number] = [AX - MX, AY - MY];
const B_C: [number, number] = [BX - MX, BY - MY];
/*
  The ink half spans 180 to 320 degrees round its centre, the gradient half 40 to 180 (the waist is
  at 180, the opening between 320 and 40). Clockwise, each half's tail is its waist end for the ink
  half and its opening end for the gradient half; counter-clockwise it is the other way round. Each
  comet runs 75 degrees back from the tail.
*/
const TRAILS = {
  aCw: comet(A_C, 105, 180),
  aCcw: comet(A_C, 395, 320),
  bCw: comet(B_C, -35, 40),
  bCcw: comet(B_C, 255, 180),
};

const SIZES = { sm: 24, md: 40, lg: 64, xl: 96 } as const;
export type LogoLoaderSize = keyof typeof SIZES;

/**
 * Loading mark built from the Handoff logo (docs/DESIGN.md section 8). The two halves of the C pass
 * the turn back and forth: the ink half swings half a turn clockwise with the gradient half
 * following just behind, they lock into the mark with places traded, then the gradient half leads
 * the swing back home with the ink half following. The leading half always moves into the opening
 * of the C, so the halves never cross. While a half travels it parts slightly from the waist and
 * draws a soft comet; a glow breathes up at every lock. A 2.4 s seamless loop of transforms and
 * opacity, coloured by the --logo-* tokens so it follows the theme.
 *
 * Reduced motion: the mark at rest, breathing slowly in opacity. `still` forces that state (gallery
 * previews). Use it for boot, route and full-page loading; content-shaped loading keeps shimmer
 * skeletons. It fades in after a short delay so fast loads never flash it.
 */
export function LogoLoader({
  size = "md",
  label,
  className,
  onConsole,
  still,
  glow = true,
}: {
  size?: LogoLoaderSize;
  /** Visible caption under the mark; also the status text read to screen readers. */
  label?: string;
  className?: string;
  /** Always-dark surfaces: use the dark logo palette whatever the theme. */
  onConsole?: boolean;
  still?: boolean;
  glow?: boolean;
}) {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const px = SIZES[size];
  const trail = (key: keyof typeof TRAILS, colour: string) => {
    const t = TRAILS[key];
    return (
      <>
        <linearGradient id={`${uid}${key}`} gradientUnits="userSpaceOnUse" x1={t.x1} y1={t.y1} x2={t.x2} y2={t.y2}>
          <stop offset="0" stopColor={colour} stopOpacity="0" />
          <stop offset="1" stopColor={colour} stopOpacity="0.9" />
        </linearGradient>
      </>
    );
  };
  const comet = (key: keyof typeof TRAILS) => (
    <path
      className={`ll-trail ll-trail-${key}`}
      d={TRAILS[key].d}
      fill="none"
      stroke={`url(#${uid}${key})`}
      strokeWidth="3.4"
      strokeLinecap="round"
    />
  );
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn("ll inline-flex flex-col items-center gap-3", onConsole && "logo-on-dark", still && "ll-still", className)}
      style={{ "--ll-size": `${px}px` } as CSSProperties}
      data-size={size}
    >
      <svg viewBox="-26 -26 52 52" width={px} height={px} aria-hidden className="ll-mark overflow-visible">
        <defs>
          <linearGradient id={`${uid}g`} gradientUnits="userSpaceOnUse" x1="4" y1="30" x2="44" y2="44">
            <stop offset="0" stopColor="var(--logo-cobalt)" />
            <stop offset="1" stopColor="var(--logo-violet)" />
          </linearGradient>
          {trail("aCw", "var(--logo-violet)")}
          {trail("aCcw", "var(--logo-violet)")}
          {trail("bCw", "var(--logo-cobalt)")}
          {trail("bCcw", "var(--logo-cobalt)")}
          <radialGradient id={`${uid}glow`}>
            <stop offset="0" stopColor="var(--logo-violet)" stopOpacity="0.32" />
            <stop offset="0.55" stopColor="var(--logo-cobalt)" stopOpacity="0.12" />
            <stop offset="1" stopColor="var(--logo-cobalt)" stopOpacity="0" />
          </radialGradient>
        </defs>
        {glow && <circle className="ll-glow" r="25" fill={`url(#${uid}glow)`} />}
        {/* Comets sit under both halves; their groups run the same keyframes as the halves. */}
        <g className="ll-a">
          <g className="ll-a-split">
            {comet("aCw")}
            {comet("aCcw")}
          </g>
        </g>
        <g className="ll-b">
          <g className="ll-b-split">
            {comet("bCw")}
            {comet("bCcw")}
          </g>
        </g>
        <g className="ll-a">
          <g className="ll-a-split">
            <path d={A_PATH} transform={`translate(${-MX} ${-MY})`} fill="var(--logo-ink)" />
          </g>
        </g>
        <g className="ll-b">
          <g className="ll-b-split">
            <path d={B_PATH} transform={`translate(${-MX} ${-MY})`} fill={`url(#${uid}g)`} />
          </g>
        </g>
      </svg>
      {label ? <span className="text-[13px] text-fg-2">{label}</span> : <span className="sr-only">Loading</span>}
    </div>
  );
}

/** Whole-viewport loading (app boot, the session check before the app shell). */
export function FullPageLoader({ label }: { label?: string }) {
  return (
    <div className="grid min-h-dvh place-items-center bg-bg px-4">
      <LogoLoader size="lg" label={label} />
    </div>
  );
}

/** Loading for a page or large panel whose shape is not known yet (a route still downloading). */
export function PanelLoader({ label, className }: { label?: string; className?: string }) {
  return (
    <div className={cn("grid min-h-[min(60vh,520px)] place-items-center", className)}>
      <LogoLoader size="lg" label={label} />
    </div>
  );
}
