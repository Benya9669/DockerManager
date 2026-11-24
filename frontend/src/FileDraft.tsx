import { useEffect, useRef, useState } from "react";
import { useBlocker } from "react-router-dom";
import { api, ApiError } from "./api";
import { Editor } from "./Editor";
import { t } from "./i18n";
import { ActionButton, Modal, toast, toastErr } from "./ui";

export function isEnv(path: string) {
  return /(^|\/)(\.env($|\.)|[^/]+\.env$)|^(env|envs|\.envs)\//i.test(path);
}

// Only named assignments are shown in safe view. Continuation lines stay with their key.
function variables(text: string) {
  const entries = new Map<string, string[]>();
  let key = "", quote = "";
  for (const line of text.split(/\r?\n/)) {
    if (quote && key) {
      const values = entries.get(key)!;
      values[values.length - 1] += "\n" + line;
      if (line.includes(quote)) quote = "";
      continue;
    }
    const m = /^\s*(?:export\s+)?([\w.-]+)\s*=\s*(.*)$/.exec(line);
    if (!m) continue;
    key = m[1];
    const value = m[2];
    const values = entries.get(key) || [];
    entries.set(key, [...values, value]);
    if ((value[0] === '"' || value[0] === "'") && !value.slice(1).includes(value[0])) quote = value[0];
  }
  return entries;
}

function Changes({ before, after }: { before: string; after: string }) {
  const a = variables(before), b = variables(after);
  return <ul>{[...new Set([...a.keys(), ...b.keys()])].filter(k => JSON.stringify(a.get(k)) !== JSON.stringify(b.get(k))).map(k =>
    <li key={k}><code>{k}</code> · {t(!a.has(k) ? "Добавлена" : !b.has(k) ? "Удалена" : "Изменена")}</li>)}</ul>;
}

export function DraftEditor({ path, value, change, env }: { path: string; value: string; change: (s: string) => void; env: boolean }) {
  const [raw, setRaw] = useState(false);
  const [visible, setVisible] = useState<string | null>(null);
  if (!env) return <Editor filename={path} value={value} onChange={change} />;
  return <div className="stack-sm">
    <button className="btn sm" onClick={() => { setRaw(!raw); setVisible(null); }}>{t(raw ? "Скрыть значения" : "Редактировать открытым текстом")}</button>
    {raw ? <Editor filename={path} value={value} onChange={change}/> :
      <div className="env-values">{Array.from(variables(value), ([key, values]) =>
        <div className="row between pad" key={key}><code>{key} = {visible === key ? values.join("\n") : "••••••"}</code>
          <button className="btn sm" onClick={() => setVisible(visible === key ? null : key)}>{t(visible === key ? "Скрыть" : "Показать")}</button></div>)}</div>}
  </div>;
}

type Guard = (next: () => void) => void;

export function useDraft(projectId: number, path: string | null, env: boolean) {
  const [content, setContent] = useState(""), [orig, setOrig] = useState("");
  const [revision, setRevision] = useState<string | null>(null);
  const [binary, setBinary] = useState(false), [ready, setReady] = useState("");
  const [conflict, setConflict] = useState<{content:string;revision:string} | null>(null);
  const [review, setReview] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const pending = useRef<(() => void) | null>(null);
  const dirty = content !== orig;
  useEffect(() => {
    let active = true;
    setRevision(null); setReady(""); setContent(""); setOrig(""); setConflict(null); setReview(false);
    if (path) api(`/projects/${projectId}/files?path=${encodeURIComponent(path)}`).then(r => {
      if (!active) return;
      setContent(r.content); setOrig(r.content); setRevision(r.revision); setBinary(r.binary); setReady(path);
    }).catch(e => active && toastErr(e));
    return () => { active = false; };
  }, [projectId, path]);
  const guard: Guard = next => {
    if (!dirty) return next();
    pending.current = next; setLeaving(true);
  };
  const blocker = useBlocker(({currentLocation, nextLocation}) => dirty &&
    (currentLocation.pathname !== nextLocation.pathname || currentLocation.search !== nextLocation.search));
  useEffect(() => {
    if (blocker.state === "blocked") {
      pending.current = blocker.proceed;
      setLeaving(true);
    }
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const unload = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);
  const finish = () => {
    const next = pending.current;
    pending.current = null;
    setLeaving(false);
    setReview(false);
    next?.();
  };
  const stay = () => { if (blocker.state === "blocked") blocker.reset(); pending.current = null; setLeaving(false); setReview(false); setConflict(null); };
  const write = async () => {
    if (!revision || !path || ready !== path) return;
    try {
      const r = await api(`/projects/${projectId}/files`, {method:"PUT", body:{path, content, revision}});
      setRevision(r.revision); setOrig(content); toast(t("Сохранено")); finish();
    } catch (e) {
      if (!(e instanceof ApiError) || e.status !== 409) throw e;
      let remote;
      try { remote = await api(`/projects/${projectId}/files?path=${encodeURIComponent(path)}`); }
      catch (err) { if (!(err instanceof ApiError) || err.status !== 404) throw err; remote = {content:"", revision:"missing"}; }
      if (remote.binary || remote.type === "dir") throw Error(t("Файл заменён на сервере"));
      stay(); setConflict(remote);
    }
  };
  const save = async () => { setLeaving(false); if (env) setReview(true); else await write(); };
  const dialogs = <>
    {leaving && <Modal title={t("Несохранённые изменения")} onClose={stay}><p>{path}</p><div className="row">
      <ActionButton onClick={save}>{t("Сохранить")}</ActionButton><button className="btn" onClick={finish}>{t("Отбросить")}</button><button className="btn" onClick={stay}>{t("Остаться")}</button></div></Modal>}
    {review && <Modal title={t("Изменения перед сохранением")} onClose={stay}><b>{path}</b><Changes before={orig} after={content}/>
      <ActionButton onClick={write}>{t("Сохранить")}</ActionButton></Modal>}
    {conflict && <Modal title={t("Файл изменился на сервере")} onClose={stay}><p>{path}</p>
      {env ? <Changes before={content} after={conflict.content}/> : <div className="cols"><div>{t("Ваш текст")}<pre>{content}</pre></div><div>{t("На сервере")}<pre>{conflict.content}</pre></div></div>}
      <button className="btn" onClick={() => {setOrig(conflict.content);setRevision(conflict.revision);setConflict(null);}}>{t("Оставить черновик и продолжить сравнение")}</button>
      <button className="btn" onClick={() => {setOrig(conflict.content);setContent(conflict.content);setRevision(conflict.revision);setConflict(null);}}>{t("Принять серверную версию")}</button></Modal>}
  </>;
  return {content, orig, setContent, save, guard, dialogs, binary, loaded: !!path && ready === path, dirty};
}
