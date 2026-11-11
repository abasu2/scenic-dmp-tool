import { describe, expect, it } from "vitest";
import cases from "./jeffrey.fixture.json";
import { nEff, previewAfter, readout, rescale } from "./jeffrey";

// Cases come from the Python jeffrey module (scripts/jeffrey_fixture.py).
const close = (a: number[], b: number[]) => a.forEach((x, i) => expect(x).toBeCloseTo(b[i], 10));

describe("jeffrey.ts agrees with jeffrey.py", () => {
  it("rescale", () => {
    for (const c of cases) close(rescale(c.nu, c.y, c.t, c.supported), c.rescaled);
  });

  it("readout", () => {
    for (const c of cases) {
      const r = readout(c.nu, c.p_hat, c.supported)!;
      close(r.w, c.w);
      close(r.a, c.a);
      expect(r.M).toBeCloseTo(c.M, 10);
    }
  });

  it("preview and n_eff from the joint table", () => {
    for (const c of cases) {
      const supported = c.p_emp.map((p) => p > 0);
      const r = readout(c.nu_emp, c.p_emp, supported)!;
      close(previewAfter(c.joint, r.w), c.after);
      expect(nEff(c.nu_emp, c.p_emp, c.n)).toBeCloseTo(c.n_eff, 6);
    }
  });

  it("readout is null when ν has mass without samples", () => {
    expect(readout([0.5, 0.5], [1, 0], [true, false])).toBeNull();
  });
});
