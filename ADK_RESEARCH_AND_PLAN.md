# LuckyHands Intel Daily, Research and Plan

Synthesized from eight parallel web research streams covering Google ADK core, tools, models, deployment, alternatives, newsletter patterns, sweepstakes sources, and production concerns. 113 findings, 92 recommendations, dated June 23, 2026.

## Executive summary

Stay on Google ADK, version 2.3.0. The framework fits the daily research brief shape, it has the multi agent primitives we need, and it runs cleanly on AWS via ECS Fargate. The two changes that matter most are: move off the Gemini free tier today by adding a credit card to the project, and add a LiteLLM proxy in front of Gemini and Claude with ordered fallbacks. After that, three architectural moves deepen the insights: convert the three research sub agents from sequential to parallel, add a loop based critic refinement stage between editor and verifier, and switch the verifier from a single LLM call to per claim NLI style citation checking. Finally, replace web search with a regulatory and trade press RSS first ingestion pipeline backed by LegiScan, Open States, and CourtListener, with web search reserved as a fallback. Confidence on every recommendation in this document is rated against the verifier output. High confidence means at least three sources agree and adversarial verification held.

## Architecture decision, ADK vs alternatives

We stay on Google ADK. Confidence, high.

The honest top three alternatives in 2026 are Claude Agent SDK, Pydantic AI plus Tavily, and LangGraph. They each have real strengths, but on balance ADK still fits our specific shape and our existing investment.

| Framework | Strengths | Weaknesses for us | Verdict |
|---|---|---|---|
| Google ADK 2.3.0 | Multi agent primitives (LlmAgent, Sequential, Parallel, Loop), output_key state passing, native MCP client, OpenTelemetry support, AgentTool composition, plugin system, recently added Flexible Execution Graphs | Gemini optimized, one builtin tool per agent limit, google_search Gemini only and cannot mix with custom tools, version 2.x is recent | Keep |
| Claude Agent SDK | Native web_search ($10 per 1000), native web_fetch, subagents with isolated context, sessions, no separate search key, MCP client | Locks search and subagents into Anthropic billing, less production proven than ADK and LangGraph as of mid 2026, less mature multi agent orchestration | Use as backup for editor and verifier via LiteLLM, not primary |
| Pydantic AI plus Tavily | Matches our exact shape (sequential research, editor, verifier), structured outputs built in, framework agnostic on model, lightweight | More glue code to write (we already wrote it in ADK), no native multi agent orchestration, smaller community | Reserve as plan B if ADK adds friction we cannot resolve |
| LangGraph | Production proven for stateful workflows, durable checkpointed execution that survives crashes, parallel branches, human in the loop, LangSmith observability | Overkill for a five minute daily cron, more complex to learn, runtime tie ins with LangChain ecosystem | Defer until we add human review or multi day analyst workflows |
| OpenAI Swarm and Assistants API | N/A | Both deprecated | Rule out |
| AutoGen | N/A | In maintenance mode | Rule out |
| Mastra, Vercel AI SDK, Inngest AgentKit | N/A | TypeScript first, language switch for us | Rule out |

Source: github.com/google/adk-python/releases, code.claude.com/docs/en/agent-sdk/overview, langchain.com/langgraph, ai.pydantic.dev.

## Backend strategy

Hybrid model stack behind a LiteLLM proxy. Confidence, high.

Replace the dual backend code path we have today (Gemini vs Ollama branching in agents.py) with a single LiteLLM proxy sidecar that owns provider selection, fallbacks, retries, and observability. Stage by stage routing.

| Stage | Primary | Secondary | Tertiary (local) |
|---|---|---|---|
| Researchers (regulatory, competitor, market) | Gemini 2.5 Flash paid tier | Claude Haiku 4.5 | Ollama qwen2.5:7b |
| Editor | Claude Sonnet 4 | Gemini 2.5 Pro paid tier | Ollama qwen2.5:14b |
| Verifier | Claude Haiku 4.5 | Gemini 2.5 Flash paid tier | Ollama qwen2.5:7b |
| NLI claim check (new) | Claude Haiku 4.5 | Gemini 2.5 Flash | Ollama qwen2.5:7b |

Why this split. Claude is more reliable at honoring strict style rules (the no apostrophes, no hyphens, no em dashes rules we kept hitting). Gemini Flash is cheap and fast for the research lane that does many tool calls. Haiku is great for high volume verifier and NLI checks. Ollama stays as the fully offline development path and the final fallback.

Two immediate actions are required regardless of framework choice.

1. **Put a credit card on the Google Cloud project today.** Confidence, high. The 503 and 429 errors we hit today were free tier quota walls. Free tier is 15 RPM and 1500 RPD on Gemini 2.5 Flash and Pro left the free tier entirely on April 1, 2026. Paid Tier 1 unlocks roughly thirty times the request quota with a 250 dollar default spend cap. Source, ai.google.dev/gemini-api/docs/rate-limits.

2. **Fix the Ollama prefix bug.** Confidence, high. ADK docs explicitly warn that `LiteLlm(model="ollama/...")` causes infinite tool call loops and context loss. Must use `ollama_chat/` prefix. Source, adk.dev/agents/models/ollama. We already use ollama_chat in our config but should add an assertion in `_researcher_model()` so this never regresses.

Anthropic Batch API gives a fifty percent discount and stacks with prompt caching (combined up to ninety five percent). Use Batch API for the daily 7am run if we are okay with results landing within twenty four hours, otherwise reserve Batch API for backfills and evals. Source, codewords.ai/blog/anthropic-batch-api.

## Tool ecosystem

What we have today.

- Gemini path: `google_search` (built in, Gemini only, cannot mix with other tools in the same agent)
- Ollama path: custom `web_search` (DuckDuckGo) plus `fetch_url`

What we should add, in priority order.

1. **McpToolset for Tavily, Exa, and Firecrawl.** Critical priority. Confidence, medium. ADK ships `McpToolset` with `StdioConnectionParams` for local subprocess MCP servers and `StreamableHTTPConnectionParams` for remote. Same tool stack runs on Gemini, Claude, and Ollama. Kills the dual backend search split. Tavily returns LLM optimized snippets, Exa is best for semantic search, Firecrawl handles rendered JavaScript pages. Caveat from verifier, Tavily costs about $1 per 1000 queries and the daily brief is roughly twenty queries, so $0.60 per month is negligible. Source, adk.dev/tools-custom/mcp-tools.

2. **AgentTool composition for nested research.** High priority. Wrap each researcher as an AgentTool callable by a top level orchestrator. Lets us add specialized sub workflows (one for state legislation, one for litigation, one for competitor signals) without restructuring the whole pipeline. Source, developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk.

3. **FunctionTool for RSS ingestion and DB writes.** High priority. Convert the planned regulatory ingestion job into a set of FunctionTools the research agents can call directly. Auto schema generation from type hints means a clean signature is all we need. Source, adk.dev/tools-custom/function-tools.

4. **LongRunningFunctionTool for human in the loop edits.** Medium priority. Useful when we add the stakeholder review preview phase. The function yields, the agent pauses, a human reviews, the function returns the approved diff and the agent continues. Source, adk.dev/tools-custom/long-running-function-tools.

5. **OpenAPI tool spec for our existing FastAPI backend.** Medium priority. Auto generate tools from the LuckyHands backend OpenAPI spec so the research agents can pull internal context (current operator list, current state market list, internal compliance notes). Source, adk.dev/tools-custom/openapi-tools.

Hard limit to remember. `google_search`, `code_execution`, and `vertex_ai_search` are Gemini only and you can use only one builtin tool per agent. You cannot combine them with custom tools in the same agent. Source, adk.dev/tools/limitations. This is why the Gemini path researchers cannot also call `fetch_url`. We work around it by adding a separate FetchAgent as an AgentTool.

## Source list, prioritized

Twelve sources, prioritized by signal quality per dollar and per integration hour.

### Tier one, free and high signal, integrate first

1. **LegiScan API.** Free public tier is 30,000 queries per month. Covers all 50 states plus Congress with structured JSON for bills, sponsors, status, full text, and roll calls. Daily polling on the keyword set `sweepstakes`, `dual currency`, `sweeps coins`, `social casino`. Source, legiscan.com/legiscan and legiscan.com/pricing/api.

2. **Open States API by Plural Policy.** Free fallback redundancy to LegiScan. Standardized API across all 50 states, DC, and Puerto Rico. Bulk data downloads also free. Source, docs.openstates.org/api-v3.

3. **CourtListener RECAP webhooks and RSS docket alerts.** Free, push based. Ingests over 380 million court documents. Set up RECAP Search Alerts on sweepstakes related keywords. Webhook delivery to a new endpoint inside `luckyhands_backend` that enqueues for the next brief. Source, courtlistener.com/help/alerts and free.law/2025/06/18.

4. **State AG press releases.** Scrape only, no consistent RSS standard except New Jersey. Start with NY, TN, MN, CA, MA, MI, MD, NJ, WA. Build a small per state scraper registry. AG actions drive the biggest market events (NY shutdown of 26 platforms, TN crackdown, MN cease and desists). Source, ag.ny.gov press releases.

5. **SBC Americas RSS, Legal Sports Report RSS.** Already wired today. Keep.

### Tier two, trade press and analyst sources, integrate second

6. **Sweepsy, Gambling Insider, Casino.org, Yogonet, CDC Gaming Reports, PlayUSA.** RSS or scraped. Wire via feedparser. Already partly wired today.

7. **Vegas Insider sweepstakes legal states tracker.** Manual scrape weekly, parses into a state matrix.

### Tier three, signal heavy but more effort

8. **Reddit r/sweepstakescasino.** Free via the Reddit API for top posts and hot threads. Use as a sentiment signal, not a fact source.

9. **Trustpilot review delta for top five operators.** Free public pages, scrape daily, look for week over week sentiment change.

10. **X (Twitter) monitoring for operator handles.** Paid API or use a third party listener. Defer to phase two.

### Tier four, paid and high cost, defer until proven need

11. **Sensor Tower or data.ai (App Annie).** App store rank data. Entry plans around $500 per month list price but median buyer pays $74,000 per year. Too expensive for current stage. Defer. Source, g2.com/products/sensor-tower/competitors.

12. **AppMagic.** Cheaper alternative at $400 to $10K depending on tier. Worth evaluating once the rest is shipped.

## Deployment plan, local POC to AWS production

Three deployment paths, ECS Fargate is the winner.

| Option | Description | Verdict |
|---|---|---|
| Vertex AI Agent Engine | Google managed runtime, sub second cold starts, autoscaling, session and memory management. $0.0864 per vCPU hour, $0.0090 per GB hour. Free tier 50 vCPU hours and 100 GB hours per month | GCP lock in, our infra is AWS, defer |
| AWS Lambda | Documented community pattern, low ops | State handoff between agents breaks, cold starts compound on LLM latency, 15 minute hard timeout, defer |
| AWS Bedrock AgentCore | Native AWS, explicitly supports ADK as a framework, consumption pricing only on active CPU and memory | Newer product, less proven, watch |
| **ECS Fargate** | Documented community pattern, runs the same `adk api_server` FastAPI container Cloud Run runs, single VPC alongside existing FastAPI plus Postgres plus Mandrill | **Choose this** |

Source, dev.to/gde/multi-agent-a2a-with-the-agent-development-kitadk-amazon-fargate-and-gemini-cli, aws.amazon.com/bedrock/agentcore/faqs.

The path to production.

```
EventBridge Scheduler (daily 6:30 ET cron)
        |
        v
   SQS queue
        |
        v
Existing Celery worker reads queue, calls ADK service over HTTP
        |
        v
ECS Fargate task, container running adk api_server
        |
        v
LiteLLM proxy sidecar
        |
        +--> Gemini paid tier
        +--> Claude (Anthropic API)
        +--> Ollama (only for local dev)
        |
        v
DatabaseSessionService backed by existing Postgres (separate schema)
        |
        v
Brief markdown returned to Celery, rendered to HTML, sent via Mandrill
```

Critical AWS pieces.

- **EventBridge Scheduler not Celery Beat.** Confidence, high. EventBridge gives retries and dead letter queues. Celery Beat does not.
- **AWS Secrets Manager.** Move ANTHROPIC_API_KEY, GOOGLE_API_KEY, LegiScan key, Open States key, Tavily key out of `.env` and into Secrets Manager. Reference from ECS task definition `secrets` block. One secret per provider so IAM scoping stays clean.
- **OpenTelemetry to CloudWatch via AWS Distro for OpenTelemetry sidecar.** ADK 1.17+ emits OpenTelemetry GenAI spans natively. ADOT forwards them to CloudWatch and X Ray. We see prompts, responses, tool calls, latencies, in one view.
- **Bitbucket Pipelines for CI.** Already in place for the main repo. Add a workflow that builds the container, pushes to ECR, and triggers an ECS service update on the dev branch.

For the local POC we keep what we have today, `python run.py preview`. Switching to ECS Fargate is a deployment concern only.

## Anti hallucination and quality controls

Five additions to our current verifier. Confidence on every item, high.

1. **Move every sub agent output to Pydantic schema enforced JSON.** Define `BriefSection` with title, claim, reasoning, evidence_url, evidence_quote, confidence float, recommended_action_flag. Use response schema on Gemini. Force tool use on Claude. Add a tenacity retry of up to three attempts that feeds Pydantic validation errors back to the model. Source, ai.pydantic.dev plus medium.com structured output comparison.

2. **Add a deterministic NLI based fact check stage.** Decompose the draft into atomic claims. For each claim, refetch the cited URL body, run a small NLI model to label Entail, Neutral, or Contradict. Drop the claim or downgrade confidence if not entailed. The current single LLM call verifier is itself prone to hallucination. NLI per claim is documented state of the art for citation accuracy. Source, arxiv.org/html/2510.24476v1.

3. **Add a Gap Analyst sub agent between research and editor.** Reads the three researcher outputs, identifies missing angles or unsupported claims, and either triggers another research round or marks the gaps for the editor. This is the single biggest lever to deepen brief insights without changing models. Maps to the generate, reflect, regenerate pattern documented across deep research products.

4. **Wrap the editor plus verifier in a LoopAgent with max_iterations=3.** Verifier calls `exit_loop` when every claim has a source citation and confidence is above a threshold. Refiner rereads flagged claims and improves them. Today the verifier flags but does not act. A bounded refinement loop is the canonical ADK pattern for higher quality output. Source, adk.dev/agents/workflow-agents/loop-agents.

5. **Build a golden eval set of 20 historical sweepstakes intel queries with known correct facts.** Score with a 5 axis LLM as judge for factual accuracy, citation accuracy, completeness, source quality, and tool efficiency. Run on every PR that touches `agents.py` or prompts. Anthropic recommends starting eval with about twenty queries rather than waiting for a perfect dataset. Source, anthropic.com/engineering/multi-agent-research-system.

Bonus, register three plugins on the Runner: Reflect and Retry for tool flakiness, AutoTracingPlugin for OpenTelemetry, and a custom Global Instruction plugin holding the voice rules. Centralizing voice rules in one Global Instruction kills the copy paste in every sub agent and means we change them once when stakeholders ask.

## Cost modeling

A daily brief at our volume is cheap. Real numbers based on roughly 100k input tokens and 20k output tokens per brief.

| Provider, model | Per brief | Per month (30 briefs) | Per year |
|---|---|---|---|
| Gemini 2.5 Pro paid | $0.40 | $12 | $144 |
| Gemini 2.5 Flash paid | $0.04 | $1.20 | $14 |
| Claude Sonnet 4 | $0.50 | $15 | $180 |
| Claude Haiku 4.5 | $0.05 | $1.50 | $18 |
| Claude Opus 4 | $2.50 | $75 | $900 |
| Ollama on existing Mac | $0 | $0 | $0 |
| OpenAI GPT-4o | $0.30 | $9 | $108 |

Add to these.

- Anthropic Batch API gives fifty percent off and stacks with prompt caching for up to ninety five percent combined.
- Gemini implicit caching auto on for paid 2.5 models gives ninety percent off repeated context.
- Search tools: Tavily $0.60 per month, Exa $0.20, LegiScan free at our volume, Open States free, CourtListener free.
- AWS infra: ECS Fargate at 0.5 vCPU and 1 GB for roughly fifteen minutes per day is about $1.50 per month. EventBridge free. Secrets Manager $1.20 per month total. CloudWatch logs about $1 per month.

Realistic monthly total at production scale: $20 to $30. Source, tldl.io/resources/llm-api-pricing-2026, ai.google.dev/gemini-api/docs/pricing, anthropic.com/pricing.

## Roadmap, week by week for the next six weeks

### Week 1, fix the bleeding, ship one polished brief

Goal. Move off free tier and produce one stakeholder ready brief.

- Add credit card to Google Cloud project. Verify Gemini 2.5 Flash paid tier works.
- Switch the three research sub agents from SequentialAgent to ParallelAgent inside the outer SequentialAgent. Three distinct output_key values so the editor reads each cleanly.
- Add OpenTelemetry instrumentation. `openinference-instrumentation-google-adk` plus `GoogleADKInstrumentor().instrument()` at startup. Local export to Phoenix or to CloudWatch.
- Lock the Ollama path to use `ollama_chat/` prefix. Assert at module load time.
- Pin `google-adk==2.3.0` and `gemini-2.5-flash` model id everywhere.

Files touched. `agents.py`, `run.py`, `config.py`, `requirements.txt`. No new files.

End of week. `python run.py preview` produces a brief good enough to send to Tyler.

### Week 2, deepen insights

Goal. Make the brief noticeably better than week one.

- Add the Gap Analyst sub agent between research and editor. New file `agents/gap_analyst.py`.
- Wrap editor plus verifier in a LoopAgent with max_iterations=3. Verifier calls `exit_loop` when confidence threshold met.
- Move all sub agent outputs to Pydantic schemas. New file `schemas.py` defining `BriefSection`, `ResearchFinding`, `VerificationResult`.
- Replace the verifier free text output with structured JSON.

Files touched. `agents.py`, new `schemas.py`, `verify.py` is renamed and rewritten.

End of week. Brief has deeper insights, citations are uniformly attached, voice is uniform.

### Week 3, source layer

Goal. Replace ad hoc web search with structured primary sources.

- Register for free LegiScan API key, free Open States API key.
- Wire CourtListener RECAP webhook delivery to a new FastAPI endpoint inside `luckyhands_backend`. Sweepstakes keyword set.
- Build per state AG press release scraper registry. Start with NY, TN, MN, CA. Add as we go.
- New module `sources/` with `legiscan.py`, `openstates.py`, `courtlistener.py`, `ag_scrapers/`. Each returns a list of `ResearchFinding` Pydantic models.
- Research agents consume from `sources/` before falling back to web search.

End of week. Brief draws from authoritative sources first, web search only fills gaps.

### Week 4, deployment to AWS production

Goal. Run the pipeline on AWS Fargate every morning at 6:30 ET.

- Containerize. `Dockerfile` with `adk api_server` entry, LiteLLM proxy as sidecar.
- Build ECR repo, push image, ECS task definition with both containers in one task.
- ECS service behind internal ALB inside existing VPC.
- EventBridge Scheduler rule, daily at 6:30 ET, sends to SQS.
- Add Celery task in `luckyhands_backend` that reads the SQS message, calls the ADK service, renders to HTML, sends via Mandrill.
- Move all keys to AWS Secrets Manager.
- Wire OpenTelemetry to CloudWatch via ADOT sidecar.
- Bitbucket pipeline that builds and deploys on dev branch push.

End of week. First production brief lands in `daniel@luckyhands.com` inbox the morning after deploy.

### Week 5, anti hallucination and quality

Goal. Stop trusting any single agent.

- Build the NLI claim check stage. Use a small NLI model (likely `bge-reranker` or `cross-encoder/nli-deberta-v3-base`) running in the same Fargate task. Decompose draft to atomic claims, recheck each.
- Build a golden eval set of 20 historical sweepstakes intel queries with known correct facts.
- Add an LLM as judge scorer on the 5 axis rubric. Run on every PR.
- Set up CI gate that blocks merges if any score drops by more than ten percent versus the last green main.

End of week. We can prove the brief is getting better, not just different.

### Week 6, stakeholder rollout

Goal. Six person stakeholder list, automatic daily send.

- Build subscription table in Postgres. Email, name, role, topic weights, send time, opt out flag.
- Add unsubscribe handling.
- Daniel reviews each brief for two weeks before any go to the wider list.
- Once edit rate is reliably under one substantive change per brief, flip the autonomous send flag.
- Brief lands in five to seven stakeholder inboxes every weekday at 6:30 ET.

End of week six. Stakeholders receive Intel Daily every weekday.

## Detailed findings appendix

The eight research streams produced 113 findings and 92 recommendations. Top three verified items per stream below. Confidence rating in brackets reflects the adversarial verifier output.

### ADK core architecture

- `[CRITICAL, high confidence]` Pin `google-adk==2.3.0` and explicitly set `model="gemini-2.5-flash"` on every LlmAgent. The default model changed in 2.2.0 ahead of the 2026-10-16 gemini-2.5-flash shutdown. Drifting on defaults will silently change behavior and price. Source, github.com/google/adk-python/releases.
- `[HIGH, high confidence]` Replace InMemorySessionService with DatabaseSessionService pointed at our existing AWS Postgres in a separate schema. Reuses existing infrastructure, gives replay debugging and resume on failure for free since the Runner already supports it. Source, adk.dev/sessions/state.
- `[HIGH, medium confidence]` Register three plugins on the Runner: Reflect and Retry for tool flakiness, AutoTracingPlugin for OpenTelemetry, custom Global Instruction plugin for voice rules. Plugins are global Runner level and run before agent callbacks. Source, adk.dev/plugins.

### ADK tool ecosystem

- `[CRITICAL, medium confidence]` Replace DuckDuckGo and custom fetch_url with McpToolset entries for Tavily, Exa, and Firecrawl. Same tool stack runs on Gemini, Claude, and Ollama. Source, adk.dev/tools-custom/mcp-tools.
- `[HIGH, high confidence]` Convert SequentialAgent chain to ParallelAgent for the three research lanes, then SequentialAgent for editor and verifier on top. Three research lanes have no data dependency. Source, adk.dev/agents/workflow-agents/parallel-agents.
- `[HIGH, high confidence]` Wrap each model call in retry policy. Exponential backoff with jitter on 429, automatic fallback to the next model in priority list. ADK builtin 429 handling is acknowledged fragile. Source, adk.dev/runtime/error-handling.

### ADK model support

- `[CRITICAL, high confidence]` Stand up a LiteLLM Proxy as a sidecar in AWS deployment with fallback chain. Primary Gemini 2.5 Flash on Vertex AI for routing and research, secondary Claude Haiku 4.5, tertiary Claude Sonnet 4 for editor only. Source, devopsboys.com/blog/llm-gateway-litellm-multi-provider-routing-production-2026.
- `[HIGH, high confidence]` Audit Ollama backend for the `ollama` vs `ollama_chat` prefix. ADK docs explicitly warn that `ollama` prefix causes infinite tool call loops and context loss. Source, adk.dev/agents/models/ollama.
- `[HIGH, high confidence]` Refactor each sub agent constructor to accept its own model parameter and load from a YAML or env keyed per stage (regulatory_model, competitor_model, market_model, editor_model, verifier_model). Per agent model selection is the biggest quality lever in a multi agent pipeline. Source, adk.dev/agents/workflow-agents/sequential-agents.

### ADK deployment paths

- `[CRITICAL, high confidence]` Target ECS Fargate as production runtime. Build POC as a single container exposing `adk api_server`, push to ECR, run as one ECS service behind internal ALB inside existing VPC. Source, dev.to/gde/multi-agent-a2a-adk-amazon-fargate.
- `[CRITICAL, high confidence]` Trigger daily run with EventBridge Scheduler hitting SQS that existing Celery worker consumes. EventBridge gives retries and dead letter queues, Celery Beat does not.
- `[HIGH, high confidence]` Move all keys to AWS Secrets Manager. Reference from ECS task definition `secrets` block. One secret per provider for IAM scoping.

### Newsletter and daily brief patterns

- `[CRITICAL, high confidence]` Refactor SequentialAgent into orchestrator with parallel research fanout, critic loop, citation pass, and final editor. Anthropic reports ninety percent improvement over single agent baseline. Source, anthropic.com/engineering/multi-agent-research-system.
- `[CRITICAL, high confidence]` Move editor and verifier outputs to Pydantic schema enforced JSON. Define BriefSection with title, claim, reasoning, evidence_url, evidence_quote, confidence float, recommended_action_flag. Source, ai.pydantic.dev.
- `[CRITICAL, high confidence]` Add a deterministic NLI based fact check stage. Decompose draft to atomic claims, for each claim fetch cited URL body, run small NLI model to label Entail Neutral Contradict. Source, arxiv.org/html/2510.24476v1.

### Sweepstakes industry data sources

- `[CRITICAL, high confidence]` Add billing card to Gemini API project today to move from Free to Tier 1. Direct fix for today blocker. No code changes.
- `[CRITICAL, high confidence]` Refactor research sub agents from web search first to RSS first. Add feedparser based ingestion job that polls seven RSS feeds. Makes system reproducible, kills dependency on flaky search grounding, cuts token cost by an order of magnitude.
- `[HIGH, high confidence]` Register for free LegiScan API key and free Open States API key. Add regulatory ingestion job that runs daily on the keyword set sweepstakes, dual currency, sweeps coins, social casino. Source, legiscan.com/legiscan and docs.openstates.org/api-v3.

### Production LLM pipeline concerns

- `[CRITICAL, high confidence]` Replace dual backend split with single LiteLLM proxy in front of Gemini, Claude, and Ollama. Solves immediate free tier quota failure, gives one observability surface for every model call. Removes dual backend branching code.
- `[CRITICAL, high confidence]` Move off Gemini free tier to paid tier. Implicit caching gives a ninety percent discount on the static system prompt and keeps daily cost under fifteen dollars.
- `[HIGH, high confidence]` Add a fourth sub agent between research and editor called the gap analyst. Reads three researcher outputs, identifies missing angles or unsupported claims, triggers another research round if needed.

### ADK vs alternatives

- `[CRITICAL, high confidence]` Put a credit card on the Google Cloud project today and bump Gemini to paid tier as same day mitigation, regardless of framework choice. Our quota error is a paid tier problem, not a framework problem.
- `[HIGH, medium confidence]` Stand up an evaluation branch that runs the brief end to end on Claude Agent SDK with native web_search and subagents. Compare brief quality side by side against current ADK output. Claude Agent SDK has lowest operational complexity (native web_search, subagents, sessions, no separate search key).
- `[MEDIUM, high confidence]` Defer LangGraph until we add durable state, human in the loop approvals, or multi day analyst workflows. Document as upgrade path in production repo. LangGraph is strongest production framework but overkill for five minute daily cron.

## Next action right now

Tell me whether you want me to start Week 1, which is. Add billing to your Google Cloud project, then update `agents.py` to switch the three researchers to ParallelAgent, then add OpenTelemetry. About two hours of work for me, gives you a noticeably better brief by end of day tomorrow.
