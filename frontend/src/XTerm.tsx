import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

type Mode = "job" | "stream" | "exec";

/**
 * Terminal bound to a websocket.
 *  job    – JSON messages {type: line|done|error, data}
 *  stream – raw text (container logs)
 *  exec   – interactive shell
 */
export function XTerm({ url, mode, onDone, height = 420 }: { url: string; mode: Mode; onDone?: (status: string) => void; height?: number | string }) {
  const ref = useRef<HTMLDivElement>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    const term = new Terminal({
      convertEol: mode !== "exec",
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",
      scrollback: 20000,
      cursorBlink: mode === "exec",
      disableStdin: mode !== "exec",
      theme: { background: "#0b0f17", foreground: "#d6deeb" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(ref.current!);
    try {
      fit.fit();
    } catch {}

    const ws = new WebSocket(url);
    let finished = false;
    ws.onmessage = (e) => {
      if (mode === "job") {
        const m = JSON.parse(e.data);
        if (m.type === "line") term.write(m.data);
        else if (m.type === "error") term.write(`\r\n\x1b[31m${m.data}\x1b[0m\r\n`);
        else if (m.type === "done") {
          finished = true;
          onDoneRef.current?.(m.data);
        }
      } else term.write(e.data);
    };
    ws.onclose = (e) => {
      if (e.code === 4401) term.write("\r\n\x1b[31m[нет доступа]\x1b[0m\r\n");
      else if (!finished) term.write("\r\n\x1b[90m[соединение закрыто]\x1b[0m\r\n");
    };

    const sendSize = () => {
      if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    };
    if (mode === "exec") {
      term.onData((d) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: "input", data: d })));
      term.onResize(sendSize);
      ws.onopen = () => {
        sendSize();
        term.focus();
      };
    }

    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {}
    });
    ro.observe(ref.current!);
    return () => {
      ro.disconnect();
      ws.close();
      term.dispose();
    };
  }, [url, mode]);

  return <div className="term" ref={ref} style={{ height }} />;
}
