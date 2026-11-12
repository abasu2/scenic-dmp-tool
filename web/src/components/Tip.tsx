import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import { create } from "zustand";

// A tooltip that can hold math, which the browser's `title` can't. Spread tip()'s
// props onto the element, and render <TipLayer /> once.

const ID = "tip";
const DELAY = 350;
const MARGIN = 6;

interface Shown {
  content: ReactNode;
  anchor: Element;
}

const useTip = create<{ shown: Shown | null }>(() => ({ shown: null }));

let timer: ReturnType<typeof setTimeout> | undefined;
/** Right after a tip hides, the next one shows at once, so moving along the bars of a chart reads them. */
let warmUntil = 0;
/** The focused element the shown tip describes, for screen readers. */
let described: Element | null = null;

function show(content: ReactNode, anchor: Element, focused?: Element) {
  clearTimeout(timer);
  if (!anchor.isConnected) return;
  described?.removeAttribute("aria-describedby");
  described = focused ?? null;
  described?.setAttribute("aria-describedby", ID);
  useTip.setState({ shown: { content, anchor } });
}

function hide() {
  clearTimeout(timer);
  described?.removeAttribute("aria-describedby");
  described = null;
  if (useTip.getState().shown) {
    warmUntil = performance.now() + DELAY;
    useTip.setState({ shown: null });
  }
}

/** Props that show `content` as a tooltip above the element on hover or keyboard focus. */
export function tip(content: ReactNode) {
  return {
    onMouseEnter: (e: React.MouseEvent) => {
      const anchor = e.currentTarget;
      clearTimeout(timer);
      if (useTip.getState().shown || performance.now() < warmUntil) show(content, anchor);
      else timer = setTimeout(() => show(content, anchor), DELAY);
    },
    onMouseLeave: hide,
    onPointerDown: hide,
    onFocus: (e: React.FocusEvent) => {
      if (e.target.matches(":focus-visible")) show(content, e.currentTarget, e.target);
    },
    onBlur: hide,
  };
}

export function TipLayer() {
  const shown = useTip((s) => s.shown);
  const box = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = box.current;
    if (!shown || !el) return;
    const a = shown.anchor.getBoundingClientRect();
    const { width, height } = el.getBoundingClientRect();
    const left = Math.max(MARGIN, Math.min(a.left + a.width / 2 - width / 2, window.innerWidth - width - MARGIN));
    const above = a.top - height - MARGIN;
    el.style.left = `${left}px`;
    el.style.top = `${above >= MARGIN ? above : a.bottom + MARGIN}px`;
    el.style.visibility = "visible";
  }, [shown]);

  // The anchor can re-render away or scroll off without a mouseleave.
  useEffect(() => {
    if (!shown) return;
    const onMove = (e: PointerEvent) => {
      if (!shown.anchor.isConnected || !shown.anchor.contains(e.target as Node)) hide();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide();
    document.addEventListener("pointermove", onMove);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("blur", hide);
    return () => {
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, true);
      window.removeEventListener("blur", hide);
    };
  }, [shown]);

  if (!shown) return null;
  return (
    <div ref={box} id={ID} className="tip" role="tooltip">
      {shown.content}
    </div>
  );
}
