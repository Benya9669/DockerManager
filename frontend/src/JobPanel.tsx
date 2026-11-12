import { t } from "./i18n";
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
          <b>{title || t("Задача")}</b>
          <Link to={`/jobs/${jobId}`} className="muted">#{jobId}</Link>
          {status === "running" ? <span className="badge yellow">{t("выполняется")}</span> : <StateBadge state={status} />}
        </div>
        <div className="row">
          {status === "running" && (
            <ActionButton className="btn danger sm" onClick={() => api(`/jobs/${jobId}/cancel`, { method: "POST" })}>
              {t("Отменить")}
            </ActionButton>
          )}
          {onClose && <button className="btn ghost sm" onClick={onClose}>{t("Закрыть")}</button>}
        </div>
      </div>
      <XTerm
        key={jobId}
        url={wsUrl(`/jobs/${jobId}/stream`)}
        mode="job"
        download={{ path: `/jobs/${jobId}/output`, filename: `job-${jobId}.log` }}
        height={height}
        onDone={(s) => {
          setStatus(s);
          onDone?.(s);
        }}
      />
    </div>
  );
}
