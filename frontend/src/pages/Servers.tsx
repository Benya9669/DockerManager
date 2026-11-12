import { t, tf } from "../i18n";
import { useState } from "react";
import { api } from "../api";
import { useServer } from "../server";
import { SshKeySelect } from "../SshKeySelect";
import { ActionButton, Loading, Modal, fmtBytes, toast, toastErr, useFetch } from "../ui";

export function ServersPage() {
  const list = useFetch<any>(() => api("/servers"), []);
  const { reload: reloadCtx } = useServer();
  const [edit, setEdit] = useState<any>(null);
  const [tests, setTests] = useState<Record<number, any>>({});
  const reload = () => {
    list.reload();
    reloadCtx();
  };

  return (
    <div className="stack">
      <div className="page-head">
        <h1>{t("Серверы")}</h1>
        <button className="btn primary" onClick={() => setEdit({ name: "", docker_host: "ssh://", ssh_key: "", description: "" })}>{t("+ Сервер")}</button>
      </div>
      <div className="hint">
        {t("Удалённые Docker-хосты. Проект, привязанный к серверу, выполняет docker compose и все Docker-операции на нём; файлы проекта и git остаются на сервере с панелью, а сборка отправляется на удалённый хост как build context.")}
        <br />{t("Подключение — по SSH (ssh://user@host), пользователь должен иметь доступ к Docker (группа docker).")}
        <br />{t("Ограничение: bind-mount'ы с относительными путями (./data:/data) на удалённом хосте указывают на его файловую систему — используйте именованные тома.")}
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      {list.data && (
        <table className="table">
          <thead><tr><th>{t("Имя")}</th><th>{t("Адрес")}</th><th>{t("SSH-ключ")}</th><th>{t("Проектов")}</th><th>{t("Проверка")}</th><th /></tr></thead>
          <tbody>
            <tr>
              <td><b>{t("Локальный")}</b><div className="muted small">{t("Docker на сервере панели")}</div></td>
              <td className="mono small">unix:///var/run/docker.sock</td><td>—</td><td>{list.data.local.projects}</td><td /><td />
            </tr>
            {list.data.servers.map((s: any) => {
              const t = tests[s.id];
              return (
                <tr key={s.id}>
                  <td><b>{s.name}</b>{s.description && <div className="muted small">{s.description}</div>}</td>
                  <td className="mono small">{s.docker_host}</td>
                  <td className="mono small">{s.ssh_key || t("по умолчанию")}</td>
                  <td>{s.projects}</td>
                  <td className="small">
                    {t && (t.ok
                      ? <span className="badge green" title={t.os}>Docker {t.version} · {t.cpus} CPU · {fmtBytes(t.mem_total)}</span>
                      : <span className="badge red" title={t.error}>{t("ошибка")}</span>)}
                    {t && !t.ok && <div className="muted small" style={{ maxWidth: 360 }}>{t.error}</div>}
                  </td>
                  <td className="actions">
                    <ActionButton className="btn sm" onClick={async () => {
                      const r = await api(`/servers/${s.id}/test`, { method: "POST" });
                      setTests((x) => ({ ...x, [s.id]: r }));
                    }}>{t("Проверить")}</ActionButton>
                    <button className="btn sm" onClick={() => setEdit(s)}>{t("Изменить")}</button>
                    <ActionButton className="btn sm danger" confirm={tf("Удалить сервер {0}?", s.name)} onClick={async () => {
                      await api(`/servers/${s.id}`, { method: "DELETE" });
                      reload();
                    }}>🗑</ActionButton>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {edit && <ServerModal s={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
    </div>
  );
}

function ServerModal({ s, onClose, onSaved }: { s: any; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ name: s.name, docker_host: s.docker_host, ssh_key: s.ssh_key || "", description: s.description || "" });
  return (
    <Modal title={s.id ? tf("Сервер: {0}", s.name) : t("Новый сервер")} onClose={onClose}>
      <form className="form" onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api(s.id ? `/servers/${s.id}` : "/servers", { method: s.id ? "PATCH" : "POST", body: f });
          toast(t("Сохранено. Нажмите «Проверить», чтобы проверить подключение"));
          onSaved();
        } catch (err) { toastErr(err); }
      }}>
        <label>{t("Имя")}<input required value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="prod-1" /></label>
        <label>{t("Адрес Docker")}<input required className="mono" value={f.docker_host} onChange={(e) => setF({ ...f, docker_host: e.target.value })} placeholder={t("ssh://deploy@10.0.0.5 или ssh://deploy@host:2222")} /></label>
        <label>{t("SSH-ключ")}<SshKeySelect value={f.ssh_key} onChange={(v) => setF({ ...f, ssh_key: v })} /></label>
        <div className="hint">
          {t("Чтобы ключ применялся к конкретному серверу, включите")} <span className="mono">DM_MANAGE_SSH_CONFIG=true</span> {t("(в docker-compose панели включено) — панель создаст для сервера SSH-алиас с этим ключом. Публичный ключ добавьте в")} <span className="mono">~/.ssh/authorized_keys</span> {t("пользователя на сервере.")}
        </div>
        <label>{t("Описание")}<input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
        <div className="row end"><button className="btn primary">{t("Сохранить")}</button></div>
      </form>
    </Modal>
  );
}
