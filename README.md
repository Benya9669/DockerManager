# 🐳 Docker Manager

Веб-панель для управления Docker Compose проектами на сервере. Почти всё делается через WebUI: проекты из git, выбор и редактирование `.env`, build/deploy, логи, терминал в контейнере, очистка образов и контейнеров, пользователи с ролями и аудит.

## Возможности

**Проекты**
- Источник: git-репозиторий (HTTPS с токеном или SSH), существующая папка на сервере или «с нуля» (шаблон compose-файла).
- Несколько compose-файлов на проект (`docker-compose.yml,docker-compose.prod.yml`).
- **Выбор активного `.env`** из найденных `.env`, `.env.*`, `*.env`, `env/*`; передаётся как `docker compose --env-file`.
- Редактор env-файлов, создание копии (например, `.env.staging` из `.env.prod`).
- Файловый менеджер проекта: просмотр, редактирование (YAML/JSON подсветка), создание, переименование, удаление.

**Compose / Build**
- Деплой одной кнопкой: `git pull → compose pull → (build --no-cache) → up -d --build --remove-orphans`.
- `up`, `build --pull` (с опцией `--no-cache`), `rebuild` (build + `--force-recreate`), `restart`, `stop`, `down`, `pull`, `config` (проверка).
- Действия по отдельному сервису: up / restart / stop / rebuild.
- Все операции выполняются как задачи с потоковым выводом в браузер, историей и отменой.

**Git**
- Статус: ветка, коммит, отставание/опережение upstream, локальные изменения.
- Fetch, pull (`--ff-only`), смена ветки, `reset --hard` к upstream, лог коммитов.
- Вебхуки для авто-деплоя при push (GitLab Secret token, GitHub/Gitea HMAC, generic `?token=`) с фильтром по ветке.
- Токены хранятся зашифрованными и передаются через HTTP-заголовок — не попадают в `.git/config`.

**Контейнеры и ресурсы**
- Список контейнеров (все / по проекту), start/stop/restart/remove, CPU/RAM.
- Логи в реальном времени (xterm, выбор хвоста, timestamps).
- Интерактивный терминал (`docker exec`) в браузере.
- Inspect, env, mounts, сети.
- Образы (pull, удаление, фильтр «не используются / dangling»), тома, сети.

**Очистка**
- Проект: удалить остановленные контейнеры проекта и неиспользуемые образы, собранные для него.
- Система: prune контейнеров, dangling или всех неиспользуемых образов, build cache, сетей, томов, с фильтром «старше N часов»; пресеты «мягкая / глубокая / всё».
- Отображение занятого места (`docker system df`).
- Автоочистка по расписанию (`DM_AUTO_PRUNE_INTERVAL_HOURS`).

**Доступ**
- Роли: `viewer` (просмотр, логи), `operator` (деплой, build, env, файлы, git, терминал), `admin` (проекты, настройки, очистка, пользователи).
- Аудит всех действий.

## Быстрый старт (сервер)

```bash
git clone git@github.com:Benya9669/DockerManager.git /opt/dockermanager/app
cd /opt/dockermanager/app
cp .env.example .env        # задайте DM_ADMIN_PASSWORD, DM_PUBLIC_URL
mkdir -p /opt/dockermanager/projects ssh
docker compose up -d --build
```

Откройте `http://server:8000`. Если `DM_ADMIN_PASSWORD` не задан, пароль администратора выводится в лог (`docker logs dockermanager`) и сохраняется в `/data/initial_admin_password.txt`.

> **Важно про пути.** `DM_PROJECTS_DIR` монтируется в контейнер по *тому же* пути, что и на хосте. Иначе относительные bind-mount'ы в проектах (`./data:/data`) будут указывать в никуда: compose запускается внутри панели, но тома создаёт Docker-демон хоста. То же относится к проектам типа «папка на сервере» — их путь должен быть смонтирован одинаково.

**SSH-репозитории:** положите ключ (`id_ed25519`) и при желании `known_hosts` в папку `./ssh` (или укажите `DM_SSH_DIR`). Для HTTPS достаточно токена в настройках проекта (GitLab: пользователь `oauth2`, GitHub: любой, например `x-access-token`).

## Разработка

```bash
# backend
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --reload --port 8000

# frontend (в другом терминале), проксирует /api на :8000
cd frontend
npm install
npm run dev     # http://localhost:5173
```

## Переменные окружения

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DM_DATA_DIR` | `./data` | БД SQLite, секретный ключ |
| `DM_PROJECTS_DIR` | `$DM_DATA_DIR/projects` | Куда клонируются проекты |
| `DM_DATABASE_URL` | SQLite | например `postgresql+psycopg://user:pass@db/dm` |
| `DM_SECRET_KEY` | генерируется | подпись JWT и шифрование токенов |
| `DM_ADMIN_USERNAME` / `DM_ADMIN_PASSWORD` | `admin` / случайный | первичный администратор |
| `DM_TOKEN_TTL_MINUTES` | `720` | время жизни сессии |
| `DM_PUBLIC_URL` | — | внешний URL для отображения вебхуков |
| `DM_ALLOW_LOCAL_PATHS` | `true` | разрешить проекты из произвольных папок |
| `DM_AUTO_PRUNE_INTERVAL_HOURS` | `0` | автоочистка каждые N часов (0 — выкл.) |
| `DM_AUTO_PRUNE_OLDER_THAN_HOURS` | `72` | чистить объекты старше N часов |

## Безопасность

- Доступ к `docker.sock` равен root-доступу к хосту. Публикуйте панель только во внутренней сети и за reverse-proxy с HTTPS (nginx/traefik). WebSocket-соединения (`/api/.../stream`, `/logs`, `/exec`) должны проксироваться.
- Терминал в контейнерах доступен ролям `operator` и `admin`; каждое подключение пишется в аудит.
- Сохраните `DM_SECRET_KEY` (или `/data/secret.key`): без него сохранённые git-токены не расшифровать.

## Архитектура и расширение

```
backend/app/
  main.py         FastAPI, статика UI, инициализация, автоочистка
  jobs.py         раннер задач: шаги-команды, стриминг вывода через WebSocket, отмена
  compose.py      построение команд docker compose (actions → steps)
  git_ops.py      git: статус, ветки, clone/pull/checkout
  dockerc.py      Docker Engine API (docker SDK)
  routers/        auth+users+audit, projects (compose/git/env/files), jobs, docker, webhooks
frontend/src/     React + Vite: pages/*, XTerm (логи/терминал/задачи), Editor (CodeMirror)
```

Новое действие добавляется в `compose.action_steps` (список команд), и оно сразу получает стриминг, историю, отмену и аудит. Новый ресурс — роутер в `routers/` плюс страница в `frontend/src/pages`.
