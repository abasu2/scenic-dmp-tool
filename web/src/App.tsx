import { useEffect } from "react";
import { connect } from "./api";
import { NuCard } from "./components/NuChart";
import { PreviewCard } from "./components/PreviewChart";
import { ProgramPane } from "./components/ProgramPane";
import { MathText } from "./components/Math";
import { SceneGallery } from "./components/SceneGallery";
import { TipLayer } from "./components/Tip";
import { Toolbar } from "./components/Toolbar";
import { ValidationPanel } from "./components/ValidationPanel";
import { ViewsPanel } from "./components/ViewsPanel";
import { onMessage, setStore, useStore } from "./store";

export function App() {
  useEffect(() => connect(onMessage, (connected) => setStore({ connected })), []);
  return (
    <div className="app">
      <Toolbar />
      <Notice />
      <main className="layout">
        <ProgramPane />
        <div className="side">
          <ViewsPanel />
          <NuCard />
          <PreviewCard />
          <ValidationPanel />
          <SceneGallery />
        </div>
      </main>
      <TipLayer />
    </div>
  );
}

function Notice() {
  const notice = useStore((s) => s.notice);
  if (!notice) return null;
  return (
    <div className={`notice${notice.where === "info" ? " info" : ""}`}>
      <span>
        <MathText text={notice.message} />
      </span>
      <button className="icon" onClick={() => setStore({ notice: null })}>
        ×
      </button>
    </div>
  );
}
