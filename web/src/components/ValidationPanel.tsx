import { useState } from "react";
import { api } from "../api";
import { int, niceMax, pct, sig } from "../lib/format";
import { attempt, useStore } from "../store";
import { PAD, W, Whisker, XLabel, YAxis } from "./chart";
import { M } from "./Math";
import { tip } from "./Tip";

const PH = 130;

/** Sample P′ itself and compare f#μ̂_{P′} with ν, and its cost with the prediction. */
export function ValidationPanel() {
  const est = useStore((s) => s.est);
  const validation = useStore((s) => s.validation);
  const job = useStore((s) => s.job);
  const [n, setN] = useState(2000);
  if (!est) return null;

  const running = job?.running ?? false;
  const checking = running && job?.kind === "validate";
  const blocked = est.blocked.length > 0;
  const stale =
    validation !== null &&
    (validation.view !== est.view ||
      validation.nu.length !== est.nu.length ||
      validation.nu.some((x, i) => Math.abs(x - est.nu[i]) > 1e-9));
  const allIn = validation?.nu_in_ci.every(Boolean);

  return (
    <section className="card">
      <div className="card-head">
        <h2>
          Check <M tex="P'" /> by sampling it
        </h2>
        <div className="buttons">
          <label>
            n <input className="num wide-num" type="number" min={10} value={n} onChange={(e) => setN(Number(e.target.value))} />
          </label>
          <button
            className="primary"
            disabled={running || blocked}
            onClick={() => attempt(() => api.validate(n))}
            {...tip(
              blocked ? (
                <>
                  <M tex="\nu" /> is blocked
                </>
              ) : (
                <>
                  Compile <M tex="P'" /> and draw <M tex="n" /> scenes from it
                </>
              ),
            )}
          >
            {checking ? (
              <>
                Sampling <M tex="P'" />…
              </>
            ) : (
              <>
                Check <M tex="P'" />
              </>
            )}
          </button>
        </div>
      </div>
      {!validation && (
        <p className="muted">
          <M tex="P'" /> keeps a scene with view value <M tex="y" /> with probability <M tex="\hat a(y)" />. Sampling{" "}
          <M tex="P'" /> checks that <M tex="f_\#\hat\mu_{P'} \approx \nu" /> and measures what the patch costs.
        </p>
      )}
      {validation && (
        <>
          {stale && !checking && (
            <div className="banner">
              <M tex="\nu" /> or the view changed since this check. Check again.
            </div>
          )}
          <div className="readout">
            <span>
              <M tex="n =" /> <b>{int(validation.n)}</b>
              {validation.n < validation.target ? ` of ${int(validation.target)}` : ""}
            </span>
            <span>
              <M tex="P'" />: <b>{sig(validation.mean_iters)}</b> iterations/scene (predicted {sig(validation.predicted_iters)})
            </span>
            <span className={allIn ? "good" : "bad"}>
              <M tex="\nu" /> {allIn ? "is inside every 95% CI" : "is outside some 95% CIs"}
            </span>
          </div>
          <div className="legend">
            <span className="swatch nu-light" />
            <M tex="\nu" />
            <span className="swatch point" />
            <span>
              <M tex="f_\#\hat\mu_{P'}" /> with 95% CI
            </span>
          </div>
          <ValidationChart />
        </>
      )}
    </section>
  );
}

function ValidationChart() {
  const v = useStore((s) => s.validation)!;
  const K = v.labels.length;
  const rotate = K > 12;
  const H = PAD.t + PH + (rotate ? 52 : 24);
  const bw = (W - PAD.l - PAD.r) / K;
  const ymax = niceMax(Math.max(...v.ci_hi, ...v.nu) * 1.1);
  const base = PAD.t + PH;
  const yOf = (p: number) => PAD.t + PH * (1 - Math.min(p, ymax) / ymax);
  return (
    <svg className="chart-svg" viewBox={`0 0 ${W} ${H}`}>
      <YAxis ymax={ymax} top={PAD.t} height={PH} />
      {v.labels.map((label, k) => {
        const cx = PAD.l + bw * (k + 0.5);
        const w = bw * 0.6;
        return (
          <g
            key={k}
            className={`col${v.nu_in_ci[k] ? "" : " outside"}`}
            {...tip(
              <>
                {label}: <M tex="\nu =" /> {pct(v.nu[k])}, <M tex="f_\#\hat\mu_{P'} =" /> {pct(v.p_hat[k])} [
                {pct(v.ci_lo[k])}, {pct(v.ci_hi[k])}] ({v.counts[k]} of {v.n})
              </>,
            )}
          >
            <rect x={cx - w / 2} y={yOf(v.nu[k])} width={w} height={base - yOf(v.nu[k])} className="nu-light" />
            <Whisker cx={cx} lo={yOf(v.ci_lo[k])} hi={yOf(v.ci_hi[k])} cap={Math.min(6, bw * 0.15)} />
            <circle cx={cx} cy={yOf(v.p_hat[k])} r={3.5} className="point" />
            <XLabel cx={cx} y={base + 15} text={label} rotate={rotate} />
          </g>
        );
      })}
    </svg>
  );
}
