"""
Trading section for F.K. AI Assistant v4:
  - Trading Academy: structured lessons + curated, real YouTube channels
  - Market Watch: live quotes for a personal watchlist (Yahoo Finance's
    public chart endpoint, no API key required)
  - Trading Journal: log trades and see win-rate / P&L stats

Nothing here executes real trades or gives personalized buy/sell signals —
it is education, live reference data, and a personal record-keeping tool.
"""
import requests
from fastapi import Depends, HTTPException
from pydantic import BaseModel

RISK_DISCLAIMER = (
    "Educational content only — not financial advice. Trading and investing "
    "involve real risk of loss, including loss of your entire principal. "
    "Past performance and hypothetical examples do not guarantee future "
    "results. Do your own research and consider talking to a licensed "
    "financial advisor before risking real money."
)

# ---------------------------------------------------------------------------
# Static curriculum. Kept as plain data (not user-editable) so it ships
# ready to use. Written to be accurate and neutral, not a trading signal
# service.
# ---------------------------------------------------------------------------
LESSONS = [
    {
        "id": "basics",
        "title": "Markets 101: what you're actually doing",
        "minutes": 10,
        "body": (
            "Trading means buying and selling a financial instrument — a "
            "stock, currency pair, commodity, crypto asset, or derivative "
            "— hoping to profit from a price change over a period ranging "
            "from seconds to years. Investing is usually the longer-horizon "
            "cousin of trading, focused on business fundamentals rather "
            "than short-term price swings.\n\n"
            "Every trade has two sides and a price is only 'right' in the "
            "sense that a willing buyer and seller agreed to it at that "
            "moment — it can go either direction afterward. A market order "
            "buys or sells immediately at the best available price; a "
            "limit order only fills at your chosen price or better; a stop "
            "order triggers a market or limit order once price reaches a "
            "level, commonly used to cap losses.\n\n"
            "Liquidity (how easily you can get in and out without moving "
            "the price) and volatility (how much price swings) are the two "
            "features that shape almost every other decision you'll make."
        ),
    },
    {
        "id": "order-types",
        "title": "Order types and how trades actually execute",
        "minutes": 8,
        "body": (
            "Market order: fills immediately at the best price available — "
            "fast, but in a fast-moving or thin market the fill price can "
            "differ from the last quoted price ('slippage').\n\n"
            "Limit order: only fills at your price or better. Gives price "
            "control but no guarantee of a fill.\n\n"
            "Stop (stop-loss) order: becomes a market order once a trigger "
            "price is touched. Widely used to define the maximum loss on a "
            "position before entering it.\n\n"
            "Stop-limit order: like a stop, but converts into a limit "
            "order rather than a market order once triggered — more price "
            "control, more risk of not filling in a fast drop.\n\n"
            "Time-in-force settings (day, good-till-cancelled, "
            "fill-or-kill) control how long an order stays live if it "
            "doesn't fill immediately."
        ),
    },
    {
        "id": "technical-analysis",
        "title": "Reading a chart: technical analysis basics",
        "minutes": 14,
        "body": (
            "Technical analysis studies price and volume history to gauge "
            "supply/demand and probability, not certainty. Candlesticks "
            "show open, high, low and close for a period; the body shows "
            "the open-close range, the wicks show the extremes.\n\n"
            "Support is a price area where buying pressure has repeatedly "
            "shown up; resistance is where selling pressure has. Trends "
            "are sequences of higher highs/higher lows (uptrend) or lower "
            "highs/lower lows (downtrend); range-bound markets oscillate "
            "between support and resistance instead.\n\n"
            "Common tools: moving averages (smooth price to show trend "
            "direction), RSI and MACD (momentum/overbought-oversold "
            "gauges), and volume (confirms or questions a price move — a "
            "breakout on light volume is weaker evidence than one on heavy "
            "volume).\n\n"
            "No indicator predicts the future. They're ways of organizing "
            "probability, and they work best combined with a risk plan, "
            "not used alone as a signal generator."
        ),
    },
    {
        "id": "risk-management",
        "title": "Risk management: the part that actually determines survival",
        "minutes": 12,
        "body": (
            "Position sizing: many traders risk a small, fixed percentage "
            "of their account on any single idea (commonly cited figures "
            "are in the 0.5%-2% range) so that a string of losses — which "
            "will happen to everyone — doesn't wipe the account.\n\n"
            "Risk/reward ratio: comparing how much you stand to lose "
            "against how much you stand to gain on a trade. A strategy can "
            "be profitable overall even with a win rate under 50% if "
            "winners are sized larger than losers, and unprofitable even "
            "with a high win rate if losers are left to run.\n\n"
            "A stop-loss defines your risk before you enter, not after. "
            "Diversification and correlation matter too — five 'different' "
            "positions that all move together during a shock behave like "
            "one large position.\n\n"
            "Leverage (margin, options, futures, CFDs) multiplies both "
            "gains and losses, and can force a loss beyond your original "
            "capital. Treat leverage as a risk-management topic first and "
            "a return-boosting topic a distant second."
        ),
    },
    {
        "id": "psychology",
        "title": "Trading psychology and common mistakes",
        "minutes": 9,
        "body": (
            "Loss aversion pushes people to hold losers hoping they'll "
            "recover, and sell winners too early to 'lock in' a gain — "
            "often the opposite of a sound rule-based exit.\n\n"
            "Revenge trading (increasing size right after a loss to 'win "
            "it back') and overtrading (trading out of boredom rather "
            "than an actual setup) are two of the most commonly cited "
            "account-killers.\n\n"
            "A trading journal — recording entry, exit, size, reasoning "
            "and outcome for every trade — is one of the most consistently "
            "recommended habits across professional and retail educators, "
            "because it turns vague impressions ('I feel like I lose on "
            "Fridays') into checkable facts. Use the Trading Journal tab "
            "in this app to keep one."
        ),
    },
    {
        "id": "strategies",
        "title": "Trading styles: day, swing, and position trading",
        "minutes": 10,
        "body": (
            "Day trading: positions opened and closed within the same "
            "day. Requires close attention, fast execution, and tight risk "
            "control; transaction costs and screen-time add up quickly.\n\n"
            "Swing trading: positions held for days to a few weeks, aiming "
            "to capture a 'swing' in price. Needs less constant attention "
            "than day trading but still requires an exit plan.\n\n"
            "Position trading / long-term investing: holding for months to "
            "years based on broader trend or fundamentals, tolerating "
            "short-term noise.\n\n"
            "None of these styles is inherently 'better' — they trade off "
            "time commitment, transaction costs, and the type of edge "
            "you're trying to exploit. Many educators recommend picking "
            "one style deliberately rather than drifting between them "
            "based on mood."
        ),
    },
    {
        "id": "options-basics",
        "title": "Options, in plain terms",
        "minutes": 11,
        "body": (
            "A call option gives the buyer the right (not the obligation) "
            "to buy an asset at a set 'strike' price before expiration; a "
            "put option gives the right to sell. Buyers pay a premium and "
            "can lose at most that premium; option sellers ('writers') can "
            "face much larger, sometimes theoretically unlimited, risk in "
            "exchange for collecting the premium.\n\n"
            "Options are priced using more variables than stocks: strike "
            "vs. current price, time to expiration (time decay works "
            "against option buyers), and implied volatility (the market's "
            "expectation of future price swings, which can rise or fall "
            "independent of the underlying price).\n\n"
            "Options are flexible but genuinely more complex than owning "
            "the underlying asset outright, and it's easy to underestimate "
            "how time decay and volatility changes affect a position even "
            "when the directional call was correct."
        ),
    },
    {
        "id": "glossary",
        "title": "Glossary of terms you'll hit constantly",
        "minutes": 6,
        "body": (
            "Bid/Ask: the highest price a buyer will pay / lowest price a "
            "seller will accept right now. Spread: the gap between them.\n"
            "Volume: number of units traded in a period.\n"
            "Volatility: magnitude of price swings.\n"
            "Drawdown: peak-to-trough decline in account value.\n"
            "Slippage: difference between expected and actual fill price.\n"
            "Long / Short: betting a price rises / falls.\n"
            "Margin: borrowed capital used to increase position size.\n"
            "Liquidity: how easily an asset trades without moving price.\n"
            "Market cap: share price × shares outstanding, for equities.\n"
            "P/E ratio: share price divided by earnings per share, a "
            "commonly used (imperfect) valuation shorthand."
        ),
    },
]

# ---------------------------------------------------------------------------
# Curated video resources — real, well-known educational channels. Linking
# to channel pages (stable) rather than individual videos, so the resource
# stays accurate over time.
# ---------------------------------------------------------------------------
VIDEO_RESOURCES = [
    {
        "title": "Investopedia",
        "url": "https://www.youtube.com/@Investopedia",
        "description": "The video arm of the reference site most traders "
                        "cite first — clear, jargon-defined explainers on "
                        "terms, order types, and market mechanics. The best "
                        "starting point if a word in this app is unfamiliar.",
    },
    {
        "title": "The Plain Bagel",
        "url": "https://www.youtube.com/@ThePlainBagel",
        "description": "Hosted by a CFA charterholder; calm, well-sourced "
                        "breakdowns of investing concepts, market history, "
                        "and the numbers behind trading claims you'll see "
                        "elsewhere online.",
    },
    {
        "title": "Rayner Teo / TradingwithRayner",
        "url": "https://www.youtube.com/@TradingwithRayner",
        "description": "Free, structured lessons on price action, chart "
                        "patterns and risk management aimed squarely at "
                        "beginner-to-intermediate traders.",
    },
    {
        "title": "Adam Khoo",
        "url": "https://www.youtube.com/@AdamKhoo",
        "description": "Singaporean trader and educator covering stock and "
                        "options trading fundamentals, technical analysis, "
                        "and portfolio-level thinking.",
    },
    {
        "title": "Warrior Trading",
        "url": "https://www.youtube.com/@WarriorTrading",
        "description": "Day-trading focused — live/recorded trade reviews "
                        "and scanner walkthroughs. Useful for seeing real "
                        "decision-making in action; treat the results shown "
                        "as illustrative, not typical.",
    },
]


def _rank_score(entry_price, exit_price, direction, quantity):
    if exit_price is None:
        return None
    diff = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
    return diff * quantity


class TradeRequest(BaseModel):
    symbol: str
    direction: str = "long"
    entry_price: float
    exit_price: float | None = None
    quantity: float = 1
    entry_at: str
    exit_at: str | None = None
    notes: str = ""
    status: str = "open"


class TradeUpdateRequest(BaseModel):
    symbol: str | None = None
    direction: str | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    quantity: float | None = None
    entry_at: str | None = None
    exit_at: str | None = None
    notes: str | None = None
    status: str | None = None


class WatchlistRequest(BaseModel):
    symbol: str


def fetch_quote(symbol: str):
    """Live quote via Yahoo Finance's public chart endpoint. No API key
    needed; this is the same data source many free ticker widgets use.
    Works for equities (AAPL), indexes (^GSPC), FX (EURUSD=X) and crypto
    (BTC-USD)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    r = requests.get(url, params={"interval": "1d", "range": "5d"},
                      headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
    r.raise_for_status()
    data = r.json()
    result = (data.get("chart") or {}).get("result")
    if not result:
        raise HTTPException(404, f"No market data found for '{symbol}'.")
    meta = result[0]["meta"]
    price = meta.get("regularMarketPrice")
    prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
    change = None
    change_pct = None
    if price is not None and prev_close:
        change = price - prev_close
        change_pct = (change / prev_close) * 100 if prev_close else None
    return {
        "symbol": meta.get("symbol", symbol.upper()),
        "currency": meta.get("currency"),
        "price": price,
        "previous_close": prev_close,
        "change": change,
        "change_percent": change_pct,
        "market_state": meta.get("marketState"),
        "exchange": meta.get("exchangeName"),
    }


def register(app, db, now, get_current_user):
    """Attach all trading-related routes onto the shared FastAPI app."""

    @app.get("/api/trading/academy")
    def academy():
        return {"disclaimer": RISK_DISCLAIMER, "lessons": LESSONS, "videos": VIDEO_RESOURCES}

    # -- Market Watch ------------------------------------------------------
    @app.get("/api/trading/quote")
    def quote(symbol: str):
        try:
            return fetch_quote(symbol.strip().upper())
        except HTTPException:
            raise
        except requests.exceptions.RequestException:
            raise HTTPException(503, "Couldn't reach the market data provider. Check your internet connection.")

    @app.get("/api/trading/watchlist")
    def get_watchlist(user=Depends(get_current_user)):
        conn = db()
        rows = conn.execute(
            "SELECT id, symbol FROM watchlist WHERE user_id=? ORDER BY id", (user["id"],)
        ).fetchall()
        conn.close()
        quotes = []
        for row in rows:
            try:
                q = fetch_quote(row["symbol"])
                q["watchlist_id"] = row["id"]
            except Exception:
                q = {"watchlist_id": row["id"], "symbol": row["symbol"], "error": "unavailable"}
            quotes.append(q)
        return quotes

    @app.post("/api/trading/watchlist")
    def add_watchlist(body: WatchlistRequest, user=Depends(get_current_user)):
        symbol = body.symbol.strip().upper()
        if not symbol:
            raise HTTPException(400, "Symbol cannot be empty.")
        conn = db()
        try:
            cur = conn.execute(
                "INSERT INTO watchlist(user_id, symbol, created_at) VALUES (?, ?, ?)",
                (user["id"], symbol, now()),
            )
            conn.commit()
            wid = cur.lastrowid
        except Exception:
            conn.close()
            raise HTTPException(409, f"{symbol} is already on your watchlist.")
        conn.close()
        return {"id": wid, "symbol": symbol}

    @app.delete("/api/trading/watchlist/{wid}")
    def remove_watchlist(wid: int, user=Depends(get_current_user)):
        conn = db()
        conn.execute("DELETE FROM watchlist WHERE id=? AND user_id=?", (wid, user["id"]))
        conn.commit()
        conn.close()
        return {"ok": True}

    # -- Trading journal -----------------------------------------------------
    @app.get("/api/trading/trades")
    def list_trades(user=Depends(get_current_user)):
        conn = db()
        rows = conn.execute(
            "SELECT * FROM trades WHERE user_id=? ORDER BY entry_at DESC, id DESC", (user["id"],)
        ).fetchall()
        conn.close()
        trades = []
        for r in rows:
            t = dict(r)
            t["pnl"] = _rank_score(t["entry_price"], t["exit_price"], t["direction"], t["quantity"])
            trades.append(t)
        return trades

    @app.post("/api/trading/trades")
    def create_trade(body: TradeRequest, user=Depends(get_current_user)):
        symbol = body.symbol.strip().upper()
        if not symbol:
            raise HTTPException(400, "Symbol cannot be empty.")
        if body.direction not in ("long", "short"):
            raise HTTPException(400, "Direction must be 'long' or 'short'.")
        status = "closed" if body.exit_price is not None else body.status
        conn = db()
        cur = conn.execute(
            "INSERT INTO trades(user_id, symbol, direction, entry_price, exit_price, quantity, "
            "status, entry_at, exit_at, notes, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], symbol, body.direction, body.entry_price, body.exit_price, body.quantity,
             status, body.entry_at, body.exit_at, body.notes.strip(), now()),
        )
        conn.commit()
        tid = cur.lastrowid
        conn.close()
        return {"id": tid}

    @app.patch("/api/trading/trades/{tid}")
    def update_trade(tid: int, body: TradeUpdateRequest, user=Depends(get_current_user)):
        fields, values = [], []
        for key in ("symbol", "direction", "entry_price", "exit_price", "quantity",
                    "entry_at", "exit_at", "notes", "status"):
            val = getattr(body, key)
            if val is not None:
                if key == "symbol":
                    val = val.strip().upper()
                fields.append(f"{key}=?")
                values.append(val)
        if body.exit_price is not None and body.status is None:
            fields.append("status=?")
            values.append("closed")
        if not fields:
            return {"ok": True}
        conn = db()
        cur = conn.execute(
            f"UPDATE trades SET {', '.join(fields)} WHERE id=? AND user_id=?",
            (*values, tid, user["id"]),
        )
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            raise HTTPException(404, "Trade not found")
        return {"ok": True}

    @app.delete("/api/trading/trades/{tid}")
    def delete_trade(tid: int, user=Depends(get_current_user)):
        conn = db()
        conn.execute("DELETE FROM trades WHERE id=? AND user_id=?", (tid, user["id"]))
        conn.commit()
        conn.close()
        return {"ok": True}

    @app.get("/api/trading/stats")
    def trade_stats(user=Depends(get_current_user)):
        conn = db()
        rows = conn.execute(
            "SELECT * FROM trades WHERE user_id=? AND status='closed'", (user["id"],)
        ).fetchall()
        conn.close()
        closed = [dict(r) for r in rows]
        pnls = [_rank_score(t["entry_price"], t["exit_price"], t["direction"], t["quantity"]) for t in closed]
        pnls = [p for p in pnls if p is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        win_rate = (len(wins) / len(pnls) * 100) if pnls else None
        avg_win = (sum(wins) / len(wins)) if wins else 0
        avg_loss = (sum(losses) / len(losses)) if losses else 0
        return {
            "closed_trades": len(pnls),
            "total_pnl": sum(pnls) if pnls else 0,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
        }
