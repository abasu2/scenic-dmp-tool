import { create } from "zustand";
import { ApiError } from "./api";
import type { ErrorInfo, Estimates, Job, ServerMessage, Validation, ViewErrorItem, ViewSpec, Workspace } from "./types";

export interface Draft {
  views: ViewSpec[];
  f: string | null;
}

export interface Selection {
  view: string;
  value: number;
}

interface Store {
  connected: boolean;
  workspace: Workspace | null;
  est: Estimates | null;
  dirty: boolean;
  programId: string | null;
  job: Job | null;
  /** Increments whenever a job finishes, so panels can refetch. */
  jobsFinished: number;
  validation: Validation | null;
  /** The views being edited; applied to the server with "Apply". */
  draft: Draft;
  draftDirty: boolean;
  viewErrors: ViewErrorItem[];
  /** ν while a bar is dragged, before it is sent to the server. */
  localNu: number[] | null;
  /** A view value picked by clicking a bar, which filters the scene gallery. */
  selection: Selection | null;
  notice: ErrorInfo | null;
  programError: ErrorInfo | null;
}

export const useStore = create<Store>(() => ({
  connected: false,
  workspace: null,
  est: null,
  dirty: false,
  programId: null,
  job: null,
  jobsFinished: 0,
  validation: null,
  draft: { views: [], f: null },
  draftDirty: false,
  viewErrors: [],
  localNu: null,
  selection: null,
  notice: null,
  programError: null,
}));

export const setStore = useStore.setState;

export function onMessage(msg: ServerMessage) {
  const s = useStore.getState();
  switch (msg.type) {
    case "workspace":
      setStore({ workspace: msg.workspace });
      if (!s.draftDirty) setStore({ draft: { views: msg.workspace.views, f: msg.workspace.f }, viewErrors: [] });
      break;
    case "state": {
      const est = msg.state.n > 0 ? (msg.state as Estimates) : null;
      setStore({ est, dirty: msg.dirty, programId: msg.program_id });
      // Forget a selected bar whose view or value no longer exists.
      const sel = s.selection;
      if (sel) {
        const labels = !est ? null : sel.view === est.view ? est.labels : est.previews.find((p) => p.name === sel.view)?.labels;
        if (!labels || sel.value >= labels.length) setStore({ selection: null });
      }
      break;
    }
    case "job": {
      const prev = s.job;
      const job = msg.job;
      setStore({ job });
      if (job?.running && !prev?.running) setStore({ programError: null });
      if (job && !job.running && prev?.running) setStore({ jobsFinished: s.jobsFinished + 1 });
      if (job && !job.running && job.error && (prev?.running || prev === null)) report(job.error);
      break;
    }
    case "validation":
      setStore({ validation: msg.validation });
      break;
  }
}

/** Show an error where it belongs: the editor, the view cards, or the notice bar. */
export function report(info: ErrorInfo) {
  if (info.where === "program" && info.line) {
    setStore({ programError: info });
  } else if (info.where === "views" && (info.errors?.length || info.view)) {
    const draft = useStore.getState().draft;
    const errors = info.errors?.length
      ? info.errors
      : [{ index: draft.views.findIndex((v) => v.name === info.view), view: info.view ?? null, field: info.field ?? null, message: info.message }];
    setStore({ viewErrors: errors });
  } else {
    setStore({ notice: info });
  }
}

/** Run a server command, reporting any error. Returns undefined on failure. */
export async function attempt<T>(fn: () => Promise<T>): Promise<T | undefined> {
  try {
    return await fn();
  } catch (e) {
    report(e instanceof ApiError ? e.info : { message: String(e) });
    return undefined;
  }
}
