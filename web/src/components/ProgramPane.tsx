import { python } from "@codemirror/lang-python";
import { unifiedMergeView } from "@codemirror/merge";
import { lintGutter, setDiagnostics } from "@codemirror/lint";
import { EditorState } from "@codemirror/state";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { basicSetup } from "codemirror";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { basename, sig } from "../lib/format";
import { useStore } from "../store";
import type { Patch } from "../types";
import { M, MathText } from "./Math";

export function ProgramPane() {
  const [tab, setTab] = useState<"P" | "P'">("P");
  const dirty = useStore((s) => s.dirty);
  const path = useStore((s) => s.workspace?.program.path);
  const reveal = useStore((s) => s.reveal);
  useEffect(() => {
    if (reveal) setTab("P");
  }, [reveal]);
  return (
    <section className="program-pane">
      <div className="tabs">
        <button className={tab === "P" ? "on" : ""} onClick={() => setTab("P")}>
          <M tex="P" /> <span className="muted">{basename(path)}</span>
        </button>
        <button className={tab === "P'" ? "on" : ""} onClick={() => setTab("P'")}>
          <M tex="P'" /> <span className="muted">patched</span>
        </button>
      </div>
      {dirty && tab === "P" && (
        <div className="banner">The program changed since it was sampled. Sample again to apply it.</div>
      )}
      <div className="editor-host" style={{ display: tab === "P" ? undefined : "none" }}>
        <ProgramEditor />
      </div>
      {tab === "P'" && <PatchView />}
    </section>
  );
}

const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
const theme = [
  EditorView.theme({
    "&": { height: "100%", fontSize: "13px" },
    ".cm-scroller": { fontFamily: "var(--mono)" },
  }),
  ...(dark ? [oneDark] : []),
];

function ProgramEditor() {
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const rev = useRef(-1);
  const remote = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const sourceRev = useStore((s) => s.workspace?.source_rev);
  const programError = useStore((s) => s.programError);
  const reveal = useStore((s) => s.reveal);

  useEffect(() => {
    const v = new EditorView({
      parent: host.current!,
      state: EditorState.create({
        doc: "",
        extensions: [
          basicSetup,
          python(),
          lintGutter(),
          theme,
          EditorView.updateListener.of((u) => {
            if (!u.docChanged || remote.current) return;
            clearTimeout(timer.current);
            const source = u.state.doc.toString();
            timer.current = setTimeout(() => api.setProgram({ source }).catch(() => {}), 350);
          }),
        ],
      }),
    });
    view.current = v;
    return () => {
      clearTimeout(timer.current);
      v.destroy();
    };
  }, []);

  // Replace the text when the server opens or loads a program (not on our own edits).
  useEffect(() => {
    const v = view.current;
    const ws = useStore.getState().workspace;
    if (!v || !ws || ws.source_rev === rev.current) return;
    rev.current = ws.source_rev;
    remote.current = true;
    v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: ws.program.source } });
    remote.current = false;
  }, [sourceRev]);

  useEffect(() => {
    const v = view.current;
    if (!v) return;
    const diagnostics = [];
    if (programError?.line) {
      const doc = v.state.doc;
      const line = doc.line(Math.min(Math.max(programError.line, 1), doc.lines));
      const from = Math.min(line.from + Math.max((programError.column ?? 1) - 1, 0), line.to);
      diagnostics.push({ from, to: Math.max(line.to, from), severity: "error" as const, message: programError.message });
      v.dispatch({ effects: EditorView.scrollIntoView(from, { y: "center" }) });
    }
    v.dispatch(setDiagnostics(v.state, diagnostics));
  }, [programError]);

  // Select a line on request, e.g. a source view's `param view_<name> = ...`.
  useEffect(() => {
    const v = view.current;
    if (!v || !reveal) return;
    const doc = v.state.doc;
    const line = doc.line(Math.min(Math.max(reveal.line, 1), doc.lines));
    v.dispatch({
      selection: { anchor: line.from, head: line.to },
      effects: EditorView.scrollIntoView(line.from, { y: "center" }),
    });
    v.focus();
  }, [reveal]);

  return <div ref={host} className="editor" />;
}

function PatchView() {
  const est = useStore((s) => s.est);
  const localNu = useStore((s) => s.localNu);
  const path = useStore((s) => s.workspace?.program.path);
  const [patch, setPatch] = useState<Patch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const host = useRef<HTMLDivElement>(null);
  const view = useRef<EditorView | null>(null);
  const original = useRef<string | null>(null);

  useEffect(() => {
    if (!est) {
      setPatch(null);
      setError("Sample the program first.");
      return;
    }
    let cancelled = false;
    const t = setTimeout(
      async () => {
        try {
          const p = localNu ? await api.previewPatch(localNu) : await api.patch();
          if (!cancelled) {
            setPatch(p);
            setError(null);
          }
        } catch (e) {
          if (!cancelled) setError((e as Error).message);
        }
      },
      localNu ? 50 : 0,
    );
    return () => {
      cancelled = true;
      clearTimeout(t);
    };
  }, [est, localNu]);

  useEffect(() => {
    if (!patch || !host.current) return;
    if (view.current && original.current === patch.original) {
      const v = view.current;
      if (v.state.doc.toString() !== patch.source) {
        v.dispatch({ changes: { from: 0, to: v.state.doc.length, insert: patch.source } });
      }
      return;
    }
    view.current?.destroy();
    original.current = patch.original;
    const v = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: patch.source,
        extensions: [
          basicSetup,
          python(),
          theme,
          EditorState.readOnly.of(true),
          EditorView.editable.of(false),
          EditorView.lineWrapping,
          unifiedMergeView({
            original: patch.original,
            mergeControls: false,
            highlightChanges: false,
            collapseUnchanged: { margin: 3, minSize: 6 },
          }),
        ],
      }),
    });
    view.current = v;
    v.dispatch({ effects: EditorView.scrollIntoView(v.state.doc.length, { y: "end" }) });
  }, [patch]);

  useEffect(() => () => view.current?.destroy(), []);

  const download = () => {
    if (!patch) return;
    const name = basename(path).replace(/\.scenic$/, "") + "_patched.scenic";
    const url = URL.createObjectURL(new Blob([patch.source], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <div className="patch-head">
        {patch && !error ? (
          <span>
            Jeffrey patch for <code>{patch.view}</code>: <M tex="M =" /> {sig(patch.M)}, <M tex="P' \approx" />{" "}
            {sig(patch.predicted_iters)}{" "}
            iterations/scene{localNu ? " (dragging)" : ""}
          </span>
        ) : (
          <span className="muted">{error ? <MathText text={error} /> : "…"}</span>
        )}
        <span className="buttons">
          <button disabled={!patch || !!error} onClick={() => patch && navigator.clipboard.writeText(patch.source)}>
            Copy
          </button>
          <button disabled={!patch || !!error} onClick={download}>
            Download
          </button>
        </span>
      </div>
      <div ref={host} className="editor patch" style={{ opacity: error ? 0.4 : 1 }} />
    </>
  );
}
