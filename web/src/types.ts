// Shapes of the server's JSON (src/scenic_dmp/server.py, Session.state()).

export interface Binding {
  name: string;
  expr: string;
}

/** A view: a form view (bindings + Python expression) or a source view (`param view_<name> = <expr>` in P). */
export interface ViewSpec {
  name: string;
  /** Form views only. */
  bindings?: Binding[];
  /** The Python expression of a form view, or the Scenic expression of a source view. */
  expr: string;
  values?: string[];
  bins?: number[];
  /** Source views only: defined in the program, at this param and line. */
  source?: boolean;
  param?: string;
  line?: number | null;
}

export interface Workspace {
  program: { source: string; path: string | null; mode2D: boolean; params: Record<string, unknown> };
  source_rev: number;
  views: ViewSpec[];
  f: string | null;
  preview: string | null;
  seed: number;
  n: number;
}

export interface PreviewData {
  name: string;
  labels: string[];
  counts: number[];
  joint: number[][];
}

/** Session.state() once there are samples. */
export interface Estimates {
  n: number;
  seed: number;
  view: string;
  labels: string[];
  counts: number[];
  p_hat: number[];
  ci_lo: number[];
  ci_hi: number[];
  supported: boolean[];
  nu: number[];
  nu_edited: boolean;
  w: number[] | null;
  a: number[] | null;
  M: number | null;
  acceptance: number | null;
  mean_iters_P: number;
  blocked: string[];
  previews: PreviewData[];
  preview_name: string | null;
}

export interface ViewErrorItem {
  index: number;
  view: string | null;
  field: string | null;
  message: string;
}

export interface ErrorInfo {
  message: string;
  where?: string;
  line?: number | null;
  column?: number | null;
  view?: string | null;
  field?: string | null;
  errors?: ViewErrorItem[];
}

export interface Job {
  kind: "sample" | "validate";
  running: boolean;
  done: number;
  target: number;
  elapsed: number;
  rate: number | null;
  stopped: boolean;
  error: ErrorInfo | null;
  /** What the job is doing before sampling, e.g. detecting a view's values. */
  note: string | null;
}

export interface Validation {
  view: string;
  labels: string[];
  n: number;
  /** P′'s scenes whose value had samples in P: the ones compared with ν. */
  n_checked: number;
  target: number;
  counts: number[];
  /** Whether the value had samples in P. p_hat and its CI are out of n_checked if so, else out of n. */
  checked: boolean[];
  p_hat: number[];
  ci_lo: number[];
  ci_hi: number[];
  nu: number[];
  /** null for a value that isn't checked. */
  nu_in_ci: (boolean | null)[];
  mean_iters: number;
  predicted_iters: number;
  M: number;
}

export interface Patch {
  view: string;
  source: string;
  block: string;
  first_line: number;
  nu: number[];
  M: number;
  predicted_iters: number;
  original: string;
}

export interface SceneObject {
  cls: string;
  x: number;
  y: number;
  heading: number;
  width: number;
  length: number;
  footprint: [number, number][];
  ego: boolean;
}

export interface Scene {
  index: number;
  objects: SceneObject[];
  args: Record<string, string>;
  values: Record<string, string>;
}

export interface MapData {
  layers: Record<string, number[][][]>;
  bounds: [number, number, number, number];
}

export type ServerMessage =
  | { type: "workspace"; workspace: Workspace }
  | { type: "state"; state: Estimates | { n: 0 }; dirty: boolean; program_id: string | null }
  | { type: "job"; job: Job | null }
  | { type: "validation"; validation: Validation | null };
