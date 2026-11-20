"""Backtest of the rule-based baseline (no LLM) through the same paper broker.

python -m ashare_quant.backtest [bars]   # default 800 daily bars
Uses forward-adjusted prices, so lot sizes in the distant past are approximate.
"""
from __future__ import annotations

import sys

import numpy as np

from . import broker, config as C, data, strategies


def run(bars: int = 800, warmup: int = 220, panel=None, fx=None) -> dict:
    fx = fx or data.fetch_usdcny()
    panel = panel or data.fetch_panel(C.ETFS + C.STOCKS + [C.BENCHMARK], bars)
    dates = list(panel[C.BENCHMARK].index)
    state = broker.new_state(C.INITIAL_CAPITAL_USD * fx, fx)
    pos = {s: {d: i for i, d in enumerate(df.index)} for s, df in panel.items()}
    curve = []
    for d in dates[warmup:]:
        view, day_bars, prices = {}, {}, {}
        for s, df in panel.items():
            i = pos[s].get(d)
            if i is None:  # suspended that day: last known price, no bar
                j = df.index.searchsorted(d)
                if j:
                    view[s] = df.iloc[:j]
                    prices[s] = float(df["close"].iloc[j - 1])
                continue
            view[s] = df.iloc[: i + 1]
            prices[s] = float(df["close"].iloc[i])
            if i:
                day_bars[s] = {"open": df["open"].iloc[i], "prev_close": df["close"].iloc[i - 1],
                               "volume": df["volume"].iloc[i]}
        broker.fill_pending(state, day_bars, d)
        for s, p in state["positions"].items():
            p["last"] = prices.get(s, p["last"])
        eq = broker.equity(state, prices)
        curve.append(eq)
        sig = strategies.compute_signals(view, eq)
        broker.make_orders(state, sig["baseline"], prices, d)

    eqs = np.array(curve)
    rets = eqs[1:] / eqs[:-1] - 1
    bench = panel[C.BENCHMARK]["close"].loc[dates[warmup]:]
    years = len(eqs) / 250
    return {
        "period": f"{dates[warmup]} ~ {dates[-1]}",
        "total_return": eqs[-1] / eqs[0] - 1,
        "annual_return": (eqs[-1] / eqs[0]) ** (1 / years) - 1,
        "annual_vol": rets.std() * 250 ** 0.5,
        "sharpe": rets.mean() / rets.std() * 250 ** 0.5,
        "max_drawdown": (eqs / np.maximum.accumulate(eqs) - 1).min(),
        "trades": len(state["trades"]),
        "fees_cny": sum(t["fee"] for t in state["trades"]),
        "benchmark_return": bench.iloc[-1] / bench.iloc[0] - 1,
        "benchmark_max_drawdown": (bench / bench.cummax() - 1).min(),
    }


if __name__ == "__main__":
    res = run(int(sys.argv[1]) if len(sys.argv) > 1 else 800)
    for k, v in res.items():
        print(f"{k:24s} {v if isinstance(v, (str, int)) else round(float(v), 4)}")
