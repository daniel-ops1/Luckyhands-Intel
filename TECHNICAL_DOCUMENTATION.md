# LuckyHands Intel Daily, Technical Documentation

For engineers picking this up or evaluating the architecture. Read DOCUMENTATION.md first if you want the non technical overview.

## The tech stack

**Language.** Python 3.11+. Tested on 3.14.

**Agent framework.** Google ADK (Agent Development Kit), version 2.3.0, pinned for stability. ADK gives us multi agent orchestration primitives (LlmAgent, SequentialAgent, ParallelAgent, LoopAgent), built in session state passing through output_key references in instruction templates, a developer web UI for live debugging with trace spans for every model call and every tool call, and a plugin system for global Runner level callbacks.

**LLM runtime.** Ollama, served locally at http://localhost:11434. Installed via Homebrew (`brew install ollama` then `brew services start ollama`). The pipeline uses a custom Ollama model named qwen_intel which is built on top of qwen2.5 14b with a 16K context window. The 16K context matters because the editor reads roughly 5KB of research findings plus a 3KB system prompt, which would truncate on the default 2K Ollama context.

**Model wrapper.** Google ADK is Gemini native by default. To run against Ollama we use LiteLLM via ADK LiteLlm wrapper. The model string must use the `ollama_chat` prefix, not bare `ollama`, because the bare prefix triggers infinite tool call loops, documented in the ADK docs.

**Web search.** DuckDuckGo Lite endpoint at `https://lite.duckduckgo.com/lite/`. Free, no API key, no signup. We picked Lite over the regular DuckDuckGo HTML endpoint because Lite tolerates more queries per minute before its anomaly detection trips. We added our own throttle of 8 seconds between calls and a per query cache to stay well under the rate limit. Tavily and Brave Search are wired as optional fallbacks if `BRAVE_API_KEY` or `TAVILY_API_KEY` are set in env.

**Article reader.** Direct `httpx` fetch plus `BeautifulSoup` parse. The fetcher strips nav, footer, scripts, and aside elements, then pulls paragraphs longer than 30 chars to get article body. Cap at 6000 chars per article so we do not blow up the LLM context.

**HTML rendering.** Jinja2 plus a small custom markdown to HTML pass with badges for ACTION, WATCH, and WARNING tags. The HTML looks like a branded email even though Slack is the primary channel today.

**Slack delivery.** Slack Block Kit via incoming webhook. Section blocks per heading, mrkdwn for content, divider blocks between sections, header block at the top, context block at the bottom for the disclaimer.

**Storage.** Local filesystem today, output briefs land in `./output`. Session state held in ADK InMemorySessionService. For production on AWS we will switch to DatabaseSessionService against an existing Postgres schema so runs are auditable and resumable.

## Why these choices

**Google ADK over LangGraph, CrewAI, AutoGen, OpenAI Swarm.** ADK fits our exact shape (sequential research, editor, verifier), has the right primitives, is actively developed with releases every two weeks, supports MCP, and has a built in web UI that turned out to be useful for live debugging. LangGraph is more powerful but overkill for a five minute daily cron. CrewAI is conceptually clean but smaller community in 2026. AutoGen is in maintenance mode. OpenAI Swarm and Assistants API are both deprecated.

**Ollama over Cloudflare Workers AI, llama.cpp direct, LM Studio.** Ollama is the easiest path to running open weights locally on a Mac. Pulls models, serves them with a single command, and the OpenAI compatible API works through LiteLLM out of the box. Cloudflare Workers AI is cloud only and a separate billing relationship. llama.cpp is what Ollama wraps and is one level lower than we need. LM Studio is GUI first which is fine for testing but not for an automated pipeline.

**qwen2.5 14b over llama3.1 8b, mistral, gpt oss.** qwen2.5 14b had the best tool calling reliability in our testing. It uses tools when prompted explicitly with a step by step protocol and stays close to the requested output format. llama3.1 8b is also pulled as a backup option and is known strong on tools but the 8b output had more drift in our tests. gpt oss 20b would be better still but is heavier than this machine is comfortable with.

**DuckDuckGo Lite over regular DDG, SearXNG public instances, Brave, Tavily.** Lite is free, no key, no signup, and tolerates our query volume with throttling. Regular DDG HTML throws 202 anomaly more aggressively. Public SearXNG instances (`searx.be`, `priv.au`) blocked us with 403 and 429 in testing. Brave and Tavily both need an API key but are wired as fallbacks if keys appear in env.

## Repository layout

```
intel_daily/
├── adk_agents/
│   └── intel_brief/
│       ├── __init__.py         ADK web discovery, imports agent module
│       └── agent.py            Exposes root_agent for ADK runtime
├── agents.py                   The pipeline. All five subagents, callbacks, voice rules
├── tools.py                    web_search and fetch_url tools, throttle, UA rotation
├── slack.py                    Slack Block Kit converter and webhook poster
├── render.py                   Markdown to HTML for the email render
├── send.py                     SMTP send, used by Phase 2 email path
├── config.py                   Env var loading, model selection
├── template.html               Jinja2 email template
├── run.py                      Standalone CLI runner, alternative to adk web
├── Dockerfile                  Container build for AWS deploy
├── docker-compose.yml          Local compose recipe
├── requirements.txt
├── .env.example                Template env
├── README.md
├── DOCUMENTATION.md            Non technical overview
├── TECHNICAL_DOCUMENTATION.md  This file
└── output/                     Generated briefs and QA notes per run
```

## Agent topology

```
newsletter_pipeline (SequentialAgent)
├── research_team (SequentialAgent)
│   ├── regulatory_researcher  (LlmAgent + web_search + fetch_url)
│   ├── competitor_researcher  (LlmAgent + web_search + fetch_url)
│   └── market_researcher      (LlmAgent + web_search + fetch_url)
├── editor                     (LlmAgent, before_agent_callback ensures state defaults)
└── verifier                   (LlmAgent, before + after callbacks)
                                          after_agent_callback publishes to disk + Slack
```

Researchers run sequentially today because the local Ollama instance serves one model at a time. Parallel agents would queue at the Ollama layer anyway. On AWS we will switch to ParallelAgent because Vertex AI or Bedrock can serve concurrent requests, which cuts wall clock by roughly 3x.

Each agent writes its findings to a named output_key on session state.

```
regulatory_researcher -> state.regulatory_findings
competitor_researcher -> state.competitor_findings
market_researcher     -> state.market_findings
editor                -> state.brief_md
verifier              -> state.verification_note
```

The editor instruction template references `{regulatory_findings}`, `{competitor_findings}`, `{market_findings}` which ADK substitutes from session state at runtime. If any key is missing, the `before_agent_callback` named `_ensure_state_defaults` seeds it with `no qualifying items today` so the template never crashes.

## How agents are told to actually use tools

The biggest finding from testing was that a 14B local model can be lazy about tool calling. Given an open ended prompt like "research X", the model sometimes just answers from training data without calling any tools.

The fix is a mandatory step by step protocol in each researcher prompt, with the queries hardcoded.

```
MANDATORY PROTOCOL. You MUST execute every step below in order.
STEP 1. Call web_search with query: "state sweepstakes casino ban 2026".
STEP 2. Call web_search with query: "attorney general sweepstakes cease and desist 2026".
STEP 3. Call web_search with query: "Illinois Gaming Board sweepstakes cease and desist".
STEP 4. Call web_search with query: "Mississippi Iowa Oklahoma sweepstakes legislation 2026".
STEP 5. Call web_search with query: "Tennessee sweepstakes attorney general 2026".
STEP 6. Call web_search with query: "California AB 831 sweepstakes".
STEP 7. After all 6 calls, optionally call fetch_url on up to three promising URLs.
STEP 8. Write findings as a markdown list using ONLY URLs from your actual search results.

DO NOT respond with `no qualifying items today` unless every one of the 6 web_search calls
above returned `No results found.` or `Search failed,`.
```

This converts the model from "decide what to do" to "execute these specific steps", which a 14B model handles well. End to end we now see all three researchers fire all six searches reliably.

## Voice rule enforcement

LLMs are unreliable at micro style rules like no apostrophes and no hyphens, especially smaller models. We solved this deterministically.

The publisher callback runs a regex pass on the editor output before rendering. It strips apostrophes, swaps hyphens between words for spaces, replaces em dashes with periods. URLs and `Stake.us` style domain references are stashed into placeholders before the strip and restored afterward, so links are never broken.

The model is told NOT to worry about voice rules, freeing its attention for content quality.

## Anti hallucination guardrails

Five layers stacked.

1. **URL discipline prompt.** Every researcher prompt and the editor prompt include an explicit instruction that URLs MUST come from actual tool results in the current turn. Inventing URLs is forbidden.

2. **Verifier subagent.** After the editor writes the brief, a verifier subagent reads both the brief and all three research streams and flags any claim or URL not supported. Output goes to `state.verification_note` which is saved to a separate QA file, never shown to the stakeholder.

3. **Voice post process.** Deterministic regex, runs no matter what the model wrote.

4. **before_agent_callback defaults.** If a researcher fails to populate its output_key, the editor and verifier get a safe default of `no qualifying items today` so the pipeline never crashes mid run.

5. **Session state inspection** via the ADK developer web UI. Every run is auditable. Every tool call, every model call, every state mutation has a trace span you can click through.

## How a run actually goes

User triggers a run, either via the ADK web UI or via cron calling `python run.py preview`.

ADK Runner instantiates the SequentialAgent pipeline.

regulatory_researcher fires first. Its instruction template tells it to run six specific web_search calls. The model calls web_search six times. Our tool issues each call against DDG Lite with an 8 second throttle. Each call returns up to 10 results. The model then optionally calls fetch_url on the most promising URLs to read article bodies. After the searches and reads complete, the model writes a markdown bullet list of findings with source links, and ADK writes that string into `state.regulatory_findings`.

competitor_researcher runs next, same pattern, different mandatory queries.

market_researcher runs after that, again same pattern.

editor runs with all three findings strings available in its instruction template through state interpolation. It writes the assembled brief into `state.brief_md`.

verifier runs last. It reads `state.brief_md` and the three findings strings and writes a fact check note into `state.verification_note`.

The `after_agent_callback` on the verifier fires when verifier finishes. The callback reads `state.brief_md`, runs it through the voice rule regex, renders to HTML using Jinja2, writes the HTML to `./output`, opens the HTML in the local browser, and posts to Slack if `SLACK_WEBHOOK_URL` is set.

A typical run end to end on the local laptop takes 12 to 14 minutes with 24 web_search calls and 7 fetch_url calls firing across the three researchers. On Gemini Flash or Claude Haiku in production this drops to roughly 60 to 90 seconds because the inference is faster and we can parallelize the researchers.

## Local development setup

```
brew install ollama
brew services start ollama
ollama pull qwen2.5:14b

cat > /tmp/Modelfile.intel << 'EOF'
FROM qwen2.5:14b
PARAMETER num_ctx 16384
EOF
ollama create qwen_intel -f /tmp/Modelfile.intel

cd ~/intel_daily
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env, paste SLACK_WEBHOOK_URL

adk web adk_agents
```

Then open http://127.0.0.1:8000/dev-ui and send any prompt to the intel_brief agent.

## Containerized setup

```
docker compose up build
```

The container runs `adk web adk_agents` on port 8000 and reaches Ollama through `host.docker.internal:11434` so the LLM weights stay on the host and are not duplicated in the container. The `./output` directory is volume mounted so rendered HTML briefs land back on the host. Env vars pass through from `.env` or from the compose `environment` block.

## Cost breakdown

Local development today. Zero recurring cost.

```
LLM inference  Ollama qwen_intel on developer machine    $0
Web search     DuckDuckGo Lite                            $0
Article fetch  Direct httpx                               $0
Slack delivery Incoming webhook                           $0
Storage        Local disk                                 $0
```

Production target on AWS, roughly 25 to 50 dollars per month at one brief per day.

```
LLM inference  Gemini Flash or Claude Haiku via LiteLLM   $5 to $15
Web search     Brave Search API, 2k free tier             $0
Storage        Existing Postgres schema                    $0
Compute        ECS Fargate, 0.5 vCPU, 15 min daily        $1 to $2
EventBridge    Scheduler trigger                           $0
Secrets        AWS Secrets Manager                         $1
Logs           CloudWatch                                  $1
LiteLLM proxy  Self hosted sidecar                         $0
```

## Production migration plan

Targeted for after we tune the brief quality and stakeholder list.

1. Container build via the existing Dockerfile, push to ECR.
2. ECS Fargate service inside the existing LuckyHands VPC.
3. EventBridge Scheduler trigger daily at 6:30 am ET, drops onto SQS.
4. Celery worker reads SQS, calls the ADK service over HTTP, posts to Slack via the existing webhook.
5. Switch LLM_BACKEND to gemini and put the Google API key into AWS Secrets Manager. Local Ollama is fine to keep as a development fallback.
6. Switch InMemorySessionService to DatabaseSessionService against a new schema in the existing Postgres instance, so runs are auditable and resumable.
7. Wire OpenTelemetry to CloudWatch via the ADK auto instrumentation.

All of this is documented in INTEL_EXECUTION_PLAN.md.

## Known gaps

1. **Editor sometimes attributes the right claim to the wrong URL.** Fix planned. A deterministic post pass that re extracts URLs from the research findings and corrects the editor URL if it does not match the closest finding.

2. **Competitor section sometimes compresses too aggressively.** Eight researcher findings can become two editor bullets. Fix planned. Stricter editor prompt with a one bullet per item rule.

3. **DDG Lite throttle still occasionally trips on the first call** when the developer has been hammering DDG manually before launching the agent. The cache warms after the first successful call. Brave Search API as a fallback is wired but disabled until we get a key.

4. **The voice post process strips apostrophes from possessives** so "Illinois Gaming Boards" reads slightly odd compared to the natural form. Acceptable today, not great long term. Future fix, rewrite possessives to "the X of Y" pattern with a small grammar pass.

## Where to look in the code

| Concern | File | Symbol |
|---|---|---|
| Pipeline composition | agents.py | `newsletter_pipeline` |
| Research subagent factory | agents.py | `_researcher()` |
| Mandatory step protocol | agents.py | inside `_researcher()` instruction string |
| Editor instruction | agents.py | `editor = LlmAgent(...)` |
| Voice rule regex | agents.py | `enforce_voice_rules()` |
| State defaults | agents.py | `_ensure_state_defaults()` |
| Publisher callback | agents.py | `_publish_callback()` |
| Web search tool | tools.py | `web_search()`, `_parse_lite()` |
| Article fetch | tools.py | `fetch_url()` |
| DDG anti throttle | tools.py | `_throttle()` |
| Slack block conversion | slack.py | `md_to_blocks()` |
| Slack webhook post | slack.py | `post_to_slack()` |
| HTML rendering | render.py | `render_email()`, `_markdown_to_html()` |
| ADK web entry | adk_agents/intel_brief/agent.py | `root_agent` |
