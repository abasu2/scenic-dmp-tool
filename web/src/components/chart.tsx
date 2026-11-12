import type { ReactNode } from "react";
import { pct } from "../lib/format";

export const W = 640;
export const PAD = { l: 46, r: 10, t: 12 };

/** Horizontal grid lines and percentage ticks at 0, ymax/2 and ymax. */
export function YAxis({ ymax, top, height }: { ymax: number; top: number; height: number }) {
  return (
    <g>
      {[0, 0.5, 1].map((f) => {
        const y = top + height * (1 - f);
        return (
          <g key={f}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y} y2={y} className={f === 0 ? "axis" : "grid"} />
            <text x={PAD.l - 6} y={y + 4} textAnchor="end" className="muted">
              {pct(ymax * f, ymax * f < 0.1 && f > 0 ? 1 : 0)}
            </text>
          </g>
        );
      })}
    </g>
  );
}

export function XLabel({ cx, y, text, rotate }: { cx: number; y: number; text: string; rotate: boolean }) {
  return rotate ? (
    <text x={cx} y={y} textAnchor="end" transform={`rotate(-40 ${cx} ${y})`}>
      {text}
    </text>
  ) : (
    <text x={cx} y={y} textAnchor="middle">
      {text}
    </text>
  );
}

export function Whisker({ cx, lo, hi, cap }: { cx: number; lo: number; hi: number; cap: number }) {
  return (
    <g className="whisker">
      <line x1={cx} x2={cx} y1={lo} y2={hi} />
      <line x1={cx - cap} x2={cx + cap} y1={lo} y2={lo} />
      <line x1={cx - cap} x2={cx + cap} y1={hi} y2={hi} />
    </g>
  );
}

export function Hatch({ id }: { id: string }) {
  return (
    <defs>
      <pattern id={id} patternUnits="userSpaceOnUse" width={6} height={6} patternTransform="rotate(45)">
        <line x1={0} y1={0} x2={0} y2={6} className="hatch" />
      </pattern>
    </defs>
  );
}

/** A muted line of math centered on cx, with its baseline at y. SVG text can't hold KaTeX's HTML. */
export function SvgMath({ cx, y, width, children }: { cx: number; y: number; width: number; children: ReactNode }) {
  return (
    <foreignObject x={cx - width / 2} y={y - 12} width={width} height={16}>
      <div className="svg-math">{children}</div>
    </foreignObject>
  );
}
