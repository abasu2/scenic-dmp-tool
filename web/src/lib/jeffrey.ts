// Jeffrey's update on a finite view, mirroring src/scenic_dmp/jeffrey.py so the
// browser can give immediate feedback while ν is dragged. The server stays the
// source of truth: ν is sent there on release.

export interface Readout {
  w: number[];
  a: number[];
  M: number;
}

/** Set nu[y] = t and rescale the other supported values proportionally (Jeffrey's rule on {y, not y}). */
export function rescale(nu: number[], y: number, t: number, supported: boolean[]): number[] {
  const out = nu.map(() => 0);
  const others = supported.map((s, i) => s && i !== y);
  const nOthers = others.filter(Boolean).length;
  if (nOthers === 0) {
    out[y] = 1;
    return out;
  }
  t = Math.min(1, Math.max(0, t));
  out[y] = t;
  let rest = 0;
  others.forEach((o, i) => {
    if (o) rest += nu[i];
  });
  others.forEach((o, i) => {
    if (o) out[i] = rest > 0 ? (nu[i] * (1 - t)) / rest : (1 - t) / nOthers;
  });
  return out;
}

/** ŵ, â and M for nu, or null if nu puts mass on a value with no samples. */
export function readout(nu: number[], pHat: number[], supported: boolean[]): Readout | null {
  for (let i = 0; i < nu.length; i++) if (nu[i] > 0 && !supported[i]) return null;
  const w = nu.map((v, i) => (supported[i] ? v / pHat[i] : 0));
  const M = Math.max(...w);
  return { w, a: w.map((x) => x / M), M };
}

/** g#μ̂′ from the joint (f, g) count table and the Jeffrey weights of f's values. */
export function previewAfter(joint: number[][], w: number[]): number[] {
  const kg = joint[0]?.length ?? 0;
  const out = new Array<number>(kg).fill(0);
  let total = 0;
  joint.forEach((row, y) => {
    row.forEach((c, z) => {
      out[z] += w[y] * c;
      total += w[y] * c;
    });
  });
  return total > 0 ? out.map((x) => x / total) : out;
}

/** Kish's effective sample size of the reweighted cache: n / Σ ν(y)² / f#μ̂(y) (notes.tex). */
export function nEff(nu: number[], pHat: number[], n: number): number {
  let s = 0;
  nu.forEach((v, i) => {
    if (pHat[i] > 0) s += (v * v) / pHat[i];
  });
  return s > 0 ? n / s : 0;
}

export function uniform(supported: boolean[]): number[] {
  const m = supported.filter(Boolean).length;
  return supported.map((s) => (s ? 1 / m : 0));
}
