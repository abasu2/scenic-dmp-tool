import katex from "katex";
import "katex/dist/katex.min.css";
import { splitMath } from "../lib/tex";

const rendered = new Map<string, string>();

function render(tex: string): string {
  let html = rendered.get(tex);
  if (html === undefined) {
    html = katex.renderToString(tex, { throwOnError: false, strict: "ignore" });
    rendered.set(tex, html);
  }
  return html;
}

/** Inline math typeset by KaTeX: <M tex="f_\#\hat\mu" />. */
export function M({ tex }: { tex: string }) {
  return <span className="math" dangerouslySetInnerHTML={{ __html: render(tex) }} />;
}

/** Text from the server, with its Unicode math (ν, P′, …) typeset by KaTeX. */
export function MathText({ text }: { text: string }) {
  return <>{splitMath(text).map((p, i) => ("tex" in p ? <M key={i} tex={p.tex} /> : p.text))}</>;
}
