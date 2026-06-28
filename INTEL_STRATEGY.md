# Intel Strategy

## Direct answers to the three user questions

### 1. How many websites are we hitting now (with Tavily + Exa)

We are effectively hitting one search index. Tavily carries 100 percent of search load because the priority chain in tools.py falls through to Exa only when Tavily returns an empty result list, which almost never happens. At 24 web_search calls per run that is roughly 720 Tavily credits per month against the 1000 credit free monthly cap (about 72 percent utilization), and Exa receives essentially zero traffic. Each Tavily call returns up to 10 URLs and each fetch_url call hits exactly one URL via Jina Reader. So per run we touch up to 240 Tavily indexed URLs and up to roughly 9 fetched pages, but only one search engine is doing the work.

### 2. Are we splitting work between Tavily and Exa or one bears all load

One bears all the load. Tavily handles every query and Exa is dead weight. The $10 Exa signup credit sits unused and we lose Exa neural semantic ranking on the entity and concept queries where it actually beats Tavily. Worse, a single bad day with retries could exhaust the Tavily monthly free tier and silently drop us to DuckDuckGo Lite which is the lowest quality fallback in the chain. The fix is to route by query intent rather than primary and fallback, sending fresh news queries to Tavily with topic equal to news and named entity plus semantic queries to Exa, with the other engine as a real fallback on weak results.

### 3. Will we get top tier coverage across all 50 US states

Not today. The 18 hardcoded mandatory queries name only 6 states (California, Illinois, Mississippi, Iowa, Oklahoma, Tennessee). The other 44 states only get caught when a Tavily generic query happens to surface them, which means high signal active enforcement states like New York, New Jersey, Michigan, Pennsylvania, Florida, Maryland, Louisiana, Maine, Indiana, and Connecticut are structurally underserved. True top tier 50 state coverage is achievable but not by stuffing more web_search calls into mandatory_queries. It requires a hot tier of 10 active enforcement states polled daily by name, a warm tier of about 10 states every 2 to 3 days, a free LegiScan API integration for the legislative layer across all 50 states, and pinned state AG plus gaming commission RSS feeds via fetch_url. With that architecture we exceed Vixio cadence on sweeps (Vixio is weekly on sweeps specifically) while staying under both engine free tiers.

## What top tier daily sweepstakes intel actually looks like

There is no incumbent publishing a true daily 50 state sweeps brief. Vixio Gambling Compliance (vixio.com) is the deepest regulatory feed with 200 plus jurisdictions and an explicit sweeps US Sweepstakes Guide, but their sweeps cadence is weekly to monthly. CDC Gaming Reports (cdcgaming.com) sets the daily cadence bar with the Adams Daily Report midday plus Last Call late afternoon, 22000 plus industry recipients, but it is broad gaming not sweeps focused. SBC Americas (sbcamericas.com) runs a daily editor curated newsletter that mixes sweeps with prediction markets and tribal gaming. Legal Sports Report (legalsportsreport.com) owns the US legal sports betting beat and has a growing social sportsbook column. Eilers and Krejcik is the only credible sweeps market sizing source via their quarterly Sweepstakes Gaming Market Monitor, which revised 2025 US sweeps revenue down from $4.7B to $4B in September 2025.

The product gap is a daily brief that fuses regulator, legal docket, operator, payments, sentiment, and capital markets in one place. We can credibly own that space because no one else is doing it daily.

Topic buckets with daily signal volume estimates.

1. State AG enforcement [CRITICAL, 0 to 5 items per day, episodic spikes]. Illinois Gaming Board plus AG Raoul hit 65 operators Feb 5 2026 with 3 percent compliance. Tennessee AG Skrmetti hit 40 operators Dec 29 2025. West Virginia AG McCuskey issued nearly 50 subpoenas 2024 to 2025. Closest analog. Vixio Regulatory Radar, but Vixio is weekly on this.
2. State gaming commission and lottery board advisories [CRITICAL, 0 to 3 per day]. Michigan Gaming Control Board, New Jersey Division of Gaming Enforcement, Mississippi Gaming Commission. Closest analog. None.
3. State legislative bills [HIGH, 2 to 4 per day during session]. Maryland HB 1226 and HB 295 alive after crossover, Iowa SF 2289 signed May 15 2026, Mississippi SB 2104. Closest analog. LegiScan and BillTrack50 are the feeds, no published daily brief.
4. Federal regulators FinCEN FTC IRS CFTC Treasury [HIGH, 0 to 2 per day]. FinCEN April 10 2026 NPRM on AML CFT reform, IRS One Big Beautiful Bill Act capping gambling loss deduction at 90 percent for tax year 2026. Closest analog. Bloomberg Tax, Reuters Regulatory.
5. Federal and state court dockets [HIGH, 0 to 2 per day]. Class actions in WD Washington and ND California against VGW. Closest analog. CourtListener RECAP, Reuters Legal.
6. Top 20 operator press releases and state exits [CRITICAL, 3 to 5 per day]. Stake.us, VGW (Chumba LuckyLand Global Poker), McLuck, Pulsz, High 5, WOW Vegas, Fortune Coins, Funrize, Modo, Fliff, Legendz, Sportzino, Crown Coins, Mega Bonanza, Hello Millions. Closest analog. SBC Americas, Casino Reports.
7. Payments and geo provider moves [HIGH, 0 to 2 per day]. GeoComply lost about 80 staff April 2026, Xpoint got Massachusetts license March 2026, Sightline Payments integrated GeoComply Jan 2026 across 80 plus partners 40 plus states. Closest analog. Payment Expert, PYMNTS.
8. SEC EDGAR 10-Q and 8-K sweeps mentions [MEDIUM, 0 to 1 per day]. Light and Wonder, Aristocrat, IGT, Bally, Penn, DraftKings, Flutter, Bragg, Genius Sports. Closest analog. SEC EDGAR full text search.
9. M&A and funding [MEDIUM, 0 to 1 per day]. Closest analog. Crunchbase News, TechCrunch gambling tag, Axios Pro Rata.
10. Analyst notes [HIGH on publish, 0 to 2 per week]. Truist, Wells Fargo, Macquarie, Jefferies, B Riley on operator adjacent public co's. Closest analog. Seeking Alpha, Hedge Eye.
11. Tribal opposition [HIGH, 0 to 1 per day]. NIGA, NIGC, CNIGA, Pechanga, Morongo, Seminole, Mohegan, Mashantucket Pequot, Choctaw, Chickasaw, San Manuel, Yaamava, Hard Rock. Three California tribes suing Kalshi and Robinhood over event contracts on tribal lands. Closest analog. Indian Gaming Magazine.
12. Prediction markets as a sibling beat [HIGH, 1 to 2 per day]. Novig converted from sweeps to CFTC prediction market June 16 2026, Kalshi got a Nevada TRO, Polymarket holds about 47 percent leader odds. Closest analog. The Event Horizon.
13. Sentiment from Reddit Trustpilot App Store [MEDIUM, weekly rollup not daily]. r/sweepstakescasino about 95K members, Trustpilot delta per operator, iTunes Lookup endpoint for rating and review count delta.
14. Distribution and ad platform shifts [MEDIUM, episodic]. Google reclassified sweeps casinos October 28 2025 with January 28 2026 enforcement.
15. AML and banking de risking [MEDIUM, episodic]. California AB 831 imposes explicit liability on payment processors.

Daily brief target is 15 to 25 items in the morning push and 5 to 7 in an optional afternoon closer, matching the proven CDC Adams Daily plus Last Call format.

## Optimal load split between Tavily and Exa

Recommended strategy. Route by query intent at the call site, not by primary plus fallback.

Tavily handles named entity polling and fresh news, including state AG newsroom queries, gaming commission queries, top 20 operator name queries, named payments and geo entity queries, specific bill number queries, Eilers and analyst firm name queries, and the daily hot state sweep. Tavily is built for freshness within 1 to 6 hours when topic is news with days filter, which is exactly what state AG cease and desist letters and operator press release pickups need.

Exa handles semantic discovery, including emerging operator detection, novel ban language detection, new payment processor entry detection, court ruling semantic search, and prediction market versus sweeps boundary watching. Exa neural ranking outperforms keyword search on entity centric queries by a meaningful margin (Exa internal benchmarks claim 81 versus 71 percent on complex retrieval, treat that as directional not gospel) and contents highlights returns 50 to 75 percent fewer tokens than Tavily include_raw_content.

DuckDuckGo Lite stays as a final fallback only when both fail, throttled at 1 call per 8 seconds.

Honest monthly burn under the recommended plan at current 24 calls per day volume. Tavily approximately 12 to 14 mandatory queries per day plus most opportunistic, call it 480 to 540 credits per month against the 1000 free tier (48 to 54 percent utilization). Exa approximately 6 to 8 mandatory queries per day plus a few opportunistic, call it 200 to 250 calls per month. The Exa $10 signup credit covers roughly 80 to 100 days at standard search plus contents pricing of about $5 per 1000 calls plus $1 per 1000 highlights, so the bucket lasts about 2.5 to 3 months. After that we are at roughly $1 to $2 per month in Exa overage. Both engines stay well under their free or cheap thresholds with real headroom for opportunistic spikes.

Code level pseudocode for the tools.py priority chain change.

```
# tools.py
def _pick_backend(query: str, intent: str | None = None) -> str:
    if intent in ("news", "entity", "fresh"):
        return "tavily"
    if intent in ("semantic", "discovery", "concept"):
        return "exa"
    # keyword sniff fallback when caller did not pass intent
    fresh_tokens = ("cease and desist", "bill", "AG", "lawsuit", "ruling",
                    "press release", "filed", "signed", "veto", "introduces")
    discovery_tokens = ("similar to", "compare", "emerging", "market size",
                        "GGR", "M and A", "trend", "analysis", "landscape")
    q = query.lower()
    if any(t in q for t in fresh_tokens):
        return "tavily"
    if any(t in q for t in discovery_tokens):
        return "exa"
    return "tavily"  # safe default for daily news brief

def web_search(query: str, intent: str | None = None, days: int = 2) -> str:
    cached = _cache_get(query)
    if cached:
        return cached
    primary = _pick_backend(query, intent)
    if primary == "tavily":
        results = _tavily_search(query, topic="news", days=days,
                                 search_depth="basic", country="united states",
                                 max_results=10)
        if not results or len(results) < 3:
            results = _exa_search(query, type="auto", category="news",
                                  highlights={"numSentences": 3,
                                              "highlightsPerUrl": 2},
                                  numResults=10, livecrawl="when_necessary")
    else:
        results = _exa_search(query, type="auto", category="news",
                              highlights={"numSentences": 3,
                                          "highlightsPerUrl": 2},
                              numResults=10, livecrawl="when_necessary")
        if not results or len(results) < 3:
            results = _tavily_search(query, topic="news", days=days,
                                     search_depth="basic",
                                     country="united states", max_results=10)
    if (not results) and DDG_AVAILABLE:
        _throttle("ddg", 8.0)
        results = _ddg_search(query)
    _cache_set(query, results)
    return results
```

Do not expose intent as a parameter on the LLM facing tool surface because Google ADK introspects function signatures and the model will pass intent values opportunistically. Instead bind intent at agent construction with functools.partial or expose three thin wrapper tools (web_search_news for Tavily news intent, web_search_semantic for Exa semantic intent, web_search_auto for the keyword sniff path) and wire each researcher to the matching wrapper.

## 50 state coverage tiered plan

The honest claim we can make is daily cadence on the highest activity states plus weekly coverage of every state via free LegiScan API and pinned state AG RSS feeds, with rotating warm tier coverage for second tier states. That exceeds Vixio sweeps cadence (weekly to monthly) without claiming we match Vixio depth.

Tier 1 hot states polled daily by name (10 states). Illinois (65 operator cease and desist Feb 5 2026 plus 97 percent non compliance follow on), Oklahoma (SB 1589 veto override June 2026 with Nov 1 deadline), Iowa (SF 2289 signed May 15 2026 with enforcement July 1), Maryland (HB 1226 and HB 295 alive after crossover), Indiana (HB 1052 signed March 13 2026 with ban July 1), Maine (LD 2007 signed April 6 2026 with mid July effective), Louisiana (HB 53 racketeering plus AG Murrill opinion plus HB 883), Minnesota (14 operators AG ordered plus HF 4410 active), Tennessee (HB 1885 and SB 2136 signed May 22 2026, post enforcement watch), Mississippi (SB 2104 plus Gaming Commission C and D letters April 2026).

Specific queries to add for Tier 1 (one per state, named officials and bill numbers). Use Tavily with topic equal to news and days equal to 2.

```
Illinois Gaming Board cease and desist sweepstakes compliance
Oklahoma SB 1589 sweepstakes November 1 enforcement
Iowa SF 2289 sweepstakes Reynolds enforcement
Maryland HB 1226 HB 295 sweepstakes ban session
Indiana HB 1052 Indiana Gaming Commission sweepstakes
Maine LD 2007 Mills sweepstakes implementation
Louisiana HB 53 racketeering AG Murrill sweepstakes
Minnesota HF 4410 Ellison sweepstakes operators
Tennessee HB 1885 SB 2136 Skrmetti sweepstakes post ban
Mississippi SB 2104 Gaming Commission sweepstakes letters
```

Tier 2 warm states polled every 2 to 3 days (9 states). California (AB 831 effective Jan 1 2026, mostly post enforcement but largest market and Eilers pegs CA at 2.42B and 17.3 percent of national sweeps revenue), New York (S5935 signed Hochul Dec 2025, post enforcement watch plus S10092 affiliate liability), New Jersey (A5447 signed Aug 15 2025 with 100K to 250K fines, DGE enforcement), Texas (largest MAU market, SB 517 failed but next session imminent), Florida (SB 1580 HB 189 HB 591 all died but next session active), Ohio (HB 298 and SB 197 stalled but Casino Control Commission active), Massachusetts (ban bill failed but MGC active), Virginia (SB 579 carried to 2027 session), Washington (pre existing ban plus AG enforcement).

Tier 3 cold states via rotating weekly sweep (remaining 31 states) using LegiScan API plus a single aggregate query per day. LegiScan free tier provides 30000 calls per month and covers all 50 state legislatures plus Congress. One nightly call per state per keyword (sweepstakes, sweeps, social casino, dual currency, promotional sweepstakes) gives full coverage at roughly 7500 to 12000 calls per month, well under free ceiling. This replaces a per state web_search query entirely for the legislative layer.

Pinned state AG RSS feeds via fetch_url (zero search credits). Empirical testing shows the following state AG feeds work reliably as of 2026. Pennsylvania, Colorado, North Carolina, Georgia, plus the New York AG press releases page via scrape. Most other state AG offices do not publish working RSS so the LegiScan API plus targeted Tavily news queries by AG name are the workable path.

## Publications and feeds we are missing

The current pipeline never names specific publications in queries and relies entirely on Tavily and Exa generic indexing. This is the biggest single quality lever.

Free RSS feeds to wire into a primary_source_pull stage that runs before the three researcher agents (verified working as of 2026 unless noted). Sources we should add.

Trade press (daily signal density 5 to 15 sweeps adjacent items per day total).
- SBC Americas at sbcamericas.com (RSS confirmed). High daily density.
- iGB North America at igamingbusiness.com (RSS confirmed). High daily density.
- CDC Gaming Reports at cdcgaming.com (RSS confirmed). High daily density via Adams Daily.
- Legal Sports Report at legalsportsreport.com (RSS confirmed). Medium daily density on sweeps.
- Sports Handle at sportshandle.com (RSS confirmed). Medium density.
- Bonus.com at bonus.com (RSS confirmed). Medium density on US operators.
- Covers at covers.com (RSS confirmed). Lower density on sweeps specifically.
- iGaming NEXT at igamingnext.com (RSS confirmed). Medium density.
- Gambling News at gamblingnews.com (RSS confirmed). Medium density.
- TechCrunch gambling tag (RSS confirmed). Low density but catches funding rounds.

Federal regulators (daily signal density less than 1 sweeps adjacent item per day, but high signal per item when it lands).
- Federal Register API at federalregister.gov/api/v1/articles.json (free, JSON, no key). Query by keyword sweepstakes or prize promotion or online gambling. This is the legally authoritative feed for federal rulemaking.
- SEC EDGAR full text search for L and W, Aristocrat, IGT, Bally, Penn, DraftKings, Flutter, Bragg CIKs (free).
- Many other federal RSS feeds (FTC, FinCEN, DOJ, IRS, CFPB) are unreliable or have moved, empirical curl testing shows most of the standard URLs return 404. Use Federal Register plus targeted Tavily queries by agency name instead.

Legislative (daily signal density 2 to 5 bills per day during session).
- LegiScan API at legiscan.com (30000 calls per month free, JSON, covers all 50 states plus Congress). Single highest leverage addition for 50 state coverage.
- OpenStates API at openstates.org/api (free backup).

Court dockets (daily signal density less than 1 per day, high signal per item).
- CourtListener RECAP at courtlistener.com (free API but current 2026 free tier is 5 per minute, 50 per hour, 125 per day, not the older 5000 per hour figure). Delivery is email or webhook, not RSS. Saved searches for sweepstakes plus named operators OR list catch federal class actions the night of filing.

Social and consumer sentiment (daily firehose, weekly rollup recommended).
- Reddit r/sweepstakescasino, r/socialcasino, r/onlinegambling top.json (free, 60 requests per minute, no auth).
- Trustpilot public business pages per operator (free scrape).
- iTunes Lookup endpoint at itunes.apple.com/lookup with app id for each operator app (free, no key, returns rating and review count delta).

Paid sources to consider only if budget opens up. Vixio Gambling Compliance at roughly 15K to 25K per seat per year is the gold standard regulatory feed but only weekly on sweeps. Eilers and Krejcik Sweepstakes Gaming Market Monitor is quarterly. Sensor Tower and data dot ai for app metrics start at thousands per month.

## Concrete code changes in priority order

1. Wire LegiScan API into a new primary_source_pull stage at /Users/ritzmish/intel_daily/agents.py before the three researcher agents fire. Free 30000 calls per month covers all 50 state legislatures. Replaces 1 to 2 generic state ban queries per day in regulatory_researcher. Expected query count impact minus 1 to minus 2 web_search calls per day. Budget burn impact zero (LegiScan is free). Intel quality lift high (50 state legislative coverage with no gaps, surfaces bills 1 to 3 days before trade press).

2. Fix Tavily call signature at /Users/ritzmish/intel_daily/tools.py lines 191 to 217. Add topic equal to news, days equal to 2, search_depth equal to basic explicitly (prevents silent auto promote to advanced which doubles credit cost to 2 per call), country equal to united states. Drop max_results from 10 to 8 if results quality testing shows degradation. Expected query count impact zero. Budget burn impact zero (basic stays at 1 credit per call). Intel quality lift high on freshness for regulatory and competitor queries.

3. Implement query intent routing in tools.py with the _pick_backend pseudocode above. Add three thin wrapper tools web_search_news, web_search_semantic, web_search_auto and wire each researcher in /Users/ritzmish/intel_daily/agents.py to the matching wrapper (regulatory and market to web_search_news, competitor to web_search_semantic, opportunistic to web_search_auto). Expected query count impact zero. Budget burn impact Tavily drops from about 720 to about 480 to 540 per month, Exa rises from 0 to about 200 to 250 per month (free for first 80 to 100 days then about $1 to $2 per month). Intel quality lift medium (Exa neural ranking on entity queries).

4. Replace 4 of the 6 regulatory_researcher mandatory queries at agents.py lines 229 to 236 with the Tier 1 hot state queries listed above. Keep California AB 831 and Illinois Gaming Board (already there). Add Oklahoma, Iowa, Maryland, Maine, Indiana, Louisiana, Mississippi, Minnesota, Tennessee enforcement queries on a rotating basis (3 of 10 per day so each Tier 1 state gets touched every 3 to 4 days). Expected query count impact zero. Budget burn impact zero. Intel quality lift high (replaces stale generic queries with named state coverage of active enforcement).

5. Add 3 to 5 named entity queries to competitor_researcher at agents.py lines 248 to 255. Add Modo, Fliff, Legendz, Sportzino, Crown Coins, Mega Bonanza, Fortune Coins, Hello Millions on a rotating basis. Add GeoComply, Xpoint, Sightline Payments, Trustly named queries. Use Exa via web_search_semantic. Expected query count impact plus 0 to 2 (some replace existing generic queries). Budget burn impact minimal. Intel quality lift high (closes the named operator gap identified in COVERAGE_AUDIT_AND_PLAN.md).

6. Add a Prediction Markets sibling beat with 2 hardcoded queries (one for CFTC and state actions, one for Kalshi, Polymarket, Novig, Robinhood Event Contracts, ForecastEx). Expected query count impact plus 2. Budget burn impact small (60 extra Tavily credits per month). Intel quality lift high (Novig converted from sweeps to CFTC June 16 2026 means readers need this context daily).

7. Add fetch_url targets for working RSS feeds at tools.py. Wire SBC Americas, iGB, CDC Gaming, Legal Sports Report, Sports Handle, Bonus.com, Gambling News, TechCrunch gambling tag, and Federal Register sweepstakes query. Run as a primary_source_pull stage before researchers fire. Expected query count impact minus 3 to minus 5 web_search calls per day (researchers verify and follow up rather than discover). Budget burn impact zero (fetch_url uses Jina Reader free tier). Intel quality lift high.

8. Add CourtListener saved search alerts via webhook receiver or polled search API at tools.py. Free tier supports daily digest. Catches federal class actions same day instead of 5 to 21 days late via trade press. Expected query count impact zero. Budget burn impact zero. Intel quality lift medium.

9. Strengthen verifier at agents.py lines 332 to 350. Add a rule that for every [Publication name](URL), the URL host must roughly match the publication name (catches the [Reuters](https colon slash slash lawandcrime.com slash) hallucination mode). Expected query count impact zero. Budget burn impact zero. Intel quality lift medium (reader trust).

10. Add a budget_ledger table to /Users/ritzmish/intel_daily/cache.db tracking monthly Tavily and Exa credit consumption. When running total exceeds 80 percent of monthly cap, auto flip default backend to the other engine with a printed warning. Expected query count impact zero. Budget burn impact zero. Intel quality lift low (defensive observability).

11. Add a daily Reddit pull for r/sweepstakescasino top.json plus iTunes Lookup endpoint for the 19 named operator apps. Roll up into a weekly Friday Sentiment section, not daily noise. Expected query count impact zero (fetch_url not web_search). Budget burn impact zero. Intel quality lift medium.

12. Move _throttle to apply to Exa at tools.py with a 1.1 second interval to stay under Exa free tier rate limit. Expected query count impact zero. Budget burn impact zero. Intel quality lift low (defensive).

## What this will cost in dollars per month

Realistic monthly burn under the recommended plan.

Tavily. About 480 to 540 calls per month at basic search_depth (1 credit per call) against the 1000 credit free monthly tier. Cost zero dollars per month. Buffer of 460 to 520 credits per month for opportunistic spikes, retries, and breaking news days.

Exa. About 200 to 250 calls per month at standard search plus contents pricing of about $5 per 1000 search calls plus $1 per 1000 highlights returned. After the $10 signup credit which lasts roughly 80 to 100 days at this volume, ongoing cost is about $1.20 to $1.80 per month. Round up to 2 dollars per month for safety.

LegiScan. About 7500 to 12000 calls per month against the 30000 call free monthly tier. Cost zero dollars per month.

CourtListener. Daily digest under the 125 call per day free tier. Cost zero dollars per month.

Federal Register API, Reddit JSON, iTunes Lookup, Trustpilot public pages, all RSS feeds. Free. Cost zero dollars per month.

Jina Reader for fetch_url. Free tier, no key. Cost zero dollars per month with rate limit handling for 429 responses.

DuckDuckGo Lite. Free, throttled at 1 call per 8 seconds. Cost zero dollars per month.

Total monthly cost. Under $5 per month, dominated by Exa overage after the signup credit runs out. Effectively free for the first 3 months while the Exa signup credit lasts.

## Risks and confidence

LegiScan API integration. High confidence the API works as documented. Risk is keyword tuning. Two keywords (sweepstakes, sweeps) is too thin and we need at least 5 to 6 keywords to catch real coverage. Mitigation is iterate keyword list against known historical bills like CA AB 831 and verify recall before declaring 50 state coverage.

Tavily and Exa query intent routing. High confidence the routing improves intel quality on entity queries. Lower confidence on the exact magnitude of the recall lift (Exa internal benchmarks claim 10 to 15 percent on entity retrieval but those are self reported on Exa chosen evals not on sweepstakes operator queries). Mitigation is A/B test on a sample of competitor queries for two weeks before fully committing. Risk is Exa $10 signup credit running out faster than expected if highlights cost is underestimated. Mitigation is the budget_ledger and auto flip default.

Hot state Tier 1 list. Medium confidence on the specific 10 state composition. The legislative environment is moving fast in 2026 and the right hot list will rotate quarterly. Mitigation is review the Tier 1 list every 90 days against AG action volume and pending bill velocity.

State AG RSS feeds. Low to medium confidence on which feeds actually work. Empirical testing shows most state AG RSS URLs return 404 or 403 (Cloudflare). Mitigation is verify each feed at integration time and fall back to LegiScan plus Tavily by named AG for non working feeds.

Primary source pull stage. Medium confidence. Will not by itself cut web_search burn unless we also rewrite the researcher MANDATORY PROTOCOL at agents.py to make queries conditional on what RSS already surfaced. That rewrite is the actual hard part and adds 3 to 5 days to build effort beyond the feed wiring itself.

CourtListener integration. Medium confidence. Free tier rate limits changed in May 2026 to 5 per minute, 50 per hour, 125 per day which is still adequate for daily digest but rules out the older 5000 per hour assumption. Delivery is email or webhook, not RSS, so we need a small webhook receiver or polled search call.

Generic year token queries. High confidence that dropping the 2026 token in favor of days equal to 2 via Tavily news topic improves precision. Search engines now downweight bare year tokens.

Vixio benchmark claim. Medium confidence. We can credibly claim daily cadence on sweeps which exceeds Vixio weekly cadence on sweeps, but we cannot match Vixio depth on regulatory filings without paying for Vixio. Honest framing is fastest daily sweeps cadence in the market with narrower regulatory filing depth than Vixio, not top tier across the board.

Eilers market sizing. High confidence Eilers is the only credible sweeps sizing source. Cite their quarterly Sweepstakes Gaming Market Monitor heavily when freshly published and surface analyst notes from Truist, Wells Fargo, Macquarie, Jefferies, B Riley on non Eilers days.

Brief format. Medium confidence on the 15 to 25 morning items plus 5 to 7 afternoon closer format. Modeled on CDC Adams Daily plus Last Call which has 22000 plus industry recipients so the format is proven for daily gaming intel. Need 4 to 6 weeks of reader feedback to confirm right cadence.
