# ARCHITECTURE

Deep dive on the components that make the LuckyHands Intel Daily brief possible.

The architecture has three layers:

1. **Primary sources and grounding** — deterministic free-tier APIs feed the editor authoritative bill facts.
2. **ADK pipeline** — three researchers, one editor, one verifier, one publisher.
3. **Interactive publisher** — verify gate, terminal preview, approve/improve/cancel prompt.

---

## Layer 1: primary sources and grounding

The brief is only as good as the inputs the editor sees. We use four free APIs to surface raw facts, then ground each bill with Gemini Flash + Google Search for authoritative status.

### LegiScan (state legislation)

`primary_sources.py:pull_sweepstakes_bills`

LegiScan is a free 30,000-call/month API for all 50 US states' legislation. We:

1. Search each state in `TIER_1_STATES` (IL, OK, IA, MD, IN, ME, LA, MN, TN, MS) plus `TIER_2_STATES` (CA, NY, NJ, TX, FL, OH, MA, VA, WA) for each keyword in `SWEEPSTAKES_KEYWORDS`.
2. Filter results to bills with on-topic title tokens (sweepstakes, dual currency, online gaming, racketeering, money transmission) and drop off-topic peripheral matches (EPA, transportation, education, etc.).
3. For each surviving bill, run dynamic grounding via `grounding.py:ground_bill_facts`.
4. Format the AUTHORITATIVE block plus the LegiScan citation into a markdown bullet.

Bills that come back from grounding marked `is_sweepstakes_relevant=false`, or `status=dead` with no `enacted_via` (meaning provisions weren't absorbed into another signed bill), are dropped before reaching the editor.

### Grounding (live web verification)

`grounding.py`

For each bill that survives the LegiScan filter, we call Gemini Flash-Lite with the Google Search tool enabled. The prompt asks for a structured JSON response with:

- `status` — signed, pending, dead, vetoed, unknown
- `signing_date` — YYYY-MM-DD if signed
- `effective_date` — YYYY-MM-DD or approximate
- `codification` — Public Law / Chapter / Session Law ref
- `key_provisions` — 1-2 sentences with penalty range, scope, AG authority
- `source_url` — authoritative state legislature, governor press release, or major trade press
- `is_sweepstakes_relevant` — true only if explicitly targets sweepstakes / social casino / dual currency / prediction markets / online gaming
- `enacted_via` — if the standalone bill failed but its provisions were absorbed into another signed bill, list that bill number here

The grounding result caches per UTC day in `cache.db.grounding_cache`. Re-running the pipeline on the same day reuses cached grounding.

The grounding is the difference between a brief that says "ME LD2007 PASSED to be enacted" (LegiScan raw status, confusing) and a brief that says "ME LD2007 was signed by Governor Mills on April 6, 2026 as Public Law 2025 Chapter 645, effective approximately July 14, 2026 under Maine's 90-day post-adjournment rule" (grounded, stakeholder-grade).

### RSS, Federal Register, CourtListener

`primary_sources.py:pull_rss_trade_press`, `pull_federal_register`, `pull_courtlistener`

These three add context the LegiScan pull cannot capture:

- **RSS**: 10 trade press feeds (SBC Americas, iGB, CDC Gaming, Legal Sports Report, Gambling News, Sports Handle, Casino.org, Bonus.com, PlayUSA, iGaming NEXT). Each item filtered by sweepstakes keywords. Lookback 48 hours.
- **Federal Register**: keyword search for "sweepstakes" + "promotional sweepstakes" + "online gambling sweepstakes". Lookback 14 days.
- **CourtListener**: 5 queries covering sweepstakes operator names and concepts. Lookback 14 days.

All three results are de-duplicated and feed the editor's `rss_findings`, `federal_register_findings`, and `courtlistener_findings` state keys.

---

## Layer 2: the ADK pipeline

`agents.py`

The pipeline is a Google ADK `SequentialAgent` of researchers + editor + verifier, with a `before_agent_callback` for primary source pulls and an `after_agent_callback` for publishing.

### Architecture diagram

```
newsletter_pipeline (SequentialAgent)
|
+-- research_team (SequentialAgent)
|   |
|   |  before_agent_callback: _primary_source_pull
|   |    populates state with legiscan, rss, federal_register, courtlistener findings
|   |
|   +-- regulatory_researcher  (Ollama qwen-intel + Tavily news search)
|   +-- competitor_researcher  (Ollama qwen-intel + Exa semantic search)
|   +-- market_researcher      (Ollama qwen-intel + Tavily/Exa auto-routing)
|
+-- editor                     (Gemini Flash, fills the 9-section template)
|
+-- verifier                   (Gemini Flash, internal QA)
    |
    |  after_agent_callback: _publish_callback
    |    sanitize, voice rules, render HTML, optional verify gate, optional Slack post
```

### Researchers

Each researcher gets a focused `mandatory_queries` list (10 queries each for ~30 total per run) plus a follow-up search step. They run in sequence — regulatory first, then competitor, then market — so context accumulates.

Researchers run on local Ollama (qwen2.5:14b). They handle the tool-call loop reliably and don't burn cloud quota.

### Editor

The editor receives all 7 research streams as templated state variables:

```
{regulatory_findings}
{competitor_findings}
{market_findings}
{legiscan_findings}
{rss_findings}
{federal_register_findings}
{courtlistener_findings}
```

The editor instruction (`agents.py:editor.instruction`) is the longest single string in the codebase. It includes:

- 5 data preservation rules (status terminology, title preservation, specifics, AUTHORITATIVE discipline, Polymarket/Kalshi framing)
- Prioritization rules (sweepstakes first; prediction markets is a sibling beat)
- Deduplication rule
- Quality bar (drop promo codes, sports tie-in bonuses, generic marketing)
- The exact 9-section template
- URL discipline
- Voice rules (no apostrophes, no hyphens between words, no em dashes)

The editor runs on Gemini Flash. Gemini's instruction following on long structured prompts is substantially better than any local 14B model.

### Verifier (internal QA)

The ADK verifier is a second Gemini Flash agent that re-reads the brief against the research findings and flags inconsistencies. Its output is informational — the verify gate that actually blocks Slack sends lives in `verify_brief.py`.

### Publisher callback

`agents.py:_publish_callback`

This is the last step in the ADK pipeline. It:

1. Sanitizes the brief (`_sanitize_brief`):
   - Drops lines with URLs not in any research input.
   - Drops lines from low-quality source hosts (sweepskings.com, casinorankr.com, etc.).
   - Drops Top story and On our radar items lacking sweepstakes-topic tokens.
   - Applies deterministic known-date corrections.
2. Enforces voice rules (`enforce_voice_rules`):
   - Strips apostrophes.
   - Replaces hyphens between words with spaces (preserves URLs).
   - Replaces em dashes with periods.
3. Renders the brief to HTML and writes to disk.
4. **If not in interactive mode** (i.e. `INTEL_DAILY_SKIP_VERIFY` is not set):
   - Runs the verify gate (`verify_brief.verify_brief_markdown`).
   - If any verdict is `incorrect`, blocks the Slack send and writes the verify report.
   - Otherwise posts to Slack with the proper Block Kit footer (`slack.post_to_slack`).

---

## Layer 3: the interactive publisher

`intel_publish.py`

When the user runs `./intel_daily.sh` without `--auto-slack`, the pipeline runs with `INTEL_DAILY_SKIP_VERIFY=1` and `INTEL_DAILY_NO_SLACK=1` set, then `intel_publish.py` takes over.

### The verify gate

`verify_brief.py`

The verify gate extracts every fact-bearing claim from the brief markdown via `_extract_claims`, then batches them 5 per Gemini Flash-Lite call with Google Search enabled. Each call returns a JSON array of verdicts. Per-claim verdicts:

- `confirmed` — the substantive facts hold up against authoritative web sources
- `partial` — most facts hold but one detail is off; `corrected_text` field provides the suggested replacement
- `incorrect` — a specific date, dollar amount, or named party is wrong; `corrected_text` mandatory
- `uncertain` — could not find authoritative source (often a Gemini quota or transient error)

The gate is **hard**: any `incorrect` verdict sets `ok=false` and blocks the Slack send.

Verify results cache per US Eastern day per claim hash in `cache.db.verify_cache`. Re-running on the same day with the same claim text returns cached verdicts.

### Terminal preview

`intel_publish.py:show_brief`

Colorized markdown print to terminal with ANSI escapes:
- Headings yellow underlined
- Bold cyan
- Markdown links: link text cyan, URL grey
- "Why it matters" lines green

### Verify report display

`intel_publish.py:show_verify_report`

Verdicts grouped by category. Incorrect items show the suggested correction inline.

### Prompt loop

`intel_publish.py:prompt_choice` and `main`

```
y  -> post_to_slack(cleaned_md), archive approved markdown, exit
n  -> save the brief and verify files, exit
i  -> apply_corrections(brief, verify_report) via Gemini Flash,
      save corrected brief, re-verify, re-prompt
```

The `i` loop costs one Gemini Flash call per pass (10-30 sec). It can run multiple passes before you approve.

### Slack rendering

`slack.py:md_to_blocks`

Converts the brief markdown into Slack Block Kit. Each section becomes:
1. A `section` block with `*<heading>*` mrkdwn
2. One or more `section` blocks with the section body (chunked at 2,900 chars per Slack limit)
3. A `divider`

The footer is special-cased: it's not rendered as a normal section. Instead it becomes:
1. A `divider`
2. A `context` block with italic disclaimer
3. A `context` block with the boilerplate "Reply to this thread with corrections / Not legal advice" line

---

## Caching

`cache.db` (sqlite, gitignored) holds three tables:

| Table | Key | TTL |
|---|---|---|
| `search_cache` | (utc_date, query) | 1 day |
| `legiscan_cache` | (utc_date, op, params) | 1 day |
| `grounding_cache` | (us_eastern_date, key) | 1 day |
| `verify_cache` | (us_eastern_date, claim_hash) | 1 day |
| `monthly_ledger` | (month, backend) | 1 month |

Re-running the pipeline on the same US Eastern day reuses all caches. To force fresh data, delete the relevant rows:

```python
import sqlite3
conn = sqlite3.connect('cache.db')
conn.execute("DELETE FROM grounding_cache WHERE utc_date = '2026-06-29'")
conn.commit()
```

---

## When you want the comprehensive 40-item brief

The local pipeline produces a decent brief (~15-25 items across sections). When you need a truly comprehensive stakeholder brief (~42 items, every section richly populated), the multi-agent Workflow approach runs via Claude Code:

1. **Discover** phase: 7 parallel grounded discovery agents (state legislation, enforcement, competitor, vendor, market, prediction markets, on-radar).
2. **Context** phase: for each discovered item, generate a stakeholder context line ("Why it matters to LuckyHands").
3. **Assemble** phase: one Gemini Flash call writes the final brief in the 9-section template, using the enriched per-item data.
4. **Verify** phase: 5-lens fact check across facts, dedup, completeness, topical relevance, source quality.
5. **Polish** phase: apply any issues found.

This workflow is invoked by asking Claude to run it ("run the comprehensive workflow brief" or similar). It uses ~50-80 subagents and ~1M output tokens. Not for daily use, but useful when you want a maximum-quality brief.

---

## Where to make changes

| Want to | Edit |
|---|---|
| Add a state to the LegiScan sweep | `primary_sources.py: TIER_1_STATES / TIER_2_STATES` |
| Add a new sweepstakes-relevance keyword | `primary_sources.py: _ON_TOPIC_TITLE_TOKENS`, `agents.py: _TOPIC_RELEVANCE_TOKENS` |
| Drop a low-quality source globally | `agents.py: _LOW_QUALITY_SOURCE_HOSTS` |
| Tighten the editor's voice | `agents.py: VOICE_RULES`, `editor.instruction` rules block |
| Change the brief template | `agents.py: editor.instruction` template block, plus `slack.py:md_to_blocks` if section names change |
| Add a researcher mandatory query | `agents.py: regulatory_researcher / competitor_researcher / market_researcher mandatory_queries` |
| Change verify batching | `verify_brief.py: verify_brief_markdown batch_size` parameter |
| Move to Groq for verify | Future work: add `VERIFY_BACKEND=groq` switch in `verify_brief.py` |

---

## File-level dependencies

```
intel_daily.sh
  + python intel_publish.py
      + verify_brief.py            (depends on grounding-cached or Gemini Flash-Lite + Search)
          + dates.py
      + slack.py
      + agents.py                  (just imports _current_issue_number and helpers, not the full pipeline)
  + python run.py
      + config.py
      + agents.py                  (full pipeline)
          + primary_sources.py
              + grounding.py       (Gemini Flash-Lite + Search per bill)
              + dates.py
          + tools.py               (Tavily, Exa, DDG, Jina Reader, ledger, cache)
              + dates.py
      + render.py
      + send.py                    (optional, SMTP path)
      + slack.py                   (used by publisher callback)
```

---

## Known limitations

1. **Gemini 20 RPD project-wide quota** — limits us to roughly one daily run. Add Groq for headroom.
2. **Local Ollama 14B model context drift** — researchers occasionally miss connections that a 32B or 70B model would surface. Bump model if you have RAM.
3. **Grounding misses cross-bill enactment some of the time** — e.g. MN HF4437 provisions enacted via SF4760. The prompt addresses this but Gemini doesn't always catch it. Verify gate is the safety net.
4. **No federal preemption modeling** — when a federal court strikes a state ban, the brief reports the ruling but doesn't automatically downgrade affected scoreboard entries. Operator judgment required.
5. **App Store and Reddit signal pulls are weekly (Friday-only)** — set `INTEL_DAILY_FORCE_SENTIMENT=1` to include them on any day.
