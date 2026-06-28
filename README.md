# LuckyHands Intel Daily

A daily AI-driven sweepstakes industry intel brief. The pipeline researches US sweepstakes regulation, operator moves, vendor news, market signals, and prediction-market activity, runs every claim through an adversarial fact-check, and posts the brief to Slack after the operator approves it.

Runs locally on a Mac. No paid APIs required — Ollama for local LLM, Google Gemini free tier for grounded fact-checking, Tavily and Exa free tiers for search, LegiScan free tier for state bills, CourtListener free tier for federal filings.

The brief covers all 50 US states plus federal regulators (FinCEN, FTC, CFTC, Treasury, IRS), every named sweepstakes operator (Stake.us, VGW brands, McLuck, Pulsz, High 5, Fortune Coins, Modo, Fliff, Legendz, WOW Vegas, Hello Millions, Sportzino, Crown Coins, Mega Bonanza, B-Two brands, more), the major vendor stack (GeoComply, Xpoint, Sightline, Trustly, Sumsub, Jumio), and the prediction-market sibling beat (Kalshi, Polymarket, Novig, Robinhood Event Contracts, ForecastEx).

---

## Daily flow at a glance

```
ollama serve  (already running)
       |
       v
./intel_daily.sh
       |
       v
[1] Pipeline runs (8-12 min)
    - 3 Ollama researchers run live web searches
      - regulatory and legal       (10 queries)
      - competitor moves           (10 queries)
      - market signals             (10 queries)
    - Primary source pulls (free APIs)
      - LegiScan        all 50 states sweepstakes bills
      - RSS trade press 10 feeds, sweepstakes-relevant filter
      - Federal Register sweepstakes-keyword filings
      - CourtListener   sweepstakes case filings
    - Bill grounding (Gemini Flash + Google Search)
      - One grounded call per bill, authoritative status and effective date
    - Editor (Gemini Flash) assembles the brief in the 9-section template
    - Verifier (Gemini Flash) does an internal QA pass

[2] intel_publish.py takes over
    - Loads the latest brief markdown
    - Runs the verify gate
      - Batches every fact-bearing claim 5 per call
      - Each batch hits Gemini Flash-Lite plus Google Search
      - Returns per-claim verdict: confirmed, partial, incorrect, uncertain
    - Prints the brief in your terminal with color highlighting
    - Prints the verify report
    - Prompts:  y to ship to Slack
                n to cancel
                i to apply corrections via Gemini and re-verify
    - Loops on i until you approve or cancel
```

The verify gate is hard: any verdict of `incorrect` blocks the Slack send. The corrections file is saved alongside the brief so you can inspect it.

---

## Setup

### 1. Clone and install Python deps

```bash
git clone git@github.com:daniel-ops1/Luckyhands-Intel.git intel_daily
cd intel_daily
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Install Ollama and pull the models

```bash
brew install ollama       # or download from https://ollama.com
ollama serve              # starts the local server at http://localhost:11434
ollama pull qwen2.5:14b   # researcher model, ~9GB. Bumps to qwen-intel via the Modelfile in this repo.
```

If you have 32GB+ RAM, also try `qwen2.5:32b` or `gemma3:27b` for tighter instruction following.

### 3. Copy and fill `.env`

```bash
cp .env.example .env
```

You need to populate:

| Variable | Where to get it | Free? |
|---|---|---|
| `GOOGLE_API_KEY` | https://aistudio.google.com/apikey | Yes, no card. 20 RPD daily project-wide cap. |
| `TAVILY_API_KEY` | https://app.tavily.com | Yes, 1,000 searches/mo, no card. |
| `EXA_API_KEY` | https://dashboard.exa.ai | Yes, signup credits, no card. |
| `LEGISCAN_API_KEY` | https://legiscan.com/legiscan | Yes, 30,000/mo, no card. |
| `COURTLISTENER_API_TOKEN` | https://www.courtlistener.com/help/api/rest/ | Yes, 125/day, no card. |
| `SLACK_WEBHOOK_URL` | https://api.slack.com/messaging/webhooks | Yes, no card. |

### 4. Sanity-check

```bash
./intel_daily.sh --help
```

Should print the usage block. Then verify your `.env` keys:

```bash
source .venv/bin/activate
python -c "from grounding import ground_bill_facts; print(ground_bill_facts('ME', 'LD2007', 'Online Sweepstakes Prohibition'))"
```

Should print a structured dict with bill status, signing date, effective date, and codification.

---

## Daily use

### Interactive (recommended for now)

```bash
./intel_daily.sh
```

This is the safe path. The pipeline runs, you see the brief in your terminal with color highlighting, you see every claim verified live against the web, you decide whether to post.

At the prompt:

| Choice | What happens |
|---|---|
| `y` | Posts to Slack, archives the approved brief, exits |
| `n` | Cancels, leaves the brief files on disk for inspection |
| `i` | Applies the verify report's suggested corrections via Gemini Flash, re-verifies, re-prompts |

### Fully automated

Once you're confident in 3-4 daily runs, you can wire this into `launchd` or `cron`:

```bash
# Run pipeline + auto-Slack if verify gate passes, no prompt.
./intel_daily.sh --auto-slack
```

The verify gate still blocks any `incorrect` Slack send even in auto mode. A blocked send leaves the verify_report on disk for you to inspect.

Skip the slow pipeline and just publish the most recent generated brief:

```bash
./intel_daily.sh --skip-run
```

---

## Architecture

| File | Role |
|---|---|
| `intel_daily.sh` | Main entry. Runs pipeline, hands off to interactive publisher. |
| `run.py` | ADK pipeline runner. Manages session, retries, file write. |
| `agents.py` | The ADK pipeline definition. Researchers, editor, verifier, publisher callback. |
| `tools.py` | Search and fetch tools (Tavily, Exa, DDG, Jina Reader, budget ledger, sqlite cache). |
| `primary_sources.py` | LegiScan, RSS feeds, Federal Register, CourtListener pulls + grounding orchestration. |
| `grounding.py` | Dynamic bill fact grounding via Gemini Flash + Google Search. Replaces static fact dicts. |
| `verify_brief.py` | Verify gate. Batched Gemini calls verify every claim against the live web. Returns structured report. |
| `intel_publish.py` | Interactive publisher. Loads brief, runs verify, terminal preview, y/n/i prompt, corrections loop, Slack post. |
| `slack.py` | Slack Block Kit renderer with proper section dividers and footer context block. |
| `render.py` | Markdown to HTML for the local rendered brief. |
| `config.py` | Reads `.env`, exposes per-agent backend choices (`RESEARCHER_BACKEND`, `EDITOR_BACKEND`). |
| `dates.py` | US Eastern timezone helpers. All dates and cache keys are in ET, the brief's business timezone. |
| `send.py` | SMTP fallback for email delivery (Slack is the primary channel). |

### Data flow

```
[ user ]
   |
   |  ./intel_daily.sh
   v
[ run.py ]
   |
   |  ADK Runner
   v
[ research_team (SequentialAgent) ]
   |  before_agent_callback fires _primary_source_pull
   |    - LegiScan search across TIER_1 + TIER_2 states for sweepstakes-relevant bills
   |    - For each bill, grounding.py asks Gemini Flash + Google Search for status,
   |      signing date, effective date, codification, key provisions, source URL
   |    - RSS feed pull across 10 trade press sites with sweepstakes-keyword filter
   |    - Federal Register pull for sweepstakes-keyword filings
   |    - CourtListener pull for sweepstakes-related case filings
   |
   +-- regulatory_researcher  (Ollama qwen-intel, web_search_news + fetch_url)
   +-- competitor_researcher  (Ollama qwen-intel, web_search_semantic + fetch_url)
   +-- market_researcher      (Ollama qwen-intel, web_search + fetch_url)
   |
[ editor (Gemini Flash) ]
   |  reads all 7 research streams plus AUTHORITATIVE blocks from grounding
   |  writes brief in the 9-section template
   |
[ verifier (Gemini Flash, ADK LlmAgent) ]
   |  internal QA pass over the brief against the findings
   |  output is informational, not gating
   |
[ _publish_callback ]
   |  - sanitize_brief drops items with URLs not in findings, low-quality sources,
   |    and topic-irrelevant On-our-radar items
   |  - enforce_voice_rules strips apostrophes, hyphens between words, em dashes
   |  - render to HTML
   |  - if INTEL_DAILY_NO_SLACK is set, save brief markdown and exit
   |  - else run the verify gate (verify_brief.py), block Slack if any incorrect
   |
[ intel_publish.py ] (when intel_daily.sh runs interactively)
   |  - loads brief markdown
   |  - verify gate runs again, terminal preview, prompt, corrections loop
   |  - on y, posts to Slack with proper Block Kit footer
```

---

## Brief template

Every brief follows this fixed 9-section structure. Empty sections render as `no qualifying items today`.

```
# LuckyHands Intel Daily

## 1. Top story
Two paragraphs. Single highest-impact sweepstakes-relevant event. One source link.
If regulatory, ends with "Verify with counsel before acting on any item in this section."

## 2. Legislative scoreboard
One bullet per bill. AUTHORITATIVE block facts (status, effective date, scope) used verbatim.
Format: **STATE BILLNUMBER** -- STATUS, effective DATE. SCOPE. [Authoritative](url) [LegiScan](url)
  Why it matters: stakeholder context line.

## 3. Enforcement and litigation
ACTION or WATCH plus jurisdiction. State AG, federal regulator, court ruling, class action.

## 4. Competitor moves
Operator-level news. State exits, lawsuits, leadership, fundraising, M&A, App Store ranks.

## 5. Vendor and infrastructure
Payment processors, geolocation, KYC, game studios.

## 6. Market and product signals
EKG forecasts, GGR, M&A, analyst notes, App Store DAU.

## 7. Prediction markets sibling beat
Kalshi, Polymarket, Novig, Robinhood Event Contracts. Always framed around the actual
cause of action (e.g. DC Consumer Protection Procedures Act), never as "unlicensed" —
both Polymarket and Kalshi are CFTC regulated.

## 8. On our radar
Lower-confidence single-source items. Each starts with WARNING, single source.

## 9. Footer
Reply to this thread with corrections. Not legal advice.
```

---

## Costs and quotas

Everything runs free.

| Component | Free tier | Per pipeline run | Headroom |
|---|---|---|---|
| Ollama (researchers) | Local, unlimited | 3 researchers x ~6 tool calls each | Hardware-bound only |
| Gemini Flash + Search (grounding) | 20 RPD project-wide | ~12 calls (one per bill) | Tight, fits 1 run/day |
| Gemini Flash-Lite (verify, batched) | Same 20 RPD project-wide | ~4 calls (5 claims per call) | Tight, fits 1 run/day |
| Gemini Flash (editor + ADK verifier) | Same 20 RPD project-wide | ~2 calls | Tight |
| Tavily | 1,000 searches/mo | ~30 per run | 33 runs/mo, fits daily |
| Exa | Signup credits | ~15 per run | Per-account, generous |
| LegiScan | 30,000/mo | ~80 search calls per run | 375 runs/mo |
| CourtListener | 125/day | ~5 per run | 25 runs/day |
| Slack webhook | Unlimited | 1 per shipped run | None |

**Daily Gemini budget:** the 20 RPD project-wide limit covers ONE full pipeline run with grounding, verify, and editor combined (~18 calls, 2 calls of buffer). Multi-test days hit the cap. If you want headroom for multiple runs, add a Groq API key (free, 1,000 RPD on Llama 3.3 70B, no card) — `verify_brief.py` and the editor can be flipped to Groq via env var, leaving Gemini just for grounding.

---

## Status of today's known limitations

- The brief verify gate uses Gemini Flash-Lite. Daily project-wide quota is 20 calls. One run/day is fine.
- Researchers are local Ollama. The 14B model occasionally misses context that a 32B or 70B model would catch. If you have 32GB+ RAM, swap up.
- The fixed template requires every section. Vendor and On-our-radar may be empty some days, which renders as `no qualifying items today`.

---

## Repository layout

```
intel_daily/
├── intel_daily.sh         # main entry
├── intel_publish.py       # interactive verify + prompt + Slack publisher
├── verify_brief.py        # batched Gemini fact-check gate
├── grounding.py           # dynamic bill fact grounding via Gemini + Google Search
├── primary_sources.py     # LegiScan, RSS, Federal Register, CourtListener pulls
├── tools.py               # web_search, fetch_url, sqlite cache, budget ledger
├── agents.py              # ADK pipeline (researchers, editor, verifier, publisher callback)
├── run.py                 # pipeline runner
├── config.py              # backend choices, models, keys
├── dates.py               # US Eastern timezone helpers
├── slack.py               # Slack Block Kit renderer
├── render.py              # markdown -> HTML
├── send.py                # SMTP fallback
├── adk_agents/            # ADK web UI agent registration
├── output/                # generated briefs, qa, verify reports (gitignored)
├── cache.db               # sqlite cache for grounding, search, verify (gitignored)
├── .env                   # secrets (gitignored)
├── .env.example           # template
├── requirements.txt
├── README.md              # this file
├── OPERATIONS.md          # daily run flow, troubleshooting, quota math
├── ARCHITECTURE.md        # deep dive on the verify gate, grounding, interactive publisher
├── SETUP_DAILY.md         # legacy daily setup doc
├── INTEL_STRATEGY.md      # editorial strategy and source quality bar
├── COVERAGE_AUDIT_AND_PLAN.md # what we cover, what we don't, why
├── TECHNICAL_DOCUMENTATION.md # earlier technical doc, partly superseded by ARCHITECTURE.md
└── ADK_RESEARCH_AND_PLAN.md  # original ADK research notes
```

See `OPERATIONS.md` for the daily run flow and troubleshooting. See `ARCHITECTURE.md` for module-level data flow. See `INTEL_STRATEGY.md` for the editorial bar.

---

## License

Internal LuckyHands tool. Not for redistribution.
