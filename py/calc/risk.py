"""Risk and performance (decision #120, family G): volatility and drawdown from prices, the ratio set from
period returns against a benchmark (Sharpe, Sortino, Treynor, Jensen's alpha, beta, tracking error,
information ratio, M², capture ratios, Calmar), the same ratios from summary figures (CFA style), value at
risk, and Roy's safety-first ratio.

Conventions, stated so results can be checked: sample (n − 1) variance and covariance; annualised return is
geometric; annualised volatility is the period SD × √(periods a year); Sharpe and the others use annualised
arithmetic mean excess return over annualised volatility; the per-period risk-free rate is (1 +
annual)^(1/p) − 1; downside deviation (Sortino) is √(Σ min(0, r − MAR)² / n) over all periods; capture
ratios are geometric (Morningstar's method)."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, localcontext
from itertools import pairwise
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
    pw,
    register,
    sqrt,
    value,
)
from .returns import PER_YEAR, chain
from .stats import cov, mean, norm_cdf, norm_inv, norm_pdf, percentile_inc, sd_s, var_s

D365 = Decimal(365)


def periodic_rf(annual: Decimal, p: Decimal) -> Decimal:
    with localcontext(ctx()):
        return pw(ONE + annual, ONE / p) - ONE


def drawdown(index: list[Decimal]) -> tuple[Decimal, int, int, int | None]:
    """Largest fall from a peak: (fraction lost, peak position, trough position, recovery position or
    None)."""
    peak_i, worst, w_peak, w_trough = 0, ZERO, 0, 0
    with localcontext(ctx()):
        for i, v in enumerate(index):
            if v > index[peak_i]:
                peak_i = i
            dd = v / index[peak_i] - ONE
            if dd < worst:
                worst, w_peak, w_trough = dd, peak_i, i
    recovery = next((i for i in range(w_trough + 1, len(index)) if index[i] >= index[w_peak]), None)
    return worst, w_peak, w_trough, recovery


# ------------------------------------------------------------------------------------------- prices

PRICES = (Column("date", "Date", "date"), Column("price", "Price or value", "money"))
PRICE_EXAMPLE = [
    {"date": d, "price": p}
    for d, p in (
        ("2025-03-31", "100"),
        ("2025-04-30", "103.2"),
        ("2025-05-31", "99.8"),
        ("2025-06-30", "106.4"),
        ("2025-07-31", "104.1"),
        ("2025-08-31", "97.5"),
        ("2025-09-30", "101.9"),
        ("2025-10-31", "108.3"),
        ("2025-11-30", "110.0"),
        ("2025-12-31", "106.2"),
        ("2026-01-31", "112.5"),
        ("2026-02-28", "115.1"),
        ("2026-03-31", "113.4"),
    )
]


def _prices(x: Inputs) -> Result:
    rows = sorted(x.table("data", min_rows=3), key=lambda rr: rr["date"])
    p = Decimal(x.choice("per_year"))
    prices = [rr["price"] for rr in rows]
    if any(v <= 0 for v in prices):
        raise CalcError("Every price must be more than zero.", "data")
    dates: list[dt.date] = [rr["date"] for rr in rows]
    with localcontext(ctx()):
        rs = [b / a - ONE for a, b in pairwise(prices)]
        days = (dates[-1] - dates[0]).days
        total = prices[-1] / prices[0]
        r = Result(value("vol", "Volatility, annualised", sd_s(rs) * sqrt(p) * HUNDRED, "percent"))
        r.add("total", "Total return", (total - ONE) * HUNDRED, "percent")
        cagr = pw(total, D365 / Decimal(days)) - ONE if days > 0 else None
        if cagr is not None:
            r.add("cagr", "CAGR (from the dates)", cagr * HUNDRED, "percent")
        r.add("vol_period", "Standard deviation per period", sd_s(rs) * HUNDRED, "percent")
        r.add("mean_period", "Mean return per period", mean(rs) * HUNDRED, "percent")
        dd, pk, tr, rec = drawdown(prices)
        r.add("max_dd", "Maximum drawdown", dd * HUNDRED, "percent")
        if dd < 0:
            r.add("dd_from", "…from the peak on", dates[pk].isoformat(), "date")
            r.add("dd_to", "…to the low on", dates[tr].isoformat(), "date")
            r.add(
                "dd_back",
                "…back to the peak on",
                dates[rec].isoformat() if rec is not None else "not yet",
                "date" if rec is not None else "text",
            )
            if cagr is not None:
                r.add("calmar", "Calmar ratio (CAGR ÷ maximum drawdown)", cagr / -dd, "ratio")
        now = prices[-1] / max(prices) - ONE
        r.add("current_dd", "Below the highest price now", now * HUNDRED, "percent")
        r.add("best", "Best period", max(rs) * HUNDRED, "percent")
        r.add("worst", "Worst period", min(rs) * HUNDRED, "percent")
        r.chart = Chart(
            "line",
            "Price",
            "Date",
            "money",
            [d.isoformat() for d in dates],
            [{"name": "Price", "values": [fmt(v, "money") for v in prices]}],
        )
        r.tables.append(
            TableOut(
                "returns",
                "Period returns",
                [
                    {"key": "date", "label": "Date", "unit": "date"},
                    {"key": "price", "label": "Price", "unit": "money"},
                    {"key": "r", "label": "Return", "unit": "percent"},
                ],
                [[dates[0].isoformat(), fmt(prices[0], "money"), ""]]
                + [
                    [dates[i + 1].isoformat(), fmt(prices[i + 1], "money"), fmt(v * HUNDRED, "percent")]
                    for i, v in enumerate(rs)
                ],
            )
        )
        r.steps = [
            "Period return = price / previous price − 1",
            "Volatility = SD of period returns (n − 1) × √(periods a year)",
            "Maximum drawdown = the largest fall from a high to a later low",
        ]
    return r


register(
    Calculator(
        key="prices",
        family="risk",
        title="Volatility and drawdown from prices",
        description="Prices or NAVs by date: period returns, annualised volatility, CAGR, maximum "
        "drawdown with "
        "its dates and recovery, and the Calmar ratio.",
        keywords="volatility standard deviation annualised drawdown max drawdown calmar nav price series "
        "risk",
        fields=[
            Field("data", "Prices", "table", columns=PRICES, rows=PRICE_EXAMPLE, fill="prices"),
            Field("per_year", "Prices are", "choice", "12", options=PER_YEAR),
        ],
        run=_prices,
    )
)


# ------------------------------------------------------------------------------------------- the ratio set

PAIR = (
    Column("period", "Period", "text", optional=True),
    Column("rp", "Portfolio %", "percent"),
    Column("rb", "Benchmark %", "percent", optional=True),
)
PAIR_EXAMPLE = [
    {"period": m, "rp": a, "rb": b}
    for m, a, b in (
        ("Apr", "2.4", "1.9"),
        ("May", "-1.1", "-1.6"),
        ("Jun", "3.6", "3.0"),
        ("Jul", "0.6", "1.1"),
        ("Aug", "-2.2", "-2.9"),
        ("Sep", "1.7", "1.3"),
        ("Oct", "4.5", "3.9"),
        ("Nov", "-0.4", "-0.9"),
        ("Dec", "1.5", "0.8"),
        ("Jan", "-2.7", "-3.4"),
        ("Feb", "2.9", "2.2"),
        ("Mar", "1.2", "1.8"),
    )
]


def _capture(rp: list[Decimal], rb: list[Decimal], up: bool, p: Decimal) -> Decimal | None:
    idx = [i for i, b in enumerate(rb) if (b > 0 if up else b < 0)]
    if not idx:
        return None
    with localcontext(ctx()):
        k = Decimal(len(idx))
        gp = pw(chain([rp[i] for i in idx]), p / k) - ONE
        gb = pw(chain([rb[i] for i in idx]), p / k) - ONE
        return gp / gb if gb != 0 else None


def _benchmark(
    r: Result,
    rp: list[Decimal],
    rb: list[Decimal],
    *,
    p: Decimal,
    rf: Decimal,
    rf_a: Decimal,
    excess: Decimal,
    vol: Decimal,
) -> None:
    """The ratios that need a benchmark: beta, alpha, Treynor, tracking error, information ratio, M²,
    capture ratios."""
    n = Decimal(len(rp))
    with localcontext(ctx()):
        vb = var_s(rb)
        if vb == 0:
            raise CalcError("The benchmark does not vary, so beta cannot be worked out.", "data")
        beta = cov(rp, rb) / vb
        sp = sd_s(rp)
        corr = cov(rp, rb) / (sp * sqrt(vb)) if sp else ZERO
        sb = sqrt(vb) * sqrt(p)
        ann_b = pw(chain(rb), p / n) - ONE
        alpha = (mean(rp) - (rf + beta * (mean(rb) - rf))) * p
        active = [a - b for a, b in zip(rp, rb, strict=True)]
        te = sd_s(active) * sqrt(p)
        r.add("beta", "Beta", beta, "ratio")
        r.add("alpha", "Jensen's alpha, annualised", alpha * HUNDRED, "percent")
        if beta:
            r.add("treynor", "Treynor ratio", excess / beta * HUNDRED, "percent")
        r.add("corr", "Correlation with the benchmark", corr, "ratio")
        r.add("r2", "R squared", corr * corr, "ratio")
        r.add("te", "Tracking error, annualised", te * HUNDRED, "percent")
        if te:
            r.add("ir", "Information ratio", mean(active) * p / te, "ratio")
        sharpe = excess / vol if vol else ZERO
        r.add(
            "m2",
            "M² (Modigliani): return at the benchmark's risk",
            (rf_a + sharpe * sb) * HUNDRED,
            "percent",
        )
        r.add(
            "m2_alpha",
            "M² alpha over the benchmark",
            (rf_a + sharpe * sb - ((mean(rb) - rf) * p + rf_a)) * HUNDRED,
            "percent",
        )
        up, down = _capture(rp, rb, True, p), _capture(rp, rb, False, p)
        if up is not None:
            r.add("up", "Upside capture", up * HUNDRED, "percent")
        if down is not None:
            r.add("down", "Downside capture", down * HUNDRED, "percent")
        r.add("ann_b", "Benchmark: annualised return", ann_b * HUNDRED, "percent")
        r.add("vol_b", "Benchmark: annualised volatility", sb * HUNDRED, "percent")
        r.add("sharpe_b", "Benchmark: Sharpe ratio", (mean(rb) - rf) * p / sb if sb else ZERO, "ratio")
        r.add("sys", "Systematic share of variance (R²)", corr * corr * HUNDRED, "percent")


def _performance(x: Inputs) -> Result:
    rows = x.table("data", min_rows=3)
    p = Decimal(x.choice("per_year"))
    rf_a = x.rate("rf")
    mar_a = x.rate("mar", default=rf_a)
    rp = [rr["rp"] for rr in rows]
    has_b = all(rr["rb"] is not None for rr in rows)
    if not has_b and any(rr["rb"] is not None for rr in rows):
        raise CalcError("Give the benchmark for every period, or for none.", "data")
    rb: list[Decimal] = [rr["rb"] for rr in rows] if has_b else []
    n = Decimal(len(rp))
    with localcontext(ctx()):
        rf = periodic_rf(rf_a, p)
        mar = periodic_rf(mar_a, p)
        sp = sd_s(rp)
        vol = sp * sqrt(p)
        ann = pw(chain(rp), p / n) - ONE
        excess = (mean(rp) - rf) * p
        r = Result(value("sharpe", "Sharpe ratio", excess / vol if vol else ZERO, "ratio"))
        r.add("ann", "Annualised return (geometric)", ann * HUNDRED, "percent")
        r.add("vol", "Annualised volatility", vol * HUNDRED, "percent")
        dd_dev = sqrt(sum((min(ZERO, v - mar) ** 2 for v in rp), ZERO) / n) * sqrt(p)
        if dd_dev:
            r.add(
                "sortino",
                f"Sortino ratio (target {fmt(mar_a * HUNDRED, 'percent')}% a year)",
                (mean(rp) - mar) * p / dd_dev,
                "ratio",
            )
        r.add("downside", "Downside deviation, annualised", dd_dev * HUNDRED, "percent")
        idx = [ONE]
        for v in rp:
            idx.append(idx[-1] * (ONE + v))
        mdd, *_ = drawdown(idx)
        r.add("max_dd", "Maximum drawdown", mdd * HUNDRED, "percent")
        if mdd < 0:
            r.add("calmar", "Calmar ratio", ann / -mdd, "ratio")
        if has_b:
            _benchmark(r, rp, rb, p=p, rf=rf, rf_a=rf_a, excess=excess, vol=vol)
        else:
            r.warnings.append(
                "Add the benchmark's return for each period for beta, alpha, Treynor, tracking "
                "error, information ratio, M² and capture ratios."
            )
        r.steps = [
            f"Per period risk-free = (1 + {fmt(rf_a * HUNDRED, 'percent')}%)^(1/{fmt(p, 'number')}) − 1",
            "Sharpe = (mean return − risk-free) × p / (SD × √p)",
            "Sortino = (mean return − target) × p / downside deviation;  DD = √(Σ min(0, r − target)² / "
            "n) × √p",
            "Beta = cov(Rp, Rb) / var(Rb);  Jensen's α = [mean Rp − (Rf + β(mean Rb − Rf))] × p",
            "Treynor = annual excess return / β;  IR = annual mean active return / tracking error",
            "M² = Rf + Sharpe × benchmark volatility",
        ]
    return r


register(
    Calculator(
        key="performance",
        family="risk",
        title="Sharpe, Sortino, alpha, beta (from returns)",
        description="Period returns of a portfolio or fund, and of a benchmark if you have it: Sharpe, "
        "Sortino, "
        "Treynor, Jensen's alpha, beta, R squared, tracking error, information ratio, M², capture "
        "ratios, maximum drawdown and Calmar.",
        keywords="sharpe sortino treynor jensen alpha beta tracking error information ratio m2 modigliani "
        "capture "
        "ratio calmar drawdown volatility performance risk adjusted",
        fields=[
            Field("data", "Returns by period", "table", columns=PAIR, rows=PAIR_EXAMPLE, fill="returns_pair"),
            Field("per_year", "Periods a year", "choice", "12", options=PER_YEAR),
            Field("rf", "Risk-free rate, annual (%)", "percent", "6.5", default_from="risk_free"),
            Field(
                "mar",
                "Target return for Sortino, annual (%)",
                "percent",
                "",
                "Blank: the risk-free rate",
                optional=True,
            ),
        ],
        run=_performance,
    )
)


# ------------------------------------------------------------------------------------------- summary figures


def _summary(x: Inputs) -> Result:
    rp = x.rate("rp")
    rf = x.rate("rf")
    sp = x.rate("sp", above=ZERO)
    with localcontext(ctx()):
        sharpe = (rp - rf) / sp
        r = Result(value("sharpe", "Sharpe ratio", sharpe, "ratio"))
        beta = x.opt("beta")
        rm = x.opt("rm")
        sm = x.opt("sm")
        if beta is not None and beta != 0:
            r.add("treynor", "Treynor ratio", (rp - rf) / beta * HUNDRED, "percent")
        if beta is not None and rm is not None:
            required = rf + beta * (rm / HUNDRED - rf)
            r.add("capm", "CAPM required return", required * HUNDRED, "percent")
            r.add("alpha", "Jensen's alpha (return − CAPM)", (rp - required) * HUNDRED, "percent")
        if sm is not None and sm > 0:
            m2 = rf + sharpe * sm / HUNDRED
            r.add("m2", "M² (return at the market's risk)", m2 * HUNDRED, "percent")
            if rm is not None:
                r.add("m2_alpha", "M² alpha over the market", (m2 - rm / HUNDRED) * HUNDRED, "percent")
                r.add("sharpe_m", "Market's Sharpe ratio", (rm / HUNDRED - rf) / (sm / HUNDRED), "ratio")
        dd = x.opt("dd")
        if dd is not None and dd > 0:
            mar = x.rate("mar", default=rf)
            r.add("sortino", "Sortino ratio", (rp - mar) / (dd / HUNDRED), "ratio")
        te = x.opt("te")
        if te is not None and te > 0 and rm is not None:
            r.add(
                "ir",
                "Information ratio (active return ÷ tracking error)",
                (rp - rm / HUNDRED) / (te / HUNDRED),
                "ratio",
            )
        r.steps = [
            "Sharpe = (Rp − Rf) / σp;  Treynor = (Rp − Rf) / βp",
            "CAPM = Rf + β(Rm − Rf);  Jensen's α = Rp − CAPM",
            "M² = Rf + Sharpe × σm;  Sortino = (Rp − target) / downside deviation;  IR = (Rp − Rb) / TE",
        ]
    return r


register(
    Calculator(
        key="ratios",
        family="risk",
        title="Risk-adjusted ratios from summary figures",
        description="The CFA exam way: from a portfolio's return, risk and beta (and the market's), work out "
        "Sharpe, Treynor, Jensen's alpha, CAPM, M², Sortino and the information ratio. Leave blank "
        "what you do not have.",
        keywords="sharpe treynor jensen alpha capm m2 sortino information ratio summary cfa",
        fields=[
            Field("rp", "Portfolio return (%)", "percent", "14"),
            Field("sp", "Portfolio standard deviation (%)", "percent", "18"),
            Field("rf", "Risk-free rate (%)", "percent", "6.5", default_from="risk_free"),
            Field("beta", "Portfolio beta", "number", "1.1", optional=True),
            Field("rm", "Market return (%)", "percent", "12", optional=True),
            Field("sm", "Market standard deviation (%)", "percent", "15", optional=True),
            Field("dd", "Downside deviation (%)", "percent", "", optional=True),
            Field(
                "mar",
                "Target return for Sortino (%)",
                "percent",
                "",
                "Blank: the risk-free rate",
                optional=True,
            ),
            Field("te", "Tracking error (%)", "percent", "", optional=True),
        ],
        run=_summary,
    )
)


# ------------------------------------------------------------------------------------------- VaR

VAR_SERIES = (Column("r", "Return %", "percent"),)


def _var(x: Inputs) -> Result:
    mode = x.choice("method")
    amount = x.num("amount", above=ZERO)
    c = x.rate("confidence")
    if not Decimal("0.5") <= c < ONE:
        raise CalcError("Confidence must be from 50% to just under 100%.", "confidence")
    days = x.num("days", default=ONE, above=ZERO)
    with localcontext(ctx()):
        if mode == "parametric":
            mu = x.rate("mean")
            sd = x.rate("sd", above=ZERO)
            h = days / Decimal(x.choice("basis"))
            m_h, s_h = mu * h, sd * sqrt(h)
            z = norm_inv(c)
            var = -(m_h - z * s_h)
            es = -(m_h - s_h * norm_pdf(z) / (ONE - c))
            r = Result(value("var", f"Value at risk, {fmt(c * HUNDRED, 'percent')}%", var * amount, "money"))
            r.add("var_pct", "…as a share of the amount", var * HUNDRED, "percent")
            r.add("es", "Expected shortfall (CVaR): average loss beyond VaR", es * amount, "money")
            r.add("z", "z", z, "number")
            r.steps = [
                "VaR = −(μ·h − z·σ·√h) × amount, h = days / days a year",
                "Expected shortfall = −(μ·h − σ·√h · φ(z) / (1 − c)) × amount",
            ]
        else:
            rs = [rr["r"] for rr in x.table("returns", min_rows=10)]
            q = percentile_inc(rs, ONE - c)
            tail = [v for v in rs if v <= q]
            scale = sqrt(days)
            r = Result(
                value(
                    "var",
                    f"Value at risk, {fmt(c * HUNDRED, 'percent')}% (historical)",
                    -q * scale * amount,
                    "money",
                )
            )
            r.add("var_pct", "…as a share of the amount", -q * scale * HUNDRED, "percent")
            r.add(
                "es",
                "Expected shortfall: average of the losses at or beyond it",
                -mean(tail) * scale * amount,
                "money",
            )
            r.add("n", "Returns used", Decimal(len(rs)), "count")
            if days != 1:
                r.warnings.append(
                    "Historical VaR for more than one period is scaled by √periods, which assumes "
                    "independent returns."
                )
            r.steps = ["VaR = the (1 − confidence) percentile of the returns (PERCENTILE.INC), as a loss"]
        r.add("prob", "Chance of a loss at least this big", (ONE - c) * HUNDRED, "percent")
    return r


register(
    Calculator(
        key="var",
        family="risk",
        title="Value at risk (VaR) and expected shortfall",
        description="How much could be lost over a period at a confidence level: parametric (normal) from "
        "a mean "
        "and standard deviation, or historical from past returns; with expected shortfall (CVaR).",
        keywords="var value at risk expected shortfall cvar parametric historical confidence loss",
        fields=[
            Field(
                "method",
                "Method",
                "choice",
                "parametric",
                options=(("parametric", "Parametric (normal)"), ("historical", "Historical returns")),
            ),
            Field("amount", "Amount invested", "money", "1000000"),
            Field("confidence", "Confidence (%)", "percent", "95"),
            Field("days", "Holding period (in the same periods as the returns)", "number", "1"),
            Field(
                "mean", "Expected return a year (%)", "percent", "12", show_when={"method": ["parametric"]}
            ),
            Field(
                "sd", "Standard deviation a year (%)", "percent", "18", show_when={"method": ["parametric"]}
            ),
            Field(
                "basis",
                "Days in a year for the holding period",
                "choice",
                "252",
                options=(("252", "252 trading days"), ("365", "365 days")),
                show_when={"method": ["parametric"]},
            ),
            Field(
                "returns",
                "Past returns",
                "table",
                columns=VAR_SERIES,
                show_when={"method": ["historical"]},
                rows=[
                    {"r": v}
                    for v in (
                        "1.2",
                        "-0.8",
                        "0.5",
                        "-2.1",
                        "1.7",
                        "0.3",
                        "-1.4",
                        "2.2",
                        "-0.6",
                        "0.9",
                        "-3.0",
                        "1.1",
                        "0.4",
                        "-0.2",
                        "1.8",
                        "-1.1",
                        "0.7",
                        "-2.5",
                        "1.3",
                        "0.1",
                    )
                ],
            ),
        ],
        run=_var,
    )
)


# ------------------------------------------------------------------------------------------- safety first

CHOICES = (
    Column("name", "Portfolio", "text"),
    Column("er", "Expected return %", "percent"),
    Column("sd", "Standard deviation %", "percent"),
)


def _safety(x: Inputs) -> Result:
    rows = x.table("data", min_rows=1)
    threshold = x.rate("threshold")
    with localcontext(ctx()):
        scored: list[tuple[dict[str, Any], Decimal]] = []
        for rr in rows:
            if rr["sd"] <= 0:
                raise CalcError(f"{rr['name']}: the standard deviation must be more than zero.", "data")
            scored.append((rr, (rr["er"] - threshold) / rr["sd"]))
        best = max(scored, key=lambda t: t[1])
        r = Result(value("best", "Best by safety-first", Decimal(0), "text"))
        r.answer.value = r.answer.exact = str(best[0]["name"])
        r.add("sfr", "Its safety-first ratio", best[1], "ratio")
        r.add(
            "shortfall",
            "Its chance of falling below the threshold (normal)",
            norm_cdf(-best[1]) * HUNDRED,
            "percent",
        )
        r.tables.append(
            TableOut(
                "all",
                "Every portfolio",
                [
                    {"key": "name", "label": "Portfolio", "unit": "text"},
                    {"key": "er", "label": "Expected return", "unit": "percent"},
                    {"key": "sd", "label": "Standard deviation", "unit": "percent"},
                    {"key": "sfr", "label": "Safety-first ratio", "unit": "ratio"},
                    {"key": "p", "label": "Chance below threshold", "unit": "percent"},
                ],
                [
                    [
                        str(rr["name"]),
                        fmt(rr["er"] * HUNDRED, "percent"),
                        fmt(rr["sd"] * HUNDRED, "percent"),
                        fmt(s, "ratio"),
                        fmt(norm_cdf(-s) * HUNDRED, "percent"),
                    ]
                    for rr, s in scored
                ],
            )
        )
        r.steps = [
            "SFRatio = (expected return − threshold) / standard deviation; choose the highest",
            "Chance below the threshold = Φ(−SFRatio), if returns are normal",
        ]
    return r


register(
    Calculator(
        key="safety_first",
        family="risk",
        title="Roy's safety-first ratio",
        description="Which portfolio is least likely to fall below a minimum return you must earn.",
        keywords="roy safety first ratio shortfall threshold minimum return cfa",
        fields=[
            Field("threshold", "Minimum acceptable return (%)", "percent", "4"),
            Field(
                "data",
                "Portfolios",
                "table",
                columns=CHOICES,
                rows=[
                    {"name": "A", "er": "9", "sd": "12"},
                    {"name": "B", "er": "11", "sd": "20"},
                    {"name": "C", "er": "6.5", "sd": "5"},
                ],
            ),
        ],
        run=_safety,
    )
)
