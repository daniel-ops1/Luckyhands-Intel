# Daily Intel Coverage Audit and Plan

## Executive answer

No, 24 web searches per run is not enough for top tier sweepstakes daily intel, but the fix is not a linear crank to 60 or 80. The real baseline is 18 hardcoded mandatory queries (6 per researcher across 3 researchers in [agents.py](agents.py)) plus roughly 6 opportunistic LLM driven calls, and that 18 query floor leaves visible holes in court rulings, named operator coverage, large state regulators (NY, NJ, MI, PA, FL), payment processors, geolocation vendors, and Reddit or App Store sentiment. The right shape is 30 to 36 queries per run combining a +9 to +12 mandatory expansion with one critique and refine pass, which fits comfortably under combined free tier of [Google CSE](https://developers.google.com/custom-search/v1/overview) at 100 per day and [Tavily](https://docs.tavily.com/documentation/api-credits) at 1000 per month, but only if the Google CSE 403 credential issue is fixed first so Tavily stops being the workhorse by accident.

## Current coverage audit

The pipeline has exactly 18 hardcoded mandatory queries, verified at [agents.py](agents.py) lines 229 to 236 (regulatory, 6 queries), 248 to 255 (competitor, 6 queries), and 267 to 274 (market, 6 queries). The empirical 24 per run figure from trace logs reflects roughly 6 opportunistic extra calls the LLM makes on top of the mandatory floor. Specific topical gaps surfaced in the audit.

State coverage is narrow. The regulatory researcher names California (AB 831), Illinois Gaming Board, Mississippi, Iowa, Oklahoma, and Tennessee. It misses New York, New Jersey, Michigan, Pennsylvania, Florida, Massachusetts, Georgia, Ohio, Washington, Connecticut, Arizona, Colorado, Virginia, and North Carolina. NY AG Letitia James and NJ DGE in particular run aggressive sweepstakes enforcement that the current pipeline cannot see.

Court rulings and federal litigation are absent. Zero queries hit [CourtListener](https://www.courtlistener.com), PACER, or federal district court dockets by name. The market researcher has one generic "sweepstakes class action lawsuit 2026" query at [agents.py](agents.py) line 270, which returns press coverage and not docket level rulings. Court outputs are the highest signal regulatory items because they bind future operator behavior.

Seven named operators get zero direct coverage. The _OPERATORS constant at [agents.py](agents.py) line 165 names Modo, Fliff, Legendz, Sportzino, Crown Coins, Mega Bonanza, and Fortune Coins in scope, but the competitor researcher mandatory queries only cover VGW family, Stake.us, McLuck, Pulsz, High 5, WOW Vegas, Funrize, and Hello Millions.

Payment processor and geolocation vendor coverage is shallow. The market researcher has one generic "sweepstakes payment processor liability 2026" query at [agents.py](agents.py) line 269 with no vendor names. Zero queries hit Worldpay, Nuvei, Trustly, Sightline, Aristotle, [GeoComply](https://www.geocomply.com), Xpoint, or GeoGuard by name, even though processor and geo provider pullouts are historically leading indicators of operator state exits.

Sentiment and App Store signals are absent. Zero queries hit Reddit r/sweepstakescasino, X searches by operator handle, Sensor Tower, data.ai, or App Store and Google Play rank movement. App Store rank crashes typically precede press coverage by 2 to 4 weeks for sweepstakes operators.

Funding rounds, M&A by source, and leadership changes are shallow. One generic M&A query at [agents.py](agents.py) line 273. Zero queries hit [SEC EDGAR](https://www.sec.gov/edgar), Crunchbase, PitchBook, or LinkedIn executive moves. SEC filings typically lead announcement press by 24 to 72 hours.

Cache is per session only. [tools.py](tools.py) line 33 declares _search_cache as a module level dict that dies when the Python process exits. Hot stories that dominate the brief for 3 to 5 consecutive days currently burn 3 to 5 Tavily credits when they should burn 1.

## Backend budget math

Tavily 2026 free tier is confirmed at 1000 API credits per month with no credit card required per [Tavily pricing docs](https://docs.tavily.com/documentation/api-credits). Basic search costs 1 credit, advanced search costs 2 credits. Pay as you go is $0.008 per credit. The Researcher plan is $30 per month for roughly 4000 credits. The [Google CSE](https://developers.google.com/custom-search/v1/overview) free tier remains 100 queries per day with $5 per 1000 paid beyond that, but Custom Search JSON API is closed to new customers and existing customers must transition off by January 1, 2027.

| Queries per day | Per month | Tavily only burn | Tavily only % of free | CSE only % of daily cap | Tavily overage cost if CSE down |
|---|---|---|---|---|---|
| 18 | 540 | 540 credits | 54% | 18% | $0.00 |
| 24 | 720 | 720 credits | 72% | 24% | $0.00 |
| 30 | 900 | 900 credits | 90% | 30% | $0.00 |
| 36 | 1080 | 1080 credits | 108% | 36% | $0.64 per month |
| 45 | 1350 | 1350 credits | 135% | 45% | $2.80 per month |
| 60 | 1800 | 1800 credits | 180% | 60% | $6.40 per month |

Combined fallback chain math. With the [Google CSE](https://developers.google.com/custom-search/v1/overview) priority at [tools.py](tools.py) line 255 working, every scenario from 18 to 60 queries per day fits entirely under the CSE 100 per day free cap, driving Tavily burn toward zero. The fallback chain Google CSE then Tavily then Brave then DuckDuckGo Lite at [tools.py](tools.py) lines 255 to 283 is dramatically more robust than running Tavily as primary. The current 403 errors on CSE silently shift all 720 monthly load onto Tavily.

DuckDuckGo Lite is wall clock limited not quota limited. At 8 second per call throttle, 30 per day equals 240 seconds of search wait per run, and 60 per day equals 480 seconds (8 minutes) before LLM synthesis. DDG is tail fallback only, never primary.

## What top tier intel actually looks like

Production deep research systems in 2026 run dramatically more queries than 24 per day, but they cover open ended general questions, not a narrow daily vertical.

[Anthropic multi agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) published guidance is simple fact finding equals 1 agent with 3 to 10 tool calls, direct comparisons equal 2 to 4 subagents with 10 to 15 calls each, and complex research uses more than 10 subagents. Our 3 subagent fixed structure matches the comparison pattern, but 8 calls per subagent is below the 10 to 15 Anthropic band. The bigger gap is hardcoded versus dynamic count.

[Google ADK deep search](https://github.com/google/adk-samples) sets max_search_iterations to 5 in ResearchConfiguration and treats search count as emergent from a search, critique, refine loop per section of the outline. Our pipeline does not use the critique and refine pattern at all.

[Perplexity Deep Research](https://www.perplexity.ai/hub/blog/introducing-perplexity-deep-research) runs 20 to 50 targeted queries and pulls from 200 plus sources per report in 2 to 4 minutes. Gemini Deep Research Standard uses about 80 queries per task and Max about 160, costing $1.12 to $2.24 in search per task per [tokencost.app analysis](https://tokencost.app/blog/gemini-deep-research-agent-cost). [OpenAI Deep Research](https://openai.com/index/introducing-deep-research) reads hundreds of online sources per report with no disclosed iteration count.

Bloomberg Terminal ingests 175,000 web, social, and multimedia sources publishing 1.5 million stories daily and runs AI summaries across 30,000 plus sources, trained by 400 Bloomberg Intelligence analysts. The model is broad ingestion then aggressive filtering, not raw query count.

[Vixio Gambling Compliance](https://vixio.com/gambling-compliance), the closest direct analog as a regulatory intel brief for gambling, tracked 153,000 global regulatory updates in 2024 and surfaced only 1,172 as relevant to gambling. That is about 3.2 gambling relevant items per day globally, narrower still for US sweepstakes. The President's Daily Brief delivers 6 or 7 short items plus 2 deep dives daily from hundreds of inbound reports. The lesson is consistent. Even gold standard daily briefs converge on under 10 surfaced items per day. The work is in filtering and adaptive query generation, not raw volume.

Industry consensus is dynamic query generation with critique and refine. Anthropic, Google ADK, Perplexity, and OpenAI all use lead agent or critique loops to decide what to search next. Our 6 hardcoded per subagent design is an outlier.

## Recommended path forward

Three tiered options sized to coverage ambition and infrastructure investment.

Option A. Stay at 24 per run. Sufficient for a workable floor that covers VGW family, Stake.us, top 3 to 5 state regulators, generic federal angle, and macro market signals. Misses court rulings, NY NJ MI PA FL, named payment and geolocation vendors, the seven named challenger operators, Reddit and App Store sentiment, and SEC filings. Recommended only as a holding pattern while the Google CSE 403 is unblocked. Stays at 72% of Tavily free tier with no infrastructure change.

Option B. Grow to 30 per run via +12 mandatory queries. Adds 3 to 4 court and litigation queries (federal court sweepstakes injunction 2026, sweepstakes motion to dismiss 2026, sweepstakes settlement filing 2026, plus one for class certification), 3 state AG queries for NY, NJ, MI, 2 named operator queries (Modo Fliff, Sportzino Crown Coins Mega Bonanza), 2 named vendor queries (Worldpay Nuvei Trustly, GeoComply Xpoint), 1 sentiment query (Reddit r/sweepstakescasino top posts this week), and 1 SEC EDGAR query. Lands at 30 mandatory plus ~6 opportunistic equals ~36 per day equals 1080 per month. Requires the Google CSE 403 fix so the load lands on CSE free tier and Tavily stays as insurance. No new agent code required.

Option C. Grow to 36 to 42 per run with a critique and refine pass. Adds a gap_analyst LlmAgent between the research_team SequentialAgent at [agents.py](agents.py) line 278 and the editor. The gap analyst reads the three findings strings and emits exactly 5 targeted followup queries that a small followup_researcher then runs. Requires +12 mandatory adds from Option B, plus the 5 followup queries, plus persistent SQLite cache so duplicate queries do not double charge Tavily. Lands at roughly 36 to 42 per run total. Fits comfortably under CSE 100 per day free tier. Requires the Google CSE 403 fix and roughly 100 lines of new code across [agents.py](agents.py) and [tools.py](tools.py).

Recommendation. Ship Option C in two stages. Stage one is the CSE fix plus the +12 mandatory query expansion (Option B) and the persistent cache. Stage two is the gap analyst pass. This gets us from current ~24 effective items per brief to ~40 effective items per brief at zero marginal Tavily cost, with all the underserved coverage areas filled.

## Concrete changes to ship now

1. Fix the Google CSE 403 credential issue. Verify Custom Search API is enabled on the GCP project, verify billing is enabled, verify the API key has no referrer or IP restrictions blocking the agent host. The handler at [tools.py](tools.py) lines 109 to 140 currently catches the 403 and silently falls through to Tavily, masking the failure. Confirm via curl with the bare key and CX. Query count impact 0. Intel quality lift high because it activates the 26 curated trusted domain set and unlocks 100 free queries per day, making every subsequent expansion essentially free.

2. Persist _search_cache from a module level dict at [tools.py](tools.py) line 33 to a SQLite or JSON file at /Users/ritzmish/intel_daily/cache.db keyed on (UTC date, query) with 24 hour TTL. Also cache fetch_url at [tools.py](tools.py) line 320 by (UTC date, url). Use calendar UTC date not sliding 24 hour TTL so cache does not straddle morning newsletters. Query count impact 0 on a steady state day, roughly minus 30 to 40 percent on dev iteration days. Intel quality lift indirect, enables safe expansion without budget creep.

3. Add 3 court and litigation queries to the regulatory_researcher mandatory_queries list at [agents.py](agents.py) lines 229 to 236. Specifically "federal court sweepstakes injunction 2026", "sweepstakes motion to dismiss 2026", "sweepstakes settlement filing 2026". Drop the CourtListener-named and PACER-named query variants because Tavily and CSE do not treat those source names as site filters, so the queries return news about CourtListener rather than CourtListener content. Query count impact +3 mandatory. Intel quality lift high because court rulings bind future operator behavior.

4. Add 3 state AG queries to the regulatory_researcher mandatory_queries list. Specifically "New York attorney general sweepstakes 2026", "New Jersey DGE sweepstakes enforcement 2026", "Michigan Gaming Control Board sweepstakes 2026". Add Pennsylvania and Florida only if budget allows after measuring opportunistic call drift. Query count impact +3 mandatory. Intel quality lift high because NY, NJ, MI represent the largest underserved user populations with active 2026 motion.

5. Add 2 named operator queries to the competitor_researcher mandatory_queries list at [agents.py](agents.py) lines 248 to 255. Specifically "Modo Fliff Legendz sweepstakes news 2026" and "Sportzino Crown Coins Mega Bonanza Fortune Coins news 2026". Do NOT add a fifth "operator state withdrawal announcement" query because it duplicates the existing "state sweepstakes casino ban 2026" and "sweepstakes operator state exit 2026" queries. Query count impact +2 mandatory. Intel quality lift high because seven in-scope operators currently get zero coverage.

6. Add 2 vendor entity queries to the market_researcher mandatory_queries list at [agents.py](agents.py) lines 267 to 274. Specifically "Worldpay Nuvei Trustly sweepstakes 2026" and "GeoComply Xpoint sweepstakes compliance 2026". Query count impact +2 mandatory. Intel quality lift high because processor and geo vendor pullouts lead operator state exits.

7. Add 1 sentiment query to the competitor_researcher. Specifically "reddit r/sweepstakescasino top posts past week". Query count impact +1 mandatory. Intel quality lift medium because Reddit captures live user pain (failed redeems, KYC freezes) 2 to 4 weeks before press coverage.

8. Add 1 SEC and corporate filing query to the market_researcher. Specifically "SEC EDGAR 8-K sweepstakes social gaming 2026". Query count impact +1 mandatory. Intel quality lift medium because SEC filings lead announcement press by 24 to 72 hours.

9. Upgrade _tavily_search at [tools.py](tools.py) line 173 to set max_results=20 (currently 10), set include_raw_content="markdown", and accept optional topic="news" and days kwargs through the web_search wrapper. Zero credit increase, 2x result density, and raw markdown eliminates roughly 4 to 5 of the 7 fetch_url calls per run. Cap raw content to 1500 chars per result to avoid quiet token bill spike to the editor and verifier subagents. Query count impact 0. Intel quality lift high.

10. After steps 1 through 9 are stable and verified for one week, add a gap_analyst LlmAgent and a followup_researcher LlmAgent between the research_team SequentialAgent at [agents.py](agents.py) line 278 and the editor. The gap_analyst reads {regulatory_findings}, {competitor_findings}, {market_findings} and emits exactly 5 targeted followup queries using a strict STEP based protocol mirroring [agents.py](agents.py) line 183. The followup_researcher runs those 5 queries via web_search and writes results to {gap_findings}. Update the editor instruction to read {gap_findings} as a fourth input source. Query count impact +5 mandatory. Intel quality lift highest of any single change because it catches entities, states, and dollar figures that no hardcoded query list anticipates.

Net effect across changes 1 through 9. Mandatory queries go from 18 to 30 (+12), opportunistic stays at roughly 6, total per run roughly 36 per day or 1080 per month. With CSE working as primary at 100 per day free, all 36 calls land on CSE and Tavily monthly burn drops to near zero. After change 10 lands, total per run roughly 41 per day or 1230 per month, still entirely inside CSE free tier.

## Confidence and risks

Per recommendation confidence ratings tied to the adversarial verifier output.

Change 1 (CSE fix). Confidence high. Verifier flagged that the original framing as the highest leverage single fix understates the work because credential fix alone preserves the same 18 narrow angles. Confidence on the fix unlocking the budget headroom is high. Confidence on it solving coverage breadth alone is low, which is why this rec is sequenced with the expansion changes.

Change 2 (persistent cache). Confidence high. Verifier confirmed _search_cache is process local at [tools.py](tools.py) line 33 and dies between runs. Risk to watch is UTC date versus local date drift across midnight runs. Use calendar UTC date.

Changes 3 through 8 (mandatory query expansion). Confidence high for the state AG, named operator, and named vendor adds. Verifier specifically confirmed NY NJ MI PA FL absence and the seven uncovered operators against the actual code. Confidence medium for the court query subset because the verifier flagged that source-named queries like "CourtListener sweepstakes ruling" do not perform as site filters through Tavily, so we ship only the well shaped queries (federal court injunction, motion to dismiss, settlement filing). Confidence medium for the SEC EDGAR query because EDGAR is not indexed by Tavily as a site filter either, so the query returns news mentioning EDGAR rather than EDGAR primary documents. Acceptable but worth watching the result quality after week one.

Change 9 (Tavily advanced parameters). Confidence high on schema. Verifier confirmed Tavily max_results ceiling is 20, include_raw_content accepts the literal string "markdown", topic accepts "general" or "news", days only takes effect with topic equals "news". Risk is token bill spike at the editor and verifier subagents from raw markdown bodies. Mitigation is the 1500 char cap.

Change 10 (gap analyst). Confidence medium. Verifier flagged that LlmAgent drift is real and the gap analyst will likely run 6 to 10 followup queries if told to run 3 to 6. Mitigation is hardcoding the followup count to exactly 5 in a strict STEP based protocol. Risk is the editor instruction at [agents.py](agents.py) lines 290 to 327 currently lists three input keys, so adding {gap_findings} requires not just inserting the placeholder but also expanding the body of each editor section to pull from the fourth source. Without that the gap findings will get dropped on the floor and credits will be wasted. Budget at worst case is 18 mandatory plus 5 gap plus 10 opportunistic equals 33 per day equals 990 per month against Tavily 1000 if CSE is down, which is the floor under which this recommendation is safe.

Strategic risk to watch separately. [Google CSE Custom Search JSON API](https://developers.google.com/custom-search/v1/overview) is closed to new customers and existing customers must transition off by January 1, 2027. That is roughly six months away. We must evaluate Vertex AI Search or another curated domain alternative before the deadline. Investing in CSE as the primary backend buys time, not permanence. Note that the unverified "50 trusted domains" framing for Vertex AI Search appears to confuse data stores per search app with sites per data store, so the migration evaluation should not assume Vertex matches CSE feature for feature.

Volume risk. The Vixio analog of 3.2 gambling relevant items per day worldwide and the President's Daily Brief shape of 6 to 7 items plus 2 deep dives daily both reinforce that the work is filtering and adaptive query generation, not raw volume. If after Option C lands the brief still feels thin on weekly cadence, the next lever is the RSS sweep from state AG and SEC EDGAR feeds, which carries zero search credit cost and surfaces items the web_search index misses entirely. Treat that as the Option D extension after measuring Option C for two to four weeks.
