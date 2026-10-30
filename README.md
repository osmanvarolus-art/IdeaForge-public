# IdeaForge

**A founder research and decision engine that gets smarter from your outcomes**

IdeaForge helps solo founders discover, evaluate, and track ideas — then learns from what you actually ship to improve future recommendations.

## What Makes This Different

Most idea tools just score ideas and call it done. IdeaForge:

1. **Research/Radar finds ideas** — YouTube search, web grounding, RSS feeds, automated discovery
2. **Evaluation scores them** — AI analysis against your founder profile (fit score, complexity, verdict)
3. **Calibration learns from outcomes** — Track what you ship vs abandon, system adapts threshold to filter low-probability builds

The more you use it, the better it gets at predicting what you'll actually ship.

## One-Command Install

```bash
bash install.sh
```

This will:
- Check Python 3.10+ is installed
- Create virtual environment (`.ideaforge/`)
- Install all dependencies
- Create `.env` template for API keys

## Setup

1. **Add your API key** to `.env`:

```bash
# Required: At least one AI backend
GEMINI_API_KEY=your-key-here
# OR
ANTHROPIC_API_KEY=your-key-here
```

Get a Gemini API key at: https://ai.google.dev/

2. **Start the server**:

```bash
source .ideaforge/bin/activate
./ideaforge
```

3. **Open in browser**: http://localhost:7888

## Core Features

### Ideas View
- Submit YouTube URLs or search queries
- View all evaluated ideas with verdict badges (BUILD/PARK/SKIP)
- Filter by verdict, search by title
- One-click evaluation from any source

### Research Mode
- Natural language research briefs → structured search plans
- Multi-source: YouTube + Web (via Gemini grounding)
- AI ranking against your founder profile
- Ingest top results as ideas for evaluation

### Radar (Auto-Discovery)
- Subscribe to YouTube channels, searches, RSS feeds, or GitHub Trending
- Automated scanning on configurable intervals
- New ideas auto-queued for evaluation
- Track discovery metrics per subscription

GitHub Trending daily is enabled on first start (up to 25 repositories every 24 hours).
Each repository keeps its observed description, language, stars today, and total stars.
Its card says "Probabilistic product analysis". Numeric demand facts come from the collector;
generated prose stays qualitative, and model ratings are opinions, not measured demand.
Repositories whose description is missing are retained with "not visible" evidence.
This initial analysis uses the trending card, not a full repository audit: sponsors links
are recorded, while pricing, actual payers, trend triggers and open issues stay "not visible".
GitHub stars are not sales. Competition is a market signal; no stack-proximity filter applies.
The existing Ideas view lists these records under the GitHub trending source.

### Outcomes & Calibration
- Log what happened: Shipped, Abandoned, In Progress, Parked
- Bulk outcome entry UI
- Calibration dashboard shows:
  - Effective threshold (learned from outcomes)
  - BUILD ship rate
  - Before/after comparison (how many low-fit ideas calibration filters)
  - Progress to next calibration milestone (10/20/30 outcomes)

### Insights
- Verdict distribution (BUILD/PARK/SKIP %)
- Ship rate by complexity level
- Founder brain export (paste into Claude/GPT as context)

## Architecture

- **Backend**: Single Python file (`ideaforge`), SQLite database
- **Frontend**: Single HTML file (`index.html`), vanilla JS
- **AI**: Gemini (recommended) or Anthropic Claude
- **Data**: `ideaforge.db` (SQLite), `data/` directory for exports

## API Keys

### Gemini (Recommended)
- Supports web grounding for Research Mode
- Free tier: 1500 requests/day
- Get key: https://ai.google.dev/

### Anthropic Claude
- Research Mode limited to YouTube-only (no web grounding)
- Requires paid API access
- Get key: https://console.anthropic.com/

## Configuration

Edit `EVAL_PROFILE` in the `ideaforge` file (around line 613) to customize:
- Developer profile (solo vs team, tech stack)
- Budget constraints
- Domain advantages
- Skip/Park/Build criteria

Or use the Settings UI (coming soon).

## Local-First

- No telemetry, no external dependencies beyond AI APIs
- All data stays on your machine
- Binds to `127.0.0.1` by default (localhost only)
- Optional `--bind` flag for LAN access

## Troubleshooting

**Server won't start:**
- Activate venv: `source .ideaforge/bin/activate`
- Check Python version: `python3 --version` (need 3.10+)
- Verify deps: `pip install -r requirements.txt`

**AI calls failing:**
- Check `.env` has valid API key
- Test: `curl -H "Authorization: Bearer $GEMINI_API_KEY" https://generativelanguage.googleapis.com/v1beta/models`

**Port 7888 already in use:**
- Kill existing server: `pkill -f ideaforge`
- Or change `PORT` in the script (line 27)

## Development

Built in 7 layers:
1. Extract (yt-dlp transcription)
2. Evaluate (profile-tuned AI scoring)
3. Instruct (Claude Code build specs)
4. Research (multi-source AI search)
5. Radar (automated discovery)
6. Calibration (outcome-driven learning)
7. Insights (pattern intelligence)

See `SYSTEM-SPEC.md` for architecture details.

## License

Private/personal use. Not open source yet.

---

Built with: Python • SQLite • Vanilla JS • Gemini AI • yt-dlp

---

## License and ownership

Copyright (c) 2026 Osman Varol. All rights reserved. The code is public so it can be read and evaluated; it is **not** open source. See [LICENSE](LICENSE) for what is and is not allowed. For any other use, ask first by opening an issue.
