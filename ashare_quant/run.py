"""Daily paper-trading step. Run after the A-share close: python -m ashare_quant.run"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from . import broker, config as C, data, strategies

STATE_DIR = Path(os.environ.get("ASHARE_STATE_DIR") or Path(__file__).parent / "state")
STATE_FILE = STATE_DIR / "state.json"
EQUITY_FILE = STATE_DIR / "equity.csv"
HALT_FILE = STATE_DIR / "HALTED"
REPORT_FILE = STATE_DIR.parent / "report.md"


def _save(state: dict) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1))


def _halt(state: dict, date: str, reason: str) -> None:
    state["halted"] = {"date": date, "reason": reason}
    state["pending"] = []
    HALT_FILE.write_text(f"{date} {reason}\n")
    print(f"[halt] {reason}")


def _drop_unfinished_bar(panel: dict) -> None:
    now = dt.datetime.now(ZoneInfo("Asia/Shanghai"))
    if now.hour * 60 + now.minute >= 15 * 60 + 5:
        return
    today = now.strftime("%Y-%m-%d")
    for s, df in list(panel.items()):
        if len(df) and df.index[-1] == today:
            panel[s] = df.iloc[:-1]


def _stats(panel: dict, symbols: list[str]) -> dict:
    out = {}
    for s in symbols:
        c = panel[s]["close"]
        if len(c) < 61:
            continue
        out[s] = {
            "close": round(float(c.iloc[-1]), 3),
            "ret_5d": round(float(c.iloc[-1] / c.iloc[-6] - 1), 4),
            "ret_20d": round(float(c.iloc[-1] / c.iloc[-21] - 1), 4),
            "ret_60d": round(float(c.iloc[-1] / c.iloc[-61] - 1), 4),
            "vol_20d": round(float(c.pct_change().tail(20).std() * 250 ** 0.5), 4),
        }
    return out


def _rounded(d: dict) -> dict:
    return {k: round(v, 4) for k, v in d.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="rule-based baseline only (testing)")
    args = ap.parse_args()

    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else None
    if state and state.get("halted"):
        print(f"[halt] bot stopped on {state['halted']['date']}: {state['halted']['reason']}")
        return 0
    if not args.no_llm and not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        print("ANTHROPIC_API_KEY is not set. Put it in ashare_quant/.env (or pass --no-llm to test).")
        return 2

    fx = data.fetch_usdcny()
    if state is None:
        state = broker.new_state(C.INITIAL_CAPITAL_USD * fx, fx)
        print(f"[init] ${C.INITIAL_CAPITAL_USD:,.0f} -> CNY {state['cash']:,.0f} @ {fx}")

    universe = C.ETFS + C.STOCKS
    panel = data.fetch_panel(universe + [C.BENCHMARK], C.HISTORY_BARS)
    _drop_unfinished_bar(panel)
    if C.BENCHMARK not in panel:
        print("benchmark data unavailable, abort")
        return 1
    date = panel[C.BENCHMARK].index[-1]
    if state["last_date"] == date:
        print(f"[skip] {date} already processed (holiday or duplicate run)")
        return 0

    # 1) yesterday's orders fill at today's open
    # (the first session after the order date, so a missed day, e.g. the Mac was off, fills correctly)
    bars = {}
    for s, df in panel.items():
        i = df.index.searchsorted(state["last_date"] or date, side="right")
        if 0 < i < len(df):
            bars[s] = {"date": df.index[i], "open": df["open"].iloc[i],
                       "prev_close": df["close"].iloc[i - 1], "volume": df["volume"].iloc[i]}
    fills = broker.fill_pending(state, bars, date) if state["last_date"] else []

    # 2) mark to market at the close
    prices = {s: float(df["close"].iloc[-1]) for s, df in panel.items()}
    for s, p in state["positions"].items():
        p["last"] = prices.get(s, p["last"])
    eq = broker.equity(state, prices)

    # 3) signals -> decision -> orders for the next open
    sig = strategies.compute_signals(panel, eq)
    names = data.fetch_names(universe)
    decision, note, targets = None, "规则基线 (--no-llm)", sig["baseline"]
    if not args.no_llm:
        from . import llm
        budget = float(os.environ.get("LLM_BUDGET_USD") or 0)
        if budget and state["llm"]["cost_usd"] >= budget:
            _halt(state, date, f"已达到设定的 API 预算 ${budget:g}")
        else:
            held = set(state["positions"])
            context = {
                "date": date,
                "account": {
                    "equity_cny": round(eq, 2), "cash_cny": round(state["cash"], 2),
                    "return_since_start": round(eq / state["initial_cny"] - 1, 4),
                    "positions": {
                        s: {"name": names.get(s, ""), "shares": p["shares"],
                            "weight": round(p["shares"] * p["last"] / eq, 4),
                            "pnl_pct": round(p["last"] / p["cost"] - 1, 4)}
                        for s, p in state["positions"].items()},
                },
                "market_timing": sig["timing"],
                "signals": {
                    "etf_rotation": {"picks": sig["etf_rotation"]["weights"],
                                     "scores": _rounded(sig["etf_rotation"]["scores"])},
                    "trend_momentum": {"picks": sig["trend_momentum"]["weights"],
                                       "scores": _rounded(sig["trend_momentum"]["scores"])},
                    "rsi2_meanrev": {"picks": sig["rsi_meanrev"]["weights"],
                                     "entry_rsi": _rounded(sig["rsi_meanrev"]["scores"])},
                },
                "baseline": sig["baseline"],
                "tradable_stocks": sig["tradable_stocks"],
                "universe": {s: names.get(s, "") for s in universe if s in panel},
                "price_stats": _stats(panel, [s for s in universe if s in panel and (
                    C.is_etf(s) or s in held or s in sig["trend_momentum"]["scores"]
                    or s in sig["rsi_meanrev"]["scores"])]),
            }
            try:
                decision, note = llm.decide(context, state["llm"])
            except llm.CreditExhausted as e:
                _halt(state, date, f"Claude API 额度用完: {e}")
            if decision:
                ok = set(C.ETFS) | set(sig["tradable_stocks"]) | held
                targets = strategies.clamp_weights(
                    {t.symbol: t.weight for t in decision.targets if t.symbol in ok and t.symbol in panel})

    if state["halted"]:
        note, targets = "已停止, 不再下单", {}
    orders = [] if state["halted"] else broker.make_orders(state, targets, prices, date)
    state["last_date"] = date

    # 4) persist + report
    bench = float(panel[C.BENCHMARK]["close"].iloc[-1])
    new = not EQUITY_FILE.exists()
    STATE_DIR.mkdir(exist_ok=True)
    with EQUITY_FILE.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "equity_cny", "equity_usd", "cash_cny", "usdcny", "csi300"])
        w.writerow([date, round(eq, 2), round(eq / fx, 2), round(state["cash"], 2), fx, bench])
    _save(state)
    REPORT_FILE.write_text(render_report(state, date, eq, fx, names, sig, decision, note, targets, fills, orders))
    print(f"[done] {date} equity CNY {eq:,.2f} (${eq / fx:,.2f}) | {note} | {len(fills)} fills, {len(orders)} new orders")
    return 0


def render_report(state, date, eq, fx, names, sig, decision, note, targets, fills, orders) -> str:
    nm = lambda s: f"{names.get(s, '')} `{s}`"
    rows = list(csv.DictReader(EQUITY_FILE.open()))
    first_bench, bench = float(rows[0]["csi300"]), float(rows[-1]["csi300"])
    peak, mdd = 0.0, 0.0
    for r in rows:
        peak = max(peak, float(r["equity_cny"]))
        mdd = min(mdd, float(r["equity_cny"]) / peak - 1)
    L = [f"# A股量化模拟盘日报 {date}", ""]
    if state["halted"]:
        L += [f"> **已停止运行** ({state['halted']['date']}): {state['halted']['reason']}", ""]
    L += [
        "| 指标 | 数值 |", "|---|---|",
        f"| 净值 | ¥{eq:,.2f} (${eq / fx:,.2f} @ {fx}) |",
        f"| 初始资金 | $10,000 = ¥{state['initial_cny']:,.2f} @ {state['fx_init']} |",
        f"| 累计收益 (人民币) | {eq / state['initial_cny'] - 1:+.2%} |",
        f"| 同期沪深300 | {bench / first_bench - 1:+.2%} |",
        f"| 最大回撤 | {mdd:.2%} |",
        f"| 现金 | ¥{state['cash']:,.2f} ({state['cash'] / eq:.1%}) |",
        f"| 大盘择时 | {sig['timing']['regime']} (个股仓位系数 {sig['timing']['exposure']}) |",
        f"| Claude 调用 | {state['llm']['calls']} 次, 约 ${state['llm']['cost_usd']:.2f} |",
        "", "## 持仓", "",
    ]
    if state["positions"]:
        L += ["| 标的 | 股数 | 成本 | 现价 | 市值 | 占比 | 盈亏 |", "|---|---|---|---|---|---|---|"]
        for s, p in state["positions"].items():
            v = p["shares"] * p["last"]
            L.append(f"| {nm(s)} | {p['shares']} | {p['cost']:.3f} | {p['last']:.3f} | ¥{v:,.0f} | {v / eq:.1%} | {p['last'] / p['cost'] - 1:+.2%} |")
    else:
        L.append("空仓")
    L += ["", f"## 今日决策: {note}", ""]
    if decision:
        L += [f"**市场判断**: {decision.market_view}", ""]
        L += ["| 标的 | 目标权重 | 理由 |", "|---|---|---|"]
        reasons = {t.symbol: t.reason for t in decision.targets}
        L += [f"| {nm(s)} | {w:.1%} | {reasons.get(s, '').replace('|', '/')} |" for s, w in targets.items()]
        L += ["", f"**风险提示**: {decision.risk_notes}"]
    else:
        L += ["| 标的 | 目标权重 |", "|---|---|"] + [f"| {nm(s)} | {w:.1%} |" for s, w in targets.items()]
    L += ["", "规则基线: " + (", ".join(f"{nm(s)} {w:.1%}" for s, w in sig["baseline"].items()) or "空仓"), ""]
    L += ["## 今日开盘成交 (上一交易日的委托)", ""]
    L += [f"- {f['side']} {nm(f['symbol'])} {f['shares']} 股" + (f" @ {f['price']} 费用 ¥{f['fee']}" if f["status"] == "filled" else f" — {f['status']}") for f in fills] or ["无"]
    L += ["", "## 下一交易日开盘委托", ""]
    L += [f"- {o['side']} {nm(o['symbol'])} {o['shares']} 股" for o in orders] or ["无"]
    L += ["", "*虚拟资金模拟交易, 不构成投资建议。*", ""]
    return "\n".join(L)


if __name__ == "__main__":
    sys.exit(main())
