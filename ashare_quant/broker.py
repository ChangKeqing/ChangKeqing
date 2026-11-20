"""Paper broker with A-share rules: 100-share lots, T+1, price limits, fees, next-open fills."""
from __future__ import annotations

from . import config as C


def new_state(cash_cny: float, fx: float) -> dict:
    return {
        "cash": cash_cny, "positions": {}, "pending": [], "trades": [],
        "last_date": None, "fx_init": fx, "initial_cny": cash_cny,
        "llm": {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0},
        "halted": None,
    }


def _fees(symbol: str, side: str, amount: float) -> float:
    fee = max(amount * C.COMMISSION_RATE, C.COMMISSION_MIN)
    if not C.is_etf(symbol):
        fee += amount * C.TRANSFER_FEE
        if side == "sell":
            fee += amount * C.STAMP_DUTY
    return fee


def equity(state: dict, prices: dict[str, float]) -> float:
    return state["cash"] + sum(
        p["shares"] * prices.get(s, p["last"]) for s, p in state["positions"].items()
    )


def fill_pending(state: dict, bars: dict[str, dict], date: str) -> list[dict]:
    """Execute yesterday's orders at today's open. bars[symbol] = {open, prev_close, volume}."""
    fills = []
    orders = sorted(state["pending"], key=lambda o: o["side"] != "sell")  # sells first to free cash
    state["pending"] = []
    for o in orders:
        s, side, bar = o["symbol"], o["side"], bars.get(o["symbol"])
        date = bar.get("date", date) if bar else date
        if bar is None or bar["volume"] <= 0:
            fills.append({**o, "date": date, "status": "skipped: 停牌/无行情"})
            continue
        op, lim = bar["open"], C.limit_pct(s)
        tick = 0.001 if C.is_etf(s) else 0.01
        nd = 3 if C.is_etf(s) else 2
        if side == "buy" and op >= round(bar["prev_close"] * (1 + lim), nd) - tick / 2:
            fills.append({**o, "date": date, "status": "skipped: 涨停开盘无法买入"})
            continue
        if side == "sell" and op <= round(bar["prev_close"] * (1 - lim), nd) + tick / 2:
            fills.append({**o, "date": date, "status": "skipped: 跌停开盘无法卖出"})
            continue
        slip = max(op * C.SLIPPAGE, tick)
        price = op + slip if side == "buy" else op - slip
        shares = o["shares"]
        pos = state["positions"].get(s)
        if side == "sell":
            shares = min(shares, pos["shares"] if pos else 0)
        else:
            while shares > 0 and shares * price + _fees(s, side, shares * price) > state["cash"]:
                shares -= C.LOT
        if shares <= 0:
            fills.append({**o, "date": date, "status": "skipped: 资金或持仓不足"})
            continue
        amount = shares * price
        fee = _fees(s, side, amount)
        if side == "buy":
            state["cash"] -= amount + fee
            pos = state["positions"].setdefault(s, {"shares": 0, "cost": 0.0, "last": price})
            pos["cost"] = (pos["cost"] * pos["shares"] + amount + fee) / (pos["shares"] + shares)
            pos["shares"] += shares
        else:
            state["cash"] += amount - fee
            pos["shares"] -= shares
            if pos["shares"] == 0:
                del state["positions"][s]
        fill = {"date": date, "symbol": s, "side": side, "shares": shares,
                "price": round(price, 4), "fee": round(fee, 2), "status": "filled"}
        fills.append(fill)
        state["trades"].append(fill)
    return fills


def make_orders(state: dict, targets: dict[str, float], prices: dict[str, float], date: str) -> list[dict]:
    """Turn target weights into lot-sized orders for the next session's open."""
    eq = equity(state, prices)
    orders = []
    for s in sorted(set(targets) | set(state["positions"])):
        price = prices.get(s)
        if not price:
            continue
        held = state["positions"].get(s, {}).get("shares", 0)
        w = targets.get(s, 0.0)
        want = int(w * eq / price / C.LOT) * C.LOT
        delta = want - held
        if delta == 0:
            continue
        if want > 0 and abs(delta) * price < max(C.REBALANCE_BAND * eq, C.LOT * price):
            continue  # inside the no-trade band
        orders.append({"symbol": s, "side": "buy" if delta > 0 else "sell",
                       "shares": abs(delta), "created": date})
    state["pending"] = orders
    return orders
