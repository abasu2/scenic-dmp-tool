import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import { duration, int } from "../lib/format";
import { attempt, setStore, useStore } from "../store";
import { M } from "./Math";
import { applyViews } from "./ViewsPanel";

export function Toolbar() {
  const workspace = useStore((s) => s.workspace);
  const job = useStore((s) => s.job);
  const connected = useStore((s) => s.connected);
  const draftDirty = useStore((s) => s.draftDirty);
  const hasEstimates = useStore((s) => s.est !== null);
  const [n, setN] = useState(1000);
  const [seed, setSeed] = useState(0);
  const [popover, setPopover] = useState<"open" | "save" | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const running = job?.running ?? false;

  useEffect(() => {
    if (workspace) setSeed(workspace.seed);
  }, [workspace?.seed]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (workspace?.n) setN(workspace.n);
  }, [workspace?.n]);

  const sample = async (fresh: boolean) => {
    if (draftDirty) {
      if (!(await applyViews())) return;
      if (useStore.getState().job?.running) return; // applying new bindings already resamples
    }
    await attempt(() => api.sample(n, fresh, seed));
  };

  const loadFile = async (file: File) => {
    let data: unknown;
    try {
      data = JSON.parse(await file.text());
    } catch {
      setStore({ notice: { message: `${file.name} isn't a JSON workspace` } });
      return;
    }
    setStore({ draftDirty: false });
    await attempt(() => api.loadWorkspace({ workspace: data }));
  };

  const downloadWorkspace = async () => {
    const data = await attempt(api.workspace);
    if (!data) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "workspace.dmp.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <header className="toolbar">
      <span className="brand">
        scenic-dmp <span className={`dot ${connected ? "ok" : "bad"}`} title={connected ? "connected" : "disconnected"} />
      </span>

      <div className="group">
        <button onClick={() => setPopover(popover === "open" ? null : "open")} disabled={running}>
          Open…
        </button>
        <label className="check" title="Compile in 2D mode (needed by driving programs)">
          <input
            type="checkbox"
            checked={workspace?.program.mode2D ?? false}
            onChange={(e) => attempt(() => api.setProgram({ mode2D: e.target.checked }))}
          />{" "}
          2D
        </label>
      </div>

      <div className="group">
        <label>
          seed{" "}
          <input className="num" type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
        </label>
        <label>
          n{" "}
          <input
            className="num wide-num"
            type="number"
            min={1}
            value={n}
            onChange={(e) => setN(Math.max(1, Number(e.target.value)))}
          />
        </label>
        <button className="primary" onClick={() => sample(true)} disabled={running} title="Recompile and draw n new scenes">
          Sample
        </button>
        <button onClick={() => sample(false)} disabled={running || !hasEstimates} title="Add n more scenes">
          + {int(n)} more
        </button>
        {running && (
          <button className="danger" onClick={() => attempt(api.stop)}>
            Stop
          </button>
        )}
      </div>

      <Progress />

      <div className="group right">
        <button onClick={() => setPopover(popover === "save" ? null : "save")}>Save…</button>
        <button onClick={() => fileInput.current?.click()} disabled={running}>
          Load…
        </button>
        <button onClick={downloadWorkspace} title="Download the workspace as JSON">
          ⤓
        </button>
        <input
          ref={fileInput}
          type="file"
          accept=".json,application/json"
          hidden
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) loadFile(f);
            e.target.value = "";
          }}
        />
      </div>

      {popover === "open" && (
        <PathPopover
          title="Open a Scenic program from disk"
          placeholder="~/research/scenic-example/vendor/Scenic/examples/driving/badlyParkedCarPullingIn.scenic"
          initial={workspace?.program.path ?? ""}
          action="Open"
          onClose={() => setPopover(null)}
          onSubmit={async (path) => (await attempt(() => api.openProgram(path))) !== undefined}
        />
      )}
      {popover === "save" && (
        <PathPopover
          title={
            <>
              Save the workspace (program, views, <M tex="\nu" />) as JSON
            </>
          }
          placeholder="/path/to/workspace.dmp.json"
          initial={workspace?.program.path ? workspace.program.path.replace(/\.scenic$/, ".dmp.json") : ""}
          action="Save"
          onClose={() => setPopover(null)}
          onSubmit={async (path) => {
            const r = await attempt(() => api.saveWorkspace(path));
            if (r) setStore({ notice: { message: `Saved ${r.path}`, where: "info" } });
            return r !== undefined;
          }}
        />
      )}
    </header>
  );
}

function Progress() {
  const job = useStore((s) => s.job);
  if (!job) return <div className="progress" />;
  const what = (
    <>
      Sampling <M tex={job.kind === "sample" ? "P" : "P'"} />
    </>
  );
  if (job.running) {
    const eta = job.rate ? (job.target - job.done) / job.rate : NaN;
    return (
      <div className="progress">
        <div className="bar">
          <div style={{ width: `${(100 * job.done) / job.target}%` }} />
        </div>
        {job.note ? (
          `${job.note}…`
        ) : (
          <span>
            {what}: {int(job.done)} / {int(job.target)}
            {job.rate && job.done ? ` · ${int(job.rate)}/s · ${duration(eta)} left` : ""}
          </span>
        )}
      </div>
    );
  }
  if (job.error)
    return (
      <div className="progress bad">
        <span>{what} failed</span>
      </div>
    );
  return (
    <div className="progress muted">
      {job.stopped ? "Stopped" : "Done"}: {int(job.done)} scenes in {duration(job.elapsed)}
    </div>
  );
}

function PathPopover(props: {
  title: ReactNode;
  placeholder: string;
  initial: string;
  action: string;
  onClose: () => void;
  onSubmit: (path: string) => Promise<boolean>;
}) {
  const [path, setPath] = useState(props.initial);
  const submit = async () => {
    if (path.trim() && (await props.onSubmit(path.trim()))) props.onClose();
  };
  return (
    <div className="popover">
      <div className="muted">{props.title}</div>
      <input
        autoFocus
        className="mono"
        value={path}
        placeholder={props.placeholder}
        onChange={(e) => setPath(e.target.value)}
        onFocus={(e) => e.target.select()}
        onKeyDown={(e) => {
          if (e.key === "Enter") submit();
          if (e.key === "Escape") props.onClose();
        }}
      />
      <div className="buttons">
        <button className="primary" onClick={submit}>
          {props.action}
        </button>
        <button onClick={props.onClose}>Cancel</button>
      </div>
    </div>
  );
}
