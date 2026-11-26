# erp/

This directory is a self-contained ERP application (Python/FastAPI backend, React frontend, PostgreSQL). It is
unrelated to the Electron app in the rest of the repository: the repository-root `CLAUDE.md` / `AGENTS.md` rules
do not apply to files under `erp/`, and work on the ERP must not touch files outside `erp/`.

Read `erp/docs/ARCHITECTURE.md` before changing anything here. It defines the layout, feature ownership,
conventions, data model, core service contracts and the accounting rules.

Quick reference:

- Backend: `cd erp/backend && uv sync && uv run pytest` · lint `uv run ruff check . && uv run ruff format --check .`
- Frontend: `cd erp/frontend && npm install && npm run typecheck && npm run build` (npm, never pnpm)
- Local PostgreSQL: `127.0.0.1:5432`, role `erp` / `erp`, dev database `erp_dev`
- The repository is public: no real company names, people, logos, tax numbers or credentials in code or seed data.
