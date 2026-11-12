"""Built-in project templates. `{{secret:NAME}}` is replaced by a random value (same NAME -> same value)."""
import re
import secrets

TEMPLATES: dict[str, dict] = {
    "nginx-static": {
        "name": "Nginx + статика",
        "description": "Статический сайт: кладёте файлы в html/, nginx отдаёт их.",
        "files": {
            "docker-compose.yml": """services:
  web:
    image: nginx:alpine
    restart: unless-stopped
    ports:
      - "${HTTP_PORT:-8080}:80"
    volumes:
      - ./html:/usr/share/nginx/html:ro
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1/"]
      interval: 10s
      retries: 3
""",
            ".env": "HTTP_PORT=8080\n",
            "html/index.html": "<!doctype html><html><body><h1>It works!</h1></body></html>\n",
        },
    },
    "postgres-redis": {
        "name": "PostgreSQL + Redis",
        "description": "База данных и кэш с томами и healthcheck, пароли генерируются.",
        "files": {
            "docker-compose.yml": """services:
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", "--appendonly", "yes"]
    ports:
      - "${REDIS_PORT:-6379}:6379"
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD-SHELL", "redis-cli -a $${REDIS_PASSWORD} ping | grep PONG"]
      interval: 10s
      retries: 5

volumes:
  pgdata:
  redisdata:
""",
            ".env": """POSTGRES_DB=app
POSTGRES_USER=app
POSTGRES_PASSWORD={{secret:pg}}
POSTGRES_PORT=5432
REDIS_PASSWORD={{secret:redis}}
REDIS_PORT=6379
""",
        },
    },
    "node-app": {
        "name": "Node.js приложение",
        "description": "Express-сервер со сборкой из Dockerfile и healthcheck.",
        "files": {
            "docker-compose.yml": """services:
  app:
    build: .
    restart: unless-stopped
    env_file: .env
    ports:
      - "${APP_PORT:-3000}:3000"
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:3000/health"]
      interval: 10s
      retries: 3
""",
            "Dockerfile": """FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
""",
            "package.json": """{
  "name": "app",
  "private": true,
  "dependencies": { "express": "^4.21.0" }
}
""",
            "server.js": """const express = require("express");
const app = express();
app.get("/health", (_, res) => res.json({ ok: true }));
app.get("/", (_, res) => res.send("Hello from Node.js"));
app.listen(3000, () => console.log("listening on 3000"));
""",
            ".env": "APP_PORT=3000\nNODE_ENV=production\n",
            ".dockerignore": "node_modules\n.env\n",
        },
    },
    "python-fastapi": {
        "name": "Python FastAPI",
        "description": "API на FastAPI + uvicorn, сборка из Dockerfile.",
        "files": {
            "docker-compose.yml": """services:
  api:
    build: .
    restart: unless-stopped
    env_file: .env
    ports:
      - "${API_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/health')"]
      interval: 10s
      retries: 3
""",
            "Dockerfile": """FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
""",
            "requirements.txt": "fastapi\nuvicorn[standard]\n",
            "main.py": """from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/")
def index():
    return {"hello": "world"}
""",
            ".env": "API_PORT=8000\n",
            ".dockerignore": "__pycache__\n.env\n",
        },
    },
    "wordpress": {
        "name": "WordPress + MariaDB",
        "description": "WordPress с базой MariaDB, данные в томах.",
        "files": {
            "docker-compose.yml": """services:
  db:
    image: mariadb:11
    restart: unless-stopped
    environment:
      MARIADB_DATABASE: wordpress
      MARIADB_USER: wordpress
      MARIADB_PASSWORD: ${DB_PASSWORD}
      MARIADB_ROOT_PASSWORD: ${DB_ROOT_PASSWORD}
    volumes:
      - db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      retries: 5

  wordpress:
    image: wordpress:latest
    restart: unless-stopped
    depends_on:
      db:
        condition: service_healthy
    environment:
      WORDPRESS_DB_HOST: db
      WORDPRESS_DB_USER: wordpress
      WORDPRESS_DB_PASSWORD: ${DB_PASSWORD}
      WORDPRESS_DB_NAME: wordpress
    ports:
      - "${HTTP_PORT:-8081}:80"
    volumes:
      - wp:/var/www/html

volumes:
  db:
  wp:
""",
            ".env": "HTTP_PORT=8081\nDB_PASSWORD={{secret:db}}\nDB_ROOT_PASSWORD={{secret:root}}\n",
        },
    },
    "uptime-kuma": {
        "name": "Uptime Kuma",
        "description": "Мониторинг доступности сайтов и сервисов с уведомлениями.",
        "files": {
            "docker-compose.yml": """services:
  kuma:
    image: louislam/uptime-kuma:1
    restart: unless-stopped
    ports:
      - "${HTTP_PORT:-3001}:3001"
    volumes:
      - data:/app/data

volumes:
  data:
""",
            ".env": "HTTP_PORT=3001\n",
        },
    },
}


def list_templates() -> list[dict]:
    return [{"id": k, "name": v["name"], "description": v["description"], "files": sorted(v["files"])}
            for k, v in TEMPLATES.items()]


def render(template_id: str) -> dict[str, str]:
    t = TEMPLATES[template_id]
    generated: dict[str, str] = {}

    def secret(m: re.Match) -> str:
        return generated.setdefault(m.group(1), secrets.token_urlsafe(18))

    return {path: re.sub(r"\{\{secret:(\w+)\}\}", secret, content) for path, content in t["files"].items()}
