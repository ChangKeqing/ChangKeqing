"""Universe, costs and risk limits for the A-share paper-trading bot."""

INITIAL_CAPITAL_USD = 10_000.0

# ETF 轮动池: 宽基 / 行业 / 跨境 / 商品 / 债券
ETFS = [
    "sh510300",  # 沪深300
    "sh510500",  # 中证500
    "sh512100",  # 中证1000
    "sz159915",  # 创业板
    "sh588000",  # 科创50
    "sh510880",  # 红利
    "sh512880",  # 证券
    "sh512480",  # 半导体
    "sh512010",  # 医药
    "sz159928",  # 消费
    "sh513100",  # 纳指
    "sh513500",  # 标普500
    "sz159920",  # 恒生
    "sh518880",  # 黄金
    "sh511010",  # 国债
]
DEFENSIVE_ETF = "sh511010"

# 个股池: 各行业高流动性龙头
STOCKS = [
    "sh600036", "sh601318", "sh600900", "sh601398", "sh601288", "sh600030",
    "sh601166", "sh600276", "sh601899", "sh600309", "sh601012", "sh600887",
    "sh601088", "sh600028", "sh601857", "sh600050", "sh601728", "sh600941",
    "sh601668", "sh600690", "sh601919", "sh600104", "sh603259", "sh601138",
    "sh600406", "sz000333", "sz000651", "sz000858", "sz002594", "sz300750",
    "sz000001", "sz002415", "sz300059", "sz002475", "sz000725", "sz002714",
    "sz300760", "sz000063", "sz002352", "sh688981",
]
BENCHMARK = "sh000300"  # 沪深300指数, 用于择时与对比

LOT = 100
HISTORY_BARS = 320

# 交易成本
COMMISSION_RATE = 0.00025   # 佣金万2.5, 双向
COMMISSION_MIN = 5.0        # 最低5元
STAMP_DUTY = 0.0005         # 印花税, 仅股票卖出
TRANSFER_FEE = 0.00001      # 过户费, 仅股票
SLIPPAGE = 0.0005           # 滑点

# 风控上限 (代码强制执行, LLM 无法突破)
MAX_WEIGHT_ETF = 0.40
MAX_WEIGHT_STOCK = 0.15
MAX_GROSS = 0.98            # 保留少量现金应付费用
REBALANCE_BAND = 0.05       # 目标与现状偏离不足净值5%则不交易

# 基线组合中各策略的资金占比
SLEEVE_ETF_ROTATION = 0.60
SLEEVE_TREND = 0.40
SLEEVE_MEANREV = 0.0   # 回测中扣费后为负 (小资金受5元最低佣金拖累), 仅作为参考信号提供给 Claude


def is_etf(symbol: str) -> bool:
    return symbol[2:4] in ("51", "58", "15", "56")


def limit_pct(symbol: str) -> float:
    code = symbol[2:]
    if code.startswith(("688", "300", "301", "588")) or code == "159915":
        return 0.20
    return 0.10
