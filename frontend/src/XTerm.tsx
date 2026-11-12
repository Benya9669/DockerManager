import { useEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { SearchAddon } from "@xterm/addon-search";
import "@xterm/xterm/css/xterm.css";
import { downloadFile, openWs } from "./api";
import { toastErr } from "./ui";

type Mode = "job" | "stream" | "exec";

const SEARCH_DECOR = {
  matchBackground: "#5a4a10", matchBorder: "#eab308", matchOverviewRuler: "#eab308",
  activeMatchBackground: "#b45309", activeMatchBorder: "#fde68a", activeMatchColorOverviewRuler: "#fde68a",
};

/**
 * Terminal bound to a websocket.
 *  job    – JSON messages {type: line|done|error, data}
 *  stream – raw text (container logs)
 *  exec   – interactive shell
 * `download` adds an export button (server-side file); search is available for job/stream modes.
 */
export function XTerm({ url, mode, onDone, height = 420, download }: {
  url: string; mode: Mode; onDone?: (status: string) => void; height?: number | string;
  download?: { path: string; filename: string };
}) {
  const ref = useRef<HTMLDivElement>(null);
  const searchRef = useRef<SearchAddon | null>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<{ idx: number; count: number } | null>(null);

  useEffect(() => {
    const term = new Terminal({
      convertEol: mode !== "exec",
      fontSize: 13,
      fontFamily: "'JetBrains Mono', 'Cascadia Mono', Consolas, monospace",
      scrollback: 50000,
      cursorBlink: mode === "exec",
      disableStdin: mode !== "exec",
      allowProposedApi: true,
      theme: { background: "#0b0f17", foreground: "#d6deeb" },
    });
    const fit = new FitAddon();
    const search = new SearchAddon();
    term.loadAddon(fit);
    term.loadAddon(search);
    searchRef.current = search;
    const sub = search.onDidChangeResults((r) => setMatches(r ? { idx: r.resultIndex, count: r.resultCount } : null));
    term.open(ref.current!);
    try {
      fit.fit();
    } catch {}

    let ws: WebSocket | null = null;
    let disposed = false;
    let finished = false;

    const wire = (ws: WebSocket) => {
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
      if (mode === "exec") {
        const sendSize = () => {
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
        };
        term.onData((d) => ws.readyState === WebSocket.OPEN && ws.send(JSON.stringify({ type: "input", data: d })));
        term.onResize(sendSize);
        ws.onopen = () => {
          sendSize();
          term.focus();
        };
      }
    };

    openWs(url)
      .then((s) => {
        if (disposed) return s.close();
        ws = s;
        wire(s);
      })
      .catch((e) => term.write(`\r\n\x1b[31m[ошибка подключения: ${e.message || e}]\x1b[0m\r\n`));

    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {}
    });
    ro.observe(ref.current!);
    return () => {
      disposed = true;
      sub.dispose();
      ro.disconnect();
      ws?.close();
      term.dispose();
      searchRef.current = null;
    };
  }, [url, mode]);

  const find = (dir: "next" | "prev") => {
    const s = searchRef.current;
    if (!s || !query) return;
    const opts = { caseSensitive: false, decorations: SEARCH_DECOR };
    if (dir === "next") s.findNext(query, opts);
    else s.findPrevious(query, opts);
  };

  return (
    <div className="stack-sm">
      {mode !== "exec" && (
        <div className="row term-bar">
          <input
            className="grow"
            placeholder="Поиск по выводу (Enter — следующее, Shift+Enter — предыдущее)"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (!e.target.value) {
                searchRef.current?.clearDecorations();
                setMatches(null);
              }
            }}
            onKeyDown={(e) => e.key === "Enter" && find(e.shiftKey ? "prev" : "next")}
          />
          {query && <span className="muted small">{matches ? (matches.count ? `${matches.idx + 1} / ${matches.count}` : "не найдено") : ""}</span>}
          <button className="btn sm" disabled={!query} onClick={() => find("prev")} title="предыдущее">↑</button>
          <button className="btn sm" disabled={!query} onClick={() => find("next")} title="следующее">↓</button>
          {download && (
            <button className="btn sm" title={query ? `скачать строки с «${query}»` : "скачать лог"}
              onClick={() => downloadFile(download.path + (query ? `${download.path.includes("?") ? "&" : "?"}grep=${encodeURIComponent(query)}` : ""), download.filename).catch(toastErr)}>
              ⬇ {query ? "Найденное" : "Скачать"}
            </button>
          )}
        </div>
      )}
      <div className="term" ref={ref} style={{ height }} />
    </div>
  );
}
