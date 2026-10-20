# CLAUDE.md — Build brief for GhostStop (PS-13)

You are helping a 2-person team build a hackathon project **today**, in a ~4.5 hour window. Read this whole file before acting. Work in the phases below, in order. After each phase: run it, show me the result, and stop for confirmation before the next phase.

---

## 1. What we are building

**Problem (PS-13):** End-to-end workflow automation agent for high-volume document processing:
intake → classification → extraction → transformation → validation → system entry → approval routing.
Must handle multi-entity documents, configurable validation with cross-record checks, escalation on low confidence / validation failure / complexity, and a full audit trail with a pipeline dashboard.

**Hook:** Samsung Securities, April 2018 — a cash dividend of 1,000 won per share was entered as 1,000 shares per share and approved by a team leader. 2,812,950,000 "ghost" shares (~31× the ~89M shares outstanding) were credited to 2,018 employee accounts. Our pipeline must make that class of error impossible to enter silently.

**Domain:** Pakistan Stock Exchange (PSX) corporate filings — financial results, dividend declarations, dividend credit notices — validated against the PSX Rule Book, the PSX Correspondence Manual and the Companies Act 2017.

---

## 2. Hard constraints (hackathon rules — never break these)

1. **No hardcoded or faked outputs.** Every result shown in the UI must be computed live by the pipeline. No mock responses may remain reachable from the UI at submission.
2. **No secrets in code or git.** Keys come only from environment variables. `.env` is in `.gitignore` and `.gcloudignore`.
3. **Every figure carries provenance:** document, page, bounding box (if available), and source text.
4. **Never invent data.** If a value (e.g. shares outstanding) can't be found, leave it blank and flag `needs_review`.
5. **The Samsung case is a labelled reconstruction** built only from publicly reported figures. The UI must always show a "Reconstruction from public reporting" badge on it.
6. **The team must be able to explain every line.** Keep code simple, small files, clear names, brief comments where logic is non-obvious. No clever abstractions.
7. Commit after each phase with a clear message.

---

## 3. Stack

| Layer | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Uvicorn |
| Orchestration | LangGraph |
| LLM | **OpenAI primary, Anthropic Claude fallback** — only when classical methods fail |
| PDF | PyMuPDF (text + bboxes), pdfplumber (tables), pytesseract (OCR for scanned pages) |
| Matching | rapidfuzz |
| Rules | YAML files loaded at runtime (no rule logic hardcoded in Python constants) |
| Storage (MVP) | In-memory state + JSON/SQLite ledger; Cloud Run runs with `--max-instances 1` |
| Streaming | Server-Sent Events (sse-starlette) |
| Frontend | Vite + React on Vercel (**not built yet** — Phase 8) |
| Deploy | Backend → GCP Cloud Run, project `finale`, region `us-central1`; Frontend → Vercel |

Model names come from env vars `OPENAI_MODEL` and `ANTHROPIC_MODEL` — never hardcode a model name.

---

## 4. Repository layout (create exactly this)

```
ghoststop/
├── CLAUDE.md
├── README.md
├── .gitignore                 .env, venv/, __pycache__/, node_modules/, *.sqlite
├── backend/
│   ├── app.py                 FastAPI routes; CORS allow_origin_regex r"https://.*\.vercel\.app" + localhost; listens on 0.0.0.0:$PORT
│   ├── orchestrator.py        LangGraph graph
│   ├── state.py               Pydantic models: Document, Track, FieldValue, RuleResult, AuditEvent
│   ├── llm.py                 OpenAI → Claude fallback, timeouts, retries, JSON validation, LLM_LOG
│   ├── prompts.py             All LLM prompts in one place
│   ├── agents/
│   │   ├── intake.py
│   │   ├── classifier.py
│   │   ├── extractor.py
│   │   ├── transformer.py     includes entity splitting
│   │   ├── validator.py
│   │   ├── resolver.py
│   │   └── router.py          approval routing + escalation
│   ├── tools/
│   │   ├── pdf_text.py        text + bboxes per page, text-layer detection
│   │   ├── ocr.py             tesseract fallback for scanned pages
│   │   ├── units.py           Rs '000 → Rs, % of face value → Rs/share, currency vs share-count typing
│   │   ├── dedup.py           sha256 + exact ID + fuzzy (company+type+period)
│   │   ├── rules_engine.py    loads YAML, evaluates, returns RuleResult list
│   │   ├── ledger.py          idempotent "system entry" keyed on doc_id + track_id
│   │   └── audit.py           append-only AuditEvent log + SSE broadcast
│   ├── rules/
│   │   ├── csv_rules.yaml
│   │   └── dividend_rules.yaml
│   ├── config/thresholds.yaml
│   ├── scripts/fetch_data.py  Phase 0
│   ├── data/
│   │   ├── csv/               ps01_documents_metadata.csv, ps07_ingestion_queue.csv
│   │   ├── real_docs/<category>/ + manifest.csv
│   │   ├── rulebooks/{psx,secp}/
│   │   ├── reference/company_master.csv
│   │   ├── fixtures/samsung_2018_replay.json
│   │   └── SOURCES.md
│   ├── tests/
│   ├── Dockerfile             python:3.12-slim + apt-get install tesseract-ocr
│   ├── requirements.txt
│   └── .env.example
├── frontend/                  Phase 8
└── docs/architecture.md       mermaid diagram of agents (submission item)
```

`.env.example`:
```
OPENAI_API_KEY=
OPENAI_MODEL=
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=
CONFIDENCE_THRESHOLD=0.80
```

---

## 5. Data

### 5.1 Provided CSVs (volume lane — metadata only, no real content)
- `ps01_documents_metadata.csv` (200 rows): `doc_id, filename, source, received_date (DD/MM/YYYY), file_type, file_size_kb, ocr_text_snippet, current_status, assigned_stream`. Snippets are templated placeholders; `assigned_stream` is inconsistent legacy routing — compare against it, don't learn from it.
- `ps07_ingestion_queue.csv` (250 rows): `job_id, document_id, filename, ingestion_timestamp (ISO), document_type_detected, contains_financial_data, contains_admin_only, analyst_action, time_spent_minutes, was_relevant`. This is the **manual baseline**.
  - Relevant types: 10-K Filing, 10-Q Filing, Quarterly Report, Earnings Release, Financial Supplement, Press Release - Financial, Dividend Declaration.
  - Irrelevant (admin): Board Resolution, Debenture Notice, Director Appointment Notice, Earnings Calendar Update, Press Release - Product.
  - Known duplicate: `FDOC-35032` (JOB-00012 and JOB-00200).
  - Baseline: 797/4,350 min on irrelevant docs; 34/101 irrelevant docs processed; avg 7.9 min irrelevant, 23.8 min relevant.
- **Never extract financial values from CSV rows.** They go through intake → classify → dedup → route only.

### 5.2 Real PSX documents (deep lane)
Real docs enter through `real_docs/manifest.csv`, which uses the same intake schema as a CSV row. Do not attach real PDFs to fake CSV rows.

### 5.3 Phase 0 download list
| Folder | URL |
|---|---|
| rulebooks/psx | https://www.psx.com.pk/psx/themes/psx/uploads/PSX-Regulations-February-09-2026.pdf |
| rulebooks/psx | https://www.psx.com.pk/psx/themes/psx/uploads/Correspondance-Manual-CM-final-version-01.pdf |
| rulebooks/secp | PDF linked from https://www.secp.gov.pk/document/the-companies-act-2017/ |
| real_docs/financial_results_dividend | https://dps.psx.com.pk/download/document/282260.pdf |
| real_docs/financial_results_dividend | https://dps.psx.com.pk/download/document/215429.pdf |
| real_docs/financial_results_dividend | https://dps.psx.com.pk/download/document/283228.pdf |
| real_docs/dividend_credit_notice | https://dps.psx.com.pk/download/document/282504.pdf |
| real_docs/dividend_credit_notice | https://dps.psx.com.pk/download/document/236785.pdf |
| real_docs/multi_entity_results | https://dps.psx.com.pk/download/document/283440.pdf |
| real_docs/multi_entity_results | https://dps.psx.com.pk/download/document/281401.pdf |
| real_docs/scanned_results | https://dps.psx.com.pk/download/document/240718.pdf |
| real_docs/template_filings | https://dps.psx.com.pk/download/document/185483.pdf |
| real_docs/template_filings | https://dps.psx.com.pk/download/document/207953.pdf |
| real_docs/template_filings | https://dps.psx.com.pk/download/document/230000.pdf |
| real_docs/regulatory_notice | https://dps.psx.com.pk/download/attachment/266509-1.pdf |

Hook articles — link only in `SOURCES.md`, do not download:
- https://www.khan.co.kr/en/article/202608121706037
- https://www.koreajoongangdaily.com/business/samsung-securities-ordered-to-pay-19-billion-won-over-2018-ghost-stock-error/12820504
- https://www.koreajoongangdaily.com/business/samsung-securities-ceo-resigns-over-blunder/10435625
- https://www.irishexaminer.com/breakingnews/business/samsung-in-270m-fat-finger-bungle-836736.html
- https://www.brecorder.com/news/amp/40419729

### 5.4 Samsung replay fixture (`fixtures/samsung_2018_replay.json`)
Build from public reporting only, with `"label": "Reconstruction from public reporting"` and the source URLs:
- Company: Samsung Securities; shares outstanding ≈ 89,000,000 (reported)
- Declared: cash dividend **1,000 KRW per share** on 2,812,950 employee-held shares (= 2,812,950,000 KRW)
- Erroneous instruction: **1,000 shares per share** → 2,812,950,000 shares to issue
- Expected pipeline outcome: DIV-01 and DIV-02 fail (critical), Resolver cannot fix, escalated with "issues ~31.6× shares outstanding"

---

## 6. Rules (YAML, loaded at runtime)

Each rule: `id, description, severity (critical|warning|info), check, params, source_clause`. `source_clause` cites the rulebook clause or the dataset; mark `verify: true` if the clause text hasn't been confirmed against the PDF yet.

### `csv_rules.yaml`
- CSV-01 relevance by document type (lists in 5.1)
- CSV-02 required metadata present; dates normalised to ISO 8601
- CSV-03 duplicate: same document_id, or same sha256, or fuzzy match on company + type + period
- CSV-04 log disagreement between agent stream and legacy `assigned_stream`

### `dividend_rules.yaml`
- DIV-01 unit type: cash dividend must be currency-per-share; bonus must be a share ratio (critical)
- DIV-02 shares to be issued ≤ shares outstanding (critical)
- DIV-03 Rs per share == percentage × face value (critical; tolerance 0.01)
- DIV-04 percent-only dividend → convert using `company_master.face_value_rs`; if face value missing → warning + lower confidence
- DIV-05 dividend credit notice amount == declared amount for the same company and period (critical)
- DIV-06 ex-price == previous close − entitlement (critical; only when both prices are supplied)
- DIV-07 total payout (per share × shares outstanding) plausible vs reported profit (warning)
- DIV-08 change vs previous period > 3× (warning)
- DIV-09 all five announcement items present: cash dividend, bonus shares, right shares, other entitlement/corporate action, other price-sensitive information (warning)
- DIV-10 book-closure dates ordered and after the announcement date (warning)

### `config/thresholds.yaml`
```
classifier_confidence_min: 0.80
resolver_max_loops: 2
complexity_escalate: {scanned: true, max_entities: 3, percent_without_face_value: true}
dividend_change_ratio_warn: 3.0
```

---

## 7. Agents (classical first → OpenAI → Claude)

Every decision records `method: classical | llm_openai | llm_claude`.

| Agent | Classical first | LLM fallback when | Decides |
|---|---|---|---|
| Orchestrator | LangGraph state machine | — | Path per doc; parallel fan-out; retries |
| Intake | normalise IDs/dates, sha256, dedup | — | accept / hold duplicate |
| Classifier | filename regex → keyword dictionary on first page → fuzzy | confidence < threshold | type, relevance, stream, confidence |
| Extractor | PyMuPDF text + bboxes, pdfplumber tables, per-category regex (`Rs. X per share`, `X%`, `NIL`, dates, `Rs '000`); OCR if no text layer | field not found / scanned / prose | values with provenance |
| Transformer | `units.py`; split tracks on "Consolidated"/"Unconsolidated"/"Standalone" headers | unclear boundaries | tracks + normalised values |
| Validator | `rules_engine.py` | — | RuleResult per rule |
| Resolver | re-extract the failed field on its page | targeted LLM re-read of that page region | fixed / unresolved (max 2 loops) |
| Router | thresholds.yaml | LLM writes a one-sentence consequence summary | auto_approve / needs_review / archive / reject / duplicate |
| Entry (tool) | `ledger.py` idempotent write | — | — |

**Routing paths:** admin → archive (skip extraction); duplicate → hold + link; relevant → extract → split → transform → validate → (fail → resolver ≤2 → validate) → entry → router.

**Escalation:** confidence below threshold; any critical rule failing after resolver; critical field from LLM without classical confirmation; complexity triggers. Escalated items **block ledger entry** until a human approves.

**Review packet** (for escalated items): consequence sentence, rule IDs + clauses, source page snippet + bbox, suggested fix.

### `llm.py` requirements
- `call_llm(prompt, schema, agent_name)`: try OpenAI → on error/timeout try Claude → on both failing raise `LLMUnavailable` so the caller uses its classical fallback.
- Per-call timeout, 2 retries with exponential backoff on 429/5xx.
- JSON output validated against a Pydantic schema, one repair retry.
- Append every call to `LLM_LOG` (agent, provider, prompt, response, latency, tokens if available).

---

## 8. Data models (Pydantic, `state.py`)

```
AuditEvent: doc_id, track_id, stage, agent, method, decision, confidence, rule_ids[],
            evidence{page, bbox, text}, started_at, duration_ms, status
FieldValue: name, value, unit, unit_type(currency_per_share|share_ratio|percent|amount|date|text),
            confidence, method, evidence{page, bbox, text}
Track:      track_id, entity_label, fields[FieldValue], rule_results[RuleResult], status
Document:   doc_id, source(csv_ps01|csv_ps07|manifest|fixture), filename, sha256, doc_type,
            relevance, stream, legacy_stream, tracks[Track], status, timings{stage: ms}
RuleResult: rule_id, passed, severity, message, expected, actual, source_clause
```

---

## 9. API contract

| Method | Path | Behaviour |
|---|---|---|
| GET | `/health` | `{ok: true}` |
| POST | `/batch` | body `{source: "csv" | "manifest" | "fixture" | "upload"}` or multipart PDFs → `{batch_id}`; runs async |
| GET | `/stream/{batch_id}` | SSE of AuditEvents |
| GET | `/batch/{batch_id}` | documents with status and stage timings |
| GET | `/doc/{doc_id}` | full Document incl. tracks, fields with provenance, rule results, review packet |
| GET | `/doc/{doc_id}/page/{n}.png` | rendered page image for the overlay |
| POST | `/review/{doc_id}` | `{action: approve|edit|reject, edits?: {...}, reviewer}` → writes to ledger if approved |
| GET | `/metrics` | automation_rate, throughput_docs_per_min, errors_caught_vs_baseline, time_saved_vs_baseline, classical_vs_llm_share, queue_depth_by_stage |
| GET | `/llm-log` | LLM_LOG (for the transparency panel) |

---

## 10. Phases (stop and show results after each)

**Phase 0 — Data acquisition.** Write and run `scripts/fetch_data.py`:
- Browser User-Agent, 30 s timeout, 3 retries with backoff, 2 s between requests.
- Verify each file starts with `%PDF` and opens in PyMuPDF; record pages, text layer, sha256.
- Rename to `<org>_<category>_<company-slug>_<period>_<psxdocid>.pdf` using company/period read from the PDF text; `unknown` + `needs_review=true` if uncertain.
- Write `real_docs/manifest.csv` (`filename, original_url, psx_doc_id, category, organisation, company, period, pages, has_text_layer, sha256, download_date, needs_review, notes`).
- Write `reference/company_master.csv` (`symbol, company, face_value_rs, shares_outstanding, source_url, retrieved_at, needs_review`), trying `https://dps.psx.com.pk/company/<SYMBOL>`; blank + flagged if not found.
- Write `SOURCES.md`; print a summary table (file, ok/failed/needs_review, reason).

**Phase 1 — Skeleton.** Layout, `.gitignore`, `.env.example`, `requirements.txt`, Dockerfile, FastAPI with `/health`, CORS, `$PORT`. Must run locally and in Docker.

**Phase 2 — Tools.** `pdf_text.py`, `ocr.py`, `units.py`, `dedup.py`, `rules_engine.py`, `ledger.py`, `audit.py` + unit tests for `units.py`, `dedup.py`, `rules_engine.py` (include the Samsung numbers as a test).

**Phase 3 — `llm.py` + `prompts.py`.**

**Phase 4 — Agents** one at a time, each with a test on one real doc.

**Phase 5 — Orchestrator** (LangGraph) wiring routing, fan-out, resolver loop, escalation.

**Phase 6 — API** (section 9) + SSE + metrics computed from audit events and the ps07 baseline.

**Phase 7 — End-to-end run:** CSV batch (450 rows) + manifest batch + Samsung fixture. Print metrics. Confirm: `FDOC-35032` held as duplicate; Shell template filings **not** flagged as duplicates; PSO filing split into unconsolidated + consolidated tracks; percent-only dividend converted via face value or flagged; Samsung fixture escalated with DIV-01 + DIV-02.

**Phase 8 — Frontend (not built yet).** Vite + React in `frontend/`, reading `VITE_API_URL`:
- Upload / run-batch screen (buttons: CSV batch, real docs, Samsung replay)
- Batch board: columns Queued → Classified → Extracting → Validating → Needs review → Done / Archived / Duplicate, live via SSE
- Document detail: page image with bbox overlay per extracted value; rule results with clauses; method badges (classical / OpenAI / Claude)
- Review panel: consequence sentence, evidence, Approve / Edit / Reject
- Metrics panel vs ps07 baseline; LLM log panel
- "Reconstruction from public reporting" badge on the Samsung fixture
- Readable on a projector and a phone

**Phase 9 — Docs.** `README.md` (problem + hook, agents, run locally, deploy, scalability path: Pub/Sub/Cloud Tasks + Firestore/BigQuery + autoscaled workers), `docs/architecture.md` mermaid diagram.

**Phase 10 — Pre-submission audit.** Report (do not silently fix): secrets anywhere incl. git history; any hardcoded/mock output reachable from the UI; UI features that don't work; TODOs reachable from the UI.

---

## 11. Deployment (give me commands; I run them)

Backend (project `finale`, secrets `openai-key` and `anthropic-key` already in Secret Manager):
```
gcloud run deploy agent-app --source ./backend --region us-central1 --allow-unauthenticated --set-secrets OPENAI_API_KEY=openai-key:latest,ANTHROPIC_API_KEY=anthropic-key:latest --set-env-vars OPENAI_MODEL=<model>,ANTHROPIC_MODEL=<model> --memory 2Gi --timeout 900 --max-instances 1
```
Before presenting: `gcloud run services update agent-app --min-instances 1`

Frontend: Vercel, root directory `frontend`, env `VITE_API_URL=<Cloud Run URL>`.

---

## 12. Working style

- Small, readable files; prefer plain functions over class hierarchies.
- Tell me which files you changed after each step.
- Ask before adding a dependency not listed in section 3.
- If a requirement here conflicts with something you find in the data, stop and tell me — don't work around it silently.
