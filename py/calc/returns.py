"""Returns (decision #120, family E): holding period return and CAGR, a series of period returns (arithmetic
and geometric means, rolling returns), and time-weighted against money-weighted return."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, localcontext
from itertools import pairwise

from .cashflow import irr_roots, sign_changes, xnpv
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
    value,
)

D365 = Decimal(365)
PER_YEAR = (
    ("252", "Daily, trading days (252)"),
    ("365", "Daily, calendar days (365)"),
    ("52", "Weekly (52)"),
    ("12", "Monthly (12)"),
    ("4", "Quarterly (4)"),
    ("1", "Yearly (1)"),
)


def annualise(growth: Decimal, years: Decimal) -> Decimal:
    """(growth)^(1/years) - 1, where growth is 1 + total return."""
    if growth <= 0:
        raise CalcError("Everything was lost, so there is no annual rate.", code="no_solution")
    with localcontext(ctx()):
        return pw(growth, ONE / years) - ONE


def chain(rs: list[Decimal]) -> Decimal:
    """1 + the compound of period returns."""
    g = ONE
    with localcontext(ctx()):
        for r in rs:
            g *= ONE + r
    return g


# ------------------------------------------------------------------------------------------- HPR and CAGR


def _hpr(x: Inputs) -> Result:
    begin = x.num("begin", above=ZERO)
    end = x.num("end", min_=ZERO)
    income = x.num("income", default=ZERO)
    if x.choice("period") == "dates":
        d0, d1 = x.date("start"), x.date("finish")
        days = (d1 - d0).days
        if days <= 0:
            raise CalcError("The end date must be after the start date.", "finish")
        years = Decimal(days) / D365
    else:
        years = x.num("years", above=ZERO)
    with localcontext(ctx()):
        hpr = (end + income - begin) / begin
        r = Result(value("hpr", "Holding period return", hpr * HUNDRED, "percent"))
        r.add("gain", "Gain (end + income − begin)", end + income - begin, "money")
        r.add("cagr", "Annualised (CAGR)", annualise(ONE + hpr, years) * HUNDRED, "percent")
        r.add("simple", "Annualised, simple (HPR ÷ years)", hpr / years * HUNDRED, "percent")
        r.add("multiple", "Money multiple", (end + income) / begin, "ratio")
        r.add("years", "Years", years, "years")
        infl = x.opt("inflation")
        if infl is not None:
            real = (ONE + annualise(ONE + hpr, years)) / (ONE + infl / HUNDRED) - ONE
            r.add("real", "Real annual return (after inflation)", real * HUNDRED, "percent")
        tax = x.opt("tax")
        if tax is not None:
            after = hpr * (ONE - tax / HUNDRED) if hpr > 0 else hpr
            r.add("after_tax", "Holding period return after tax on the gain", after * HUNDRED, "percent")
            r.add(
                "after_tax_cagr", "Annualised after tax", annualise(ONE + after, years) * HUNDRED, "percent"
            )
        r.steps = ["HPR = (end + income − begin) / begin", "CAGR = (1 + HPR)^(1/years) − 1"]
    return r


register(
    Calculator(
        key="hpr",
        family="returns",
        title="Holding period return and CAGR",
        description="What an investment returned between two values, with any income received: holding "
        "period "
        "return, CAGR, simple annual return, and after inflation or tax if you give them.",
        keywords="hpr holding period return cagr annualised absolute return growth multiple real after tax",
        fields=[
            Field("begin", "Value at the start", "money", "100000"),
            Field("end", "Value at the end", "money", "185000"),
            Field("income", "Income received in between", "money", "0", optional=True),
            Field(
                "period",
                "Period given as",
                "choice",
                "years",
                options=(("years", "Years"), ("dates", "Dates")),
            ),
            Field("years", "Years", "number", "5", show_when={"period": ["years"]}),
            Field("start", "Start date", "date", "2021-04-01", show_when={"period": ["dates"]}),
            Field("finish", "End date", "date", "2026-03-31", show_when={"period": ["dates"]}),
            Field("inflation", "Inflation a year (%)", "percent", "", optional=True),
            Field("tax", "Tax on the gain (%)", "percent", "", optional=True),
        ],
        run=_hpr,
    )
)


# ------------------------------------------------------------------------------------------- a series

RETURNS = (Column("period", "Period", "text", optional=True), Column("r", "Return %", "percent"))
RETURN_EXAMPLE = [
    {"period": m, "r": r}
    for m, r in (
        ("Apr", "2.1"),
        ("May", "-1.4"),
        ("Jun", "3.3"),
        ("Jul", "0.8"),
        ("Aug", "-2.6"),
        ("Sep", "1.9"),
        ("Oct", "4.2"),
        ("Nov", "-0.7"),
        ("Dec", "1.1"),
        ("Jan", "-3.0"),
        ("Feb", "2.4"),
        ("Mar", "1.6"),
    )
]


def _series(x: Inputs) -> Result:
    rows = x.table("data", min_rows=1)
    rs = [rr["r"] for rr in rows]
    p = Decimal(x.choice("per_year"))
    n = len(rs)
    with localcontext(ctx()):
        if any(r <= -1 for r in rs):
            raise CalcError(
                "A period lost everything (−100% or worse); the returns cannot be chained.", "data"
            )
        g = chain(rs)
        arith = sum(rs, ZERO) / n
        geo = pw(g, ONE / Decimal(n)) - ONE
        r = Result(value("cumulative", "Cumulative return", (g - ONE) * HUNDRED, "percent"))
        r.add("arith", "Arithmetic mean per period", arith * HUNDRED, "percent")
        r.add("geo", "Geometric mean per period", geo * HUNDRED, "percent")
        r.add("annual", "Annualised (geometric)", (pw(g, p / Decimal(n)) - ONE) * HUNDRED, "percent")
        r.add("annual_arith", "Annualised arithmetic mean (× periods a year)", arith * p * HUNDRED, "percent")
        r.add("best", "Best period", max(rs) * HUNDRED, "percent")
        r.add("worst", "Worst period", min(rs) * HUNDRED, "percent")
        r.add("positive", "Periods with a gain", Decimal(sum(1 for v in rs if v > 0)), "count")
        r.add("count", "Periods", Decimal(n), "count")
        window = x.int_("window", default=0, min_=0, max_=10_000)
        if window and window <= n:
            rolling = []
            for i in range(n - window + 1):
                gw = chain(rs[i : i + window])
                rolling.append((i, pw(gw, p / Decimal(window)) - ONE))
            vals = [v for _, v in rolling]
            r.add(
                "roll_avg",
                f"Rolling {window}-period returns, annualised: average",
                sum(vals, ZERO) / len(vals) * HUNDRED,
                "percent",
            )
            r.add("roll_min", "…lowest", min(vals) * HUNDRED, "percent")
            r.add("roll_max", "…highest", max(vals) * HUNDRED, "percent")
            r.add("roll_neg", "…windows that lost money", Decimal(sum(1 for v in vals if v < 0)), "count")
        elif window:
            r.warnings.append(f"The rolling window ({window}) is longer than the series ({n} periods).")
        xs, ys, idx = [], [], HUNDRED
        rows_out = []
        for i, (row, ret) in enumerate(zip(rows, rs, strict=True)):
            idx = idx * (ONE + ret)
            label = row["period"] or str(i + 1)
            xs.append(label)
            ys.append(fmt(idx, "money"))
            rows_out.append([label, fmt(ret * HUNDRED, "percent"), fmt(idx, "number")])
        r.chart = Chart(
            "line", "Growth of 100", "Period", "money", xs, [{"name": "Value of 100", "values": ys}]
        )
        r.tables.append(
            TableOut(
                "growth",
                "Growth of 100",
                [
                    {"key": "period", "label": "Period", "unit": "text"},
                    {"key": "r", "label": "Return", "unit": "percent"},
                    {"key": "index", "label": "Value of 100", "unit": "number"},
                ],
                rows_out,
            )
        )
        r.steps = [
            "Cumulative = Π(1 + r) − 1;  geometric mean = (Π(1 + r))^(1/n) − 1",
            "Annualised = (Π(1 + r))^(periods a year / n) − 1",
        ]
    return r


register(
    Calculator(
        key="return_series",
        family="returns",
        title="Returns over many periods",
        description="A run of monthly (or any) returns: cumulative return, arithmetic and geometric "
        "means, the "
        "annualised return, best and worst, rolling returns, and the growth of 100.",
        keywords="arithmetic geometric mean return series cumulative annualised rolling returns monthly "
        "growth of 100",
        fields=[
            Field("data", "Period returns", "table", columns=RETURNS, rows=RETURN_EXAMPLE, fill="returns"),
            Field("per_year", "Periods a year", "choice", "12", options=PER_YEAR),
            Field("window", "Rolling window (periods; 0 for none)", "int", "6", optional=True),
        ],
        run=_series,
    )
)


# ------------------------------------------------------------------------------------------- TWR and MWR

VALUATIONS = (
    Column("date", "Date", "date"),
    Column("value", "Value before money in or out", "money"),
    Column("flow", "Money in (+) or out (−)", "money", optional=True),
)
VALUATION_EXAMPLE = [
    {"date": "2025-04-01", "value": "0", "flow": "100000"},
    {"date": "2025-07-01", "value": "108000", "flow": "50000"},
    {"date": "2025-10-01", "value": "150000", "flow": "-20000"},
    {"date": "2026-03-31", "value": "146000", "flow": ""},
]


def _twr(x: Inputs) -> Result:
    rows = sorted(x.table("data", min_rows=2), key=lambda rr: rr["date"])
    with localcontext(ctx()):
        index = ONE
        table: list[list[str]] = []
        for prev, cur in pairwise(rows):
            start = prev["value"] + (prev["flow"] or ZERO)
            if start <= 0:
                raise CalcError(
                    f"On {prev['date'].isoformat()} nothing is invested after the money in or out, so "
                    "the next period has no return.",
                    "data",
                )
            sub = cur["value"] / start - ONE
            index *= ONE + sub
            table.append(
                [
                    prev["date"].isoformat(),
                    cur["date"].isoformat(),
                    fmt(start, "money"),
                    fmt(cur["value"], "money"),
                    fmt(sub * HUNDRED, "percent"),
                ]
            )
        days = (rows[-1]["date"] - rows[0]["date"]).days
        twr = index - ONE
        r = Result(value("twr", "Time-weighted return", twr * HUNDRED, "percent"))
        if days > 0:
            r.add(
                "twr_annual",
                "Time-weighted, annualised",
                annualise(index, Decimal(days) / D365) * HUNDRED,
                "percent",
            )
        flows: list[tuple[dt.date, Decimal]] = []
        first = rows[0]
        flows.append((first["date"], -(first["value"] + (first["flow"] or ZERO))))
        for rr in rows[1:-1]:
            if rr["flow"]:
                flows.append((rr["date"], -rr["flow"]))
        last = rows[-1]
        flows.append(
            (last["date"], last["value"])
        )  # money moved on the last day cancels out: value is before it
        roots = irr_roots(lambda q: xnpv(q, flows), sign_changes([a for _, a in flows]))
        if roots:
            r.add("mwr", "Money-weighted return (XIRR, annual)", roots[0] * HUNDRED, "percent")
        else:
            r.add("mwr", "Money-weighted return (XIRR, annual)", "none", "text")
        put_in = sum((rr["flow"] for rr in rows if rr["flow"] and rr["flow"] > 0), ZERO) + first["value"]
        taken = -sum((rr["flow"] for rr in rows if rr["flow"] and rr["flow"] < 0), ZERO)
        r.add("put_in", "Money put in (with the opening value)", put_in, "money")
        r.add("taken", "Money taken out", taken, "money")
        r.add("gain", "Gain (end + taken out − put in)", last["value"] + taken - put_in, "money")
        r.tables.append(
            TableOut(
                "periods",
                "Sub-periods",
                [
                    {"key": "from", "label": "From", "unit": "date"},
                    {"key": "to", "label": "To", "unit": "date"},
                    {"key": "start", "label": "Value after money in/out", "unit": "money"},
                    {"key": "end", "label": "Value at the end", "unit": "money"},
                    {"key": "r", "label": "Return", "unit": "percent"},
                ],
                table,
            )
        )
        r.steps = [
            "Each sub-period: r = value at its end / (value at its start + money in or out then) − 1",
            "TWR = Π(1 + r) − 1, which the timing of your money does not affect",
            "MWR = the XIRR of your money in and out with the final value; it does reflect the timing",
        ]
    return r


register(
    Calculator(
        key="twr_mwr",
        family="returns",
        title="Time-weighted and money-weighted return",
        description="Valuations on each date you put money in or took it out. The time-weighted return "
        "measures "
        "the investment; the money-weighted return (XIRR) measures your own result, timing included.",
        keywords="twr mwr time weighted money weighted return xirr cfa performance measurement",
        fields=[
            Field(
                "data",
                "Valuations",
                "table",
                columns=VALUATIONS,
                rows=VALUATION_EXAMPLE,
                hint="Value just before the money moved that day; the last row is the final value",
            )
        ],
        run=_twr,
    )
)
