import { api } from "../api";
import { nEff, previewAfter, readout } from "../lib/jeffrey";
import { int, niceMax, pct } from "../lib/format";
import { attempt, setStore, useStore } from "../store";
import { PAD, W, XLabel, YAxis } from "./chart";
import { M } from "./Math";
import { tip } from "./Tip";

const PH = 120;

/** How a second view g changes under μ̂′, recomputed live from the (f, g) count table while ν is dragged. */
export function PreviewCard() {
  const est = useStore((s) => s.est);
  const localNu = useStore((s) => s.localNu);
  const selection = useStore((s) => s.selection);
  if (!est || est.previews.length === 0) return null;
  const preview = est.previews.find((p) => p.name === est.preview_name) ?? est.previews[0];
  const nu = localNu ?? est.nu;
  const ro = readout(nu, est.p_hat, est.supported);
  const n = preview.counts.reduce((a, b) => a + b, 0);
  const before = preview.counts.map((c) => c / n);
  const after = ro ? previewAfter(preview.joint, ro.w) : null;
  const neff = ro ? nEff(nu, est.p_hat, est.n) : null;

  const K = preview.labels.length;
  const rotate = K > 12;
  const H = PAD.t + PH + (rotate ? 52 : 24);
  const bw = (W - PAD.l - PAD.r) / K;
  const ymax = niceMax(Math.max(...before, ...(after ?? [0])) * 1.1);
  const base = PAD.t + PH;
  const yOf = (v: number) => PAD.t + PH * (1 - Math.min(v, ymax) / ymax);

  const choose = (name: string) => {
    setStore({ est: { ...est, preview_name: name } });
    attempt(() => api.setPreview(name));
  };

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          Preview of{" "}
          <select value={preview.name} onChange={(e) => choose(e.target.value)}>
            {est.previews.map((p) => (
              <option key={p.name} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>{" "}
          under <M tex="\hat\mu'" />
        </h2>
        <span className="muted" title="Kish effective sample size of the reweighted cached scenes">
          {neff !== null ? (
            <>
              <M tex="n_{\text{eff}} =" /> {int(neff)} of {int(est.n)}
            </>
          ) : (
            <>
              <M tex="\nu" /> is blocked
            </>
          )}
        </span>
      </div>
      <div className="legend">
        <span className="swatch ghost-solid" />
        <span>
          <M tex="g_\#\hat\mu" /> (now)
        </span>
        <span className="swatch nu" />
        <span>
          <M tex="g_\#\hat\mu'" /> (cached scenes reweighted by <M tex="\hat w" />)
        </span>
      </div>
      <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`}>
        <YAxis ymax={ymax} top={PAD.t} height={PH} />
        {preview.labels.map((label, k) => {
          const cx = PAD.l + bw * (k + 0.5);
          const w = bw * 0.38;
          const selected = selection?.view === preview.name && selection.value === k;
          const same = selected;
          return (
            <g
              key={k}
              className={`col clickable${selected ? " selected" : ""}`}
              onClick={() => setStore({ selection: same ? null : { view: preview.name, value: k } })}
              {...tip(
                <>
                  {label}: <M tex="g_\#\hat\mu =" /> {pct(before[k])}
                  {after && (
                    <>
                      , <M tex="g_\#\hat\mu' =" /> {pct(after[k])}
                    </>
                  )}
                </>,
              )}
            >
              <rect x={PAD.l + bw * k} y={PAD.t} width={bw} height={PH} className="hit" />
              <rect x={cx - w} y={yOf(before[k])} width={w} height={base - yOf(before[k])} className="ghost-solid" />
              {after && <rect x={cx} y={yOf(after[k])} width={w} height={base - yOf(after[k])} className="nu" />}
              <XLabel cx={cx} y={base + 15} text={label} rotate={rotate} />
            </g>
          );
        })}
      </svg>
    </section>
  );
}
