import { useState } from "react";
import { Link } from "react-router-dom";
import { api, wsUrl } from "./api";
import { XTerm } from "./XTerm";
import { ActionButton, StateBadge } from "./ui";

/** Live output of a running/finished job with a cancel button. */
export function JobPanel({ jobId, title, onClose, onDone, height = 360 }: {
  jobId: number; title?: string; onClose?: () => void; onDone?: (status: string) => void; height?: number;
}) {
  const [status, setStatus] = useState("running");
  return (
    <div className="card job-panel">
      <div className="row between">
        <div className="row">
          <b>{title || "Задача"}</b>
          <Link to={`/jobs/${jobId}`} className="muted">#{jobId}</Link>
          {status === "running" ? <span className="badge yellow">выполняется</span> : <StateBadge state={status} />}
        </div>
        <div className="row">
          {status === "running" && (
            <ActionButton className="btn danger sm" onClick={() => api(`/jobs/${jobId}/cancel`, { method: "POST" })}>
              Отменить
            </ActionButton>
          )}
          {onClose && <button className="btn ghost sm" onClick={onClose}>Закрыть</button>}
        </div>
      </div>
      <XTerm
        key={jobId}
        url={wsUrl(`/jobs/${jobId}/stream`)}
        mode="job"
        height={height}
        onDone={(s) => {
          setStatus(s);
          onDone?.(s);
        }}
      />
    </div>
  );
}
