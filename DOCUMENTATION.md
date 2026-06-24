# LuckyHands Intel Daily

A daily AI agent that researches the US sweepstakes industry every morning and posts a brief to a Slack channel. It covers state regulation, attorney general actions, court rulings, what competitors are doing, and broader market signals.

The whole thing runs on a developer laptop today. We will move it onto AWS once the brief quality is where we want it.

## Why we built it

Right now anyone tracking sweepstakes industry news has to do it manually. Someone catches a tweet, someone else forwards an SBC Americas article, leadership keeps asking what we are doing about something that already happened three days ago.

The state regulatory landscape is changing fast. California banned sweepstakes through AB 831 effective January 1, 2026. Illinois sent 65 cease and desist letters in February. Tennessee, Mississippi, Iowa, and Oklahoma all moved in 2026. Missing one of these by 48 hours can become a compliance gap that now reaches our payment processors and geolocation partners, not just operators.

The brief gives stakeholders a single place to look every morning and a record they can search later.

## What stakeholders see

A Slack post around 6:30 am ET every weekday with these sections.

**Top story.** The single most important thing in the last 24 hours, written in plain English with a source link.

**Regulatory and legal.** Three to six items per day, each tagged ACTION or WATCH, each with the state, what happened, why it matters, and a source link.

**Competitor moves.** Three to five items covering named operators like Stake.us, McLuck, Chumba, LuckyLand, Global Poker, Pulsz, High 5, Fortune Coins, Modo, Fliff, Funrize, Legendz, WOW Vegas, Hello Millions, Sportzino, Crown Coins, and Mega Bonanza.

**Market and product signals.** Revenue estimates, GGR, M&A, payment processor exposure, class actions, App Store rank moves.

**On our radar.** Lower confidence items flagged so we can watch them.

Every claim has a source URL. Nothing is invented. The voice is plain English, no apostrophes, no hyphens, so the tone stays consistent.

## How it works, plain English

1. The agent wakes up daily.
2. Three research subagents run in sequence, one for regulation, one for competitors, one for market signals.
3. Each subagent runs six targeted web searches and reads the most promising articles in full.
4. An editor subagent reads all three streams and writes the brief in our fixed template.
5. A verifier subagent fact checks the brief against the research, flagging anything not supported by a source.
6. A publisher step posts the brief into a Slack channel.

The whole pipeline runs roughly 13 minutes today on a developer laptop with a local LLM. On AWS with a paid LLM it will run closer to 60 to 90 seconds.

## Where the brief goes

Slack, into a dedicated channel like #intel_daily. The brief uses Slack Block Kit so headings, source links, and ACTION or WATCH tags render cleanly inside Slack. Email delivery is built but is Phase 2 since Slack is faster, free, and stakeholders read it more reliably.

## What it costs

Today it costs nothing in API fees because the LLM runs locally on the developer machine via Ollama. When we move it to AWS the cost is roughly 25 dollars per month for compute and search. If we swap the local model for paid Gemini Flash or Claude Haiku in production the cost rises to around 50 dollars per month total. All in cheap.

## Status today

What works.

The full pipeline runs end to end. Three researchers each run six web searches and read articles. The editor writes the brief in our template. The verifier fact checks. The publisher renders to HTML and posts to Slack. Roughly 24 web searches and 7 article fetches per run, around 13 cited sources in the final brief. All claims have real source URLs from authoritative places like state .gov pages, casinos.com, mlive.com, playpennsylvania.com, casinoindustrynews.com.

What is left before we ship daily delivery to a wider stakeholder list.

1. Tweak the editor so the competitor section has more bullets and is not over compressed.
2. Add a small URL post check that catches the rare case where the editor cites the wrong link.
3. Move the daily cron from a developer laptop to an AWS scheduled task so we are not relying on someone leaving their laptop open.

Once those are done the daily Slack drop is fully autonomous and we can expand to the broader stakeholder list.

## Sample of what landed in Slack from yesterday run

> **LuckyHands Intel Daily, June 24, 2026**
>
> **Top story**
> Over 100 class action lawsuits have been filed against sweepstakes casino operators, with Virtual Gaming Worlds (VGW) the parent company behind Chumba Casino, LuckyLand Slots, and Global Poker facing the most legal pressure in 2026. Verify with counsel before acting on any item in this section.
>
> **Regulatory and legal**
> ACTION IL. The Illinois Gaming Board has issued over 60 cease and desist letters to entities operating illegal online sweepstakes gaming platforms, including VGW Chumba Casino and Global Poker.
> ACTION TN. Tennessee has sent formal cease and desist letters to nearly 40 sweepstakes casinos, joining other states taking action against such businesses.
> ACTION KY. Kentucky Attorney General filed a civil enforcement action against VGW, alleging illegal operations of Chumba Casino, Global Poker, and LuckyLand Slots under gambling loss recovery laws and consumer protection statutes.
> ACTION MD. Maryland legislators refiled a sweepstakes casino ban targeting VGW platforms Chumba Casino and LuckyLand Slots, effective July 1 if passed.
> WATCH CA. California AB 831 extends liability to payment processors, financial institutions, geolocation providers, and media affiliates supporting sweepstakes casinos.
>
> **Competitor moves**
> Virtual Gaming Worlds (VGW) has exited at least twelve US states and launched new brands like LuckyLand Casino and Just Slots in response to legal pressures.
> VGW entered a multi year partnership with WWE starting in 2026 to bring their sweepstakes platforms to SmackDown and WrestleMania.
>
> **Market and product signals**
> Sweepstakes market revenue is projected to fall to 3.6 billion dollars in 2026 due to accelerating state bans.
> Social casino revenue is expected to top 10 billion dollars in 2026 as freemium models gain popularity.
> Sweepstakes software companies are experiencing moderate M&A activity, with acquisitions aimed at strengthening market share and expanding offerings.

That is what the pipeline produced from one fresh run, with real URLs we can click through.

## Questions for stakeholders

1. Which Slack channel should the brief land in?
2. Who should be in the recipient set for the email delivery once we ship that too?
3. Are there specific operators or topics we should add to the daily research focus?
4. Is the 6:30 am ET drop time right or do you want it earlier?

Reply in the thread with answers and we will tune accordingly.
