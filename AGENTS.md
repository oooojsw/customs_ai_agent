# Repository Guidelines

## Project Structure & Module Organization
`src/` contains the application code: `api/` for FastAPI routes, `core/` for audit orchestration and prompt building, `services/` for chat/report/RAG/OCR logic, `database/` for SQLite access, and `config/` for runtime loaders. `web/` is the static frontend (`index.html`, `js/`, `css/`). `config/` stores rule files such as `risk_rules.json` and SOP text. `data/knowledge/` holds RAG source documents; `data/skills/` contains local skill packages. `tests/` covers config, export, deep research, and reporter flows. Keep `进度报告/`, `接口规范/`, and `方案文档/` versioned.

## Build, Test, and Development Commands
- `pip install -r requirements.txt`: install backend dependencies.
- `python src/main.py`: start the app locally on port `8000`.
- `uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload`: run with hot reload.
- `pytest tests/ -v`: run the main automated test suite.
- `python tests/test_export.py`: run a focused script-style test.
- `docker-compose up -d --build`: build and launch the containerized stack.

If a test starts the server, confirm port `8000` is released afterward with `netstat -ano | findstr :8000`.

## Coding Style & Naming Conventions
Use 4-space indentation, 100-character max line length, and explicit type hints on public functions. Follow the existing Python organization: standard library imports, blank line, third-party imports, blank line, local imports. Use `snake_case` for functions/variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Prefer async I/O for network, database, and file-processing flows. Keep docstrings short and Google-style when needed.

## Testing Guidelines
Use `pytest` for new tests and keep file names as `tests/test_<feature>.py`. Add or update tests when changing API routes, config loading, export flows, or knowledge-base behavior. No formal coverage threshold is enforced, but changed code should have a targeted regression test or a runnable verification command.

## Commit & Pull Request Guidelines
Recent history uses prefix-based commits such as `feat:`, `fix:`, `chore:`, and `release:`. Keep messages short and scoped, for example: `fix: stabilize PDF cache rebuild`. PRs should include a summary, affected paths, test evidence, and screenshots for `web/` changes. Call out `.env`, proxy, model, or knowledge-base impacts explicitly.

## Security & Configuration Tips
Do not commit real API keys or proxy secrets. Load runtime settings from `.env`. When adding knowledge files under `data/knowledge/`, note whether a FAISS index rebuild is required. Avoid deleting cached DB or index files unless the change explicitly requires regeneration.
