export const pct = (x: number, digits = 1) => `${(100 * x).toFixed(digits)}%`;

/** x to 3 significant digits, without trailing zeros. */
export const sig = (x: number, p = 3) => Number(x.toPrecision(p)).toString();

export const int = (x: number) => Math.round(x).toLocaleString();

/** A round axis maximum at or above x, for probabilities. */
export function niceMax(x: number): number {
  for (const s of [0.02, 0.05, 0.1, 0.2, 0.25, 0.4, 0.5, 0.6, 0.8, 1]) if (x <= s) return s;
  return 1;
}

/** About k equal-width bins with round edges covering [min, max]. */
export function niceBins(min: number, max: number, k = 6): number[] {
  if (!(max > min)) return [Math.floor(min), Math.floor(min) + 1];
  const raw = (max - min) / k;
  const mag = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
  const lo = Math.floor(min / step) * step;
  const edges: number[] = [];
  for (let e = lo; e <= max + step / 2; e += step) edges.push(Number(e.toPrecision(12)));
  if (edges[edges.length - 1] <= max) edges.push(Number((edges[edges.length - 1] + step).toPrecision(12)));
  return edges;
}

export function duration(seconds: number): string {
  if (!Number.isFinite(seconds)) return "–";
  if (seconds < 60) return `${Math.ceil(seconds)} s`;
  return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
}

export function basename(path: string | null | undefined): string {
  if (!path) return "untitled.scenic";
  return path.split(/[\\/]/).pop() ?? path;
}
