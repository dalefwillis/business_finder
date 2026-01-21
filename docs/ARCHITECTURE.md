# Business Finder Architecture

## Purpose

Automated deal sourcing pipeline that:
1. Periodically visits acquisition marketplaces and broker sites
2. Identifies new opportunities matching our criteria
3. Extracts and scores listings against our framework
4. Surfaces high-potential deals via Slack
5. Captures feedback to refine scoring over time

This is a **top-of-funnel** tool for deal discovery and idea generation, not a full due diligence system.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           LOCAL MACHINE (Docker)                         │
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   Scheduler  │───▶│   Scraper    │───▶│   Extractor  │              │
│  │   (cron)     │    │  (Playwright)│    │   & Parser   │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│                                                 │                        │
│                                                 ▼                        │
│                      ┌──────────────────────────────────────┐           │
│                      │            SQLite DB                  │           │
│                      │  ┌─────────┐ ┌─────────┐ ┌─────────┐ │           │
│                      │  │Listings │ │ Scores  │ │Feedback │ │           │
│                      │  └─────────┘ └─────────┘ └─────────┘ │           │
│                      └──────────────────────────────────────┘           │
│                                                 │                        │
│                                                 ▼                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │   Scoring    │◀───│   New Item   │───▶│    Slack     │              │
│  │   Engine     │    │   Detector   │    │  Notifier    │              │
│  └──────────────┘    └──────────────┘    └──────────────┘              │
│         │                                       ▲                        │
│         │            ┌──────────────┐           │                        │
│         └───────────▶│  Daily       │───────────┘                        │
│                      │  Digest      │                                    │
│                      └──────────────┘                                    │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Optional: Ollama (Local LLM)                   │   │
│  │                    RTX 5070 Ti 16GB - for description parsing     │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                           ┌──────────────┐
                           │    Slack     │
                           │  Workspace   │
                           └──────────────┘
                                    │
                                    ▼
                           ┌──────────────┐
                           │   Feedback   │◀─── User reactions/replies
                           │   Ingestion  │
                           └──────────────┘
```

---

## Components

### 1. Scheduler
- Simple cron-based scheduling
- Default: daily runs
- Configurable per-source (some sources may warrant more frequent checks)
- Tracks last-run timestamps per source

### 2. Scraper (Playwright)
- Headless browser automation
- One scraper module per source
- Handles login where required (credentials in env/secrets)
- **Development approach**: Use Claude Chrome "student-teacher" method to discover interaction patterns, then codify into Playwright scripts

### 3. Extractor & Parser
- Source-specific parsers to extract structured data from HTML
- Maps to common listing schema (see Database section)
- Flags fields that couldn't be extracted

### 4. SQLite Database
- Single file, easy backup, good enough for this volume
- Core tables: `listings`, `scores`, `feedback`, `sources`, `scrape_runs`
- Upgrade path to Postgres if needed later

### 5. Scoring Engine
- Applies scoring framework from SCORING_FRAMEWORK.md
- Only scores dimensions where data is available
- Returns: total score, breakdown by dimension, flags for missing data
- Hard gates evaluated first (pass/fail before scoring)

### 6. Slack Notifier
- **Immediate notification**: High-scoring listings (configurable threshold)
- **Daily digest**: Everything else that's new
- Rich formatting with key metrics, link to source
- Interactive elements for feedback (buttons or reaction-based)

### 7. Feedback System
- Capture: thumbs up/down + optional reason
- Store feedback linked to listing
- Future: use feedback to adjust scoring weights

### 8. Local LLM (Optional)
- Ollama with a model that fits 16GB VRAM (e.g., Llama 3 8B, Mistral 7B, or similar)
- Use cases:
  - Parse unstructured listing descriptions
  - Categorize industry/business type
  - Extract seller motivation signals
  - Flag potential red flags in description text
- Not required for MVP - can add when we see the need

---

## Data Sources

### In Scope (Initial)

**Tier B (SaaS):**
| Source | Auth Required | Notes |
|--------|---------------|-------|
| Acquire.com | No (public listings) | Subscription later for full access |
| Flippa | No | Filter for SaaS only, high noise |
| Microns.io | No | Curated, smaller deals |
| Little Exits | No | Newsletter-style, weekly deals |

**Tier A (Traditional):**
| Source | Auth Required | Notes |
|--------|---------------|-------|
| BizBuySell | No | Largest traditional marketplace |
| BizQuest | No | Same parent company as BizBuySell |

### Deferred (Add After Learning)

**Tier A - Broker Sites:**
- Lake Country Advisors, Sunbelt Wisconsin, etc. (from BUSINESS_BROKERS.md)
- Add once we understand patterns from BizBuySell/BizQuest

**Tier A - Franchise:**
- FranNet, Transworld, franchise resale sites
- Add as secondary priority

**Not Included:**
- SideProjectors (low quality, skip for now)
- Indie Hackers, Twitter/X (community-based, not automatable)
- LoopNet (too RE-focused)
- MicroConf Connect, newsletters (relationship-based)

### Source Configuration

Each source needs:
```yaml
source_id: acquire_com
name: Acquire.com
url: https://acquire.com/
tier: B
requires_auth: false  # true when we get subscription
poll_frequency: daily
scraper_module: scrapers.acquire
parser_module: parsers.acquire
enabled: true
```

---

## Browser Automation Approach

### Student-Teacher Method

1. **Discovery phase** (using Claude Chrome):
   - Navigate to source manually with Claude Chrome observing
   - Identify the steps: login flow, navigation to listings, pagination, individual listing pages
   - Document the selectors, URLs, interaction patterns
   - Note any anti-bot measures or dynamic content

2. **Codification phase**:
   - Translate discovered patterns into Playwright scripts
   - Build reusable utilities for common patterns (pagination, infinite scroll, etc.)
   - Add error handling and retry logic

3. **Maintenance**:
   - When a scraper breaks, use Claude Chrome to re-discover the pattern
   - Update the Playwright script accordingly

### Playwright Script Structure

```
scrapers/
├── base.py          # Base scraper class with common utilities
├── acquire.py       # Acquire.com scraper
├── flippa.py        # Flippa scraper
├── bizbuy.py        # BizBuySell scraper
└── ...
```

Each scraper implements:
- `login()` - if auth required
- `get_listing_urls()` - find all listing links
- `scrape_listing(url)` - extract data from single listing
- `run()` - orchestrate full scrape

---

## Database Schema (Draft)

### listings
```sql
CREATE TABLE listings (
    id TEXT PRIMARY KEY,           -- source_id + external_id
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,

    -- Financials
    asking_price INTEGER,          -- cents
    revenue INTEGER,               -- annual, cents
    mrr INTEGER,                   -- cents, for SaaS
    profit INTEGER,                -- SDE/annual profit, cents

    -- Classification
    tier TEXT,                     -- A or B
    industry TEXT,
    business_type TEXT,            -- SaaS, service, manufacturing, etc.

    -- Details
    description TEXT,
    customer_count INTEGER,
    employee_count INTEGER,
    location TEXT,                 -- for Tier A
    tech_stack TEXT,               -- for Tier B
    seller_reason TEXT,
    time_commitment TEXT,

    -- Metadata
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    listing_date DATE,             -- when seller listed it
    raw_data JSON,                 -- original scraped data

    UNIQUE(source_id, external_id)
);
```

### scores
```sql
CREATE TABLE scores (
    id INTEGER PRIMARY KEY,
    listing_id TEXT REFERENCES listings(id),
    scored_at TIMESTAMP,

    -- Gate results
    gates_passed BOOLEAN,
    gate_failures JSON,            -- array of failed gate names

    -- Dimension scores (0-10 each)
    payback_score REAL,
    revenue_quality_score REAL,
    customer_concentration_score REAL,
    market_tailwinds_score REAL,
    operational_load_score REAL,
    seller_motivation_score REAL,
    defensibility_score REAL,
    growth_levers_score REAL,
    tech_stack_score REAL,

    -- Totals
    total_score REAL,              -- weighted sum
    missing_dimensions JSON,       -- couldn't score these
    flags JSON,                    -- things to note

    -- Franchise overlay (if applicable)
    is_franchise BOOLEAN DEFAULT FALSE,
    franchise_scores JSON
);
```

### feedback
```sql
CREATE TABLE feedback (
    id INTEGER PRIMARY KEY,
    listing_id TEXT REFERENCES listings(id),
    created_at TIMESTAMP,

    rating TEXT,                   -- up, down, maybe
    reason TEXT,                   -- free text
    slack_user TEXT,
    slack_channel TEXT,
    slack_ts TEXT,                 -- for threading

    -- Structured feedback (future)
    structured_feedback JSON
);
```

### sources
```sql
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    name TEXT,
    url TEXT,
    tier TEXT,
    requires_auth BOOLEAN,
    poll_frequency TEXT,
    enabled BOOLEAN,
    last_run_at TIMESTAMP,
    last_run_status TEXT,
    config JSON
);
```

### scrape_runs
```sql
CREATE TABLE scrape_runs (
    id INTEGER PRIMARY KEY,
    source_id TEXT REFERENCES sources(id),
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status TEXT,                   -- running, success, failed
    listings_found INTEGER,
    new_listings INTEGER,
    error_message TEXT
);
```

---

## Scoring Implementation

### Hard Gates (from SCORING_FRAMEWORK.md)

Check these first - any failure = reject:
1. Profitable (SDE > 0)
2. Real customers (≥5 paying)
3. Business model (B2B SaaS preferred)
4. Excluded categories (content, ecomm, mobile, food, lawncare, daycare, construction, B2C)
5. Acquisition ceiling (10% down ≤ $350k)
6. Infrastructure (not on-prem)
7. Domain licensing (no deep license required)

### Dimension Scoring

For each dimension:
1. Check if we have the data
2. If yes, apply scoring rules from framework
3. If no, mark as "not scored" and flag

### Score Calculation

```python
def calculate_score(listing, dimension_scores):
    weights = {
        'payback': 0.20,
        'revenue_quality': 0.20,
        'customer_concentration': 0.15,
        'market_tailwinds': 0.10,
        'operational_load': 0.10,
        'seller_motivation': 0.10,
        'defensibility': 0.05,
        'growth_levers': 0.05,
        'tech_stack': 0.05,
    }

    total = 0
    weight_sum = 0

    for dim, weight in weights.items():
        if dim in dimension_scores and dimension_scores[dim] is not None:
            total += dimension_scores[dim] * weight
            weight_sum += weight

    # Normalize to account for missing dimensions
    if weight_sum > 0:
        return (total / weight_sum) * 10  # Scale to 0-100
    return None
```

---

## Slack Integration

### Message Format (High-Score Alert)

```
🔥 *New High-Scoring Listing*

*[Title]* — Score: 78/100

📊 *Key Metrics*
• Asking: $85,000
• MRR: $4,200 ($50k ARR)
• Profit: $38k/yr
• Customers: 127

📈 *Score Breakdown*
• Payback: 8/10 (2.2 yrs)
• Revenue Quality: 9/10 (95% recurring)
• Concentration: 10/10 (<5% top customer)

⚠️ *Flags*
• Tech stack not disclosed
• Churn rate unknown

🔗 [View on Acquire.com](https://...)

React: 👍 interested | 👎 pass | 🤔 maybe
```

### Daily Digest Format

```
📬 *Daily Deal Digest* — Jan 20, 2026

*12 new listings* (3 Tier A, 9 Tier B)

*Top 5 by Score:*
1. SaaS Analytics Tool — 72/100 — $65k — [link]
2. Manufacturing Co (Madison) — 68/100 — $1.2M — [link]
3. B2B Service Platform — 65/100 — $42k — [link]
4. ...

*Passed Hard Gates but Low Score (5):*
• [listing] — 45/100 — [reason for low score]
• ...

*Failed Hard Gates (7):*
• [listing] — B2C (excluded category)
• ...
```

### Feedback Handling

**Option A: Reaction-based**
- 👍 = interested
- 👎 = pass
- 🤔 = maybe
- Reply in thread for reason

**Option B: Buttons**
- Slack Block Kit buttons for rating
- Opens modal for reason input

**Option C: Thread reply interpretation**
- User replies with free text
- Parse intent (requires LLM or simple keyword matching)

Starting with Option A (simplest), can evolve.

---

## Implementation Phases

### Phase 0: Setup & Exploration
- [ ] Project structure, dependencies (Poetry)
- [ ] SQLite database initialization
- [ ] Basic config management
- [ ] Use Claude Chrome to explore 2-3 sources, document patterns

### Phase 1: Single Source MVP
- [ ] Playwright scraper for one Tier B source (Flippa or Microns - no auth)
- [ ] Parser to extract listing data
- [ ] Store in database
- [ ] Basic scoring (hard gates + available dimensions)
- [ ] CLI to view listings and scores

### Phase 2: Slack Integration
- [ ] Slack app setup
- [ ] High-score immediate notification
- [ ] Daily digest
- [ ] Reaction-based feedback capture

### Phase 3: Additional Sources
- [ ] Add remaining Tier B sources
- [ ] Add Tier A sources (BizBuySell, BizQuest)
- [ ] Source-specific scheduling

### Phase 4: Refinement
- [ ] Local LLM integration (Ollama) for description parsing
- [ ] Feedback analysis
- [ ] Scoring weight adjustments
- [ ] Docker packaging

### Phase 5: Future Enhancements
- [ ] Acquire.com with subscription (full access)
- [ ] Broker site scrapers
- [ ] More sophisticated feedback loop
- [ ] Simple web UI for browsing/filtering

---

## Open Questions & Decisions to Revisit

1. **Score threshold for immediate notification**: Start at 70/100? Adjust based on volume.

2. **What to do with listings missing key data**: Score what we can and flag, or require manual review before scoring?

3. **Deduplication across sources**: Same business listed on multiple platforms - how to detect and merge?

4. **Price for Acquire.com subscription**: Worth $390/yr once we validate the pipeline?

5. **Feedback granularity**: Simple up/down may not give enough signal. May need "why" categories:
   - Wrong industry
   - Too expensive
   - Too small
   - Red flags in description
   - Actually interesting

6. **Ollama model selection**: Test a few to find best balance of quality vs speed on 16GB VRAM:
   - Llama 3 8B (good general purpose)
   - Mistral 7B (fast, decent quality)
   - Phi-3 medium (Microsoft, good reasoning)

7. **Rate limiting / anti-bot**: How aggressive can we be? Start conservative (1 req/sec, daily only).

---

## Tech Stack Summary

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language | Python | Ecosystem, Playwright support, LLM libraries |
| Dependency mgmt | Poetry | Per CLAUDE.md |
| Browser automation | Playwright | Modern, reliable, good Python API |
| Database | SQLite | Simple, local, good enough for volume |
| Scheduling | APScheduler or cron | Simple, reliable |
| Slack | slack-sdk | Official Python SDK |
| Local LLM | Ollama | Easy setup, good model support |
| Containerization | Docker | Eventually, for deployment consistency |

---

## Directory Structure (Proposed)

```
business_finder/
├── pyproject.toml
├── README.md
├── docs/
│   ├── OBJECTIVE.md
│   ├── BUSINESS_BROKERS.md
│   ├── SAAS_BROKERS.md
│   ├── SCORING_FRAMEWORK.md
│   └── ARCHITECTURE.md
├── src/
│   └── business_finder/
│       ├── __init__.py
│       ├── config.py
│       ├── db/
│       │   ├── __init__.py
│       │   ├── models.py
│       │   └── migrations/
│       ├── scrapers/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── ... (per-source)
│       ├── parsers/
│       │   ├── __init__.py
│       │   └── ... (per-source)
│       ├── scoring/
│       │   ├── __init__.py
│       │   ├── gates.py
│       │   └── dimensions.py
│       ├── slack/
│       │   ├── __init__.py
│       │   ├── notifier.py
│       │   └── feedback.py
│       ├── llm/
│       │   ├── __init__.py
│       │   └── ollama.py
│       └── cli.py
├── scripts/
│   └── ... (adhoc exploration scripts)
├── tests/
│   └── ...
└── docker/
    └── Dockerfile
```
