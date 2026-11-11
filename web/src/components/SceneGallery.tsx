import { useEffect, useMemo, useState } from "react";
import { api, type ScenesSource } from "../api";
import { int } from "../lib/format";
import { setStore, useStore } from "../store";
import type { MapData, Scene, SceneObject } from "../types";

const MAP_ID = "dmp-map";
const LAYER_CLASS: Record<string, string> = {
  roadRegion: "road",
  intersectionRegion: "intersection",
  shoulderRegion: "shoulder",
  sidewalkRegion: "sidewalk",
  crossingRegion: "crossing",
};

/** Example scenes for a selected view value, from μ̂, μ̂′ (reweighted) or P′'s own samples. */
export function SceneGallery() {
  const est = useStore((s) => s.est);
  const selection = useStore((s) => s.selection);
  const programId = useStore((s) => s.programId);
  const jobsFinished = useStore((s) => s.jobsFinished);
  const hasValidation = useStore((s) => s.validation !== null);
  const [source, setSource] = useState<ScenesSource>("mu");
  const [shuffle, setShuffle] = useState(0);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [map, setMap] = useState<MapData | null>(null);
  const [open, setOpen] = useState<Scene | null>(null);

  const nuKey = source === "muprime" ? est?.nu.join(",") : "";
  const ready = est !== null;

  useEffect(() => {
    if (!programId) return;
    api.map().then((r) => setMap(r.map), () => setMap(null));
  }, [programId]);

  useEffect(() => {
    if (!ready) return;
    if (source === "pprime" && !hasValidation) {
      setScenes([]);
      setTotal(0);
      setError("Check P′ by sampling it first.");
      return;
    }
    let cancelled = false;
    api
      .scenes({ source, view: selection?.view, value: selection?.value, count: 12, seed: shuffle })
      .then(
        (r) => {
          if (cancelled) return;
          setScenes(r.scenes);
          setTotal(r.total);
          setError(null);
        },
        (e) => !cancelled && setError((e as Error).message),
      );
    return () => {
      cancelled = true;
    };
  }, [ready, source, selection?.view, selection?.value, shuffle, programId, jobsFinished, nuKey, hasValidation]);

  if (!est) return null;
  const selLabel =
    selection &&
    (selection.view === est.view
      ? est.labels[selection.value]
      : est.previews.find((p) => p.name === selection.view)?.labels[selection.value]);

  return (
    <section className="card">
      <div className="card-head">
        <h2>Example scenes</h2>
        <div className="buttons">
          <div className="segmented">
            {(
              [
                ["mu", "μ̂", "Scenes of P"],
                ["muprime", "μ̂′", "Scenes of P drawn with probability ∝ ŵ"],
                ["pprime", "P′", "Scenes sampled from P′"],
              ] as const
            ).map(([key, label, title]) => (
              <button key={key} className={source === key ? "on" : ""} title={title} onClick={() => setSource(key)}>
                {label}
              </button>
            ))}
          </div>
          <button onClick={() => setShuffle(shuffle + 1)} title="Draw other scenes">
            Shuffle
          </button>
        </div>
      </div>
      <div className="gallery-filter">
        {selection && selLabel !== undefined ? (
          <span className="chip">
            {selection.view} = {selLabel}
            <button className="icon" onClick={() => setStore({ selection: null })} title="Show all scenes">
              ×
            </button>
          </span>
        ) : (
          <span className="muted">All scenes. Click a bar to filter by its value.</span>
        )}
        {!error && <span className="muted">{int(total)} matching</span>}
      </div>
      {error && <div className="muted">{error}</div>}
      {map && <MapDefs map={map} />}
      <div className="gallery">
        {scenes.map((scene) => (
          <button key={`${source}-${scene.index}`} className="thumb" onClick={() => setOpen(scene)}>
            <SceneSvg scene={scene} hasMap={map !== null} />
            <div className="thumb-label">{Object.entries(scene.values).map(([k, v]) => `${k}=${v}`).join(" · ")}</div>
          </button>
        ))}
      </div>
      {open && <SceneModal scene={open} hasMap={map !== null} onClose={() => setOpen(null)} />}
    </section>
  );
}

function SceneModal({ scene, hasMap, onClose }: { scene: Scene; hasMap: boolean; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" onClick={onClose}>
      <div className="modal-body" onClick={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h2>Scene {scene.index}</h2>
          <button className="icon" onClick={onClose}>
            ×
          </button>
        </div>
        <SceneSvg scene={scene} hasMap={hasMap} large />
        <table className="kv">
          <tbody>
            {Object.entries(scene.values).map(([k, v]) => (
              <tr key={`v-${k}`}>
                <th>{k}</th>
                <td>{v}</td>
              </tr>
            ))}
            {Object.entries(scene.args).map(([k, v]) => (
              <tr key={`a-${k}`}>
                <th className="mono">{k}</th>
                <td className="mono">{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** The map's polygons, defined once and referenced by every scene drawing. */
function MapDefs({ map }: { map: MapData }) {
  const paths = useMemo(
    () =>
      Object.entries(map.layers).map(([name, polys]) => {
        let d = "";
        for (const rings of polys) {
          for (const ring of rings) {
            for (let i = 0; i < ring.length; i += 2) d += `${i === 0 ? "M" : "L"}${ring[i]} ${ring[i + 1]}`;
            d += "Z";
          }
        }
        return { name, d };
      }),
    [map],
  );
  return (
    <svg width={0} height={0} style={{ position: "absolute" }} aria-hidden>
      <defs>
        <g id={MAP_ID}>
          {paths.map(({ name, d }) => (
            <path key={name} d={d} className={`map ${LAYER_CLASS[name] ?? ""}`} fillRule="evenodd" />
          ))}
        </g>
      </defs>
    </svg>
  );
}

const PALETTE = ["#d97706", "#059669", "#7c3aed", "#db2777", "#0891b2", "#65a30d"];

function classColor(cls: string): string {
  let h = 0;
  for (const c of cls) h = (h * 31 + c.charCodeAt(0)) | 0;
  return PALETTE[Math.abs(h) % PALETTE.length];
}

/** A top-down drawing, framed on the objects. Scenic's y points up, so the drawing is flipped. */
function SceneSvg({ scene, hasMap, large }: { scene: Scene; hasMap: boolean; large?: boolean }) {
  const xs = scene.objects.flatMap((o) => o.footprint.map((p) => p[0]));
  const ys = scene.objects.flatMap((o) => o.footprint.map((p) => p[1]));
  let [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const size = Math.max(x1 - x0, y1 - y0, 3);
  const pad = Math.max(1, size * 0.15);
  const aspect = 4 / 3;
  let w = x1 - x0 + 2 * pad;
  let h = y1 - y0 + 2 * pad;
  if (w / h < aspect) w = h * aspect;
  else h = w / aspect;
  const cx = (x0 + x1) / 2;
  const cy = (y0 + y1) / 2;
  [x0, x1, y0, y1] = [cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2];
  return (
    <svg className={`scene${large ? " large" : ""}`} viewBox={`${x0} ${-y1} ${w} ${h}`}>
      <g transform="scale(1,-1)">
        {hasMap && <use href={`#${MAP_ID}`} />}
        {scene.objects.map((o, i) => (
          <SceneObj key={i} o={o} />
        ))}
      </g>
    </svg>
  );
}

function SceneObj({ o }: { o: SceneObject }) {
  const hx = -Math.sin(o.heading);
  const hy = Math.cos(o.heading);
  const r = o.length / 2;
  const deg = ((o.heading * 180) / Math.PI).toFixed(1);
  return (
    <g className={`obj${o.ego ? " ego" : ""}`} style={o.ego ? undefined : { color: classColor(o.cls) }}>
      <title>{`${o.ego ? "ego: " : ""}${o.cls}\n(${o.x.toFixed(2)}, ${o.y.toFixed(2)}), heading ${deg}°\n${o.width} × ${o.length}`}</title>
      <polygon points={o.footprint.map((p) => p.join(",")).join(" ")} vectorEffect="non-scaling-stroke" />
      <line x1={o.x} y1={o.y} x2={o.x + hx * r} y2={o.y + hy * r} vectorEffect="non-scaling-stroke" />
    </g>
  );
}
