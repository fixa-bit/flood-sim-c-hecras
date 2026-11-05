import { useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent, ReactNode } from "react";

const STEP = 40;

/**
 * A pane whose height the viewer drags with the bar below it. Double-click
 * the bar (or press End) to fit the whole content; Home returns to the
 * shared default height. Arrow keys resize in steps.
 */
export function ResizablePane({
  label,
  minHeight = 140,
  children,
}: {
  label: string;
  minHeight?: number;
  children: ReactNode;
}) {
  const body = useRef<HTMLDivElement>(null);
  const [height, setHeight] = useState<number>();
  const clamp = (value: number) => Math.max(minHeight, Math.round(value));
  const full = () => body.current?.scrollHeight ?? minHeight;

  const drag = (event: PointerEvent<HTMLDivElement>) => {
    const pane = body.current;
    if (!pane || event.button !== 0) return;
    event.preventDefault();
    const top = pane.getBoundingClientRect().top;
    const handle = event.currentTarget;
    handle.setPointerCapture(event.pointerId);
    const move = (next: globalThis.PointerEvent) =>
      setHeight(clamp(Math.min(next.clientY - top, full())));
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  };

  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const current = body.current?.clientHeight ?? minHeight;
    const next = {
      ArrowDown: () => clamp(Math.min(current + STEP, full())),
      ArrowUp: () => clamp(current - STEP),
      End: () => clamp(full()),
      Home: () => undefined,
    }[event.key];
    if (!next) return;
    event.preventDefault();
    setHeight(next());
  };

  return (
    <div className={`resizable-pane ${height ? "sized" : ""}`}>
      <div
        ref={body}
        className="resizable-pane-body"
        style={height ? { height } : undefined}
      >
        {children}
      </div>
      <div
        role="separator"
        aria-orientation="horizontal"
        aria-label={`Resize ${label}`}
        aria-valuemin={minHeight}
        aria-valuenow={height}
        tabIndex={0}
        className="pane-splitter"
        title="Drag to resize · double-click to show all"
        onPointerDown={drag}
        onDoubleClick={() =>
          setHeight(height && height >= full() ? undefined : clamp(full()))
        }
        onKeyDown={keys}
      >
        <i />
      </div>
    </div>
  );
}
