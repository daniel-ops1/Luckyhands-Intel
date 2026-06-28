# Daily Slack Brief, Local Setup Walkthrough

End to end guide to get the intel brief running every morning on your Mac, posting to a Slack channel, no browser pop, with the best local model you can run on this machine.

Total time, about 25 minutes, most of which is downloading the model.

## What this gives you

Every morning at 6:30 am ET (configurable), your Mac wakes the daily job. The job runs the three research subagents, the editor, the verifier, and posts the finished brief to a Slack channel. No browser opens. No interaction needed. A log entry lands in `logs/daily.log` so you can see what happened.

If the laptop is asleep at 6:30 am, the job runs the next time the laptop is awake. If you want guaranteed delivery even when the laptop is asleep, see the AWS production migration in TECHNICAL_DOCUMENTATION.md.

## Prerequisites

1. Mac with at least 16 GB RAM (you have 24 GB on M5 Pro, plenty).
2. Homebrew installed.
3. Python 3.11 or higher.
4. A Slack workspace where you can create an incoming webhook.

## Step 1, install Ollama and pull the best model your Mac can run

```
brew install ollama
brew services start ollama
```

You have 24 GB RAM so the best model that fits comfortably is `gpt-oss:20b`, OpenAI open weight, around 13 GB on disk, top tier tool calling.

```
ollama pull gpt-oss:20b
```

The download takes 5 to 10 minutes depending on your connection. I started this pull for you already.

Smaller fallback if you want faster runs and slightly lower quality, `qwen2.5:14b` at 9 GB which is already pulled.

## Step 2, create the custom Ollama model with bigger context window

Ollama defaults to 2K context which truncates the editor input. We need 16K.

```
cat > /tmp/Modelfile.intel << 'EOF'
FROM gpt-oss:20b
PARAMETER num_ctx 16384
EOF

ollama create qwen-intel -f /tmp/Modelfile.intel
```

(I'm keeping the model name `qwen-intel` so all existing config keeps working. The name is just a label, the underlying model is now gpt-oss:20b.)

If you prefer to keep using qwen2.5:14b instead, change `FROM gpt-oss:20b` to `FROM qwen2.5:14b` and rerun.

## Step 3, set up the Python virtual environment

```
cd ~/intel_daily
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Step 4, create the Slack incoming webhook

1. Visit https://api.slack.com/apps in a browser.
2. Click `Create New App`, pick `From scratch`, name it `LuckyHands Intel Daily`, select your workspace, click Create.
3. On the app page, click `Incoming Webhooks` in the left sidebar, toggle it on.
4. Click `Add New Webhook to Workspace`, pick the channel you want the brief to land in (recommend `#intel_daily`), click Allow.
5. Copy the webhook URL Slack gives you. It looks like `https://hooks.slack.com/services/T01234567/B01234567/abcdef...`.

## Step 5, fill in .env

```
cd ~/intel_daily
cp .env.example .env
```

Edit `.env` and set these values.

```
LLM_BACKEND=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_RESEARCHER_MODEL=qwen-intel
OLLAMA_EDITOR_MODEL=qwen-intel

SLACK_WEBHOOK_URL=https://hooks.slack.com/services/T01234567/B01234567/your_real_webhook_here
SLACK_USERNAME=LuckyHands Intel Daily
SLACK_ICON_EMOJI=:newspaper:

LOOKBACK_WINDOW=past 7 days
```

Everything else can stay as default.

## Step 6, optional but recommended, get a Brave Search API key

This eliminates the rare DuckDuckGo anomaly errors entirely. Free, 2000 queries per month is plenty for a daily brief which uses about 18 queries per run.

1. Go to https://api.search.brave.com/.
2. Sign up with your email, no credit card needed.
3. Create a subscription, pick `Free AI` plan.
4. Copy the API key they give you.
5. In `.env`, add:

```
BRAVE_API_KEY=your_brave_key_here
```

The code already tries Brave first if the key is set, with DDG as fallback. So you get the best of both, no URL errors and the free tier never runs out.

## Step 7, smoke test the Slack webhook before running the full pipeline

```
cd ~/intel_daily
source .venv/bin/activate
python -c "from slack import post_to_slack; ok, detail = post_to_slack('# Test\n\n## Top story\nThis is a smoke test.\n\n## Footer\nIgnore this message.', 'Setup test', issue='test'); print(ok, detail)"
```

You should see `True ok` in the terminal and a test message in your Slack channel. If you see `False SLACK_WEBHOOK_URL not set`, double check `.env`. If you see `False Slack returned 404`, the webhook URL is wrong.

## Step 8, do one manual full pipeline run to verify everything works

```
cd ~/intel_daily
source .venv/bin/activate
python run.py slack
```

This takes 8 to 14 minutes the first run (model needs to load into RAM). You can watch progress with `tail -f logs/daily.log` in another terminal (or just look at the console output).

At the end, the brief lands in your Slack channel. The HTML version is saved to `output/brief_<date>.html` for audit but no browser opens.

If anything fails, the error is printed and logged. Common ones.

- `Ollama not reachable` → run `brew services start ollama`
- `Slack returned 400` → check the webhook URL in `.env`
- `Search failed` → temporary DDG hiccup, run again, or set `BRAVE_API_KEY` as in Step 6

## Step 9, install the daily schedule

You have two options. launchd is the Mac native scheduler and is preferred over cron.

### Option A, launchd (recommended)

```
cp ~/intel_daily/scripts/com.luckyhands.intel_daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.luckyhands.intel_daily.plist
```

Verify it loaded.

```
launchctl list | grep intel_daily
```

You should see `com.luckyhands.intel_daily`. The job will fire daily at 6:30 am local time.

To change the time, edit `~/Library/LaunchAgents/com.luckyhands.intel_daily.plist`, change the Hour and Minute values, then reload.

```
launchctl unload ~/Library/LaunchAgents/com.luckyhands.intel_daily.plist
launchctl load ~/Library/LaunchAgents/com.luckyhands.intel_daily.plist
```

To test the schedule by triggering it manually right now.

```
launchctl start com.luckyhands.intel_daily
```

Then watch `tail -f ~/intel_daily/logs/daily.log` to see the run.

To stop receiving daily briefs.

```
launchctl unload ~/Library/LaunchAgents/com.luckyhands.intel_daily.plist
```

### Option B, cron (if you prefer)

```
crontab -e
```

Add this line.

```
30 6 * * * /Users/ritzmish/intel_daily/scripts/run_daily.sh
```

Save and exit. The launcher script handles environment activation.

## How to monitor

```
tail -50 ~/intel_daily/logs/daily.log
```

The log shows every run start, the agent trace, and the publisher result. If the Slack post failed, the log says why.

Old briefs are kept in `~/intel_daily/output/`. The QA notes (verifier output) for each run are in `~/intel_daily/output/qa_<date>.md`.

## What to do if the laptop sleeps

launchd will run the missed job the next time the laptop wakes if the `StartInterval` style is used. With `StartCalendarInterval` (what we use), missed runs are skipped. If your laptop is closed at 6:30 am you will not get a brief that day.

Two fixes.

1. Schedule for a time when the laptop is always awake (e.g. 10 am or 2 pm).
2. Use `caffeinate` or pmset to keep the Mac awake at 6:30 am, e.g. `sudo pmset repeat wake MTWRF 06:25:00`.
3. Move to AWS for guaranteed delivery, plan documented in TECHNICAL_DOCUMENTATION.md.

## Costs at this setup

Zero. LLM runs on your Mac, search is free, Slack delivery is free.

Energy. The 14 minute pipeline run uses roughly 30 to 50 watt minutes of energy, the cost of running a laptop fan for 14 minutes. Negligible.
