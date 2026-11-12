import katex from "katex";
import { describe, expect, it } from "vitest";
import { splitMath, texText } from "./tex";

describe("splitMath", () => {
  it("typesets the server's Unicode math and keeps the rest as text", () => {
    expect(splitMath("ν is blocked, so there is no μ̂′")).toEqual([
      { tex: "\\nu" },
      { text: " is blocked, so there is no " },
      { tex: "\\hat\\mu'" },
    ]);
  });

  it("reads pushforwards and P′ as single symbols", () => {
    expect(splitMath("f#μ̂ ≈ ν in P′")).toEqual([
      { tex: "f_\\#\\hat\\mu" },
      { text: " " },
      { tex: "\\approx" },
      { text: " " },
      { tex: "\\nu" },
      { text: " in " },
      { tex: "P'" },
    ]);
  });

  it("leaves text without math alone", () => {
    expect(splitMath("sample the program first")).toEqual([{ text: "sample the program first" }]);
    expect(splitMath("")).toEqual([]);
  });
});

describe("texText", () => {
  it("escapes TeX's special characters so KaTeX accepts any label", () => {
    const label = String.raw`a_b {c} 5% #1 ~x^2 \ $ &`;
    expect(() => katex.renderToString(texText(label), { throwOnError: true, strict: "error" })).not.toThrow();
  });
});
