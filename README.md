# Community Smells Hub

Community Smells Hub is a socio-technical analysis platform for software repositories.  
It combines repository mining, network analysis, code smell detection, vulnerability scanning, developer profiling, and time-windowed historical analysis.

## What the project does

For each tracked repository, the system:

1. Mines commits and developers from Git history.
2. Splits project evolution into contiguous 3-month windows.
3. For each window, analyzes the snapshot at the latest commit in that window.
4. Computes:
   - Collaboration network and communication network.
   - Community smells.
   - ML-specific smells (CodeSmile integration).
   - Traditional code smells (DPy integration).
   - Security vulnerabilities (Bandit integration).
   - Developer classification (Software Engineer / AI-Engineer / Hybrid).
   - Developer gender/pronouns inference (GitHub bio-based, if available).
   - Developer sentiment (BERT-based emotion pipeline, train-on-first-run).
   - Socio-Technical Quality Factors (Table-3 style metrics).
5. Stores everything in `data/projects.json` and visualizes it in the frontend.

## Main features

- Project tracking by Git URL or local absolute path.
- Bulk project creation and analysis (`/projects/bulk`).
- Historical analysis in 3-month windows (forward/backward navigation in UI).
- Community smell evidence in results.
- PR/Issue communication extraction from GitHub (with fallback commit-based proxy).
- Full CSV export:
  - Current/selected window.
  - Full history (`all_windows=true`) across all windows.

## Repository structure

- `api/main.py`: FastAPI app, orchestration, persistence, REST API.
- `models/schemas.py`: Pydantic data model.
- `core/miner.py`: Commit/developer mining and basic bug-fix tagging.
- `core/network_builder.py`: Collaboration/communication/dependency graph building.
- `analyzers/community_smells.py`: Community smell detection.
- `analyzers/developer_classifier.py`: Developer role classification.
- `analyzers/ml_smells.py`: ML smell detection via `smell_ai`.
- `analyzers/traditional_smells.py`: Traditional smells via `DPy`.
- `analyzers/vulnerabilities.py`: Bandit-based vulnerability detection.
- `analyzers/rszz.py`: R-SZZ approximation.
- `analyzers/developer_sentiment.py`: BERT sentiment/emotion analysis.
- `web/frontend/`: HTML/CSS/JS dashboard.
- `SE_Emotion_PTM-3589/`: sentiment datasets/model assets.
- `smell_ai/`: ML-specific smell detector source.
- `tests/`: unit/integration tests for key behaviors.

## Requirements

- Python 3.11+ recommended.
- Git installed and available in PATH.
- Optional but recommended:
  - `bandit` (for vulnerability analysis).
  - Internet access + GitHub token for richer PR/Issue and profile data.
- Local tools integrated by this project:
  - `DPy` binary in project root (`./DPy`).
  - `smell_ai` package in `./smell_ai`.

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Current `requirements.txt` includes:

- fastapi, uvicorn, gitpython, pydantic
- pandas, networkx, matplotlib, scipy
- astunparse, requests, python-multipart, python-dotenv, pygments
- bandit, torch, transformers

## Environment variables

Optional environment variables used by the backend:

- `GITHUB_TOKEN`: GitHub API token (recommended to reduce rate-limit issues).
- `PRONOUN_PARADIGMS_FILE`: custom pronoun paradigms file path.
- `GITHUB_PROFILE_LOOKUP_LIMIT` (default `120`): max GitHub profile lookups per analysis.
- `DEV_SENTIMENT_TRAIN_LIMIT` (default `1200`): max training rows for first-run sentiment training.
- `DEV_SENTIMENT_BATCH_SIZE` (default `16`)
- `DEV_SENTIMENT_EPOCHS` (default `1`)
- `DEV_SENTIMENT_LR` (default `2e-5`)

## How to run

From project root:

```bash
python3 -m uvicorn api.main:app --host 127.0.0.1 --port 8001
```

Open:

- `http://127.0.0.1:8001`

The frontend is served directly by FastAPI (mounted static files).

## Build executable (Windows/macOS/Linux)

Non esiste un singolo binario universale per tutti gli OS: va generato un eseguibile per ciascun sistema operativo.

1. Installa dipendenze runtime + builder:

```bash
pip install -r requirements.txt
pip install pyinstaller
```

2. Build eseguibile per il tuo OS:

```bash
python3 scripts/build_executable.py
```

Opzione single-binary:

```bash
python3 scripts/build_executable.py --onefile
```

3. Avvio:

- Build `--onedir` (default):
  - macOS/Linux: `./dist/SmellHub/SmellHub`
  - Windows: `dist\\SmellHub\\SmellHub.exe`
- Build `--onefile`:
  - macOS/Linux: `./dist/SmellHub`
  - Windows: `dist\\SmellHub.exe`

Note operative:

- L'eseguibile salva i dati utente in `~/.smellhub` (cross-platform).
- Al lancio apre automaticamente il browser su `http://127.0.0.1:8001`.
- Variabili utili:
  - `SMELLHUB_PORT` (default `8001`)
  - `SMELLHUB_HOST` (default `127.0.0.1`)
  - `SMELLHUB_OPEN_BROWSER` (`1`/`0`)
  - `SMELLHUB_DATA_DIR` (override path dati)

## API overview

### Create one project

`POST /projects?name=...&url=...&local_path=...`

- Use `url` for clone-based creation.
- Use absolute `local_path` for existing local repo.

### Create many projects at once

`POST /projects/bulk`

Body:

```json
{
  "repositories": [
    {"url": "https://github.com/org/repo1.git", "name": "repo1"},
    {"url": "https://github.com/org/repo2.git", "name": "repo2"}
  ],
  "auto_analyze": true
}
```

### Start analysis

`POST /projects/{project_id}/analyze`

Runs background historical analysis.

### List/get/delete

- `GET /projects`
- `GET /projects/{project_id}`
- `DELETE /projects/{project_id}`

### Export developers CSV

`GET /projects/{project_id}/developers/export.csv`

Options:

- `window_id=<id>` for a specific window.
- `all_windows=true` for full historical export.

Notes:

- Full-history export includes one row per developer per window.
- CSV contains project-level metrics columns plus developer-level columns.
- The socio-technical metrics JSON column is named:
  - `Socio-Technical Quality Factors`

## Time-window model

- Windows are contiguous 3-month blocks aligned to calendar months.
- Example label format: `2020-09-01 -> 2020-11-30`.
- For each window:
  - The analyzed code snapshot is the latest commit within that window.
  - Smell/vulnerability attribution to developers uses git blame and introduction-date filtering.
  - Developer list/classification/stats are window-specific.

## Communication model

Primary source:

- GitHub Issues/PR interactions (authors, assignees, comments, reviews, PR comments).

Fallback:

- Same-day co-activity proxy from commits when explicit communication is unavailable.

This communication layer feeds community smell detection and socio-technical metrics.

## Sentiment model behavior

- On first run, the BERT model is trained (bounded dataset/epochs by env vars).
- Trained artifacts are saved under:
  - `SE_Emotion_PTM-3589/models/bert_multilabel/`
- Later runs reuse saved model.
- Sentiment is computed per developer per time window from commit messages.

## Frontend usage

1. Click **Add Project**.
2. Add one or multiple repository URLs.
3. Open project report (**View Report**).
4. Navigate windows with:
   - previous/next arrows
   - window dropdown
5. Export data:
   - **Export Current Window CSV**
   - **Export Full History CSV**

## Running tests

From project root:

```bash
pytest -q
```

Existing test modules include:

- `tests/test_ml_smells_integration.py`
- `tests/test_gender_inference.py`
- `tests/test_table3_metrics.py`
- `tests/test_developer_sentiment.py`
- `tests/test_community_smell_evidence.py`

## Developer Role Classification (Rule-Based)

Developer roles (`Software Engineer`, `AI-Engineer`, `Hybrid`, `Unknown`) are inferred with
keyword/pattern matching using:

- Libraries/imports detected in touched files.
- Commit message patterns.
- GitHub PR/Issue textual activity (titles, bodies, comments, reviews), when available.

If GitHub textual activity is unavailable (missing token/rate limits/private repo access),
classification still works using repository-local signals (libraries + commits).

## Troubleshooting

### Backend not reachable

- Ensure server is running on `127.0.0.1:8001`.
- Check port usage:

```bash
lsof -n -P -iTCP:8001 -sTCP:LISTEN
```

### Analysis stuck or interrupted

- If backend restarts during analysis, status is marked interrupted.
- Re-run analysis from UI (`Re-analyze`) or API.

### No PR/Issue communication data

- Check repository URL is GitHub.
- Set `GITHUB_TOKEN` to avoid API rate limits.
- Without GitHub data, commit proxy is used.

### Sentiment unavailable

- Ensure `torch` and `transformers` are installed.
- Ensure datasets exist under `SE_Emotion_PTM-3589/datasets/`.

### Traditional/ML smells missing

- Verify local tools exist:
  - `./DPy`
  - `./smell_ai`
- Some windows may legitimately report 0 findings.

Linux note for DPy:

- If your Linux binary is not named exactly `DPy`, set:
  - `export DPY_BINARY=/absolute/path/to/your/dpy-binary`
- Ensure execute permission:
  - `chmod +x /absolute/path/to/your/dpy-binary`

## Current limitations

- Many detectors are heuristic-based and may produce false positives/negatives.
- Gender inference is pronoun/bio-based and may be unavailable or inaccurate.
- Communication proxy is approximate, not direct conversation evidence.
- Large repositories can require substantial time for full historical analysis.

## License

No project-wide license file is currently defined at repository root.
