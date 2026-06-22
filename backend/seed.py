"""
seed.py — Generate 200,000 products fast using PostgreSQL COPY.
"""

import asyncio
import asyncpg
import os
import random
import socket
import string
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from urllib.parse import urlparse, urlunparse

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]

CATEGORIES = ["Electronics","Clothing","Books","Home","Sports",
              "Beauty","Toys","Automotive","Garden","Food"]
ADJECTIVES  = ["Premium","Classic","Ultra","Pro","Lite","Smart",
               "Eco","Flex","Turbo","Mega","Mini","Super"]
NOUNS       = ["Widget","Gadget","Device","Tool","Kit","Pack",
               "Set","Bundle","Series","Edition","Model","Unit"]
TOTAL = 200_000

def random_name():
    return f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)} {''.join(random.choices(string.ascii_uppercase+string.digits,k=4))}"

def random_price():
    return round(random.uniform(1.99, 9999.99), 2)

def random_dt(start, end):
    return start + timedelta(seconds=random.randint(0, int((end-start).total_seconds())))

def resolve_to_ipv4(url: str) -> str:
    """Replace hostname with its IPv4 address to avoid IPv6 issues on Windows."""
    parsed = urlparse(url)
    host   = parsed.hostname
    try:
        # getaddrinfo with AF_INET forces IPv4 only
        infos = socket.getaddrinfo(host, parsed.port or 5432, socket.AF_INET, socket.SOCK_STREAM)
        ipv4  = infos[0][4][0]
        print(f"  Resolved {host} → {ipv4} (IPv4)")
        # Rebuild URL with IP instead of hostname
        netloc = f"{parsed.username}:{parsed.password}@{ipv4}:{parsed.port or 5432}"
        return urlunparse(parsed._replace(netloc=netloc))
    except Exception as e:
        print(f"  IPv4 resolve failed ({e}), using original URL")
        return url

async def main():
    print("Connecting to database...")

    resolved_url = resolve_to_ipv4(DATABASE_URL)

    try:
        conn = await asyncpg.connect(
            resolved_url,
            ssl="require",
            server_settings={"application_name": "seed_script"},
        )
    except Exception as e:
        print(f"\n❌ Connection failed: {e}")
        print("\nNext step: use Neon instead of Supabase direct connection.")
        print("  1. Go to https://neon.tech → sign up free")
        print("  2. New Project → copy connection string")
        print("  3. Replace DATABASE_URL in .env")
        return

    print("✅ Connected!\n")

    print("Creating table + indexes...")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id         BIGSERIAL PRIMARY KEY,
            name       TEXT          NOT NULL,
            category   TEXT          NOT NULL,
            price      NUMERIC(10,2) NOT NULL,
            created_at TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ   NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS idx_products_created_id
            ON products (created_at DESC, id DESC);
        CREATE INDEX IF NOT EXISTS idx_products_category_created_id
            ON products (category, created_at DESC, id DESC);
    """)
    print("✅ Table + indexes ready!\n")

    print(f"Building {TOTAL:,} rows in memory...")
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=730)
    rows  = []
    for _ in range(TOTAL):
        ts = random_dt(start, now)
        rows.append((random_name(), random.choice(CATEGORIES), random_price(), ts, ts))
    print(f"✅ {TOTAL:,} rows ready — inserting via COPY...\n")

    await conn.copy_records_to_table(
        "products",
        records=rows,
        columns=["name","category","price","created_at","updated_at"],
    )

    count = await conn.fetchval("SELECT COUNT(*) FROM products")
    print(f"✅ Done! Total products in DB: {count:,}\n")

    sample = await conn.fetch(
        "SELECT id,name,category,price FROM products ORDER BY created_at DESC,id DESC LIMIT 3"
    )
    print("Top 3 rows (newest first):")
    for r in sample:
        print(f"  id={r['id']}  {r['name']:<32} {r['category']:<14} ${r['price']}")

    await conn.close()

if __name__ == "__main__":
    asyncio.run(main())