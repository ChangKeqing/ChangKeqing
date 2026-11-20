"""Claude as portfolio manager: reads the quant signals and decides the final target weights."""
from __future__ import annotations

import json
import os

import anthropic
from pydantic import BaseModel

MODEL = os.environ.get("CLAUDE_MODEL") or "claude-opus-5-5"
# USD per million tokens (input, output), used only for the spend log / optional budget.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0), "claude-fable-5-2": (8.0, 40.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.1, 0.5),
}

SYSTEM = """你是一个 A 股模拟盘的投资组合经理。每个交易日收盘后, 你会收到账户状态和若干量化策略的信号, 需要给出下一交易日开盘执行的目标持仓权重。

规则:
- 只能选择输入中 universe 列出的代码; 权重是占账户净值的比例, 未列出的代码视为 0, 剩余为现金。
- 硬约束由程序强制执行: 单只 ETF <= 40%, 单只股票 <= 15%, 总仓位 <= 98%; 股票必须在 tradable_stocks 内 (账户小, 买不起一手的已剔除)。
- A 股 T+1、100 股一手、有交易成本, 避免无谓的频繁调仓; 与当前持仓偏离不足 5% 净值的调整不会被执行。
- baseline 是规则组合 (ETF 动量轮动 60% + 周频趋势动量 40%, 个股部分按大盘择时系数缩放)。rsi2_meanrev 仅是参考信号: 它在回测中扣除费用后为负, 没有其他证据支持时不要为它单独开仓。你可以直接采用, 也可以在有明确理由时偏离: 例如信号相互矛盾、持仓过度集中于同一风格、回撤期需要降低仓位等。
- 你看不到新闻和基本面, 只依据给出的价格与信号数据判断, 不要编造信息。
- 这是虚拟资金的模拟交易。用中文简明写出理由。"""


class Target(BaseModel):
    symbol: str
    weight: float
    reason: str


class Decision(BaseModel):
    market_view: str
    targets: list[Target]
    risk_notes: str


class CreditExhausted(Exception):
    """API credit / spend limit is used up: the bot must stop for good."""


_BILLING_ERRORS = tuple(
    getattr(anthropic, n) for n in (
        "PaymentRequiredError", "EnforcedSpendLimitReachedError", "ContractSpendLimitReachedError",
        "LinkedOrganizationSpendLimitReachedError", "LinkedOrganizationBillingUnavailableError",
    ) if hasattr(anthropic, n)
)


def _is_billing(e: anthropic.APIStatusError) -> bool:
    text = str(e).lower()
    return (
        isinstance(e, _BILLING_ERRORS)
        or e.status_code == 402
        or getattr(e, "type", None) == "billing_error"
        or "credit balance" in text
        or "spend limit" in text
        or "usage limit" in text
    )


def decide(context: dict, usage: dict, client: anthropic.Anthropic | None = None):
    """Returns (Decision | None, note). None means: fall back to the rule-based baseline today.

    Raises CreditExhausted when the API credit is gone, and lets auth errors propagate
    (a bad key is a configuration problem, not a reason to trade without the model).
    """
    client = client or anthropic.Anthropic()
    try:
        resp = client.beta.messages.parse(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
            output_config={"effort": "medium"},
            output_format=Decision,
            # If a safety classifier declines, the API re-runs the request on a fallback model.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        if _is_billing(e):
            raise CreditExhausted(str(e)) from e
        raise
    except anthropic.RateLimitError as e:
        if _is_billing(e):
            raise CreditExhausted(str(e)) from e
        return None, f"Claude 限流, 当日使用规则基线: {e}"
    except anthropic.APIStatusError as e:
        if _is_billing(e):
            raise CreditExhausted(str(e)) from e
        return None, f"Claude API 错误 {e.status_code}, 当日使用规则基线: {e}"
    except anthropic.APIConnectionError as e:
        return None, f"Claude 网络错误, 当日使用规则基线: {e}"

    pin, pout = PRICES.get(resp.model, PRICES.get(MODEL, (4.0, 20.0)))
    u = resp.usage
    usage["calls"] += 1
    usage["input_tokens"] += u.input_tokens
    usage["output_tokens"] += u.output_tokens
    usage["cost_usd"] = round(usage["cost_usd"] + (u.input_tokens * pin + u.output_tokens * pout) / 1e6, 4)

    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return None, f"Claude 未给出有效决策 (stop_reason={resp.stop_reason}), 当日使用规则基线"
    return resp.parsed_output, f"Claude ({resp.model}) 决策"
