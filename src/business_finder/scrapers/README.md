# Scrapers

## Microns.io

**Source:** https://www.microns.io
**Listings URL:** `/online-businesses-and-startups-for-sale`
**Total listings:** ~350 (as of 2026-01-21)

### Categories

Discovered via full site scan on 2026-01-21:

| Category | Count | % | Status |
|----------|-------|---|--------|
| Micro-SaaS | 112 | 32.0% | **Include** |
| Web app | 49 | 14.0% | **Include** |
| Mobile app | 39 | 11.1% | **Include** |
| (Uncategorized) | 35 | 10.0% | **Include** (review manually) |
| Newsletter | 31 | 8.9% | Blacklist - content business |
| E-commerce | 29 | 8.3% | Blacklist - product business |
| Marketplace | 14 | 4.0% | Blacklist - platform/product |
| Directory | 12 | 3.4% | Blacklist - content/SEO |
| Browser Extension | 11 | 3.1% | **Include** |
| Agency | 8 | 2.3% | Blacklist - service business |
| Content | 5 | 1.4% | Blacklist - content business |
| Community | 5 | 1.4% | Blacklist - engagement-based |

### Blacklisted Categories

These categories are excluded because we're focused on software/SaaS, not content or product businesses:

```python
CATEGORY_BLACKLIST = [
    "Newsletter",
    "E-commerce",
    "Marketplace",
    "Directory",
    "Agency",
    "Content",
    "Community",
]
```

**Result:** ~246 listings pass category filter (70% of total)

### Pagination

- URL pattern: `?c150de50_page=N`
- Pages are 1-indexed (page 1 = first page)
- 12 listings per page
- ~30 pages total

### Card Structure

On the listings page, card text is structured as:
```
[0] Title
[1] Description
[2] Category
[3] Revenue (e.g., "$54,200")
[4] "Annual Revenue"
[5] Price (e.g., "$230,000")
[6] "Asking Price"
```

### Detail Page Selectors (updated 2026-01-21)

- Title: `h2.h2-heading-2`
- Category: `.listing_tag_holder`
- Asking Price: `h3.h3-heading-2` inside `.seller-listing_priceholder`
- ARR: `h5.h5-heading-2` or `h5.h5-heading` (sibling to "ARR" label)
- Customers: `h5.h5-heading` (sibling to "Customers" label)
- Launched Year: `h5.h5-heading` (sibling to "Launched" label)
- Posted Date: `.listing_date-holder` (contains "Published on\n{date}")
- Description: `p` after "Startup description" label, fallback to `div.body-text.opacity70`

### Extracted Fields

| Field | Type | Description |
|-------|------|-------------|
| title | string | Business name |
| category | string | Business type (e.g., "Micro-SaaS") |
| asking_price | int (cents) | Listed sale price |
| annual_revenue | int (cents) | 12-month revenue (ARR for SaaS, TTM for others) |
| customers | int | Number of customers |
| launched_year | int | Year business was started |
| posted_at | datetime | When listing was posted to Microns |
| description | string | Business description |
