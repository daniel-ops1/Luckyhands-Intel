# OPERATIONS

Day-to-day running, troubleshooting, and quota math for LuckyHands Intel Daily.

---

## Daily run, the default flow

Start with Ollama running in the background:

```bash
ollama serve &
```

Then trigger the pipeline:

```bash
cd /Users/ritzmish/intel_daily
./intel_daily.sh
```

### What happens, step by step

1. The script checks Ollama is reachable, fails fast if not.
2. The pipeline runs in 4 phases (8-12 min total on M5 Pro 24GB):
   - **Primary sources** (~30 sec): LegiScan, RSS, Federal Register, CourtListener.
   - **Grounding** (~2 min): Gemini Flash plus Google Search verifies every LegiScan bill's status, effective date, codification.
   - **Researchers** (~5 min): three Ollama agents run 30 mandatory queries plus follow-up searches and article reads.
   - **Editor + verifier** (~30 sec): Gemini Flash assembles the brief in the 9-section template; ADK verifier does an internal QA pass.
3. The publisher callback renders the brief to HTML at `output/brief_<date>.html`, writes the QA notes, and the markdown.
4. `intel_publish.py` takes over:
   - Re-loads the brief markdown.
   - Runs the verify gate (batched Gemini Flash-Lite + Google Search).
   - Prints the brief in color in your terminal.
   - Prints the verify report grouped by verdict.
   - Prompts: `y` ship to Slack, `n` cancel, `i` apply corrections.
5. On `y`, posts to Slack and archives the approved markdown at `output/brief_approved_<date>.md`.

### The improve loop

If the verify gate flags anything, type `i`. The system:

1. Reads the verify report's per-claim corrected text.
2. Sends the current brief + verify report to Gemini Flash with instructions to apply only the corrections.
3. Saves the new brief as `output/brief_corrected_<date>_pass<N>_<ts>.md`.
4. Re-runs the verify gate.
5. Re-prompts.

Loop until clean or you cancel.

---

## Quota math

Gemini free tier on a typical Google AI Studio project: **20 requests per day, project-wide across all Gemini models.**

| Component | Calls per run | Cumulative |
|---|---|---|
| Grounding (Flash-Lite + Search) | ~12 (1 per bill) | 12 |
| Editor (Flash, ADK LlmAgent) | ~1-2 | 14 |
| ADK Verifier (Flash, internal QA) | ~1 | 15 |
| Verify gate (Flash-Lite + Search, batched 5/call) | ~4 for an 18-claim brief | 19 |
| **Daily total** | | **~19** |

You have **about 1 call of headroom**. One full run per day fits. A second run on the same day will hit the quota mid-verify and most verify verdicts will return as `uncertain`.

When you need multi-test days, the structural answers are:
- Add a `GROQ_API_KEY` and flip `EDITOR_BACKEND=groq` plus `VERIFY_MODEL=groq/llama-3.3-70b-versatile`. Groq free tier is 1,000 RPD on Llama 3.3 70B.
- Or upgrade your Google Cloud project to billing-enabled (~$0.10 per run on Flash; you'd burn maybe $3 a month).

### Quota reset

Gemini free tier resets at **midnight Pacific Time**, which is **3am Eastern**. If you blow through the quota in testing, you're back online a few hours later.

Tavily (1,000/mo), Exa (signup credits), LegiScan (30,000/mo), CourtListener (125/day), and Slack webhook all have separate, generous free tiers that the pipeline does not threaten in normal use.

---

## What time to run

| Goal | When |
|---|---|
| Have the brief in Slack by 10:30am ET | Start at 10:15am ET (12 min pipeline + ~1 min verify + buffer for one improve pass) |
| Have a fresh brief for the US business day open | Start between 6am and 8am ET, after the 3am ET Gemini quota reset |
| Stress-test on a slow weekend | Start whenever, just leave 12-15 min |

The pipeline does not need an internet pause around Gemini's reset — primary sources pull in parallel and the editor doesn't fire until grounding is done.

---

## Other modes

```bash
./intel_daily.sh --auto-slack    # no interactive prompt, verify gate gates the Slack send
./intel_daily.sh --skip-run      # skip pipeline, publish the most recent generated brief
./intel_daily.sh --help          # show usage
```

For `cron` or `launchd`, use `--auto-slack`. The verify gate will block any `incorrect` Slack send, leaving the brief and verify report on disk for you to triage.

---

## File outputs per run

```
output/brief_pipeline_<date>.md        # pipeline-generated brief, raw markdown
output/brief_<date_long>.html          # rendered HTML
output/qa_<date_long>.md               # ADK verifier's QA notes
output/verify_report_<date>_pass1.md   # verify gate result, pass 1
output/brief_corrected_<date>_pass1_<ts>.md   # if you ran improve
output/brief_approved_<date>.md        # if you approved and posted to Slack
output/run_<timestamp>.log             # full pipeline log
```

The `output/` directory is gitignored. Cleanup is on you; recommend keeping the last 30 days for audit.

---

## Issue counter

Each successful pipeline run bumps `.issue_counter`. This number shows in the Slack header (`Issue 1 ...`).

Override for testing:

```bash
INTEL_DAILY_ISSUE_OVERRIDE=0 ./intel_daily.sh
```

This forces the issue number to 0 without bumping the persistent counter.

Reset the counter manually:

```bash
echo "0" > .issue_counter   # next real run will be Issue 1
```

---

## Troubleshooting

### "Ollama is not reachable at http://localhost:11434"

Run `ollama serve` in another terminal. Confirm with `curl http://localhost:11434/api/tags`.

### Pipeline times out after 1200s

The default `LLM_TIMEOUT_S=1200` covers the slow 14B+context Ollama call. If your hardware is slower, bump it:

```bash
LLM_TIMEOUT_S=1800 ./intel_daily.sh
```

### Verify gate returns mostly `uncertain` with 429 errors

You hit the Gemini 20 RPD quota. Wait until 3am ET for reset or use a Groq backend (see Quota math above).

### Brief markdown lacks URLs in items

The editor stripped URLs because the prompt confused it. Check `agents.py` URL_DISCIPLINE block hasn't been edited. The single line `[Publication name](URL)` format is mandatory.

### Slack post returns non-200

Check `SLACK_WEBHOOK_URL` is correct and the webhook is bound to a live channel. Test with:

```bash
curl -X POST -H 'Content-Type: application/json' --data '{"text":"test"}' "$SLACK_WEBHOOK_URL"
```

### Verify gate flags items the brief should not have

Examples we've seen: brick-and-mortar poker bills wrongly grounded as sweepstakes-relevant, off-topic geopolitics or restaurant-fee legislation slipping through the sanitizer.

Two layers handle this:
- `grounding.py` is_sweepstakes_relevant filter drops bills with no sweepstakes nexus.
- `agents.py _sanitize_brief` drops On-our-radar items that lack any sweepstakes-topic token.

If something still slips through, add the keyword to `_LOW_QUALITY_SOURCE_HOSTS` (host-based) or `_TOPIC_RELEVANCE_TOKENS` (topic-based) in `agents.py`.

### Pipeline produces a thin brief (3-4 items per section)

The local pipeline is constrained by what the Ollama researchers surface. For a fuller brief (40+ items across all sections), use the multi-agent Workflow approach via Claude Code — see `ARCHITECTURE.md` for the workflow script.

---

## Logs and history

Every run logs to `output/run_<timestamp>.log`. The pipeline also writes verbose stdout including:

- `[primary_source]` lines for LegiScan, RSS, Federal Register, CourtListener phases
- `[grounding]` lines for each bill's Gemini call
- `[web_search]` lines for each Tavily/Exa/DDG call
- `[sanitize]` lines for any items the sanitizer dropped
- `[link_check]` lines for any markdown-link to URL-host mismatches
- `publisher,` lines for the final verify + render + Slack outcome

Grep these prefixes to debug a specific stage.

---

## Cost model

Today: **$0/month** for everyone.

If you migrate to AWS for a fully unattended hosted version with no quota concerns:

| Component | Monthly cost |
|---|---|
| AWS t3.large + EBS | ~$25 |
| Gemini Flash with billing enabled | ~$3-5 |
| Tavily Pro (if you outgrow 1,000/mo) | $0 to $30 |
| LegiScan paid tier (if you outgrow 30k/mo) | $0 to $30 |
| **Total** | **~$30-90/mo all-in** |

For the laptop run, the only cost is electricity.
