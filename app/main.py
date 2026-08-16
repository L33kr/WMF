import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db, db
from .config import HISTORY_RETENTION_DAYS
from .wfm import WFMClient
from .collector import Collector


client = WFMClient()
collector = Collector(client)

STATIC_DIR = (
    Path(__file__).resolve().parent.parent
    / "static"
)


def spawn(coro):
    return asyncio.create_task(coro)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    tasks = [
        spawn(collector.rest_loop()),
        spawn(collector.ws_loop()),
    ]

    async def prune():
        while not collector.stop.is_set():
            try:
                with db() as c:
                    c.execute(
                        """
                        DELETE FROM price_history
                        WHERE ts < ?
                        """,
                        (
                            time.time()
                            - HISTORY_RETENTION_DAYS * 86400,
                        ),
                    )
            except Exception as exc:
                print(
                    f"[WFM] history cleanup error: {exc}"
                )

            await asyncio.sleep(3600)

    tasks.append(
        spawn(prune())
    )

    try:
        yield
    finally:
        collector.stop.set()

        for task in tasks:
            task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        await client.close()


app = FastAPI(
    title="WFM Trader API",
    version="2.0.0",
    lifespan=lifespan,
)

app.mount(
    "/static",
    StaticFiles(
        directory=STATIC_DIR
    ),
    name="static",
)


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    include_in_schema=False,
)
def home():
    return FileResponse(
        STATIC_DIR / "index.html"
    )


# ============================================================
# HEALTH
# ============================================================

@app.get("/api/health")
def health():
    with db() as c:
        total = c.execute(
            """
            SELECT COUNT(*)
            FROM items
            """
        ).fetchone()[0]

        priced = c.execute(
            """
            SELECT COUNT(*)
            FROM market
            """
        ).fetchone()[0]

    return {
        "ok": True,
        "items": total,
        "priced_items": priced,
        "time": time.time(),
    }


# ============================================================
# STATS
# ============================================================

@app.get("/api/stats")
def stats_api():
    with db() as c:
        row = c.execute(
            """
            SELECT
                COUNT(*) AS items,
                (
                    SELECT COUNT(*)
                    FROM market
                ) AS priced,
                AVG(m.liquidity)
                    AS avg_liquidity,
                MAX(m.updated_at)
                    AS last_update
            FROM items AS i
            LEFT JOIN market AS m
                ON m.item_id = i.id
            """
        ).fetchone()

    return dict(row)


# ============================================================
# SORTING
# ============================================================

SORTS = {
    "name": "i.name",
    "min": "m.min_price",
    "median": "m.median",
    "roi": """
        CASE
            WHEN
                m.min_price > 0
                AND m.median IS NOT NULL
            THEN
                (
                    m.median - m.min_price
                )
                / m.min_price
            ELSE NULL
        END
    """,
    "buy": "m.buy_max",
    "sellers": "m.sellers",
    "buyers": "m.buyers",
    "liquidity": "m.liquidity",
    "score": "m.score",
    "updated": "m.updated_at",
}


# ============================================================
# ALL ITEMS
# ============================================================

@app.get("/api/items")
def items(
    search: str = "",
    min_price: float | None = None,
    max_price: float | None = None,
    min_roi: float | None = None,
    min_liquidity: float | None = None,
    sort: str = "score",
    order: str = "desc",
    page: int = 1,
    page_size: int = 100,
):
    page = max(
        1,
        page,
    )

    page_size = max(
        1,
        min(
            500,
            page_size,
        ),
    )

    conditions = [
        "1=1"
    ]

    params = []

    # Search
    if search:
        conditions.append(
            """
            (
                i.name LIKE ?
                OR i.slug LIKE ?
            )
            """
        )

        pattern = f"%{search}%"

        params.extend(
            [
                pattern,
                pattern,
            ]
        )

    # Min price
    if min_price is not None:
        conditions.append(
            "m.min_price >= ?"
        )
        params.append(
            min_price
        )

    # Max price
    if max_price is not None:
        conditions.append(
            "m.min_price <= ?"
        )
        params.append(
            max_price
        )

    # Min liquidity
    if min_liquidity is not None:
        conditions.append(
            """
            COALESCE(
                m.liquidity,
                0
            ) >= ?
            """
        )
        params.append(
            min_liquidity
        )

    # Min ROI
    if min_roi is not None:
        conditions.append(
            """
            CASE
                WHEN
                    m.min_price > 0
                    AND m.median IS NOT NULL
                THEN
                    (
                        m.median -
                        m.min_price
                    )
                    /
                    m.min_price
                    * 100
                ELSE -999
            END >= ?
            """
        )
        params.append(
            min_roi
        )

    where_sql = (
        " AND ".join(
            conditions
        )
    )

    sort_sql = SORTS.get(
        sort,
        SORTS["score"],
    )

    direction = (
        "ASC"
        if order.lower() == "asc"
        else "DESC"
    )

    with db() as c:

        # Total
        total = c.execute(
            f"""
            SELECT COUNT(*)
            FROM items AS i
            LEFT JOIN market AS m
                ON m.item_id = i.id
            WHERE
                {where_sql}
            """,
            params,
        ).fetchone()[0]

        # Rows
        offset = (
            page - 1
        ) * page_size

        rows = c.execute(
            f"""
            SELECT
                i.id,
                i.slug,
                i.name,
                i.category,

                i.updated_at
                    AS item_updated,

                m.min_price,
                m.median,
                m.avg_price,
                m.p25,
                m.p75,
                m.buy_max,
                m.sellers,
                m.buyers,
                m.liquidity,
                m.score,

                m.updated_at
                    AS market_updated

            FROM items AS i

            LEFT JOIN market AS m
                ON m.item_id = i.id

            WHERE
                {where_sql}

            ORDER BY
                {sort_sql}
                {direction},
                i.name ASC

            LIMIT ?
            OFFSET ?
            """,
            [
                *params,
                page_size,
                offset,
            ],
        ).fetchall()

    result = []

    for row in rows:
        item = dict(row)

        if (
            item["median"] is not None
            and item["min_price"] is not None
            and item["min_price"] > 0
        ):
            item["roi"] = round(
                (
                    (
                        item["median"]
                        -
                        item["min_price"]
                    )
                    /
                    item["min_price"]
                )
                * 100,
                1,
            )
        else:
            item["roi"] = None

        result.append(
            item
        )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result,
    }


# ============================================================
# SINGLE ITEM
# ============================================================

@app.get(
    "/api/items/{slug}"
)
def item(
    slug: str,
):
    with db() as c:
        row = c.execute(
            """
            SELECT
                i.id,
                i.slug,
                i.name,
                i.category,

                i.updated_at
                    AS item_updated,

                m.min_price,
                m.median,
                m.avg_price,
                m.p25,
                m.p75,
                m.buy_max,
                m.sellers,
                m.buyers,
                m.seller_qty,
                m.buyer_qty,
                m.liquidity,
                m.score,

                m.updated_at
                    AS market_updated

            FROM items AS i

            LEFT JOIN market AS m
                ON m.item_id = i.id

            WHERE
                i.slug = ?
            """,
            (
                slug,
            ),
        ).fetchone()

        if not row:
            raise HTTPException(
                status_code=404,
                detail="Item not found",
            )

        history = c.execute(
            """
            SELECT
                ts,
                min_price,
                median,
                buy_max,
                liquidity,
                score

            FROM price_history

            WHERE
                item_id = ?

            ORDER BY
                ts DESC

            LIMIT 300
            """,
            (
                row["id"],
            ),
        ).fetchall()

    return {
        "item": dict(row),
        "history": [
            dict(entry)
            for entry in reversed(
                history
            )
        ],
    }


# ============================================================
# QUEUE REFRESH
# ============================================================

@app.post(
    "/api/items/{slug}/refresh"
)
def refresh(
    slug: str,
):
    with db() as c:
        row = c.execute(
            """
            SELECT id
            FROM items
            WHERE slug = ?
            """,
            (
                slug,
            ),
        ).fetchone()

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Item not found",
        )

    collector.mark(
        row["id"]
    )

    return {
        "ok": True,
        "queued": True,
        "slug": slug,
    }


# ============================================================
# BEST DEALS
# ============================================================

@app.get("/api/deals")
def deals(
    limit: int = 100,
    min_roi: float = 10,
    min_liquidity: float = 50,
):
    limit = max(
        1,
        min(
            500,
            limit,
        ),
    )

    with db() as c:
        rows = c.execute(
            """
            SELECT
                i.slug,
                i.name,

                m.min_price,
                m.median,
                m.buy_max,

                m.sellers,
                m.buyers,

                m.liquidity,
                m.score,

                m.updated_at

            FROM market AS m

            JOIN items AS i
                ON i.id = m.item_id

            WHERE
                m.min_price IS NOT NULL

                AND m.median IS NOT NULL

                AND m.min_price > 0

                AND m.median >
                    m.min_price

                AND m.liquidity >= ?

            ORDER BY
                m.score DESC

            LIMIT ?
            """,
            (
                min_liquidity,
                limit,
            ),
        ).fetchall()

    result = []

    for row in rows:
        item = dict(row)

        if (
            item["min_price"] is None
            or
            item["median"] is None
            or
            item["min_price"] <= 0
        ):
            continue

        roi = (
            (
                item["median"]
                -
                item["min_price"]
            )
            /
            item["min_price"]
        ) * 100

        if roi < min_roi:
            continue

        item["roi"] = round(
            roi,
            1,
        )

        item["profit"] = round(
            item["median"]
            -
            item["min_price"],
            1,
        )

        result.append(
            item
        )

    return result
