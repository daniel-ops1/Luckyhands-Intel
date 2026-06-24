# LuckyHands Intel Daily, POC

A multi agent sweepstakes intel newsletter built on Google ADK. Three sequential research agents do live web research (regulatory and legal, competitor moves, market signals). An editor agent assembles the brief in our fixed template. A verifier agent fact checks the brief against the research output. Output renders to HTML and either opens in your browser or sends to a stakeholder over SMTP.

Two LLM backends supported.

**Ollama** for fully local testing, no keys, no quota. Uses DuckDuckGo as the search tool.

**Google Gemini** for production quality. Uses native Google Search grounding via the Gemini API.

## Setup, Ollama path (recommended for local testing)

1. Install Python deps in a venv.

```
cd /Users/ritzmish/intel_daily
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Install Ollama. Download the Mac app from https://ollama.com and run it. It also starts a local server at http://localhost:11434.

3. Pull a model. qwen2.5:7b is a good balance of size and reasoning for this task. About 4.7 GB download.

```
ollama pull qwen2.5:7b
```

If your Mac has 32 GB or more of RAM you can try qwen2.5:14b for better synthesis, or llama3.1:70b if you have an M3 Max or better.

4. Copy and edit .env.

```
cp .env.example .env
```

Defaults are already set for Ollama, you do not need to change anything if you used qwen2.5:7b.

5. Run.

```
python run.py preview
```

## Setup, Gemini path

1. Same Python steps as above.

2. Get a free API key at https://aistudio.google.com/apikey.

3. In .env.

```
LLM_BACKEND=gemini
GOOGLE_API_KEY=AQ...your key
```

4. Run.

```
python run.py preview
```

Note. Free tier is 20 requests per day per project per model. The pipeline uses 10 to 20 calls per run, so you get one or two free runs per day per model. Enable billing on the Google Cloud project for unlimited use, about 5 to 15 cents per run on Flash.

## Run

### Option 1, the Google ADK web UI (recommended for interactive testing)

This launches Google ADK's built in web UI. You get a chat interface, live agent trace, full visibility into every tool call, model call, and state mutation. When the verifier finishes, a publisher callback automatically renders the brief to HTML and opens it in your browser.

```
cd /Users/ritzmish/intel_daily
source .venv/bin/activate
adk web adk_agents
```

Then open http://localhost:8000 in a browser. Select `intel_brief` from the agent picker. Type any prompt like `Generate today brief` and hit send. Watch the pipeline run live. The styled HTML brief opens automatically when verifier finishes.

### Option 2, the CLI runner

For non interactive runs, scheduled jobs, or sending email.

```
python run.py build     # run agents, write HTML to ./output, no browser, no email
python run.py preview   # run agents, write HTML, open in browser
python run.py send      # run agents, write HTML, send email to RECIPIENT_EMAIL
```

A run takes 30 to 90 seconds on Gemini, or 2 to 6 minutes on Ollama depending on model size and Mac specs.

## What is in the box

config.py. API keys, model selection, backend switch.
agents.py. The ADK pipeline. Three sequential researchers, then editor, then verifier. Models and tools swap based on LLM_BACKEND.
tools.py. Custom search and fetch tools used when LLM_BACKEND=ollama.
run.py. Entry point. Runs pipeline async, pulls final state, renders, optionally sends.
render.py. Markdown to HTML with badges for ACTION, WATCH, WARNING.
send.py. SMTP send.
template.html. Email body template.

## The agent architecture

```
newsletter_pipeline (SequentialAgent)
|
+-- research_team (SequentialAgent)
|   |
|   +-- regulatory_researcher  LLM + search tool
|   +-- competitor_researcher  LLM + search tool
|   +-- market_researcher      LLM + search tool
|
+-- editor                     LLM, synthesizes the three streams
|
+-- verifier                   LLM, internal QA only
```

On the Ollama path, search tool is DuckDuckGo HTML plus a follow up fetch_url tool for reading full article bodies. On the Gemini path, search tool is the native google_search grounding built into the Gemini API.

## Output

For every run.

```
./output/brief_<date>.html   the rendered brief, what stakeholders see
./output/qa_<date>.md        internal QA, including the verification pass
```

The QA file stays local. Only the brief HTML gets sent or opened.

## What this POC does not do yet

Stakeholder subscription list, POC sends to one recipient.
Postgres archive, POC writes to disk only.
LegiScan integration for primary state bill text.
Slack delivery in addition to email.

These are in scope for production. See INTEL_EXECUTION_PLAN.md in the luckyhands repo.
