// TeX helpers for KaTeX, kept free of React so they can be unit tested.

const TEXT_ESCAPES: Record<string, string> = {
  "\\": "\\textbackslash{}",
  "{": "\\{",
  "}": "\\}",
  $: "\\$",
  "&": "\\&",
  "#": "\\#",
  "^": "\\textasciicircum{}",
  _: "\\_",
  "%": "\\%",
  "~": "\\textasciitilde{}",
};

/** `s` (e.g. a view value's label) as TeX text, with TeX's special characters escaped. */
export function texText(s: string): string {
  return `\\text{${s.replace(/[\\{}$&#^_%~]/g, (c) => TEXT_ESCAPES[c])}}`;
}

// The Unicode math the server writes in its messages ("ν is blocked, so there is
// no μ̂′"): f#μ̂ or g#μ̂, μ̂, each optionally primed, P′, ν and ≈.
const UNICODE_MATH = /([fg])#\u03bc\u0302(\u2032?)|\u03bc\u0302(\u2032?)|P\u2032|\u03bd|\u2248/g;

function toTex(m: RegExpExecArray): string {
  if (m[1]) return `${m[1]}_\\#\\hat\\mu${m[2] ? "'" : ""}`;
  if (m[0].startsWith("\u03bc")) return `\\hat\\mu${m[3] ? "'" : ""}`;
  if (m[0] === "P\u2032") return "P'";
  if (m[0] === "\u03bd") return "\\nu";
  return "\\approx";
}

export type Piece = { text: string } | { tex: string };

/** Split text from the server into plain text and the TeX for its Unicode math. */
export function splitMath(s: string): Piece[] {
  const pieces: Piece[] = [];
  let at = 0;
  for (const m of s.matchAll(UNICODE_MATH)) {
    if (m.index > at) pieces.push({ text: s.slice(at, m.index) });
    pieces.push({ tex: toTex(m) });
    at = m.index + m[0].length;
  }
  if (at < s.length) pieces.push({ text: s.slice(at) });
  return pieces;
}
