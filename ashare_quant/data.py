"""Market data from Tencent's public quote endpoints (reachable from overseas runners)."""
from __future__ import annotations

import time

import pandas as pd
import requests

KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
QUOTE_URL = "https://qt.gtimg.cn/q="
_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0"


def _get(url: str, **kw) -> requests.Response:
    last: Exception | None = None
    for attempt in range(2):
        try:
            r = _session.get(url, timeout=15, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:  # transient network errors
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"data request failed: {url}") from last


EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
COLS = ["date", "open", "close", "high", "low", "volume"]


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame([row[:6] for row in rows], columns=COLS)
    for c in COLS[1:]:
        df[c] = df[c].astype(float)
    return df.set_index("date")


def _fetch_eastmoney(symbol: str, bars: int) -> pd.DataFrame:
    secid = ("1." if symbol.startswith("sh") else "0.") + symbol[2:]
    r = _get(EM_KLINE_URL, params={
        "secid": secid, "klt": 101, "fqt": 1, "end": "20500101", "lmt": bars,
        "fields1": "f1", "fields2": "f51,f52,f53,f54,f55,f56"})
    klines = (r.json().get("data") or {}).get("klines") or []
    return _frame([k.split(",") for k in klines])


def fetch_daily(symbol: str, bars: int = 320) -> pd.DataFrame:
    """Forward-adjusted daily bars, oldest first. Tencent first, Eastmoney as fallback."""
    try:
        return _fetch_tencent(symbol, bars)
    except Exception as e:
        print(f"[data] tencent failed for {symbol} ({e}), trying eastmoney")
        return _fetch_eastmoney(symbol, bars)


def _fetch_tencent(symbol: str, bars: int) -> pd.DataFrame:
    r = _get(KLINE_URL, params={"param": f"{symbol},day,,,{bars},qfq"})
    node = r.json()["data"][symbol]
    rows = node.get("qfqday") or node.get("day") or []
    return _frame(rows)


def fetch_panel(symbols: list[str], bars: int = 320) -> dict[str, pd.DataFrame]:
    panel = {}
    for s in symbols:
        try:
            df = fetch_daily(s, bars)
        except Exception as e:  # one bad symbol must not kill the run
            print(f"[data] skip {s}: {e}")
            continue
        if len(df):
            panel[s] = df
        time.sleep(0.05)
    return panel


def fetch_names(symbols: list[str]) -> dict[str, str]:
    names = {}
    try:
        for i in range(0, len(symbols), 50):
            r = _get(QUOTE_URL + ",".join(symbols[i:i + 50]))
            for line in r.content.decode("gbk", "ignore").split(";"):
                if "~" in line and "=" in line:
                    sym = line.split("=")[0].strip().removeprefix("v_")
                    names[sym] = line.split("~")[1]
    except Exception as e:
        print(f"[data] names unavailable: {e}")
    return names


def fetch_usdcny() -> float:
    r = _get(QUOTE_URL + "whUSDCNY")
    rate = float(r.content.decode("gbk", "ignore").split("~")[3])
    if not 5 < rate < 10:
        raise RuntimeError(f"implausible USDCNY {rate}")
    return rate
