---
spec_version: "2.1"
name: "ideaforge"
version: "2.1.0"
type: "service"
status: "active"
created: "2026-03-08"
updated: "2026-03-18"
---

## Purpose

IdeaForge is a local-first idea extraction, evaluation, and learning pipeline. It ingests content from YouTube videos, PDFs, RSS feeds, and raw text, evaluates ideas through LLM analysis (Gemini or Anthropic) against a solo developer profile, and generates paste-ready Claude Code implementation instructions. Beyond evaluation, IdeaForge tracks outcomes (did you actually build it?), surfaces patterns from evaluation history, runs overnight radar scans on subscribed channels/feeds, and exports a calibrated "Founder Brain" profile. The goal: every evaluation makes the next one smarter.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  HTTP Server (127.0.0.1:7888)                │
│             ThreadedHTTPServer + Handler (do_GET/POST/DELETE)│
├──────────────┬───────────────────────────────────────────────┤
│  index.html  │  REST API (/api/*)                           │
│  SPA frontend│  JSON endpoints for all operations           │
│  Vanilla JS  │  Serves frontend at /                        │
├──────────────┴───────────────────────────────────────────────┤
│                  Job Queue + Worker Thread                    │
│  queue.Queue → worker_loop() → handle_job() → chain next    │
├──────────────┬───────────────┬───────────────────────────────┤
│  Phase 1     │  Phase 2      │  Phase 3                     │
│  Extract     │  Evaluate     │  Instruct                    │
│  yt-dlp/PDF/ │  LLM call     │  LLM call                   │
│  RSS/Text    │  JSON verdict │  Markdown instruction        │
├──────────────┴───────────────┴───────────────────────────────┤
│  Radar Thread (daemon)                                       │
│  Hourly scan_due_subscriptions() → radar_scan → auto-ingest │
├──────────────────────────────────────────────────────────────┤
│  Pattern Intelligence + Brain Export                         │
│  compute_patterns() / build_brain_export()                   │
├──────────────────────────────────────────────────────────────┤
│  NotebookLM Integration (optional)                           │
│  nlm CLI: create notebooks, add sources, generate artifacts  │
├──────────────────────────────────────────────────────────────┤
│  SQLite WAL (ideaforge.db)  │  Filesystem (data/<id>/)      │
│  ideas, events, notebooks,  │  Transcripts, evals, instrs,  │
│  subscriptions, calibration │  brain exports                 │
└─────────────────────────────┴────────────────────────────────┘
```

**Components:**
- `ideaforge` -- Single-file Python executable (~2170 lines); HTTP server, job queue, worker, radar thread, and all pipeline logic
- `index.html` -- Self-contained SPA frontend (~3385 lines, vanilla JS + CSS, no build step, no dependencies)
- `ideaforge.db` -- SQLite WAL database storing ideas, events, notebooks, subscriptions, calibration log
- `data/<id>/` -- Per-idea directory with raw subtitles, cleaned transcript, evaluation JSON, instruction markdown
- `data/brain/` -- Founder brain exports (JSON + Markdown)
- `.env` -- API keys and config (GEMINI_API_KEY, ANTHROPIC_API_KEY, IDEAFORGE_MODEL, IDEAFORGE_ALLOW_NO_AI, IDEAFORGE_TELEGRAM_TOKEN, IDEAFORGE_TELEGRAM_CHAT_ID)

## Features (v2.1)

| Feature | Layer | Description |
|---------|-------|-------------|
| Multi-Source Ingestion | L4 | YouTube, PDF, RSS, raw text inputs |
| Outcome Tracking | L1 | Track shipped/abandoned/pivoted outcomes per idea |
| Calibration Log | L1 | Ship rate per verdict, effective threshold snapshots |
| Overnight Radar | L2 | Subscription-based auto-scanning (channels/searches/feeds) |
| Telegram Digest | L2 | Optional notifications for new radar discoveries |
| Pattern Intelligence | L3 | Verdict distribution, ship rates, complexity breakdown |
| Founder Brain Export | L5 | Portable calibrated judgment as JSON + CLAUDE.md markdown |
| Visual Grid UI | UI | Full-width thumbnail grid with verdict overlays and filter chips |

## Frontend (index.html)

### Theme & Visual Style

Dark cyberpunk glassmorphism aesthetic. All styling via CSS custom properties:

```css
--bg: #0a0a0a;                          /* Page background */
--bg-card: rgba(17,17,17,0.7);         /* Card background (glass) */
--bg-card-solid: #111;                  /* Solid card background */
--bg-input: #0d0d0d;                    /* Input field background */
--accent: #00f0ff;                      /* Cyan primary accent */
--accent-dim: rgba(0,240,255,0.12);    /* Cyan dim background */
--accent-glow: rgba(0,240,255,0.25);   /* Cyan glow */
--text: #d1d1d1;                        /* Primary text */
--text-muted: #888;                     /* Secondary text */
--text-dim: #555;                       /* Tertiary/disabled */
--border: #282828;                      /* Default border */
--border-hover: #444;                   /* Hover border */
--build: #00ff88;                       /* BUILD verdict (green) */
--build-dim: rgba(0,255,136,0.12);     /* BUILD dim background */
--skip: #ff4444;                        /* SKIP verdict (red) */
--skip-dim: rgba(255,68,68,0.12);      /* SKIP dim background */
--park: #ffaa00;                        /* PARK verdict (orange) */
--park-dim: rgba(255,170,0,0.12);      /* PARK dim background */
--font-display: 'JetBrains Mono', monospace;  /* Headers, code */
--font-body: 'IBM Plex Sans', sans-serif;     /* Body text */
--radius: 10px;                         /* Default border radius */
--radius-sm: 6px;                       /* Small border radius */
```

Cards use `backdrop-filter: blur(12px)` for glass effect. Elements lift on hover (`translateY(-2px)`). Loading states use pulse animations. Verdict badges use their respective colors on tinted backgrounds.

### Layout Structure

Full-width responsive design. Content uses `padding: 0 24px` with no max-width cap (except pipeline view at 1400px). Hero section is compact (~150px) with main input and action buttons.

**Responsive breakpoints:**
- Desktop XL (>1281px): 40px side padding, 300px min grid columns
- Tablet (641-1024px): 280px min grid columns, pipeline 100% width
- Mobile (<640px): single-column grid, stacked input group, vertical stepper

### Navigation & Views

4 main tabs via sticky `.main-tabs` bar:

| Tab | View ID | Content |
|-----|---------|---------|
| Ideas | `#view-ideas` | Search results, notebooks panel, ideas grid with filter toolbar |
| Pipeline | `#view-pipeline` | 5-step wizard: Source → Processing → Results → Generate → Done |
| Radar | `#view-radar` | Subscription management (create, toggle, run, delete) |
| Insights | `#view-insights` | Pattern metrics + Founder Brain export |

### Ideas Grid (Visual Cards)

Ideas render in a CSS Grid (`repeat(auto-fill, minmax(320px, 1fr))`) as visual cards (`.idea-card-visual`):

```
┌─────────────────────────────────┐
│  [Thumbnail 16:9]               │
│  ┌BUILD┐              ┌──82──┐  │  ← verdict badge (top-left), fit score (top-right)
│  └─────┘              └──────┘  │
│  ☑                    ● ● ●    │  ← checkbox (top-left), status dots (bottom-right)
├─────────────────────────────────┤
│  Title of the Video             │
│  One-sentence AI summary        │  ← from eval_one_sentence
├─────────────────────────────────┤
│  [Eval] [Spec] [Trans]  [Re-run]│  ← action buttons
└─────────────────────────────────┘
```

**Thumbnail derivation:** YouTube thumbnails pulled from `https://img.youtube.com/vi/{VIDEO_ID}/mqdefault.jpg` (320x180). Non-YouTube sources show a fallback icon (PDF=📄, RSS=📡, Text=📝, Video=🎬).

**Video ID extraction:** `extractVideoId(url)` parses `?v=`, `youtu.be/`, `/embed/`, `/shorts/` patterns.

**Filter toolbar:** Chips for ALL / BUILD / PARK / SKIP / Pending. Shows `filtered / total` count. Filter state stored in `activeFilter` global variable.

**Verdict badge colors:** BUILD=green, SKIP=red, PARK=orange. Badges position absolute over thumbnail top-left.

**Status dots:** 3 small dots (bottom-right of thumbnail) for Extract/Evaluate/Instruct pipeline status. Colors: done=green, running=orange, failed=red, pending=gray.

### Search Results (Visual Cards)

YouTube search results render as `.search-card-visual` in the existing `.search-grid`:

```
┌───────────────┐
│  [Thumbnail]  │
│          3:42 │  ← duration badge (bottom-right)
│  ☐            │  ← selection checkmark (top-left)
├───────────────┤
│  Title        │
│  Channel · 2K │
│  2026-01-15   │
└───────────────┘
```

Selection toggles via `toggleSearchCard()` / `pipeToggleSearch()` using `.scv-check` selector.

### Modal System

`#modal` overlay with 4 tabs:
- **Transcript** -- raw extracted text with copy button
- **Evaluation** -- AI analysis JSON rendered as structured display
- **Build Spec** -- paste-ready markdown with "Copy for Claude Code" (adds header)
- **Events** -- processing timeline with timestamps

### Discovery Layer

- **Forge Map** (`?` key or button) -- command palette overlay with clustered feature list, filterable by category
- **Whisper Hints** -- rotating placeholder text in main input showing example queries
- **Feature Discovery Glow** -- CSS animation highlighting unexplored tabs
- **Floating Hint Bar** -- bottom bar with contextual suggestions

### Key JS Functions

**State:**
```
currentIdeaId, pendingJobs, selectedSearch, selectedIdeas, ideaCache,
nlmAvailable, nlmAuth, chatAnswers, activeFilter, pipe, pipeSearchSel, postRenderHooks
```

**API loaders:** `preflight()`, `loadIdeas()`, `loadNotebooks()`, `loadSubscriptions()`, `loadPatterns()`, `loadBrain()`, `checkNlmAuth()`

**Handlers:** `handleSubmit()`, `handleExtractOnly()`, `ingestSelected()`, `queueEval()`, `queueInstr()`, `queueRunAll()`, `del()`, `setOutcome()`, `createSubscription()`, `runSubscription()`, `toggleSubscription()`, `deleteSubscription()`, `exportBrain()`

**Renderers:** `renderIdeas()`, `renderStepper()`, `renderVerdict()`, `renderSearchResults()`, `renderNotebooks()`, `renderSubscriptions()`, `renderPatterns()`, `renderBrain()`, `renderPipeSearch()`, `renderPipeChips()`, `renderForgeMap()`

**Helpers:** `extractVideoId()`, `thumbnailUrl()`, `filterIdeas()`, `formatViews()`, `fmtTok()`, `esc()`, `isDirectSource()`, `sourceBadge()`, `toast()`

**Polling:** `setInterval(loadIdeas, 3000)`, `setInterval(loadNotebooks, 5000)`, `setInterval(checkNlmAuth, 30000)`

## API / Tools

### GET Endpoints

| Endpoint | Input | Output |
|----------|-------|--------|
| `/` | -- | `index.html` SPA |
| `/api/preflight` | -- | System status: yt-dlp, AI backend, model, NLM, PDF, RSS availability |
| `/api/ideas` | -- | All ideas (DESC by created_at) |
| `/api/events/<id>` | idea ID in path | Last 80 events for idea |
| `/api/content/<id>/<kind>` | idea ID + kind (transcript\|evaluation\|instruction) | Raw artifact text |
| `/api/notebooks` | -- | All notebooks with idea counts |
| `/api/pipeline-status/<id>` | notebook ID | Notebook + linked ideas + progress counters |
| `/api/notebook/<id>` | notebook ID | Notebook detail with linked ideas |
| `/api/patterns` | -- | Pattern intelligence (verdicts, fit scores, complexity, trends) |
| `/api/calibration` | -- | Latest calibration snapshot |
| `/api/brain/latest` | -- | Latest brain export JSON or null |
| `/api/subscriptions` | -- | All subscriptions with run stats |
| `/api/subscription/<id>/runs` | subscription ID | Run history (last 50) |
| `/api/nlm/status` | -- | NotebookLM CLI auth status |
| `/api/nlm/notebooks` | -- | Remote NLM notebook list |

### POST Endpoints

| Endpoint | Input (JSON body) | Output |
|----------|-------------------|--------|
| `/api/ingest` | `{url}` | Extract-only: queues Phase 1 (auto-detects source kind) |
| `/api/run-all` | `{url}` | Full pipeline: extract -> evaluate -> instruct |
| `/api/run-all/<id>` | idea ID in path | Re-run pipeline for existing idea |
| `/api/evaluate/<id>` | idea ID in path | Queue Phase 2 only |
| `/api/instruct/<id>` | idea ID in path | Queue Phase 3 only |
| `/api/outcome/<id>` | `{outcome, notes?}` | Set outcome (shipped\|abandoned\|pivoted\|in_progress) |
| `/api/brain/export` | `{}` | Build + save brain export, returns JSON |
| `/api/subscription` | `{name, kind, target, frequency_hours?, max_items?}` | Create subscription |
| `/api/subscription/<id>` | `{action:"update"\|"toggle", ...}` | Update/toggle subscription |
| `/api/subscription/<id>/run` | -- | Manual trigger radar scan |
| `/api/search` | `{query, max_results?}` | YouTube search via yt-dlp |
| `/api/bulk-ingest` | `{urls[], run_all?}` | Batch ingest multiple URLs |
| `/api/notebook` | `{name, idea_ids[]}` | Create NLM notebook from ideas |
| `/api/pipeline` | `{urls[], notebook_name?}` | Full pipeline + notebook creation |
| `/api/notebook/<id>/finalize` | notebook ID in path | Trigger NLM notebook creation |
| `/api/notebook/<id>/generate` | `{type}` | Generate artifact (audio/video/quiz/mind-map/slide-deck) |
| `/api/nlm/push` | `{idea_id, notebook_name?, nlm_id?}` | Push idea to NLM directly |
| `/api/nlm/generate` | `{nlm_id, type?}` | Generate NLM artifact by remote ID |
| `/api/nlm/chat` | `{nlm_id, question}` | Query NLM notebook sources |
| `/api/nlm/share` | `{nlm_id, enable?}` | Toggle notebook sharing |

### DELETE Endpoints

| Endpoint | Input | Output |
|----------|-------|--------|
| `/api/ideas/<id>` | idea ID in path | Deletes idea + purges data directory |
| `/api/notebook/<id>` | notebook ID in path | Deletes notebook + junction records |
| `/api/subscription/<id>` | subscription ID | Deletes subscription + run history |

## Data Models

### SQLite Schema

```sql
CREATE TABLE ideas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  youtube_url TEXT NOT NULL,
  video_title TEXT,

  transcript_path TEXT,           -- raw SRT/VTT path
  transcript_clean_path TEXT,     -- cleaned plaintext path
  transcript_format TEXT,         -- "srt" or "vtt"
  transcript_sha256 TEXT,
  transcript_preview TEXT,        -- first 800 chars

  extract_status TEXT NOT NULL DEFAULT 'pending',   -- pending|extracting|done|failed
  eval_status TEXT NOT NULL DEFAULT 'pending',      -- pending|running|done|failed|disabled
  instr_status TEXT NOT NULL DEFAULT 'pending',     -- pending|running|done|failed|disabled

  evaluation_path TEXT,           -- JSON file path
  instruction_path TEXT,          -- Markdown file path

  extract_duration_ms INTEGER,
  eval_input_tokens INTEGER,
  eval_output_tokens INTEGER,
  eval_duration_ms INTEGER,
  instr_input_tokens INTEGER,
  instr_output_tokens INTEGER,
  instr_duration_ms INTEGER,

  eval_verdict TEXT,              -- BUILD|SKIP|PARK
  eval_fit_score INTEGER,         -- 0-100
  eval_complexity INTEGER,        -- 1-5
  eval_one_sentence TEXT,         -- top idea summary

  outcome TEXT,                   -- shipped|abandoned|pivoted|in_progress
  outcome_notes TEXT,
  outcome_at TEXT,

  source_kind TEXT DEFAULT 'youtube',  -- youtube|pdf|rss|text
  source_path TEXT,

  last_error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  idea_id INTEGER,
  ts TEXT NOT NULL,
  kind TEXT NOT NULL,              -- extract:*|eval:*|instr:*|ingest|outcome:*|radar:*|...
  detail TEXT,
  FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE
);

CREATE TABLE notebooks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  nlm_id TEXT,                    -- NotebookLM remote ID
  status TEXT NOT NULL DEFAULT 'pending',
  artifact_type TEXT,
  artifact_status TEXT,
  artifact_path TEXT,
  error TEXT,
  share_status TEXT,
  share_url TEXT,
  audio_status TEXT,
  video_status TEXT,
  quiz_status TEXT,
  mindmap_status TEXT,
  slides_status TEXT,
  source_count INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE idea_notebooks (
  idea_id INTEGER NOT NULL,
  notebook_id INTEGER NOT NULL,
  PRIMARY KEY (idea_id, notebook_id),
  FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE CASCADE,
  FOREIGN KEY(notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE TABLE calibration_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_at TEXT NOT NULL,
  total_with_outcome INTEGER,
  build_count INTEGER,
  skip_count INTEGER,
  park_count INTEGER,
  build_ship_rate REAL,
  skip_ship_rate REAL,
  park_ship_rate REAL,
  avg_fit_shipped REAL,
  avg_fit_not_shipped REAL,
  effective_threshold REAL
);

CREATE TABLE subscriptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,              -- youtube_channel|youtube_search|rss_feed
  target TEXT NOT NULL,
  frequency_hours INTEGER NOT NULL DEFAULT 24,
  max_items INTEGER NOT NULL DEFAULT 5,
  auto_evaluate INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_run_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE subscription_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  sub_id INTEGER NOT NULL,
  run_at TEXT NOT NULL,
  new_ideas INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ok',
  detail TEXT,
  FOREIGN KEY(sub_id) REFERENCES subscriptions(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX idx_ideas_created ON ideas(created_at);
CREATE INDEX idx_events_idea ON events(idea_id, ts);
```

### Filesystem Layout

```
data/
  <idea_id>/
    sub.en.srt              -- raw subtitle (yt-dlp output)
    sub.en-orig.srt         -- alternate subtitle track
    transcript.cleaned.txt  -- timestamps/indices stripped, single text block
    evaluation.json         -- Phase 2 LLM output (strict JSON schema)
    instruction.md          -- Phase 3 LLM output (Claude Code paste-ready markdown)
  notebooks/
    <notebook_id>/
      <artifact_type>.<ext> -- downloaded NLM artifact (mp3/mp4/md/json/pdf/csv/png)
  brain/
    brain-latest.json       -- latest founder brain export
    FOUNDER-BRAIN.md        -- markdown version for CLAUDE.md integration
```

### Evaluation JSON Schema (Phase 2 output)

```json
{
  "video_title": "string",
  "top_idea": {
    "one_sentence": "string",
    "why_now": "string",
    "who_pays": "string",
    "mvp_scope": ["string"],
    "non_goals": ["string"]
  },
  "fit": {
    "fit_score_0_100": "int",
    "time_to_mvp_days": "int",
    "complexity_1_5": "int",
    "maintenance_burden_1_5": "int",
    "budget_risk_1_5": "int"
  },
  "build_recommendation": {
    "verdict": "BUILD|SKIP|PARK",
    "reasons": ["string"],
    "killer_risks": ["string"]
  },
  "execution": {
    "suggested_stack": ["string"],
    "milestones": [{"name": "string", "exit_criteria": ["string"]}],
    "what_to_verify_first": ["string"],
    "what_to_ignore": ["string"]
  },
  "evidence_hooks": [
    {"claim": "string", "transcript_support": "string"}
  ]
}
```

### Brain Export JSON Schema

```json
{
  "version": 1,
  "exported_at": "ISO timestamp",
  "profile": {
    "role": "solo_developer",
    "total_evaluated": "int",
    "total_with_outcome": "int",
    "overall_ship_rate": "float"
  },
  "calibration": {
    "build_ship_rate": "float",
    "skip_ship_rate": "float",
    "park_ship_rate": "float",
    "effective_threshold": "float"
  },
  "patterns": {
    "avg_fit_by_verdict": {"BUILD": "float", "SKIP": "float", "PARK": "float"},
    "complexity_distribution": {"1": "int", "2": "int", "3": "int", "4": "int", "5": "int"}
  },
  "verdict_anchors": {
    "top_builds": [{"title": "string", "fit_score": "int", "outcome": "string"}],
    "top_skips": [{"title": "string", "fit_score": "int", "outcome": "string"}]
  },
  "signature": "SHA-256 of exported_at + total_evaluated"
}
```

## Constraints

- **Single-file architecture** -- entire backend is one Python script (`ideaforge`), no modules or packages
- **Single-file frontend** -- entire frontend is one HTML file (`index.html`), no build step, no npm, no framework
- **Loopback only** -- binds to 127.0.0.1:7888, not exposed to network
- **AI backend optional** -- runs in extract-only mode if no API key set (IDEAFORGE_ALLOW_NO_AI=1)
- **AI priority** -- prefers Gemini (free tier) over Anthropic to avoid cost
- **Transcript limit** -- evaluation prompt truncates transcript to 120K chars
- **Token budgets** -- Phase 2: 1400 max output tokens; Phase 3: 1800 max output tokens
- **yt-dlp dependency** -- requires yt-dlp installed system-wide for transcript extraction and YouTube search
- **NotebookLM optional** -- NLM features require `notebooklm-py[browser]` pip package
- **PDF optional** -- requires `pdfminer.six` pip package
- **RSS optional** -- requires `feedparser` pip package
- **Telegram optional** -- digest requires `requests` pip package + env vars
- **No auth** -- HTTP server has no authentication (loopback-only design assumption)
- **SQLite WAL mode** -- concurrent reads allowed, single writer
- **Patterns minimum** -- Pattern intelligence requires 10+ evaluated ideas
- **YouTube thumbnails** -- derived client-side from video URL, no API key needed (`img.youtube.com/vi/{id}/mqdefault.jpg`)

## Quality

- **Working means:** Server starts, preflight returns green for yt-dlp, a YouTube URL submits and progresses through extract -> evaluate -> instruct, artifacts appear in data/<id>/, ideas grid shows thumbnail cards with verdict badges
- **Verification:** `/api/preflight` endpoint reports system health (yt-dlp, AI backend, NLM, PDF, RSS status)
- **Event log:** Every pipeline step logs to `events` table with timestamps and duration metrics
- **Token tracking:** Input/output token counts stored per idea for cost monitoring
- **Calibration:** Outcome tracking feeds calibration log; patterns computed from 10+ evaluated ideas
- **Error capture:** `last_error` field on ideas, `error` field on notebooks; errors capped at 2000/500 chars
- **No automated tests** -- verification is manual via the web UI and API

## Agent Guidance

**What this project does well:**
- Single-file, zero-dependency-bloat architecture (2 files total: backend + frontend)
- Clean 3-phase pipeline with job chaining
- Full audit trail via events table
- Profile-tuned evaluation (not generic summarization)
- Compounding learning: outcomes feed calibration, calibration feeds patterns, patterns feed brain export
- Visual grid with YouTube thumbnails for browseable idea discovery
- Dark cyberpunk aesthetic with consistent design language

**What to focus on if improving:**
- Add automated tests (currently zero)
- The frontend is a ~3385-line monolith -- consider splitting if adding features
- Error recovery: failed jobs don't auto-retry
- No rate limiting on LLM calls
- YouTube search results are not cached
- Radar scan deduplication only checks exact URL match

**What to avoid:**
- Don't break the single-file backend pattern without strong reason
- Don't break the single-file frontend pattern without strong reason
- Don't remove the extract-only fallback mode (ALLOW_NO_AI)
- Don't expose the server beyond loopback without adding auth
- Don't switch away from SQLite WAL (concurrent read performance matters)
- Don't remove conditional imports (PDF, RSS, requests are optional)
- Don't add npm/webpack/framework dependencies to the frontend
- Don't change the CSS custom property names (theme contract)
- Don't change the verdict color semantics (BUILD=green, SKIP=red, PARK=orange)

**Replication checklist (for another AI to rebuild this):**
1. Create `ideaforge` Python script: HTTP server on 127.0.0.1:7888, SQLite WAL, job queue with worker thread, 3-phase pipeline (extract via yt-dlp, evaluate via Gemini/Anthropic, instruct via same), radar daemon thread, pattern computation, brain export
2. Create `index.html` SPA: dark theme with CSS variables above, 4-tab navigation (Ideas/Pipeline/Radar/Insights), responsive CSS Grid for idea cards with YouTube thumbnails, verdict badge overlays, filter toolbar, search with thumbnail cards, modal with transcript/evaluation/instruction/events tabs, pipeline wizard, subscription management, pattern display, brain export UI
3. Create `.env` with GEMINI_API_KEY and/or ANTHROPIC_API_KEY
4. Install yt-dlp system-wide
5. Run `python3 ideaforge` and open http://127.0.0.1:7888/

## Related Systems

- **yt-dlp** -- External CLI for transcript extraction and YouTube search
- **notebooklm-py** -- Optional CLI for Google NotebookLM integration (podcast/video/quiz generation)
- **pdfminer.six** -- Optional Python library for PDF text extraction
- **feedparser** -- Optional Python library for RSS/Atom feed parsing
- **Anthropic API / Google Gemini API** -- LLM backends for Phase 2 (evaluation) and Phase 3 (instruction generation)
- **Telegram Bot API** -- Optional digest notifications for radar discoveries
- **agent-memory** -- Shared memory at `~/.mcp-memory/` (IdeaForge findings can be written there for cross-agent context)
