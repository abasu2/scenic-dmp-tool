import { useEffect, useState } from "react";
import { api } from "../api";
import { niceBins } from "../lib/format";
import { attempt, setStore, useStore } from "../store";
import type { ViewErrorItem, ViewSpec } from "../types";

function splitList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

function parseBins(text: string): number[] {
  return text
    .split(/[\s,]+/)
    .filter((s) => s.length > 0)
    .map(Number);
}

function newView(existing: ViewSpec[]): ViewSpec {
  let i = existing.length + 1;
  while (existing.some((v) => v.name === `view${i}`)) i++;
  return { name: `view${i}`, bindings: [{ name: "x", expr: "" }], expr: "x", values: [] };
}

/** Apply the draft views; the server reclassifies or resamples as needed. */
export async function applyViews(): Promise<boolean> {
  const { draft, workspace } = useStore.getState();
  const r = await attempt(() => api.setViews(draft.views, draft.f, workspace?.preview ?? null));
  if (!r) return false;
  setStore({ draft: { views: r.views, f: r.f }, draftDirty: false, viewErrors: [] });
  return true;
}

export function ViewsPanel() {
  const draft = useStore((s) => s.draft);
  const draftDirty = useStore((s) => s.draftDirty);
  const viewErrors = useStore((s) => s.viewErrors);
  const workspace = useStore((s) => s.workspace);
  const running = useStore((s) => s.job?.running ?? false);

  const update = (views: ViewSpec[], f = draft.f) => setStore({ draft: { views, f }, draftDirty: true });

  const chooseF = async (name: string) => {
    if (draftDirty) {
      update(draft.views, name);
      return;
    }
    setStore({ draft: { ...draft, f: name } });
    const r = await attempt(() => api.setViews(draft.views, name, workspace?.preview ?? null));
    if (r) setStore({ draft: { views: r.views, f: r.f } });
    else setStore({ draft });
  };

  const revert = () =>
    setStore({
      draft: { views: workspace?.views ?? [], f: workspace?.f ?? null },
      draftDirty: false,
      viewErrors: [],
    });

  const f = draft.f ?? draft.views[0]?.name ?? null;
  return (
    <section className="card">
      <div className="card-head">
        <h2>Views</h2>
        <button onClick={() => update([...draft.views, newView(draft.views)])} disabled={running}>
          + Add view
        </button>
      </div>
      {draft.views.length === 0 && (
        <p className="muted">
          A view f maps a scene to a finite set of values. Bind names to Scenic expressions, then write f as a Python
          expression over those names.
        </p>
      )}
      {draft.views.map((spec, i) => (
        <ViewCard
          key={i}
          spec={spec}
          isF={spec.name === f}
          errors={viewErrors.filter((e) => e.index === i)}
          disabled={running}
          onChange={(next) => {
            const views = draft.views.slice();
            views[i] = next;
            update(views, spec.name === f ? next.name : draft.f);
          }}
          onRemove={() => update(draft.views.filter((_, j) => j !== i), spec.name === f ? null : draft.f)}
          onChooseF={() => chooseF(spec.name)}
        />
      ))}
      {draftDirty && (
        <div className="apply-bar">
          <span className="muted">Views changed.</span>
          <button className="primary" onClick={applyViews} disabled={running}>
            Apply
          </button>
          <button onClick={revert}>Revert</button>
        </div>
      )}
    </section>
  );
}

function ViewCard(props: {
  spec: ViewSpec;
  isF: boolean;
  errors: ViewErrorItem[];
  disabled: boolean;
  onChange: (spec: ViewSpec) => void;
  onRemove: () => void;
  onChooseF: () => void;
}) {
  const { spec, isF, errors, disabled, onChange } = props;
  const kind = spec.bins !== undefined ? "bins" : "values";
  const [valuesText, setValuesText] = useState((spec.values ?? []).join(", "));
  const [binsText, setBinsText] = useState((spec.bins ?? []).join(", "));
  const [detecting, setDetecting] = useState(false);

  // Follow changes from outside (apply, load) without fighting the text being typed.
  useEffect(() => {
    if (splitList(valuesText).join("\n") !== (spec.values ?? []).join("\n")) setValuesText((spec.values ?? []).join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.values]);
  useEffect(() => {
    if (parseBins(binsText).join("\n") !== (spec.bins ?? []).join("\n")) setBinsText((spec.bins ?? []).join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec.bins]);

  const err = (field: string) => errors.filter((e) => e.field === field).map((e) => e.message);
  const other = errors.filter((e) => !["name", "bindings", "expr", "values", "bins"].includes(e.field ?? ""));

  const setBinding = (j: number, key: "name" | "expr", value: string) => {
    const bindings = spec.bindings.map((b, i) => (i === j ? { ...b, [key]: value } : b));
    onChange({ ...spec, bindings });
  };

  const setKind = (k: "values" | "bins") => {
    if (k === kind) return;
    const { values: _v, bins: _b, ...rest } = spec;
    onChange(k === "bins" ? { ...rest, bins: parseBins(binsText) } : { ...rest, values: splitList(valuesText) });
  };

  const detect = async () => {
    setDetecting(true);
    const r = await attempt(() => api.detect(spec));
    setDetecting(false);
    if (!r) return;
    const { values: _v, bins: _b, ...rest } = spec;
    if (r.values) {
      setValuesText(r.values.join(", "));
      onChange({ ...rest, values: r.values });
    } else if (r.numeric && r.min !== undefined && r.max !== undefined) {
      const bins = niceBins(r.min, r.max);
      setBinsText(bins.join(", "));
      onChange({ ...rest, bins });
    } else {
      setStore({ notice: { message: `view ${spec.name}: too many distinct non-numeric values to list` } });
    }
  };

  const argList = spec.bindings.map((b) => b.name || "?").join(", ");
  return (
    <div className={`view-card${isF ? " is-f" : ""}${errors.length ? " has-error" : ""}`}>
      <div className="view-head">
        <input
          className="view-name"
          value={spec.name}
          onChange={(e) => onChange({ ...spec, name: e.target.value })}
          disabled={disabled}
          aria-label="View name"
        />
        <label className="radio" title="Edit ν on this view; the others are previews">
          <input type="radio" checked={isF} onChange={props.onChooseF} disabled={disabled} /> edit ν
        </label>
        <button className="icon" onClick={props.onRemove} disabled={disabled} title="Remove view">
          ×
        </button>
      </div>
      <Errors messages={err("name")} />

      <div className="field-label">Bindings (name = Scenic expression)</div>
      {spec.bindings.map((b, j) => (
        <div className="binding" key={j}>
          <input
            className="mono bname"
            value={b.name}
            onChange={(e) => setBinding(j, "name", e.target.value)}
            disabled={disabled}
            aria-label="Binding name"
          />
          <span>=</span>
          <input
            className="mono"
            value={b.expr}
            placeholder="distance from ego to ped"
            onChange={(e) => setBinding(j, "expr", e.target.value)}
            disabled={disabled}
            aria-label="Scenic expression"
          />
          <button
            className="icon"
            onClick={() => onChange({ ...spec, bindings: spec.bindings.filter((_, i) => i !== j) })}
            disabled={disabled || spec.bindings.length <= 1}
            title="Remove binding"
          >
            ×
          </button>
        </div>
      ))}
      <button
        className="link"
        onClick={() => onChange({ ...spec, bindings: [...spec.bindings, { name: "", expr: "" }] })}
        disabled={disabled}
      >
        + binding
      </button>
      <Errors messages={err("bindings")} />

      <div className="field-label">
        f({argList}) = <span className="muted">Python expression; isclose, deg, sqrt, … available</span>
      </div>
      <input
        className="mono wide"
        value={spec.expr}
        onChange={(e) => onChange({ ...spec, expr: e.target.value })}
        disabled={disabled}
        aria-label="View expression"
      />
      <Errors messages={err("expr")} />

      <div className="y-row">
        <div className="segmented">
          <button className={kind === "values" ? "on" : ""} onClick={() => setKind("values")} disabled={disabled}>
            values
          </button>
          <button className={kind === "bins" ? "on" : ""} onClick={() => setKind("bins")} disabled={disabled}>
            bins
          </button>
        </div>
        {kind === "values" ? (
          <input
            className="mono wide"
            value={valuesText}
            placeholder="brake, continue"
            onChange={(e) => {
              setValuesText(e.target.value);
              onChange({ ...spec, values: splitList(e.target.value) });
            }}
            disabled={disabled}
            aria-label="Values"
          />
        ) : (
          <input
            className="mono wide"
            value={binsText}
            placeholder="20, 25, 30, 35"
            onChange={(e) => {
              setBinsText(e.target.value);
              onChange({ ...spec, bins: parseBins(e.target.value) });
            }}
            disabled={disabled}
            aria-label="Bin edges"
          />
        )}
        <button onClick={detect} disabled={disabled || detecting} title="Fill in from sampled scenes">
          {detecting ? "Detecting…" : "Detect"}
        </button>
      </div>
      <Errors messages={[...err("values"), ...err("bins"), ...other.map((e) => e.message)]} />
    </div>
  );
}

function Errors({ messages }: { messages: string[] }) {
  if (messages.length === 0) return null;
  return (
    <div className="field-error">
      {messages.map((m, i) => (
        <div key={i}>{m}</div>
      ))}
    </div>
  );
}
