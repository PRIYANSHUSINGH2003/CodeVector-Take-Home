from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncpg, os, base64, json
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
print("DATABASE_URL =", DATABASE_URL) 
pool = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10,ssl="require")
    yield
    await pool.close()

app = FastAPI(title="Product Browser API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

CATEGORIES = ["Electronics","Clothing","Books","Home","Sports",
              "Beauty","Toys","Automotive","Garden","Food"]

def encode_cursor(created_at: datetime, id: int) -> str:
    payload = {"t": created_at.isoformat(), "id": id}
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

def decode_cursor(cursor: str):
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
        return datetime.fromisoformat(payload["t"]), int(payload["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid cursor")

@app.get("/", include_in_schema=False)
async def serve_ui():
    ui_path = os.path.join(os.path.dirname(__file__), "index.html")
    return FileResponse(ui_path)

@app.get("/products")
async def list_products(
    category: Optional[str] = Query(None),
    cursor:   Optional[str] = Query(None),
    limit:    int           = Query(20, ge=1, le=100),
):
    """
    Newest-first product listing with cursor-based pagination.

    Why cursor, not OFFSET?
    ───────────────────────
    OFFSET shifts when rows are inserted at the top — users skip or
    see duplicates. A (created_at, id) cursor anchors to the last row
    seen; new inserts above it are invisible to the current session.
    Composite index on (created_at DESC, id DESC) keeps each page O(log n).
    """
    async with pool.acquire() as conn:
        if cursor:
            cur_ts, cur_id = decode_cursor(cursor)
            if category:
                rows = await conn.fetch(
                    "SELECT id,name,category,price,created_at,updated_at FROM products "
                    "WHERE category=$1 AND (created_at,id)<($2,$3) "
                    "ORDER BY created_at DESC,id DESC LIMIT $4",
                    category, cur_ts, cur_id, limit + 1,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id,name,category,price,created_at,updated_at FROM products "
                    "WHERE (created_at,id)<($1,$2) "
                    "ORDER BY created_at DESC,id DESC LIMIT $3",
                    cur_ts, cur_id, limit + 1,
                )
        else:
            if category:
                rows = await conn.fetch(
                    "SELECT id,name,category,price,created_at,updated_at FROM products "
                    "WHERE category=$1 ORDER BY created_at DESC,id DESC LIMIT $2",
                    category, limit + 1,
                )
            else:
                rows = await conn.fetch(
                    "SELECT id,name,category,price,created_at,updated_at FROM products "
                    "ORDER BY created_at DESC,id DESC LIMIT $1",
                    limit + 1,
                )

    has_next = len(rows) > limit
    rows     = rows[:limit]
    items = [{"id":r["id"],"name":r["name"],"category":r["category"],
              "price":float(r["price"]),"created_at":r["created_at"].isoformat(),
              "updated_at":r["updated_at"].isoformat()} for r in rows]
    next_cursor = encode_cursor(rows[-1]["created_at"], rows[-1]["id"]) if has_next and rows else None
    return {"items": items, "next_cursor": next_cursor, "has_next": has_next, "count": len(items)}

@app.get("/categories")
async def list_categories():
    return {"categories": CATEGORIES}

@app.get("/products/{product_id}")
async def get_product(product_id: int):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id,name,category,price,created_at,updated_at FROM products WHERE id=$1",
            product_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Product not found")
    return dict(row)

@app.get("/health")
async def health():
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM products")
    return {"status": "ok", "product_count": count}