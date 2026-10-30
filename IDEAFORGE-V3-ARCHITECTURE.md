# IdeaForge v3 Architecture Brief

**Document type:** Implementation-grade architecture brief
**Status:** Decision document — not marketing, not code
**Date:** 2026-03-18
**Author:** Claude Code (Opus 4.6), commissioned by Osman
**Central thesis:** IdeaForge v3 should transform the current multi-source research-to-build app into a calibrated founder-brain service that other agents can query before they search, rank, or build.

---

## 1. Executive Summary

IdeaForge is currently a local-first, multi-source idea triage system that evaluates content against a solo founder profile and generates implementation specs. It already has outcome tracking, calibration, pattern intelligence, radar scanning, brain export, and a compounding learning loop. It is not a summarizer. It is a decision engine.

**v3 adds three things:**

1. **Research Mode** — natural-language research briefs that search, rank, and explain sources before ingesting them into the pipeline. Replaces blind URL-pasting with intentional, AI-planned retrieval.

2. **Brain-as-infrastructure** — the calibrated founder brain becomes a queryable service, not just an export file. The brain influences research ranking, evaluation thresholds, and surfaces historical patterns to guide future decisions.

3. **MCP interface** — IdeaForge exposes its decision engine as MCP tools that other agents (Claude Code sessions, Opi, future tools) can call. "Should I build this?" becomes a single tool call.

**The single biggest strategic shift:** IdeaForge stops being a dashboard you visit and becomes a decision layer that other tools consult.

---

## 2. Current-State Reality Check

### What v2.1 actually is

IdeaForge v2.1 is a 2-file local application:
- `ideaforge` — single-file Python backend (~2170 lines), HTTP server on 127.0.0.1:7888, SQLite WAL, job queue with worker thread, radar daemon
- `index.html` — single-file SPA frontend (~3385 lines), dark cyberpunk theme, 4-tab navigation, visual grid with YouTube thumbnails

### What it already does (that older specs miss)

| Feature | Status | Detail |
|---------|--------|--------|
| Multi-source ingestion | Done | YouTube, PDF, RSS, raw text |
| 3-phase pipeline | Done | Extract → Evaluate → Instruct |
| Outcome tracking | Done | shipped/abandoned/pivoted/in_progress per idea |
| Calibration log | Done | Ship rate per verdict, effective threshold snapshots |
| Pattern intelligence | Done | Verdict distribution, complexity breakdown, weekly trends (requires 10+ evaluated ideas) |
| Brain export | Done | JSON + CLAUDE.md markdown, includes verdict anchors and calibration |
| Radar scanning | Done | Subscriptions for YouTube channels/searches and RSS feeds, hourly daemon |
| Telegram digest | Done | Optional BUILD alerts from radar discoveries |
| Visual grid UI | Done | Thumbnail cards with verdict badge overlays, fit scores, status dots |
| Filter toolbar | Done | ALL/BUILD/PARK/SKIP/Pending chips |
| Discovery layer | Done | Forge Map (command palette), whisper hints, discovery glow |
| Compounding loop | Done | evaluate → outcome → calibrate → patterns → brain → feed back |

### What older descriptions get wrong

- Calling it "YouTube-only" — it handles 4 source types
- Calling it a "summarizer" — it produces verdicts and implementation specs, not summaries
- Claiming 10 instruction sections — the actual Phase 3 prompt produces 7 consolidated sections
- Ignoring the learning loop — the compounding cycle (outcomes → calibration → patterns → brain) is the most architecturally interesting feature
- Treating NotebookLM as central — it's a downstream optional multiplier, not the core product

### Current numbers

- 30 ideas ingested, 22 evaluated (73%), 1 with tracked outcome (3%)
- Evaluation uses `EVAL_PROFILE` with 4 fields: developer_profile, budget, domain_advantage, style
- AI backends: Gemini 2.0 Flash (primary, free), Claude Sonnet 4.5 (fallback)
- Token budgets: Phase 2 = 1400 max output, Phase 3 = 1800 max output

---

## 3. v3 Product Thesis

### One sentence

IdeaForge v3 turns a calibrated founder decision engine into reusable infrastructure that other agents can query before they search, rank, or build.

### One paragraph

The moat is not search. Every tool can search. The moat is calibrated judgment — a system that knows what you've evaluated, what you shipped, what you abandoned, and what your actual hit rate is across different complexity levels, verdict types, and domains. v3 exposes that judgment as a service: Research Mode feeds the brain faster by bringing structured retrieval into the pipeline, and the MCP interface makes the brain callable by any agent that needs a founder-fit check before starting work.

### Expanded framing

IdeaForge v1 was a YouTube evaluator. v2 added multi-source ingestion, outcome tracking, calibration, patterns, brain export, and radar — turning it into a learning system. v3 completes the loop by making the learned judgment accessible:

```
v1: paste URL → get verdict
v2: paste URL → get verdict → track outcome → calibrate → learn → export brain
v3: describe research → AI searches → brain-ranked results → ingest best → verdict → outcome → calibrate → brain improves → brain queryable by any agent
```

The progression: **tool → learning system → decision infrastructure.**

---

## 4. Target Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                        MCP Interface Layer                            │
│  tools: brain_query, evaluate_idea, research_run, pattern_export     │
│  resources: brain://latest, calibration://snapshot, patterns://all   │
├──────────────────────────────────────────────────────────────────────┤
│                        HTTP Server (127.0.0.1:7888)                  │
│                ThreadedHTTPServer + Handler (existing)               │
├──────────────┬───────────────────────────────────────────────────────┤
│  index.html  │  REST API (/api/*)                                   │
│  SPA frontend│  + /api/research/* (new)                             │
├──────────────┴───────────────────────────────────────────────────────┤
│                        Research Layer (new)                           │
│  Planner (LLM) → Retrieval (yt-dlp/YT API/RSS/web) → Reranker (LLM)│
│  research_runs + research_results → ingest into ideas               │
├──────────────────────────────────────────────────────────────────────┤
│                        Brain Layer (enhanced)                        │
│  Calibration → Patterns → Threshold → Brain Export → Brain Query    │
│  research_briefs tracking → funnel analytics → decision memory      │
├──────────────────────────────────────────────────────────────────────┤
│                        Core Pipeline (existing, unchanged)           │
│  Phase 1: Extract → Phase 2: Evaluate → Phase 3: Instruct          │
│  Job queue → worker_loop → handle_job → chain next                  │
├──────────────────────────────────────────────────────────────────────┤
│                        Radar (existing, enhanced)                    │
│  Subscriptions + Research Briefs (saveable as recurring scans)       │
│  Hourly daemon + manual triggers + Telegram digest                   │
├──────────────────────────────────────────────────────────────────────┤
│  SQLite WAL (ideaforge.db)          │  Filesystem (data/)            │
│  + research_runs, research_results  │  + data/research/              │
│  + research_briefs                  │  + data/brain/                 │
└─────────────────────────────────────┴────────────────────────────────┘
```

**Key architectural rules:**
- Research Layer sits ABOVE the pipeline — it feeds ideas into the existing extract/evaluate/instruct flow
- Brain Layer sits BESIDE the pipeline — it reads outcomes from ideas and influences both research ranking and evaluation thresholds
- MCP Layer sits ABOVE everything — it exposes brain, research, and evaluation as callable tools
- The existing pipeline is untouched — v3 adds layers, it does not rewrite the core

---

## 5. Research Mode Design

### 5.1 Research Planner

The user writes a natural-language research brief. The LLM converts it into a structured search plan.

**Input example:**
```
Find videos about Claude Code agent teams and subagents for solo developers,
published in 2026, at least 15 minutes, English preferred, Turkish acceptable.
Focus on practical builds, not enterprise demos.
```

**Planner output:**
```json
{
  "topic": "Claude Code agent teams for solo developers",
  "date_from": "2026-01-01T00:00:00Z",
  "date_to": "2026-03-18T23:59:59Z",
  "min_duration_minutes": 15,
  "languages": ["en", "tr"],
  "queries": [
    "\"Claude Code\" agent teams subagents solo developer 2026",
    "\"Claude Code\" skills CLAUDE.md MCP tutorial 2026",
    "Claude Code indie hacker workflow automation 2026"
  ],
  "must_signals": ["agent teams", "subagents", "real build", "solo developer"],
  "exclude_signals": ["enterprise", "corporate", "marketing"],
  "scoring_rubric": {
    "founder_fit": "Solo Arch Linux dev, ships fast, local-first preference",
    "actionability": "Shows a buildable technique, not just a demo",
    "recency": "Published in 2026, fresher is better"
  },
  "max_candidates": 50,
  "source_types": ["youtube"]
}
```

**Planner prompt:** Uses the same `EVAL_PROFILE` that Phase 2 uses. The founder brain context is injected: "This founder's effective threshold is 72. They ship 60% of BUILD verdicts. They execute best on CLI tools (80% ship rate) vs web dashboards (20%)."

This means **the planner already knows what you're good at building** before it even searches.

### 5.2 Deterministic Retrieval Adapters

Research Mode uses pluggable retrieval adapters:

| Adapter | Source | Method | Structured Filters |
|---------|--------|--------|-------------------|
| `yt-dlp` (existing) | YouTube | CLI scraping | keyword, count |
| YouTube Data API (new) | YouTube | REST API | date range, duration, language, sort, captions |
| RSS/feedparser (existing) | RSS feeds | HTTP + parse | feed URL |
| Gemini Google Search (new) | Web | Gemini grounding | query, recency |

**Phase 1 approach:** Use existing yt-dlp for YouTube search. It already works, costs nothing, has no quota. Add YouTube Data API later when yt-dlp filters are insufficient.

**Phase 2 approach:** Add YouTube Data API with `search.list` + `videos.list` enrichment. Quota: ~6 research runs/day on free tier (10,000 units, ~1,600 units per multi-query run).

**Phase 3 approach:** Add Gemini Google Search grounding for web sources (blog posts, docs, HN, GitHub). This extends research beyond YouTube without building custom scrapers.

**Deduplication:** Before ranking, deduplicate against all existing ideas in the database (exact URL match + fuzzy title match for cross-source).

### 5.3 AI Reranker

After retrieval, the LLM scores each candidate against the research rubric AND the founder brain.

**Reranker input:** Candidate metadata (title, channel, duration, view count, description) + founder brain context (effective threshold, complexity ship rates, domain strengths).

**Reranker output per candidate:**
```json
{
  "score": 82,
  "founder_fit": "high",
  "reason": "Practical Claude Code agent tutorial focused on subagent orchestration. Matches your domain advantage in agent tooling. 23-minute deep dive from a known builder.",
  "signals_found": ["subagents", "real build", "solo developer"],
  "red_flags": [],
  "brain_note": "Your ship rate on agent tooling ideas is 80%. Similar videos scored 75+ in past evaluations."
}
```

The reranker is NOT stateless. It consults the brain before ranking. This is the differentiator.

### 5.4 Research Memory

Every research run is saved. Over time, IdeaForge can answer: "When you research topic X, what fraction of findings do you actually build and ship?"

**Tracked metrics per research brief:**
- How many candidates retrieved
- How many ranked above threshold
- How many ingested into pipeline
- How many received BUILD verdict
- How many were shipped

This produces a **research-to-ship funnel** that exposes which research topics lead to real builds.

### 5.5 Merge with Radar

A research brief can be saved as a recurring radar subscription. Instead of just watching a YouTube channel, you can say: "Run this research brief every Sunday. Only show me new results."

The existing `subscriptions` table gains a new kind: `research_brief`. The `target` field stores the brief text. The `plan_json` stores the last-used search plan. Each radar run executes the plan, deduplicates against previous results, and ingests only new candidates.

---

## 6. Brain Layer Design

### 6.1 The Founder Brain as Internal System

The founder brain is not just an export. In v3, it becomes an internal queryable system that influences:

1. **Research planning** — the planner knows what topics you ship on
2. **Reranking** — candidates are scored against your actual calibration data
3. **Evaluation thresholds** — Phase 2 prompt injects the effective threshold
4. **Decision memory** — the brain remembers verdicts that were wrong (BUILD but abandoned, SKIP but should have built)

### 6.2 Brain State

The brain state is computed from:

```
ideas (with eval_verdict, eval_fit_score, eval_complexity, outcome)
  → calibration_log (ship rates, effective threshold)
    → patterns (verdict distribution, complexity breakdown, trends)
      → brain export (profile + calibration + patterns + anchors + signature)
```

v3 adds:
```
research_briefs (topic → ingest rate → build rate → ship rate)
  → topic_performance (which research areas lead to real builds)
    → brain.research_insights (injected into planner and reranker)
```

### 6.3 Threshold Evolution

The effective threshold is currently a simple midpoint: `(avg_fit_shipped + avg_fit_not_shipped) / 2`.

v3 should make this more useful:
- **Per-complexity thresholds:** "For complexity 1-2, your threshold is 65. For complexity 4-5, your threshold is 80."
- **Per-domain thresholds:** "For agent tooling, your threshold is 60 (you ship these). For web dashboards, your threshold is 85 (you rarely ship these)."
- **Trend-aware:** "Your threshold has risen from 65 to 72 over the last 3 months. You're getting more selective."

This doesn't require ML. It requires grouping outcomes by complexity bucket and computing per-bucket thresholds. The existing `complexity_rates` in `compute_patterns()` already tracks `{total, shipped, rate}` per complexity level.

### 6.4 Research-to-Build Funnel Analytics

New metric surfaces in the Insights tab:

```
Research Brief: "Claude Code agent tutorials"
  → 47 candidates retrieved
    → 12 ranked above threshold (25%)
      → 5 ingested into pipeline (42%)
        → 3 received BUILD verdict (60%)
          → 1 shipped (33%)

Research-to-ship rate: 2.1%
```

This tells you: "Your research on Claude Code agent tutorials yields about 1 shipped project per 50 candidates searched." That's decision-grade information.

### 6.5 Brain Query Interface

The brain should be queryable with simple questions:

- `brain.should_build(title, description, source_type)` → quick BUILD/PARK/SKIP prediction based on pattern matching against historical evaluations (no LLM call needed for obvious cases)
- `brain.calibration()` → current threshold, ship rates, confidence
- `brain.topic_fit(topic_keywords)` → how well this topic matches your shipping history
- `brain.similar_ideas(title)` → past ideas with similar titles/topics and their outcomes

---

## 7. MCP / Interface Layer

### 7.1 MCP Server Design

IdeaForge runs as an MCP server alongside its HTTP server. The MCP server exposes the decision engine to other agents.

**Implementation:** A separate lightweight MCP server process (or integrated into the main `ideaforge` script) that reads from the same SQLite database and calls the same brain/pattern/calibration functions.

### 7.2 MCP Tools

| Tool Name | Input | Output | Use Case |
|-----------|-------|--------|----------|
| `ideaforge_brain_query` | `{question: "Should I build a CLI tool for invoice reconciliation?"}` | `{verdict: "BUILD", confidence: 0.85, reason: "Matches your domain advantage in invoice workflows. Complexity 2, your ship rate at this complexity is 75%.", similar_ideas: [...]}` | Any agent asking "is this worth building?" |
| `ideaforge_evaluate_url` | `{url: "https://youtube.com/watch?v=..."}` | `{id: 35, status: "queued", message: "Idea queued for full pipeline"}` | External agent triggering evaluation |
| `ideaforge_research` | `{brief: "Find AI agent framework tutorials from 2026"}` | `{run_id: 7, candidates: 23, top_5: [...]}` | Agent-initiated research |
| `ideaforge_patterns` | `{}` | `{threshold: 72, build_ship_rate: 0.6, top_domains: [...]}` | Agent reading your decision patterns |
| `ideaforge_recent_builds` | `{limit: 5}` | `[{title, verdict, fit_score, outcome, shipped_at}]` | Context for what you're currently building |

### 7.3 MCP Resources

| Resource URI | Returns | Purpose |
|-------------|---------|---------|
| `brain://latest` | Latest brain export JSON | Portable founder profile |
| `brain://markdown` | FOUNDER-BRAIN.md content | For injecting into CLAUDE.md |
| `calibration://current` | Current calibration snapshot | Threshold and rates |
| `patterns://all` | Full pattern analysis | Decision intelligence |
| `ideas://recent?limit=10` | Recent ideas with verdicts | Context |

### 7.4 Example MCP Interactions

**Claude Code session asking before building:**
```
User: "Build me a CLI tool for tracking restaurant inventory"
Claude Code internally calls: ideaforge_brain_query({
  question: "CLI tool for restaurant inventory tracking",
  complexity_estimate: 2
})
→ Response: {
  verdict: "BUILD",
  confidence: 0.88,
  reason: "Strong domain match (restaurant operations). Complexity 2 has 75% ship rate in your history. Similar to idea #12 which you shipped.",
  effective_threshold: 72,
  estimated_fit: 81
}
Claude Code: "IdeaForge brain says this is a strong fit. Your ship rate on complexity-2 projects is 75%. Proceeding."
```

**Opi delegating research:**
```
Opi writes to TASKS.md: "Research AI voice-to-video tools"
Opi calls: ideaforge_research({brief: "AI voice-to-video tools for solo developers, 2026"})
→ Returns ranked results
Opi writes findings to agent-memory
```

### 7.5 What Stays Local-Only

- Database writes (only through the main IdeaForge process)
- LLM calls (only through the main process, respects token budgets)
- Credential management (API keys stay in .env)
- Deletion operations (never via MCP — destructive actions require the web UI)

### 7.6 Local API and MCP Relationship

The MCP tools are thin wrappers around the same Python functions that power the HTTP API. They share:
- `compute_patterns()`
- `compute_calibration()`
- `build_brain_export()`
- `llm_call()`
- The same SQLite database

The MCP server reads from the DB but only the main HTTP server writes to it (except for queueing new ideas via `ideaforge_evaluate_url`).

---

## 8. Data Model Changes

### New Tables

```sql
-- Research runs (each execution of Research Mode)
CREATE TABLE research_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mode TEXT NOT NULL,                    -- youtube|web|hybrid
  prompt TEXT NOT NULL,                  -- original natural-language brief
  plan_json TEXT,                        -- structured search plan
  summary_md TEXT,                       -- AI-generated synthesis of findings
  total_candidates INTEGER DEFAULT 0,
  total_above_threshold INTEGER DEFAULT 0,
  total_ingested INTEGER DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending', -- pending|searching|ranking|done|failed
  error TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Individual results from a research run
CREATE TABLE research_results (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id INTEGER NOT NULL,
  source_type TEXT NOT NULL,             -- youtube|rss|web
  source_id TEXT,                        -- YouTube video ID, RSS item GUID, etc.
  title TEXT,
  url TEXT NOT NULL,
  channel_or_domain TEXT,
  published_at TEXT,
  duration_seconds INTEGER,
  view_count INTEGER,
  language TEXT,
  description TEXT,
  score REAL,                            -- reranker score (0-100)
  reason TEXT,                           -- reranker explanation
  signals_found TEXT,                    -- JSON array of matched signals
  brain_note TEXT,                       -- brain context note
  selected INTEGER NOT NULL DEFAULT 0,   -- user selected for ingestion
  idea_id INTEGER,                       -- linked idea if ingested
  raw_json TEXT,                         -- raw API response for debugging
  FOREIGN KEY(run_id) REFERENCES research_runs(id) ON DELETE CASCADE,
  FOREIGN KEY(idea_id) REFERENCES ideas(id) ON DELETE SET NULL
);

-- Research briefs (reusable research templates, can become radar subscriptions)
CREATE TABLE research_briefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,                    -- user-facing label
  prompt TEXT NOT NULL,                  -- natural-language brief
  plan_json TEXT,                        -- last-used structured plan
  total_runs INTEGER DEFAULT 0,
  total_ingested INTEGER DEFAULT 0,
  total_built INTEGER DEFAULT 0,         -- ideas that got BUILD verdict
  total_shipped INTEGER DEFAULT 0,       -- ideas that were shipped
  hit_rate REAL,                         -- shipped / ingested
  radar_sub_id INTEGER,                  -- linked subscription if saved as recurring
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(radar_sub_id) REFERENCES subscriptions(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX idx_research_results_run ON research_results(run_id, score DESC);
CREATE INDEX idx_research_briefs_name ON research_briefs(name);
```

### Modified Tables

```sql
-- subscriptions: add new kind
-- kind now includes: youtube_channel|youtube_search|rss_feed|research_brief (new)
-- target for research_brief kind: stores the research_briefs.id reference

-- ideas: add research linkage
ALTER TABLE ideas ADD COLUMN research_result_id INTEGER
  REFERENCES research_results(id) ON DELETE SET NULL;
-- Tracks which research result led to this idea being ingested
```

### Brain Export Version

Brain export gains a `research_insights` section:

```json
{
  "version": 2,
  "research_insights": {
    "total_research_runs": 15,
    "avg_candidates_per_run": 34,
    "avg_ingest_rate": 0.12,
    "avg_research_to_ship_rate": 0.021,
    "best_topics": [
      {"topic": "CLI automation", "ship_rate": 0.08},
      {"topic": "agent tooling", "ship_rate": 0.05}
    ],
    "worst_topics": [
      {"topic": "web dashboards", "ship_rate": 0.0}
    ]
  }
}
```

---

## 9. API / Endpoint Changes

### New Research Endpoints

| Method | Endpoint | Input | Output |
|--------|----------|-------|--------|
| POST | `/api/research/plan` | `{prompt}` | Structured search plan JSON |
| POST | `/api/research/search` | `{plan_json}` or `{run_id}` | Raw candidate results |
| POST | `/api/research/rank` | `{run_id}` | Scored/ranked results with brain notes |
| POST | `/api/research/run` | `{prompt, mode?}` | All-in-one: plan → search → rank |
| POST | `/api/research/ingest` | `{run_id, result_ids[]}` | Ingest selected results as ideas |
| GET | `/api/research/<id>` | run ID in path | Research run with results |
| GET | `/api/research/history` | -- | Recent research runs |
| POST | `/api/research/save-brief` | `{run_id, name}` | Save as reusable brief |
| POST | `/api/research/brief/<id>/run` | brief ID | Re-run a saved brief |
| POST | `/api/research/brief/<id>/radar` | `{frequency_hours}` | Convert brief to radar subscription |

### New Brain Endpoints

| Method | Endpoint | Input | Output |
|--------|----------|-------|--------|
| POST | `/api/brain/query` | `{question, complexity_estimate?}` | Quick verdict + reasoning from brain |
| GET | `/api/brain/funnel` | -- | Research-to-build funnel data |
| GET | `/api/brain/thresholds` | -- | Per-complexity, per-domain thresholds |
| GET | `/api/brain/topics` | -- | Topic performance from research history |

### Existing Endpoints (unchanged)

All current GET/POST/DELETE endpoints remain as-is. The core pipeline (`/api/run-all`, `/api/evaluate`, `/api/instruct`, etc.) is not modified.

---

## 10. UI / UX Changes

### New Tab: Research

Add a 5th main tab. The tab bar becomes:

```
Ideas | Pipeline | Research | Radar | Insights
```

**Research view layout:**

```
┌─────────────────────────────────────────────────────┐
│  Research Brief                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Describe what you want to research...          │ │
│  │  (textarea, 3-4 lines)                          │ │
│  └─────────────────────────────────────────────────┘ │
│  [Search YouTube]  [Search Web]  [Hybrid]            │
│                                                      │
│  ── Saved Briefs ──────────────────────────────────  │
│  [Claude Code tutorials] [AI agent frameworks] [+]   │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Research Run #7 — "Claude Code agent tutorials"     │
│  47 candidates → 12 above threshold → 5 ingested     │
│                                                      │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│  │ [Thumbnail]  │ │ [Thumbnail]  │ │ [Thumbnail]  │ │
│  │ Score: 89    │ │ Score: 82    │ │ Score: 76    │ │
│  │ Title...     │ │ Title...     │ │ Title...     │ │
│  │ "Strong fit" │ │ "Good match" │ │ "Moderate"   │ │
│  │ [Ingest]     │ │ [Ingest]     │ │ [Ingest]     │ │
│  └──────────────┘ └──────────────┘ └──────────────┘ │
│                                                      │
│  [Ingest Selected] [Save as Brief] [Save as Radar]   │
└─────────────────────────────────────────────────────┘
```

Research result cards reuse the `.search-card-visual` component with an added score badge and brain note.

### Enhanced Insights Tab

Add two new surfaces to the existing Insights view:

**1. Research Funnel**
```
Research Funnel (last 30 days)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Candidates searched    ████████████████  234
Above threshold        ████████         48  (21%)
Ingested               ████             22  (46%)
BUILD verdict          ███              14  (64%)
Shipped                █                 3  (21%)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Research-to-ship rate: 1.3%
```

**2. Topic Performance**
```
Topic Performance
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CLI automation     ████████  8% ship rate
Agent tooling      █████     5% ship rate
Invoice workflows  ████      4% ship rate
Web dashboards     ▏         0% ship rate
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### Radar/Research Merge

In the Radar tab, saved research briefs appear alongside channel/search/feed subscriptions. They use the same card layout with a distinct icon. Running a research brief subscription triggers the full plan → search → rank → ingest flow.

### What Doesn't Change

- Ideas tab layout (visual grid, filter toolbar, modal system)
- Pipeline wizard (all 5 steps)
- NotebookLM panel
- Toast notifications
- Empty state showcase
- Forge Map command palette
- All existing CSS variables and theme

---

## 11. Hybrid Local/Cloud Strategy

### AI Backend Usage

| Task | Backend | Why |
|------|---------|-----|
| Research planner | Gemini 2.0 Flash | Free tier, good at structured JSON output |
| Retrieval | yt-dlp / YouTube Data API / feedparser | Deterministic, no AI cost |
| Reranker | Gemini 2.0 Flash | Batch scoring of 30-50 candidates, cost-sensitive |
| Phase 2 evaluation | Gemini 2.0 Flash (primary) | Existing, proven, free |
| Phase 3 instruction | Gemini 2.0 Flash (primary) | Existing, proven, free |
| Brain query (simple) | No LLM — pure computation | Pattern matching against calibration data |
| Brain query (complex) | Gemini 2.0 Flash | When reasoning about novel topics |
| Web research | Gemini with Google Search grounding | Current-web access with citations |
| MCP tool responses | No LLM — data lookups | Direct DB queries, no AI cost per call |

### Cost Model

- **Gemini 2.0 Flash:** Free tier covers most usage. If rate-limited, queue and retry.
- **YouTube Data API:** 10,000 units/day free. ~6 research runs/day. Cache aggressively.
- **Anthropic:** Fallback only. Used when Gemini is unavailable. Max subscription covers it.
- **Local LLM:** Not recommended for v3. Quality variance would undermine calibration accuracy. Revisit when local models reliably produce structured JSON.

### Supply Chain Diversification

IdeaForge already supports Gemini and Anthropic backends. The `llm_call()` function abstracts the provider. Adding a third backend (e.g., local Ollama) requires only adding a new branch to this function. The architecture is already provider-agnostic.

---

## 12. Implementation Phases

### Phase 1 — Research Mode (Core)

**Scope:** Research planner, yt-dlp retrieval, AI reranking, research results UI, ingest bridge.

**What gets built:**
- `research_runs` and `research_results` tables
- `POST /api/research/run` (all-in-one endpoint)
- `POST /api/research/ingest`
- `GET /api/research/<id>`
- Research planner prompt (uses EVAL_PROFILE + brain context)
- Reranker prompt (scores against founder profile)
- Research tab in frontend with brief textarea + result cards
- Reuse existing `.search-card-visual` component for result display

**Why now:** This is the highest-leverage new feature. It changes how ideas enter the system — from random URL pasting to intentional, brain-aware research.

**Dependencies:** None. Uses existing yt-dlp search, existing Gemini backend, existing UI patterns.

**Risks:**
- Reranker quality depends on Gemini's ability to score candidates from metadata alone (no transcript yet). Mitigate by keeping scoring rubric simple and letting the existing Phase 2 evaluation do the deep analysis after ingestion.
- yt-dlp search lacks date filtering. Mitigate by having the reranker deprioritize old content based on `upload_date`.

**Usable at end:** User can type a research brief, get ranked YouTube results with brain-informed scores, and ingest the best into the pipeline.

**Estimated effort:** 2-3 days.

### Phase 2 — Research Memory + Radar Merge

**Scope:** Research briefs, funnel tracking, recurring research as radar, research-to-build analytics.

**What gets built:**
- `research_briefs` table
- Save/reuse research briefs
- Convert brief to radar subscription (new subscription kind: `research_brief`)
- Research funnel metrics (candidates → threshold → ingested → BUILD → shipped)
- Topic performance tracking
- Funnel visualization in Insights tab
- `POST /api/research/save-brief`
- `POST /api/research/brief/<id>/radar`
- `GET /api/brain/funnel`

**Why now:** Research Mode without memory is stateless. Memory makes it compound. The radar merge makes it passive.

**Dependencies:** Phase 1 complete. Existing radar daemon. Existing outcome tracking.

**Risks:**
- Funnel metrics require outcome tracking to be used. Currently only 1/30 ideas has an outcome. Mitigate by surfacing prompts: "You have 14 BUILD ideas without outcomes. Update them to improve your brain calibration."
- Brief-as-radar needs clear deduplication. Mitigate by tracking `source_id` per result and skipping known IDs.

**Usable at end:** Saved research briefs that run as recurring radar scans. Funnel analytics showing research-to-ship conversion. Topic performance insights.

**Estimated effort:** 2-3 days.

### Phase 3 — Brain-as-Service + MCP

**Scope:** MCP server, brain query tool, enhanced brain export, per-complexity thresholds.

**What gets built:**
- MCP server (can be a separate script `ideaforge-mcp` or integrated)
- `ideaforge_brain_query` tool — quick verdict from brain without full pipeline
- `ideaforge_evaluate_url` tool — trigger evaluation from external agent
- `ideaforge_patterns` tool — export patterns
- `ideaforge_recent_builds` tool — recent ideas context
- `brain://latest` and `calibration://current` MCP resources
- Per-complexity thresholds in brain
- Brain export v2 with research insights
- `POST /api/brain/query`
- `GET /api/brain/thresholds`

**Why now:** After Phase 1-2, the brain has enough data to be useful as a service. MCP makes it callable by Claude Code sessions and Opi.

**Dependencies:** Phase 2 complete (research memory feeds brain insights). MCP SDK familiarity.

**Risks:**
- MCP server adds a second process. Mitigate by making it optional (`python3 ideaforge --mcp` flag) and having it read-only from the same SQLite DB.
- Brain query without enough outcome data gives weak answers. Mitigate by being honest: "Low confidence — only 3 outcomes tracked. Track more outcomes for better brain calibration."

**Usable at end:** Claude Code can call `ideaforge_brain_query` before starting any project. Opi can trigger research runs. The brain is no longer a file export — it's a live service.

**Estimated effort:** 3-4 days.

### Phase 4 — Extended Retrieval + Web Research

**Scope:** YouTube Data API adapter, Gemini Google Search grounding for web research, hybrid research mode.

**What gets built:**
- YouTube Data API adapter (replaces yt-dlp for research searches, keeps yt-dlp for transcript extraction)
- Gemini Google Search grounding adapter (web sources)
- Hybrid research mode (YouTube + web in one run)
- Result type indicators (YouTube vs web)
- `GET /api/brain/topics`
- Research summary synthesis (AI-generated cross-result patterns)

**Why now:** After the core research loop works (Phase 1-2) and the brain is queryable (Phase 3), extending retrieval to more sources multiplies value without changing architecture.

**Dependencies:** Phase 1-3 complete. YouTube Data API key. Gemini grounding API access.

**Risks:**
- YouTube Data API quota (10,000 units/day). Mitigate by keeping yt-dlp as fallback and caching results.
- Web research via Gemini grounding returns different metadata shapes than YouTube. Mitigate by normalizing into `research_results` table schema.

**Usable at end:** Research Mode searches YouTube with proper filters AND the web. Hybrid research surfaces the best sources from multiple channels. IdeaForge becomes a true multi-source research engine.

**Estimated effort:** 2-3 days.

---

## 13. Uniqueness and Monetization

### What Makes v3 Unique

| Competitor | What They Do | What IdeaForge v3 Does That They Don't |
|-----------|-------------|---------------------------------------|
| Perplexity | Search + summarize + cite | IdeaForge gives BUILD/SKIP verdicts calibrated to YOUR shipping history, not generic summaries |
| NotebookLM | Ingest + RAG + podcast | IdeaForge evaluates BEFORE ingesting — it filters. NotebookLM accepts everything |
| Claude Projects | Research + chat + context | IdeaForge tracks outcomes across sessions and calibrates. Claude Projects forget between conversations |
| Cursor / Windsurf | Code from context | IdeaForge decides WHAT to code. Cursor decides HOW. They're complementary, not competitive |
| Generic RAG | Chat over documents | IdeaForge has a founder profile that evolves from real outcomes. RAG has no judgment layer |
| AI search tools | Find information | IdeaForge ranks information against your calibrated judgment profile. Search has no memory of what you shipped |

**The moat in one sentence:** Nobody else has a system that tracks whether you shipped what you said you'd build, calibrates itself from the results, and then uses that calibration to rank future research and make better build decisions.

### Why the Brain Is the Real Product

The brain is valuable because it's:
- **Personal** — trained on YOUR decisions, not aggregate data
- **Outcome-aware** — knows what you actually shipped vs abandoned
- **Portable** — exportable as JSON/Markdown for use in other tools
- **Queryable** — other agents can ask "should I build this?" and get a calibrated answer
- **Compounding** — every evaluation and outcome makes it more accurate

Research Mode is the acquisition funnel. It gets more data into the brain faster. But the brain itself is the product.

### Monetization Ladder

**Tier 0 — Free / Local (current state)**
- Local-only, bring your own API keys
- yt-dlp search (no quota, no cost)
- Manual evaluation pipeline
- Basic brain export (JSON + Markdown file)
- No MCP server
- Value: Personal decision tool

**Tier 1 — Pro ($19-29/mo)**
- Research Mode with AI planning + reranking
- YouTube Data API managed quota
- Research memory + funnel analytics
- Recurring research-as-radar
- Topic performance tracking
- Enhanced brain export with research insights
- Value: Structured research + decision intelligence

**Tier 2 — Infrastructure ($49-79/mo)**
- MCP server (brain-as-a-service)
- Brain query API for external tools
- Web research via Gemini grounding
- Multi-agent integration (Claude Code, Opi, future agents)
- Per-complexity and per-domain thresholds
- Community patterns (anonymous aggregate — "founders who ship 5+ projects tend to SKIP ideas with complexity > 3")
- Priority support
- Value: Decision infrastructure for your entire workflow

**Monetization logic:** The free tier sells transcript extraction + verdicts. Tier 1 sells structured research + calibration. Tier 2 sells the brain as infrastructure. Each tier is genuinely more valuable than the last because it adds compounding intelligence, not just features.

**What NOT to charge for:** Don't gate basic evaluation or transcript extraction. The core loop must remain free and local. Charge for intelligence (research, memory, brain query, cross-agent integration).

---

## 14. Anti-Goals

v3 must NOT become:

1. **A generic search engine.** Research Mode exists to feed the brain, not to be Perplexity.
2. **An enterprise platform.** No multi-user, no team management, no SSO. Solo founder tool.
3. **A SaaS with a required cloud backend.** Local-first is non-negotiable. Cloud features are additive.
4. **A framework.** IdeaForge is a product, not a library. The MCP interface is for consuming, not for building on top of.
5. **An AI chatbot.** No open-ended conversation interface. The interactions are structured: research, evaluate, decide, build.
6. **A content creation platform.** NotebookLM handles content generation. IdeaForge handles decision-making.
7. **Over-engineered.** No React, no Next.js, no webpack, no Docker, no Kubernetes. Two files and a database.
8. **Dependent on a single AI provider.** Must work with Gemini OR Anthropic. Adding a third backend should be a one-function change.
9. **A data hoarder.** Research results that aren't ingested can be pruned. The brain state is what matters, not raw search history.
10. **An excuse to stop shipping.** IdeaForge should accelerate building, not become an infinite research loop. If Research Mode makes the user research more but build less, it has failed.

---

## 15. Final Recommendation

### Build first: Research Mode (Phase 1)

This is the single highest-leverage move. It changes how ideas enter the system from "paste a URL you already found" to "describe what you want to learn and let the brain-aware planner find the best sources." It uses existing infrastructure (yt-dlp, Gemini, EVAL_PROFILE) and existing UI patterns (`.search-card-visual`, filter chips).

**Estimated effort: 2-3 days.** Delivers immediate value.

### Build second: Research Memory (Phase 2)

Without memory, Research Mode is a fancy search. With memory, it becomes the data acquisition layer for the brain. The funnel analytics and topic performance tracking make the brain visibly smarter.

### Postpone: MCP server (Phase 3)

MCP is strategically important but not urgent. The brain needs more outcome data before it's useful as a service. Build the brain's data pipeline (Phases 1-2) before exposing it to other agents (Phase 3).

### Postpone: YouTube Data API / Web Research (Phase 4)

yt-dlp works today. YouTube Data API and Gemini grounding add precision but not new capabilities. Build the research loop first, then upgrade the retrieval.

### The single highest-leverage move

**Implement `POST /api/research/run` and the Research tab.** One endpoint, one UI surface. It transforms IdeaForge from a reactive tool (you paste what you already found) into a proactive one (you describe what you want to learn, and the brain helps you find it).

Everything else — memory, MCP, web search, monetization — builds on top of that foundation.
