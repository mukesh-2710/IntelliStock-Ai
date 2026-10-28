# AI Usage Disclosure
Guideline 03 asks for transparent LLM use. Facts below are accurate; **lines marked `CANDIDATE:` must be edited by you to say only what you personally did.** Do not submit claims you cannot defend in the walkthrough.

## Tools used
- Claude (Anthropic) in a chat interface: planning, edge-case brainstorming, and writing/running the code in this repo. Full prompts: `docs/PROMPT_HISTORY.md`.

## Where AI accelerated the work
- Breaking the brief into a build plan and listing candidate edge cases (the long ~140-item list was brainstormed; only the 5 required plus a handful of natural exception paths were implemented).
- First drafts of every module in `src/`, `app/`, `tests/`, `docs/` and `scripts/`.
- Writing the data dictionary as code (`src/schema.py`) and the validation rules generated from it.

## Where I relied on AI heavily
- Vectorised NumPy simulation in `src/generator.py` and the Croston / seasonal-naive code in `src/forecasting.py`.
- Dashboard and API (`app/`): these were compile-checked only; they were **not** executed in the AI environment (streamlit/fastapi were not installable there).
- README and docs prose.

## What was verified (by running code, not by assertion)
- 30 tests pass (`pytest -q`); the full-scale same-seed run matches on row counts and SHA-256 (`docs/reproducibility_report_full.txt`).
- Baseline validation 110/110 checks; injected-anomaly detection P/R = 1.0 on the full-scale run.
- Bug found and fixed during the run: a full-scale-only validation failure (`reorder_point=mu*L+SS`, 27 rows) caused by comparing against rounded inputs with an absolute tolerance; fixed with a relative tolerance and re-verified at full scale.

## What I personally reviewed, changed, or validated
- CANDIDATE: re-run `pytest -q`, `python scripts/reproduce.py`, and the full-scale command on your machine and note the results/timing here.
- CANDIDATE: read `generator.py`, `forecasting.py`, `replenishment.py`; list anything you changed (parameters, rules, naming) and why.
- CANDIDATE: run the dashboard (`streamlit run app/dashboard.py`) and API, and note any fixes you made.
- CANDIDATE: state which design decisions in `docs/REASONING.md` you agree/disagree with.

## Known limits of AI-generated parts
- Forecast accuracy is modest (WAPE ~0.44) and biased low; this is reported, not hidden.
- Detection scores of 1.0 reflect rule-defined synthetic anomalies, not real-world performance.
