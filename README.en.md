# Light Classroom

[中文](README.zh.md)

Operations software for ordinary senior high schools in China: organization and staff, classes and students, constraint-based timetabling (OR-Tools CP-SAT), timetables, and a file center.

Start with [docs/README.md](docs/README.md). Most long-form docs are in Chinese; command blocks and headings are enough to run and deploy.

## Features

- Multi-tenant schools isolated by the `X-School-Code` request header
- Platform admin to provision schools; separate school-side login
- Rule workbench, async timetable generation (Celery), and lesson moves
- Teacher profiles, course hours, and teaching assignments
- File center (MinIO or Tencent COS)
- Optional Prometheus metrics at `GET /metrics`

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 19 · Vite · Ant Design · TypeScript |
| Backend | Python 3.11+ · FastAPI · SQLModel · Alembic |
| Data | PostgreSQL · Redis · RabbitMQ · MinIO |
| Solver | OR-Tools CP-SAT (`pip install ortools`; not yet listed in `pyproject.toml`) |

## Layout

```
frontend-react/   School UI and platform-admin UI
backend/          API, migrations, workers, tests
monitoring/       Optional Prometheus / Grafana
docs/             Architecture, config, deploy, ops, specs
```

Do **not** commit or publish SQL dumps that contain students or password hashes. See [db/README-sql.md](db/README-sql.md).

## Quick start (development)

### Backend

```bash
cd backend
cp .env.example .env   # set JWT_SECRET_KEY at minimum
pip install -e ".[dev]"
pip install ortools
docker compose up -d postgres redis rabbitmq minio
uvicorn app.main:app --reload --port 8001
# another terminal:
celery -A app.workers.celery_app worker -Q scheduling,academic --loglevel=info
```

- OpenAPI UI: http://localhost:8001/docs
- Health: http://localhost:8001/health

With `APP_ENV=dev` the app creates tables and built-in roles on startup. Production must use `alembic upgrade head`. See [docs/deploy.md](docs/deploy.md).

### Frontend

```bash
cd frontend-react
pnpm install
pnpm dev
```

Open http://localhost:5176 . The Vite proxy forwards `/api/v1` to `127.0.0.1:8001` (`VITE_DEV_PROXY` overrides this).

| Entry | Path |
|-------|------|
| School login | `/login` |
| Platform admin | `/admin/login` |

Dev admin credentials come from `ADMIN_USERNAME` / `ADMIN_PASSWORD` in `.env` (sample `admin` / `admin123` — change before any real deploy).

## Configuration

There is no Spring `application.yml`. Precedence is **process environment variables > `backend/.env` > field defaults** in code. See [docs/config.md](docs/config.md).

## Tests

```bash
cd backend
pytest
```

Full timetable tests are heavy; start with auth, RBAC, and the rule-engine subset.

## Docs

- [Architecture](docs/architecture.md) · [Config](docs/config.md) · [Deploy](docs/deploy.md) · [Ops](docs/ops.md) · [Monitoring](docs/monitoring.md)
- [UI routes](docs/frontend.md) · [ER](docs/ER-diagram.md) · [Scheduling spec](docs/specs/schedule-and-seating.md)
- [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [License](LICENSE)

## License

[MIT](LICENSE).
