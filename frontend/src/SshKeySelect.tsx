import { useState } from "react";
import { api } from "./api";
import { toast, useFetch } from "./ui";

/** Select of SSH private keys available to the panel, with the public key for copying into deploy keys. */
export function SshKeySelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const keys = useFetch<any>(() => api("/projects/ssh-keys"), []);
  const [showPub, setShowPub] = useState(false);
  const list: any[] = keys.data?.keys || [];
  const sel = list.find((k) => k.name === value);

  return (
    <div className="stack-sm">
      <div className="row">
        <select className="grow" value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">по умолчанию (стандартные ключи и ~/.ssh/config)</option>
          {list.map((k) => <option key={k.name} value={k.name}>{k.name}</option>)}
          {value && !sel && <option value={value}>{value} (не найден)</option>}
        </select>
        {sel?.public_key && (
          <button type="button" className="btn sm" onClick={() => setShowPub(!showPub)}>
            {showPub ? "скрыть" : "публичный ключ"}
          </button>
        )}
      </div>
      {showPub && sel?.public_key && (
        <pre className="small" title="Нажмите, чтобы скопировать" style={{ cursor: "pointer" }}
          onClick={() => navigator.clipboard?.writeText(sel.public_key).then(() => toast("Скопировано"))}>
          {sel.public_key}
        </pre>
      )}
      {keys.data && !list.length && <div className="muted small">Ключей в {keys.data.dir} не найдено</div>}
    </div>
  );
}
