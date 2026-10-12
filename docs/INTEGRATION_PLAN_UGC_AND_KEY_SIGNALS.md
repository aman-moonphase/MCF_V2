# MCF Integration Plan: UGC Explorer & Key Signals

**Document Version:** 1.0  
**Status:** Proposal / Ready for Decision  
**Checkpoint:** `2776829` (feature/final-production-audit)  
**Authors:** MultiContent Factory (MCF) Engineering Team  

---

## 1. Executive Summary & Core Principles

The MultiContent Factory (MCF) competitor intelligence workflow is grounded on strict provenance:
1. **Never fabricate research:** Unsupported claims remain explicit hypotheses or unknowns (`evidence_needed`).
2. **Evidence-backed grounding:** Findings cite concrete, stored evidence (`E1`, `C1:E1`).
3. **Demo Mode baseline:** MCF must operate fully offline without external keys or network calls.
4. **Human review boundary:** AI suggestions and external candidates remain `unverified` until a human reviews and grounds them with evidence.

This document plans the transition of **UGC Explorer** and **Key Signals** from architecture placeholders (`competitor_intelligence.py#L9-L11`) into real, evidence-backed external integrations.

---

## 2. UGC Explorer Integration Specification

### 2.1 Purpose & Scope
UGC Explorer retrieves authentic User Generated Content (reviews, discussions, unprompted feedback) regarding competitors and category alternatives. It serves two distinct purposes:
1. **Candidate Discovery:** Discover alternative products discussed by real users in the same category.
2. **Competitor Evidence Collection:** Ingest actual user sentiment, recurring complaints, and loved features as citable evidence items for a competitor.

### 2.2 Target Platforms & Sources
- **B2B / SaaS Products:** G2, Capterra, Trustpilot.
- **Consumer / General Tech:** Reddit (e.g. `r/software`, `r/productivity`, niche subreddits), Product Hunt discussions, YouTube/X reviews.

### 2.3 Proposed External Providers & Endpoints
Because direct enterprise platform APIs (e.g., G2 Partner API, LinkedIn Enterprise) often require costly partner agreements, two viable provider architectures are proposed:

#### Option 1: Managed Scraping / Actor API (e.g., Apify)
- **Endpoint:** `POST https://api.apify.com/v2/acts/{actor-id}/runs?token={APIFY_API_KEY}`
- **Actors:**
  - Reddit Scraper / Search Actor
  - G2 Reviews Scraper Actor
  - Trustpilot Reviews Scraper Actor
- **Credentials:** `UGC_EXPLORER_API_KEY` (Apify API Token)
- **Configuration:** `UGC_EXPLORER_PROVIDER=apify` (fallback: `demo`)

#### Option 2: Direct Reddit API (Free / Self-Hosted OAuth)
- **Endpoint:** `GET https://oauth.reddit.com/r/{subreddit}/search?q={competitor}&sort=relevance`
- **Credentials:** `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`
- **Scope:** Free tier / read-only public post search.

### 2.4 Payload & Output Schema

#### Provider Input Payload:
```json
{
  "query": "FocusFlow OR Pomodoro alternative",
  "category": "productivity",
  "target_competitor": "Toggl Track",
  "max_results": 5,
  "min_rating_or_score": 1
}
```

#### Normalized UGC Item Response:
```json
{
  "id": "ugc_reddit_18xyz",
  "platform": "reddit",
  "author": "productive_dev_99",
  "source_url": "https://www.reddit.com/r/productivity/comments/18xyz/best_timer",
  "published_at": "2026-08-14T18:22:00Z",
  "title": "Toggl vs Clockify for remote dev teams",
  "raw_text": "Toggl Track is super easy to start with, but their paid tier gets way too expensive as soon as you have more than 5 users. Looking for simpler alternatives.",
  "sentiment": "negative_pricing",
  "verified_post": true
}
```

### 2.5 Mapping to MCF Models & Evidence Storage
- **Candidate Discovery:** Extracted company names mapped to `CandidateCompetitor(name="Clockify", origin="ugc_explorer", reason="Mentioned as alternative in Reddit discussion: r/productivity")`.
- **Competitor Evidence:** Mapped directly to `CompetitorEvidence`:
  - `evidence_type = "ugc"`
  - `source_url = item.source_url` (validated via `validate_public_url()`)
  - `title = f"UGC ({item.platform}): {item.title[:80]}"`
  - `content = item.raw_text[:2000]`
  - `provenance = {"platform": item.platform, "author": item.author, "published_at": item.published_at}`

---

## 3. Key Signals Integration Specification

### 3.1 Purpose & Scope
Key Signals retrieves macro market signals, industry announcements, trend spikes, and strategic movements regarding competitors and category keywords.
- **Candidate Discovery:** Identify rapidly growing or emerging entrants breaking into the category.
- **Competitor Evidence Collection:** Ingest recent product launches, pricing shifts, funding rounds, and positioning pivots.

### 3.2 Target Platforms & Sources
- **Search & Market Trends:** Google Trends data (search momentum over 90 days).
- **Industry News & PR:** Google News / RSS / Curated News APIs (NewsAPI, SerpApi News).
- **Company Strategic Updates:** Crunchbase / Dealroom / Official press releases.

### 3.3 Proposed External Providers & Endpoints

#### Option 1: SerpApi (Google Trends + Google News)
- **Endpoints:**
  - News: `GET https://serpapi.com/search.json?engine=google_news&q={competitor_name}&api_key={SERPAPI_API_KEY}`
  - Trends: `GET https://serpapi.com/search.json?engine=google_trends&q={competitor_name}&api_key={SERPAPI_API_KEY}`
- **Credentials:** `KEY_SIGNALS_API_KEY` (SerpApi Token)
- **Configuration:** `KEY_SIGNALS_PROVIDER=serpapi` (fallback: `demo`)

#### Option 2: NewsAPI.org (News & Public Media)
- **Endpoint:** `GET https://newsapi.org/v2/everything?q={competitor_name}+software&sortBy=relevancy&apiKey={NEWS_API_KEY}`
- **Credentials:** `NEWS_API_KEY`
- **Scope:** 100 free requests/day developer tier.

### 3.4 Payload & Output Schema

#### Normalized Signal Item Response:
```json
{
  "id": "sig_news_9921",
  "source_name": "TechCrunch",
  "signal_type": "product_launch",
  "source_url": "https://techcrunch.com/2026/07/20/example-launches-ai-tracking",
  "published_at": "2026-07-20T14:00:00Z",
  "headline": "Competitor X introduces automated attendance tracking",
  "summary": "Competitor X announced their enterprise expansion today with new attendance tracking capabilities.",
  "confidence_score": 0.92
}
```

### 3.5 Mapping to MCF Models & Evidence Storage
- **Candidate Discovery:** Rising entities mapped to `CandidateCompetitor(name=..., origin="key_signals", reason="Trending in category news: TechCrunch")`.
- **Competitor Evidence:** Mapped to `CompetitorEvidence`:
  - `evidence_type = "market_signal"`
  - `source_url = item.source_url`
  - `title = f"Signal ({item.source_name}): {item.headline[:80]}"`
  - `content = item.summary`
  - `provenance = {"signal_type": item.signal_type, "published_at": item.published_at, "confidence": item.confidence_score}`

---

## 4. Preserving Provenance, URLs, Confidence, and Unknowns

To maintain MCF's RAG grounding integrity:
1. **Source URLs:** Every UGC review and market signal MUST retain its original canonical public URL. Any private or non-HTTP URL is rejected via `validate_public_url()`.
2. **Timestamps:** Ingested items store `published_at` to detect stale market signals or outdated reviews.
3. **Verification States:**
   - Any competitor discovered via UGC Explorer or Key Signals enters the system as `verification = "unverified"`.
   - The competitor cannot be approved or marked `evidence_backed` until evidence is linked and reviewed by the user.
4. **Preserving Unknowns:** If UGC or signals do not mention a feature in our Product Profile, it remains strictly an `unknown` in `CompetitorAnalysis.unknowns`, generating an `evidence_needed` hypothesis rather than a fabricated negative claim.

---

## 5. Smallest Implementation Plan (Reusing MCF Architecture)

We can implement both integrations incrementally without disrupting existing workflows:

### Step 1: Base Provider Classes & Contract Tests (Zero External Calls)
- In `backend/app/services/competitor_intelligence.py`:
  - Create `UGCExplorerIntelligence(CompetitorIntelligenceProvider)` with key `"ugc_explorer"`.
  - Create `KeySignalsIntelligence(CompetitorIntelligenceProvider)` with key `"key_signals"`.
- Support `is_available()` returning `False` in Demo Mode or when keys are missing.
- Add mocked unit tests in `tests/test_competitor_analysis.py` asserting normalized discovery output and graceful skips when unconfigured.

### Step 2: Database & Schema Extension
- In `backend/app/models/competitor.py`:
  - Extend allowed `origin`: add `"ugc_explorer"`, `"key_signals"`.
  - Extend allowed `evidence_type`: add `"ugc"`, `"market_signal"`.
- In `backend/app/schemas/competitor.py`:
  - Update `verification` literal types: `"ugc_derived"`, `"signal_derived"`.
  - Add optional `provenance` metadata to `EvidenceResponse`.

### Step 3: HTTP Client & Credential Integration (Mocked First)
- Implement backend-only HTTP requests with:
  - 10-second timeout
  - Strict response payload size limits (max 50KB)
  - Redaction of API keys from all error logs and user-facing messages
  - Unit tests using mocked responses.

### Step 4: Frontend UI Badging
- In `frontend/src/components/projects/stages/competitor-analysis-stage.tsx`:
  - Add visual badges for `ugc_derived` ("UGC Explorer · unverified") and `signal_derived` ("Market Signal · unverified").
  - Add evidence tags for `ugc` and `market_signal` alongside existing `url`, `note`, and `pdf` badges.

---

## 6. Exact Decisions Needed from Ayush Before Implementation

Before writing real external API clients, Ayush needs to confirm:

1. **UGC Explorer Target Platforms:**
   - Should UGC Explorer prioritize B2B reviews (G2 / Capterra / Trustpilot) or social community discussions (Reddit)?
2. **UGC Explorer Provider Choice:**
   - Does Ayush prefer a managed actor service (e.g. Apify with an API token), a direct platform API (e.g. Reddit Developer API), or a specific custom webhook/feed?
3. **Key Signals Data Source:**
   - For market signals, is the primary source general news/press releases (NewsAPI / SerpApi News) or search trend momentum (Google Trends)?
4. **Credentials & Budgets:**
   - Which specific API keys will be supplied in `.env` (e.g., `APIFY_API_KEY`, `SERPAPI_API_KEY`, `NEWS_API_KEY`), and are there any monthly query/credit limits to enforce?
5. **Human Ingest Mode:**
   - Should UGC and Signals be discovered automatically on **Find candidates**, or should users also have a dedicated **Search UGC / Search Signals** button inside each competitor's evidence drawer?
