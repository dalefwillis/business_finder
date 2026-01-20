# Business Acquisition Framework

## Overview

Tool to search, score, and prioritize franchises and existing businesses for acquisition.

**Target outcomes:**
- Tier A: Income replacement ($200k+ SDE)
- Tier B: Supplemental income / side project ($1k+ MRR)

---

## Tier Classification

| Tier | Definition | Price Range | Min Customers | Geography |
|------|------------|-------------|---------------|-----------|
| **A** | Income replacement potential | $100k–$3M | ≥5 paying | Within 2hrs of Madison |
| **B** | Supplement/side project | $10k–$100k | ≥5 paying | Anywhere US |

*Both tiers equally valuable—classification determines evaluation context, not priority.*

---

## Hard Gates (Pass/Fail)

Reject before scoring if any gate fails:

| Gate | Rule | Rationale |
|------|------|-----------|
| **Profitable** | SDE > 0 | No pre-revenue, no VC burn models |
| **Real customers** | ≥5 paying, non-founder-affiliated | Proven traction signal |
| **Business model** | B2B SaaS preferred | Predictable revenue, scalable |
| **Excluded categories** | Content/YouTube, ecomm, mobile apps, food, lawncare, daycare, construction, B2C | Operator fit / preference |
| **Acquisition ceiling** | 10% down ≤ $350k | Max ~$3.5M purchase price |
| **Infrastructure** | Not on-prem | No "rewrite everything for cloud" projects |
| **Domain licensing** | No deep domain license required | Unless license is transferable |

---

## Scoring Dimensions

Total score = weighted sum, max 100 points.

| Dimension | Weight | Metric | 10 pts | 7 pts | 4 pts | 1 pt |
|-----------|--------|--------|--------|-------|-------|------|
| **Payback period** | 20% | Price ÷ Annual SDE | <1 yr | 1–2 yr | 2–3 yr | >3 yr |
| **Revenue quality** | 20% | MRR %, churn rate | >90% recurring, <2% mo churn | >80%, <4% | >60%, <6% | <60% or >6% |
| **Customer concentration** | 15% | Top customer % of rev | <10% | 10–20% | 20–40% | >40% |
| **Market tailwinds** | 10% | TAM growth rate | >10% CAGR | 5–10% | 2–5% | Flat/declining |
| **Operational load** | 10% | Steady-state hrs/week | <5 | 5–10 | 10–20 | >20 |
| **Seller motivation** | 10% | Why selling | Serial entrepreneur | Retirement | Burnout | Distressed/evasive |
| **Defensibility** | 5% | Switching costs, moat | Deep integrations | Moderate | Commodity | Zero moat |
| **Growth levers** | 5% | Executable upsell paths | 3+ clear | 2 | 1 | None |
| **Tech stack** | 5% | Maintainability | Modern cloud-native | Dated but OK | Legacy functional | On-prem/rewrite |

---

## Seller Motivation Scoring Guide

| Signal | Score | Notes |
|--------|-------|-------|
| "Built it, bored, want new thing" | 10 | Serial entrepreneur—clean handoff likely |
| "Retiring / life event" | 8 | Usually clean, motivated to transition well |
| "Too many projects" | 7 | Distraction sale—verify neglect level |
| "Burned out" | 5 | Dig into whether product/market or just founder |
| "Need cash fast" | 3 | Red flag—why? Hard DD required |
| Vague / evasive | 2 | Likely hiding something |

---

## Capex Requirement (Relative Rule)

Not a hard gate—evaluated contextually:

| Scenario | Rule |
|----------|------|
| Business is cash-flow positive | Additional capex from profits → OK |
| Requires out-of-pocket before profit | OOP ≤ max(10% of purchase price, $15k) |

---

## Revenue Quality Details

### Churn Thresholds
| Monthly Churn | Score Impact |
|---------------|--------------|
| <2% | Full points |
| 2–4% | Minor penalty |
| 4–6% | Moderate penalty |
| >6% | Major penalty / possible gate |

### Customer Concentration Risk
| Top Customer Revenue % | Risk Level |
|------------------------|------------|
| <10% | Low—diversified |
| 10–20% | Acceptable |
| 20–40% | Elevated—DD on relationship |
| >40% | High—key-man risk |

---

## Tech Stack Scoring Guide

| Category | Examples | Score |
|----------|----------|-------|
| Modern cloud-native | Python, Node/TS, Go, Postgres, AWS/GCP, Docker | 10 |
| Dated but manageable | PHP 7+, Ruby, MySQL, Heroku | 7 |
| Legacy but functional | Older PHP, .NET Core, monolith | 4 |
| Problematic | On-prem, .NET Framework, requires full rewrite | 1 |

---

## Data Sources

### Tier B: SaaS/Software Marketplaces

| Platform | Deal Flow | Fee Structure | Verification | Notes |
|----------|-----------|---------------|--------------|-------|
| **Acquire.com** | Primary — best SaaS inventory in sub-$100k | 8% seller fee, free for buyers | Stripe MRR verification, integrated | Dominant platform for this tier |
| **Flippa** | High volume, high noise | ~10% success fee | Minimal — buyer beware | Filter aggressively; lots of content/ecom |
| **Microns.io** | Curated, smaller deals | Flat fee model | Light vetting | Good for micro-SaaS <$30k |
| **Little Exits** | Newsletter/curated | Free newsletter | Curated by operator | Weekly deals, fast-moving |
| **Indie Hackers** | Community/forum | None (direct deals) | None | Relationship-based, less formal |
| **Twitter/X** | Founders posting exits | None | None | Follow #buildinpublic, SaaS founders |

**Not useful for Tier B:**
- Empire Flippers — $50k+ minimum, mostly content sites
- FE International — $100k+ minimum, longer sales cycles
- Quiet Light — $100k+ minimum

### Tier A: Traditional Business Marketplaces

| Platform | Deal Flow | Fee Structure | Notes |
|----------|-----------|---------------|-------|
| **BizBuySell** | Largest traditional marketplace | Varies by broker | Mix of broker and FSBO listings |
| **BizQuest** | Similar to BizBuySell | Varies | Owned by same parent company |
| **LoopNet** | Commercial RE + businesses | Broker-dependent | Better for RE-heavy businesses |
| **Franchise brokers** | Franchise resales | 10-15% typically | FranNet, Transworld, local brokers |
| **Business brokers** | Local/regional deals | 10-12% of sale price | IBBA member directory |
| **Acquire.com** | Larger SaaS ($100k-$5M) | 8% seller | Good for tech-enabled Tier A |

### Tier A: Franchise-Specific

| Source | Type | Notes |
|--------|------|-------|
| **Franchise Resales** | Existing territories | FranNet, Transworld, direct from franchisors |
| **FDD databases** | Research | FRANdata, Franchise Grade |
| **Franchisor direct** | New territories | Usually less interesting than resales |

### Deal Sourcing Strategy

**Tier B Priority:**
1. Acquire.com daily scan (set up alerts)
2. Microns.io weekly newsletter
3. Little Exits weekly newsletter
4. Flippa filtered search (SaaS only, >$1k MRR, exclude content)

**Tier A Priority:**
1. BizBuySell alerts (filtered by geography, industry)
2. Local business broker relationships
3. Acquire.com for tech-enabled businesses
4. Franchise broker if going that route

### Valuation Expectations by Source

| Tier | Typical Multiple | Basis |
|------|------------------|-------|
| Tier B (<$100k) | 2-4x annual profit | SDE or net profit |
| Tier A ($100k-$1M) | 2.5-4x SDE | Seller's discretionary earnings |
| Tier A ($1M-$3M) | 3-5x SDE | More competition, cleaner books |
| Franchise resale | 2-3x SDE | Varies by brand strength |

---

## Implementation Notes

### Ingestion Pipeline
1. Scrape/API pull from data sources
2. Parse listing → structured fields
3. Apply hard gates → pass/reject
4. Calculate weighted score
5. Flag missing data for manual review
6. Rank and surface top candidates

### Key Fields to Extract
- Asking price
- Revenue (MRR or annual)
- SDE / profit margin
- Customer count
- Churn rate (if disclosed)
- Tech stack
- Seller stated reason
- Time commitment estimate
- Location (for Tier A)

### Scoring Output
```
{
  "listing_id": "...",
  "source": "acquire.com",
  "tier": "B",
  "gates_passed": true,
  "gate_failures": [],
  "score": 72,
  "score_breakdown": {
    "payback": 7,
    "revenue_quality": 8,
    "customer_concentration": 10,
    ...
  },
  "flags": ["churn not disclosed", "tech stack unclear"],
  "recommendation": "review"
}
```

---

## Franchise-Specific Scoring

When evaluating franchise opportunities, apply standard scoring dimensions plus these franchise-specific factors:

### Franchise Hard Gates

| Gate | Rule |
|------|------|
| FDD available | Must have current FDD for review |
| Territory protection | Exclusive territory required |
| Transfer allowed | Franchisor permits resale to new buyer |
| No litigation red flags | Item 3 (litigation) clean or explainable |

### Franchise Scoring Dimensions (Replace/Augment Standard)

| Dimension | Weight | Metric | 10 | 7 | 4 | 1 |
|-----------|--------|--------|-----|---|---|---|
| **Royalty load** | 15% | Royalty + brand fund % | <5% | 5-7% | 7-10% | >10% |
| **Franchisee success** | 15% | Item 20 turnover, closures | <10% 3yr failure | 10-15% | 15-25% | >25% |
| **Unit economics** | 15% | Item 19 financials (if disclosed) | Top quartile | Median | Below median | Not disclosed |
| **Territory quality** | 10% | Demographics, competition density | Underserved, growing | Adequate | Saturated | Declining |
| **Franchisor support** | 10% | Training, ongoing support quality | Strong rep, good reviews | Adequate | Mixed reviews | Poor/absent |
| **Brand strength** | 5% | Recognition, NPS, market position | Category leader | Known regional | Unknown | Negative reputation |

### Franchise Fee Analysis Template

For any franchise, calculate total effective fee load:

```
Gross Revenue:                    $X
- Royalty (X%):                   -$Y
- Brand/Marketing Fund (X%):      -$Y
- Technology Fee (flat or %):     -$Y
- Required vendor markup (est):   -$Y
= Effective Take-Home Revenue:    $Z
Effective Fee Rate:               (X-Z)/X = ___%
```

### FDD Red Flags Checklist

- [ ] Item 3: Significant litigation history
- [ ] Item 4: Bankruptcy history
- [ ] Item 5: High initial fees relative to competition
- [ ] Item 6: Hidden ongoing fees (tech, required purchases)
- [ ] Item 19: No financial performance representations (or poor numbers)
- [ ] Item 20: High franchisee turnover (>20% in 3 years)
- [ ] Item 21: Audited financials show franchisor struggling

---

## Data Storage & Pipeline

### Phase 1: Database + Export (Current)

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Ingest    │────▶│   SQLite/   │────▶│   Export    │
│  (scrapers) │     │   Postgres  │     │  to Sheets  │
└─────────────┘     └─────────────┘     └─────────────┘
```

**Storage Schema** (see Implementation Notes)
- Raw listings table
- Scored listings table
- Flags/notes table
- Export command → Google Sheets for review

### Phase 2: Pipeline Tracker (Future)

Potential integrations when volume warrants:
- Notion database (kanban for pipeline stages)
- Trello board (simple card-based tracking)
- Airtable (if more structured views needed)

### Pipeline Stages

```
Ingested → Scored → Review → DD in Progress → LOI → Closed/Passed
```

---

## Design Decisions

| Question | Decision |
|----------|----------|
| Geography for Tier A | 2 hours **driving time** from Madison |
| Scoring weights | Starting point; will adjust after seeing real listings |
| Franchise handling | Separate scoring overlay (see above) |
| Tracking system | Database first, export to Sheets; future Notion/Trello |
