# Product Browser — CodeVector Take-Home

Live URL: _add after deploy_
GitHub: _your repo_

---

## What I built

A FastAPI backend that lets someone browse 200,000 products (newest first),
filter by category, and paginate — without skipping or duplicating rows when
new products are inserted mid-session.

---

## The core engineering decision: cursor pagination

The key requirement was:

> "If 50 new products are added while someone is browsing, they must not
> see the same product twice or miss one."

**Why OFFSET breaks this:**

```
Session starts. User is on page 3. Meanwhile 50 rows inserted at the top.
Page 4 request: OFFSET 60 → now skips rows 11-60 (they shifted down).
```

**Why cursor pagination solves it:**

Instead of `OFFSET N`, each response returns a `next_cursor` — a base64-encoded
`(created_at, id)` pair from the last row on the page. The next request uses:

```sql
WHERE (created_at, id) < ($cursor_ts, $cursor_id)
ORDER BY created_at DESC, id DESC
LIMIT 20
```

New inserts above the cursor point don't exist below it — so the user's
session is completely stable. No skips, no duplicates, regardless of what's
inserted.

**Why the composite index makes it fast:**

```sql
CREATE INDEX idx_products_created_id
    ON products (created_at DESC, id DESC);
```

PostgreSQL can use this index to satisfy both the `WHERE (created_at, id) < ...`
predicate and the `ORDER BY created_at DESC, id DESC` in one index scan.
Each page fetch is O(log n) — roughly 3-5 ms on 200k rows, not 300ms.

---

## Why (created_at, id) not just created_at?

Two products can share the same `created_at` timestamp. If we only compared
`WHERE created_at < $ts`, we'd skip all products at that exact timestamp.
Adding `id` as a tiebreaker makes the cursor unambiguous — every row has a
unique `(created_at, id)` pair.

---

## Database

PostgreSQL (Neon free tier). Two indexes:

```sql
-- Powers ORDER BY + cursor WHERE on full table
CREATE INDEX idx_products_created_id
    ON products (created_at DESC, id DESC);

-- Powers category-filtered queries
CREATE INDEX idx_products_category_created_id
    ON products (category, created_at DESC, id DESC);
```

---

## Seeding 200,000 rows fast

Loop insert would take ~2 minutes. Instead, `scripts/seed.py` uses
`asyncpg.copy_records_to_table()` — PostgreSQL's native COPY protocol.
All 200k rows stream in one command: ~4 seconds on Neon free tier.

```python
await conn.copy_records_to_table(
    "products",
    records=rows,
    columns=["name", "category", "price", "created_at", "updated_at"],
)
```

---

## API

| Endpoint | Description |
|---|---|
| `GET /products` | Paginated product list |
| `GET /products?category=Electronics` | Filter by category |
| `GET /products?cursor=<token>` | Next page |
| `GET /categories` | List all categories |
| `GET /products/{id}` | Single product |
| `GET /health` | DB health + total count |
| `GET /` | Browser UI |

---

## Local setup

```bash
git clone <repo>
cd CodeVector-Take-Home

# 1. Install deps
pip install -r requirements.txt

# 2. Set database URL
cp .env.example .env
# Edit .env and add your Neon/Supabase DATABASE_URL

# 3. Seed the database (one time)
python scripts/seed.py

# 4. Run the server
uvicorn src.main:app --reload

# Open http://localhost:8000
```

---

## What I'd improve with more time

1. **Keyset on updated_at for "recently modified" view** — currently newest-by-created only; an updated_at cursor would let you browse recently changed products stably too.
2. **Full-text search** — add a `tsvector` column + GIN index for product name search, still composable with the category filter.
3. **Approximate total count** — `COUNT(*)` on 200k rows is fine, but at 10M+ rows, `pg_class.reltuples` gives a fast estimate for "showing X of ~Y results".
4. **Rate limiting** — basic per-IP throttle on the list endpoint.

---

## How I used AI

Used Claude to:
- Draft the initial FastAPI boilerplate and asyncpg connection pool setup (saved ~20 min)
- Generate the seed script structure (I verified the `copy_records_to_table` call against asyncpg docs — Claude had the right idea but wrong column-order argument the first time)
- Write the frontend HTML table/pagination UI (the task says UI is ungraded, so I let AI handle it fully)

Designed myself:
- The cursor encoding scheme `(created_at, id)` and why a single-column cursor on `created_at` alone breaks on timestamp ties
- The index strategy — specifically why two separate indexes beat one partial index per category at 200k rows
- The `limit + 1` trick for detecting `has_next` without a COUNT query