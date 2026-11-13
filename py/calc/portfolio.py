"""Portfolio mathematics (decision #120, family H): return and risk of a portfolio of any number of assets
from their correlations, minimum-variance weights and the frontier of two assets, CAPM and the security
market line, the capital allocation line, and rebalancing to target weights."""

from __future__ import annotations

from decimal import Decimal, localcontext
from typing import Any

from .core import (
    HUNDRED,
    ONE,
    ZERO,
    CalcError,
    Calculator,
    Chart,
    Column,
    Field,
    Inputs,
    Result,
    TableOut,
    ctx,
    fmt,
    register,
    sqrt,
    value,
)

ASSETS = (
    Column("name", "Asset", "text"),
    Column("w", "Weight %", "percent"),
    Column("er", "Expected return %", "percent"),
    Column("sd", "Standard deviation %", "percent"),
)
CORRS = (Column("a", "Asset", "text"), Column("b", "With asset", "text"), Column("rho", "Correlation"))


def _corr_lookup(rows: list[dict[str, Any]], names: list[str]) -> dict[tuple[str, str], Decimal]:
    out: dict[tuple[str, str], Decimal] = {}
    for rr in rows:
        a, b, rho = str(rr["a"]).strip(), str(rr["b"]).strip(), rr["rho"]
        if a not in names or b not in names:
            raise CalcError(f"Correlation {a} with {b}: name both as they appear among the assets.", "corr")
        if not Decimal(-1) <= rho <= ONE:
            raise CalcError(f"Correlation {a} with {b} must be from −1 to 1.", "corr")
        out[a, b] = out[b, a] = rho
    return out


def port_sd(
    w: list[Decimal], sd: list[Decimal], names: list[str], rho: dict[tuple[str, str], Decimal]
) -> Decimal:
    with localcontext(ctx()):
        var = ZERO
        for i, a in enumerate(names):
            for j, b in enumerate(names):
                r = ONE if i == j else rho.get((a, b), ZERO)
                var += w[i] * w[j] * sd[i] * sd[j] * r
        return sqrt(var)


def _portfolio(x: Inputs) -> Result:
    assets = x.table("assets", min_rows=2)
    names = [str(a["name"]).strip() for a in assets]
    if len(set(names)) != len(names):
        raise CalcError("Give each asset its own name.", "assets")
    rho = _corr_lookup(x.table("corr", min_rows=0), names)
    w = [a["w"] for a in assets]
    er = [a["er"] for a in assets]
    sd = [a["sd"] for a in assets]
    with localcontext(ctx()):
        total = sum(w, ZERO)
        if abs(total - ONE) > Decimal("1e-9"):
            raise CalcError(f"The weights add up to {fmt(total * HUNDRED, 'percent')}%, not 100%.", "assets")
        ret = sum((a * b for a, b in zip(w, er, strict=True)), ZERO)
        risk = port_sd(w, sd, names, rho)
        r = Result(value("sd", "Portfolio standard deviation", risk * HUNDRED, "percent"))
        r.add("er", "Portfolio expected return", ret * HUNDRED, "percent")
        avg = sum((a * b for a, b in zip(w, sd, strict=True)), ZERO)
        r.add("weighted_sd", "Weighted average of the standard deviations", avg * HUNDRED, "percent")
        if risk:
            r.add("div_ratio", "Diversification ratio (weighted SD ÷ portfolio SD)", avg / risk, "ratio")
        rf = x.opt("rf")
        if rf is not None and risk:
            r.add("sharpe", "Sharpe ratio", (ret - rf / HUNDRED) / risk, "ratio")
        missing = [(a, b) for i, a in enumerate(names) for b in names[i + 1 :] if (a, b) not in rho]
        if missing:
            r.warnings.append("No correlation given for " + ", ".join(f"{a}–{b}" for a, b in missing) +
                              "; taken as 0.")  # fmt: skip
        if len(names) == 2:
            _two_asset(r, names, er, sd, rho.get((names[0], names[1]), ZERO))
        r.steps = ["σp² = Σᵢ Σⱼ wᵢ wⱼ σᵢ σⱼ ρᵢⱼ;  E(Rp) = Σ wᵢ E(Rᵢ)"]
    return r


def _two_asset(r: Result, names: list[str], er: list[Decimal], sd: list[Decimal], rho: Decimal) -> None:
    s1, s2 = sd
    with localcontext(ctx()):
        cov = rho * s1 * s2
        den = s1 * s1 + s2 * s2 - 2 * cov
        if den:
            w1 = (s2 * s2 - cov) / den
            r.add("mv_w1", f"Minimum-variance weight in {names[0]}", w1 * HUNDRED, "percent")
            mv = sqrt(max(w1 * w1 * s1 * s1 + (ONE - w1) ** 2 * s2 * s2 + 2 * w1 * (ONE - w1) * cov, ZERO))
            r.add("mv_sd", "…its standard deviation", mv * HUNDRED, "percent")
            r.add("mv_er", "…its expected return", (w1 * er[0] + (ONE - w1) * er[1]) * HUNDRED, "percent")
        xs, rows = [], []
        series_r, series_s = [], []
        for k in range(0, 21):
            w = Decimal(k) / 20
            s = sqrt(max(w * w * s1 * s1 + (ONE - w) ** 2 * s2 * s2 + 2 * w * (ONE - w) * cov, ZERO))
            e = w * er[0] + (ONE - w) * er[1]
            xs.append(fmt(w * HUNDRED, "percent"))
            series_r.append(fmt(e * HUNDRED, "percent"))
            series_s.append(fmt(s * HUNDRED, "percent"))
            rows.append(
                [fmt(w * HUNDRED, "percent"), fmt(e * HUNDRED, "percent"), fmt(s * HUNDRED, "percent")]
            )
        r.tables.append(TableOut("frontier", f"Mixes of {names[0]} and {names[1]}", [
            {"key": "w", "label": f"Weight in {names[0]}", "unit": "percent"},
            {"key": "er", "label": "Expected return", "unit": "percent"},
            {"key": "sd", "label": "Standard deviation", "unit": "percent"},
        ], rows))  # fmt: skip
        r.chart = Chart("line", f"Return and risk by weight in {names[0]}", f"Weight in {names[0]} (%)",
                        "percent", xs, [{"name": "Expected return", "values": series_r},
                             {"name": "Standard deviation", "values": series_s}])  # fmt: skip


register(Calculator(
    key="portfolio",
    family="portfolio",
    title="Portfolio return and risk",
    description="Weights, expected returns and standard deviations of any number of assets with their "
                "correlations: the portfolio's return and risk, the diversification benefit, and for two "
                "assets the minimum-variance mix and every mix in between.",
    keywords="portfolio return risk standard deviation variance correlation covariance diversification "
    "minimum "
             "variance efficient frontier markowitz two asset",
    fields=[
        Field("assets", "Assets", "table", columns=ASSETS, rows=[
            {"name": "Equity", "w": "60", "er": "13", "sd": "18"},
            {"name": "Debt", "w": "40", "er": "7", "sd": "4"},
        ]),
        Field("corr", "Correlations (pairs not listed are 0)", "table", columns=CORRS, rows=[
            {"a": "Equity", "b": "Debt", "rho": "0.1"},
        ]),
        Field("rf", "Risk-free rate for Sharpe (%)", "number", "", optional=True, default_from="risk_free"),
    ],
    run=_portfolio,
))  # fmt: skip


# ------------------------------------------------------------------------------------------- CAPM


def _capm(x: Inputs) -> Result:
    rf = x.rate("rf")
    beta = x.num("beta")
    rm = x.rate("rm")
    with localcontext(ctx()):
        req = rf + beta * (rm - rf)
        r = Result(value("required", "Required return (CAPM)", req * HUNDRED, "percent"))
        r.add("mrp", "Market risk premium", (rm - rf) * HUNDRED, "percent")
        r.add("premium", "This asset's risk premium", beta * (rm - rf) * HUNDRED, "percent")
        exp_r = x.opt("expected")
        if exp_r is not None:
            alpha = exp_r / HUNDRED - req
            r.add("alpha", "Alpha (expected − required)", alpha * HUNDRED, "percent")
            r.add(
                "verdict",
                "On the security market line it is",
                "above: undervalued" if alpha > 0 else "below: overvalued" if alpha < 0 else "on the line",
                "text",
            )
        target_sd = x.opt("target_sd")
        sm = x.opt("sm")
        if target_sd is not None and sm is not None and sm > 0:
            w = target_sd / sm
            r.add("cal_w", "Capital allocation line: share in the market portfolio", w * HUNDRED, "percent")
            r.add("cal_r", "…expected return at that risk", (rf + w * (rm - rf)) * HUNDRED, "percent")
        r.steps = ["E(R) = Rf + β (Rm − Rf)", "CAL: E(R) = Rf + (σ / σm)(Rm − Rf)"]
    return r


register(Calculator(
    key="capm",
    family="portfolio",
    title="CAPM and the security market line",
    description="The return an asset should earn for its beta, its alpha against an expected return, and on "
                "the capital allocation line the mix that reaches a target risk.",
    keywords="capm capital asset pricing model beta required return security market line sml cal alpha "
             "undervalued overvalued market risk premium",
    fields=[
        Field("rf", "Risk-free rate (%)", "percent", "6.5", default_from="risk_free"),
        Field("beta", "Beta", "number", "1.2"),
        Field("rm", "Market return (%)", "percent", "12"),
        Field("expected", "Your expected return for it (%)", "number", "", optional=True),
        Field("sm", "Market standard deviation (%)", "number", "", optional=True),
        Field("target_sd", "Target standard deviation (%)", "number", "", optional=True),
    ],
    run=_capm,
))  # fmt: skip


# ------------------------------------------------------------------------------------------- rebalance

HOLDINGS = (Column("name", "Holding", "text"), Column("value", "Value now", "money"),
            Column("target", "Target %", "percent"))  # fmt: skip


def _rebalance(x: Inputs) -> Result:
    rows = x.table("holdings", min_rows=1)
    new = x.num("new_money", default=ZERO)
    with localcontext(ctx()):
        tsum = sum((rr["target"] for rr in rows), ZERO)
        if abs(tsum - ONE) > Decimal("1e-9"):
            raise CalcError(f"The targets add up to {fmt(tsum * HUNDRED, 'percent')}%, not 100%.", "holdings")
        now = sum((rr["value"] for rr in rows), ZERO)
        total = now + new
        if total <= 0:
            raise CalcError("There is nothing to rebalance.", "holdings")
        out = []
        moved = ZERO
        for rr in rows:
            goal = total * rr["target"]
            trade = goal - rr["value"]
            moved += abs(trade)
            out.append([str(rr["name"]), fmt(rr["value"], "money"), fmt(rr["value"] / now * HUNDRED if now
                        else ZERO, "percent"), fmt(rr["target"] * HUNDRED, "percent"), fmt(goal, "money"),
                        fmt(trade, "money")])  # fmt: skip
        r = Result(value("total", "Total after new money", total, "money"))
        r.add("turnover", "Buying and selling in all", moved, "money")
        r.tables.append(TableOut("trades", "Trades to reach the targets", [
            {"key": "name", "label": "Holding", "unit": "text"},
            {"key": "now", "label": "Value now", "unit": "money"},
            {"key": "pct", "label": "Share now", "unit": "percent"},
            {"key": "target", "label": "Target", "unit": "percent"},
            {"key": "goal", "label": "Value at target", "unit": "money"},
            {"key": "trade", "label": "Buy (+) or sell (−)", "unit": "money"},
        ], out))  # fmt: skip
    return r


register(Calculator(
    key="rebalance",
    family="portfolio",
    title="Rebalance to target weights",
    description="What to buy and sell, with any new money, to bring holdings back to their target weights.",
    keywords="rebalance asset allocation target weights buy sell new money drift",
    fields=[
        Field("holdings", "Holdings", "table", columns=HOLDINGS, rows=[
            {"name": "Equity funds", "value": "780000", "target": "60"},
            {"name": "Debt funds", "value": "320000", "target": "30"},
            {"name": "Gold", "value": "60000", "target": "10"},
        ]),
        Field("new_money", "New money to invest", "money", "40000", optional=True),
    ],
    run=_rebalance,
))  # fmt: skip
