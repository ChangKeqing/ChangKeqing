"""Rule-based A-share strategies. Each returns target weights within its own sleeve (sum <= 1)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from . import config as C


def _rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, 1e-12))


def market_timing(panel) -> dict:
    """大盘择时: 沪深300 相对 MA120 及 MA20/MA60 的位置决定个股仓位系数."""
    df = panel.get(C.BENCHMARK)
    if df is None or len(df) < 130:
        return {"regime": "unknown", "exposure": 0.6}
    c = df["close"]
    above = c.iloc[-1] > c.tail(120).mean()
    trend = c.tail(20).mean() > c.tail(60).mean()
    if above and trend:
        return {"regime": "bull", "exposure": 1.0}
    if above or trend:
        return {"regime": "neutral", "exposure": 0.6}
    return {"regime": "bear", "exposure": 0.3}


def etf_rotation(panel, lookback: int = 25, top_n: int = 2):
    """ETF 动量轮动: 以 25 日对数价格回归的年化斜率 x R2 打分, 持有得分为正的前 N 只, 其余放国债 ETF."""
    scores = {}
    for s in C.ETFS:
        df = panel.get(s)
        if df is None or len(df) < lookback + 1:
            continue
        y = np.log(df["close"].tail(lookback).to_numpy())
        x = np.arange(lookback)
        slope, icpt = np.polyfit(x, y, 1)
        resid = y - (slope * x + icpt)
        r2 = 1 - resid.var() / max(y.var(), 1e-12)
        scores[s] = float((np.exp(slope * 250) - 1) * r2)
    ranked = sorted((s for s in scores if s != C.DEFENSIVE_ETF), key=scores.get, reverse=True)
    picks = [s for s in ranked[:top_n] if scores[s] > 0]
    weights = {s: 1 / top_n for s in picks}
    rest = 1 - sum(weights.values())
    if rest > 1e-9 and C.DEFENSIVE_ETF in panel:
        weights[C.DEFENSIVE_ETF] = rest
    return weights, scores


def _last_week_close(panel) -> str:
    """Date of the last bar of the previous calendar week (weekly rebalancing keeps turnover low)."""
    idx = panel[C.BENCHMARK].index if C.BENCHMARK in panel else next(iter(panel.values())).index
    last = dt.date.fromisoformat(idx[-1])
    monday = (last - dt.timedelta(days=last.weekday())).isoformat()
    prev = [d for d in idx[-10:] if d < monday]
    return prev[-1] if prev else idx[-1]


def trend_momentum(panel, stocks, top_n: int = 3):
    """趋势动量 (周频): 处于多头排列 (收盘>MA60 且 MA20>MA60) 的股票里, 按 120 日动量(跳过近5日)/60 日波动率取前 N."""
    scores = {}
    cutoff = _last_week_close(panel)
    for s in stocks:
        df = panel.get(s)
        df = None if df is None else df.loc[:cutoff]
        if df is None or len(df) < 130:
            continue
        c = df["close"]
        ma20, ma60 = c.tail(20).mean(), c.tail(60).mean()
        if not (c.iloc[-1] > ma60 and ma20 > ma60):
            continue
        mom = c.iloc[-6] / c.iloc[-126] - 1
        vol = c.pct_change().tail(60).std() * np.sqrt(250)
        if mom > 0 and vol > 0:
            scores[s] = float(mom / vol)
    picks = sorted(scores, key=scores.get, reverse=True)[:top_n]
    return {s: 1 / top_n for s in picks}, scores


def rsi_meanrev(panel, stocks, max_n: int = 2):
    """RSI(2) 均值回归: 长期趋势向上 (收盘>MA200) 时 RSI2<10 买入, 收盘站上 MA5 卖出."""
    scores = {}
    for s in stocks:
        df = panel.get(s)
        if df is None or len(df) < 210:
            continue
        c = df["close"]
        rsi = _rsi(c, 2)
        ma5 = c.rolling(5).mean()
        ma200 = c.rolling(200).mean()
        active, entry_rsi = False, None
        for i in range(-10, 0):  # replay the last 10 sessions so the rule is stateless
            if active and c.iloc[i] > ma5.iloc[i]:
                active = False
            if not active and rsi.iloc[i] < 10 and c.iloc[i] > ma200.iloc[i]:
                active, entry_rsi = True, float(rsi.iloc[i])
        if active:
            scores[s] = entry_rsi
    picks = sorted(scores, key=scores.get)[:max_n]
    return {s: 1 / max_n for s in picks}, scores


def affordable_stocks(panel, equity: float) -> list[str]:
    """One lot must fit inside the per-stock weight cap, otherwise a small account cannot hold it."""
    cap = equity * C.MAX_WEIGHT_STOCK
    return [s for s in C.STOCKS if s in panel and panel[s]["close"].iloc[-1] * C.LOT <= cap]


def compute_signals(panel, equity: float) -> dict:
    stocks = affordable_stocks(panel, equity)
    timing = market_timing(panel)
    etf_w, etf_s = etf_rotation(panel)
    trend_w, trend_s = trend_momentum(panel, stocks)
    mr_w, mr_s = rsi_meanrev(panel, stocks)

    baseline: dict[str, float] = {}
    for sleeve, weights, scale in (
        (C.SLEEVE_ETF_ROTATION, etf_w, 1.0),
        (C.SLEEVE_TREND, trend_w, timing["exposure"]),
        (C.SLEEVE_MEANREV, mr_w, timing["exposure"]),
    ):
        for s, w in weights.items():
            baseline[s] = baseline.get(s, 0) + sleeve * scale * w
    return {
        "timing": timing,
        "etf_rotation": {"weights": etf_w, "scores": etf_s},
        "trend_momentum": {"weights": trend_w, "scores": trend_s},
        "rsi_meanrev": {"weights": mr_w, "scores": mr_s},
        "tradable_stocks": stocks,
        "baseline": clamp_weights(baseline),
    }


def clamp_weights(weights: dict[str, float]) -> dict[str, float]:
    """Hard risk limits applied to any target, rule-based or LLM-made."""
    out = {}
    for s, w in weights.items():
        cap = C.MAX_WEIGHT_ETF if C.is_etf(s) else C.MAX_WEIGHT_STOCK
        w = min(max(float(w), 0.0), cap)
        if w > 0.005:
            out[s] = w
    gross = sum(out.values())
    if gross > C.MAX_GROSS:
        out = {s: w * C.MAX_GROSS / gross for s, w in out.items()}
    return {s: round(w, 4) for s, w in out.items()}
