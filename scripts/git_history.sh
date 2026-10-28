#!/usr/bin/env bash
# Creates a meaningful commit history from the current tree (real timestamps = when YOU run it).
# Usage: bash scripts/git_history.sh   then: git remote add origin <url> && git push -u origin main
set -e; cd "$(dirname "$0")/.."; [ -d .git ] || git init -q -b main
c() { msg="$1"; shift; git add -- "$@" 2>/dev/null; git diff --cached --quiet || git commit -q -m "$msg" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"; }
c "chore: project skeleton, config, requirements, gitignore" config requirements.txt .gitignore src/__init__.py
c "feat(schema): data dictionary as code with PK/FK/enum definitions" src/schema.py
c "feat(generator): deterministic SKU/store matrix, censored sales, inventory simulation" src/generator.py
c "feat(forecast): censoring-aware models, temporal holdout, calibrated intervals" src/forecasting.py
c "feat(replenishment): ROP/safety stock, MOQ-pack-capacity logic, lifecycle events" src/replenishment.py
c "feat(validation): schema-driven checks and anomaly detectors with ground-truth scoring" src/validation.py src/anomaly_detection.py src/injection.py
c "feat(pipeline): end-to-end CLI, exports, manifest, SQLite" src/pipeline.py
c "test: 30 tests (generator, forecasting, replenishment, validation, reproducibility)" tests
c "feat(app): Streamlit dashboard and FastAPI service" app
c "feat(repro): reproducibility script and reports" scripts/reproduce.py docs/reproducibility_report_starter.txt docs/reproducibility_report_full.txt
c "docs: README, schema, architecture, data dictionary, reasoning" README.md docs/schema.md docs/architecture.md docs/data_dictionary.md docs/REASONING.md
c "docs: AI usage disclosure and prompt history" docs/AI_USAGE.md docs/PROMPT_HISTORY.md scripts/git_history.sh
c "data: starter sample dataset, ground truth, manifest" data
git log --oneline
