# Deployment
Local only: `pip install -r requirements.txt && ./run.sh` → http://127.0.0.1:8787. Data in `./data` (`COMPANION_DATA`). Do not bind to 0.0.0.0 (no auth).
Optional cloud LLM (explicit opt-in; sends recent utterances for unanswered questions to the vendor):
```bash
COMPANION_PROVIDER=anthropic COMPANION_MODEL=<model-id> COMPANION_API_KEY=... COMPANION_CLOUD_OPT_IN=1 ./run.sh
```
Before publishing to GitHub: run a secret scan (e.g. gitleaks), `pip-audit`, and a license review (deps: fastapi, uvicorn, httpx — permissive). `.gitignore` excludes `data/` and `.env`. Per the strategy, keep proprietary policy/prompts private and publish docs/demo only — the owner decides; nothing has been pushed. Desktop packaging (Tauri) is not done.
