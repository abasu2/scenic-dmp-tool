import { useId, useRef, useState } from "react";
import { api } from "../api";
import { readout, rescale, uniform } from "../lib/jeffrey";
import { int, niceMax, pct, sig } from "../lib/format";
import { attempt, setStore, useStore } from "../store";
import type { Estimates } from "../types";
import { Hatch, PAD, W, Whisker, XLabel, YAxis } from "./chart";

const PH = 190;

interface Drag {
  k: number;
  base: number[];
  ymax: number;
  sx: number;
  sy: number;
  active: boolean;
  id: number;
}

/** Send ν to the server, keeping it on screen until the server's state catches up. */
async function commit(nu: number[]) {
  const total = nu.reduce((a, b) => a + b, 0);
  const normalized = nu.map((x) => x / total);
  setStore((s) => ({
    localNu: null,
    est: s.est ? { ...s.est, nu: normalized, nu_edited: true } : s.est,
  }));
  await attempt(() => api.setNu(normalized));
}

export function NuCard() {
  const est = useStore((s) => s.est);
  const localNu = useStore((s) => s.localNu);
  const job = useStore((s) => s.job);
  if (!est) {
    return (
      <section className="card">
        <h2>Desired distribution ν</h2>
        <p className="muted">
          {job?.running ? "Sampling…" : "Define a view and sample the program to see f#μ̂ and edit ν."}
        </p>
      </section>
    );
  }
  const nu = localNu ?? est.nu;
  const ro = readout(nu, est.p_hat, est.supported);
  return (
    <section className="card">
      <div className="card-head">
        <h2>
          ν for <code>{est.view}</code>
        </h2>
        <div className="buttons">
          <button onClick={() => attempt(api.resetNu)} title="Make ν follow f#μ̂ again (no change to P)">
            Reset ν = f#μ̂
          </button>
          <button onClick={() => commit(uniform(est.supported))}>Uniform</button>
        </div>
      </div>
      <ReadoutLine est={est} ro={ro} nu={nu} />
      <div className="legend">
        <span className="swatch ghost" /> f#μ̂ with 95% CI <span className="swatch nu" /> ν (drag)
      </div>
      <NuChart est={est} nu={nu} />
      <p className="muted small">
        Drag a bar to set ν; the others rescale proportionally. Double-click to type a value. Click a bar to see
        its scenes.
      </p>
    </section>
  );
}

function ReadoutLine({ est, ro, nu }: { est: Estimates; ro: ReturnType<typeof readout>; nu: number[] }) {
  if (!ro) {
    const bad = est.labels.filter((_, i) => nu[i] > 0 && !est.supported[i]);
    return (
      <div className="status bad">
        ν puts mass on values with no samples: {bad.join(", ")}. Drag a bar, or use Reset or Uniform.
      </div>
    );
  }
  return (
    <div className="readout">
      <span>
        n = <b>{int(est.n)}</b>
      </span>
      <span>
        P: <b>{sig(est.mean_iters_P)}</b> iterations/scene
      </span>
      <span title="M = max ŵ(y)">
        M = <b>{sig(ro.M)}</b>
      </span>
      <span title="The fraction of P's scenes the patch keeps">
        acceptance 1/M = <b>{pct(1 / ro.M)}</b>
      </span>
      <span title="P's iterations per scene × M">
        P′ ≈ <b>{sig(est.mean_iters_P * ro.M)}</b> iterations/scene
      </span>
    </div>
  );
}

function NuChart({ est, nu }: { est: Estimates; nu: number[] }) {
  const selection = useStore((s) => s.selection);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);
  const lastClick = useRef<{ k: number; t: number } | null>(null);
  const [editor, setEditor] = useState<{ k: number; text: string } | null>(null);
  const hatchId = useId().replace(/:/g, "") + "hatch";

  const ro = readout(nu, est.p_hat, est.supported);
  const K = est.labels.length;
  const rows = K <= 12;
  const H = PAD.t + PH + (rows ? 54 : 72);
  const bw = (W - PAD.l - PAD.r) / K;
  const ymax = drag.current?.active ? drag.current.ymax : niceMax(Math.max(...est.ci_hi, ...nu) * 1.1);
  const base = PAD.t + PH;
  const yOf = (p: number) => PAD.t + PH * (1 - Math.min(p, ymax) / ymax);

  const toLocal = (e: React.PointerEvent) => {
    const svg = svgRef.current!;
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    return pt.matrixTransform(svg.getScreenCTM()!.inverse());
  };

  const columnAt = (e: React.PointerEvent) => {
    const p = toLocal(e);
    if (p.y < PAD.t - 8 || p.y > base + 4) return -1;
    const k = Math.floor((p.x - PAD.l) / bw);
    return k >= 0 && k < K ? k : -1;
  };

  const onPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const k = columnAt(e);
    if (k < 0) return;
    drag.current = { k, base: nu.slice(), ymax, sx: e.clientX, sy: e.clientY, active: false, id: e.pointerId };
    svgRef.current!.setPointerCapture(e.pointerId);
    e.preventDefault();
  };

  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.id || !est.supported[d.k]) return;
    if (!d.active && Math.hypot(e.clientX - d.sx, e.clientY - d.sy) < 3) return;
    d.active = true;
    const t = ((base - toLocal(e).y) / PH) * d.ymax;
    setStore({ localNu: rescale(d.base, d.k, t, est.supported) });
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d || e.pointerId !== d.id) return;
    drag.current = null;
    const local = useStore.getState().localNu;
    if (d.active && local) {
      lastClick.current = null;
      commit(local);
      return;
    }
    if (e.type !== "pointerup") return;
    // A click selects the value for the scene gallery; a second click opens the editor.
    const now = performance.now();
    if (lastClick.current && lastClick.current.k === d.k && now - lastClick.current.t < 400) {
      lastClick.current = null;
      if (est.supported[d.k]) setEditor({ k: d.k, text: (100 * nu[d.k]).toFixed(1) });
    } else {
      lastClick.current = { k: d.k, t: now };
      const sel = useStore.getState().selection;
      const same = sel && sel.view === est.view && sel.value === d.k;
      setStore({ selection: same ? null : { view: est.view, value: d.k } });
    }
  };

  const submitEditor = () => {
    if (!editor) return;
    const v = parseFloat(editor.text);
    setEditor(null);
    if (Number.isFinite(v)) commit(rescale(nu, editor.k, v / 100, est.supported));
  };

  return (
    <div className="chart">
      <svg
        ref={svgRef}
        className="chart-svg draggable"
        viewBox={`0 0 ${W} ${H}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        <Hatch id={hatchId} />
        <YAxis ymax={ymax} top={PAD.t} height={PH} />
        {est.labels.map((label, k) => {
          const cx = PAD.l + bw * (k + 0.5);
          const selected = selection?.view === est.view && selection.value === k;
          const active = drag.current?.active && drag.current.k === k;
          let tip = `${label}: ${est.counts[k]} of ${est.n} (${pct(est.p_hat[k])}), 95% CI [${pct(est.ci_lo[k])}, ${pct(est.ci_hi[k])}]\nν = ${pct(nu[k])}`;
          if (ro && est.supported[k]) tip += `\nŵ = ${sig(ro.w[k])}, â = ${sig(ro.a[k])}`;
          if (!est.supported[k]) tip += "\nNo samples, so ν is locked at 0.";
          const gw = bw * 0.8;
          const nw = bw * 0.46;
          return (
            <g
              key={k}
              className={`col${est.supported[k] ? "" : " unsupported"}${active ? " active" : ""}${selected ? " selected" : ""}`}
            >
              <title>{tip}</title>
              <rect x={PAD.l + bw * k} y={PAD.t} width={bw} height={PH} className="hit" />
              {est.supported[k] ? (
                <>
                  <rect x={cx - gw / 2} y={yOf(est.p_hat[k])} width={gw} height={base - yOf(est.p_hat[k])} className="ghost" />
                  <rect x={cx - nw / 2} y={yOf(nu[k])} width={nw} height={base - yOf(nu[k])} className="nu" />
                  <Whisker cx={cx} lo={yOf(est.ci_lo[k])} hi={yOf(est.ci_hi[k])} cap={Math.min(6, bw * 0.15)} />
                </>
              ) : (
                <>
                  <rect x={cx - bw * 0.4} y={PAD.t} width={bw * 0.8} height={PH} fill={`url(#${hatchId})`} />
                  <text x={cx} y={base - 6} textAnchor="middle" className="muted">
                    0 of {int(est.n)}
                  </text>
                </>
              )}
              <XLabel cx={cx} y={base + 15} text={label} rotate={!rows} />
              {rows && ro && est.supported[k] && (
                <>
                  <text x={cx} y={base + 31} textAnchor="middle" className="muted">
                    ŵ {sig(ro.w[k])}
                  </text>
                  <text x={cx} y={base + 46} textAnchor="middle" className="muted">
                    â {sig(ro.a[k])}
                  </text>
                </>
              )}
            </g>
          );
        })}
      </svg>
      {editor && (
        <div className="bar-editor" style={{ left: `${((PAD.l + bw * (editor.k + 0.5)) / W) * 100}%` }}>
          ν({est.labels[editor.k]}) ={" "}
          <input
            autoFocus
            type="number"
            min={0}
            max={100}
            step={0.1}
            value={editor.text}
            onChange={(e) => setEditor({ ...editor, text: e.target.value })}
            onKeyDown={(e) => {
              if (e.key === "Enter") submitEditor();
              if (e.key === "Escape") setEditor(null);
            }}
            onBlur={() => setEditor(null)}
          />{" "}
          %
        </div>
      )}
    </div>
  );
}
