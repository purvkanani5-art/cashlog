"""Cash flows (decision #120, family D): the BA II Plus CF worksheet (NPV, IRR, MIRR, payback, PI, NFV, EAA)
and dated cash flows (XNPV, XIRR, as in Excel: Actual/365 from the first date)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from decimal import Decimal, localcontext
from itertools import pairwise

from .core import (
    HUNDRED,
    ONE,
    TWO,
    ZERO,
    CalcError,
    Calculator,
    Chart,
    Field,
    Flow,
    Inputs,
    Result,
    TableOut,
    all_roots,
    ctx,
    fmt,
    newton,
    pw,
    register,
    value,
)

D365 = Decimal(365)
LO, HI = Decimal("-0.9999"), Decimal(1000)
TABLE_MAX = 1_200
PER_YEAR = (("1", "Yearly"), ("2", "Half-yearly"), ("4", "Quarterly"), ("12", "Monthly"))


def expand(flows: list[Flow]) -> list[Decimal]:
    out: list[Decimal] = []
    for f in flows:
        out.extend([f.amount] * f.count)
    return out


def npv(rate: Decimal, flows: list[Flow]) -> Decimal:
    """Sum of CFt / (1 + r)^t with CF0 at t = 0; a group of Fj equal flows is one geometric sum."""
    with localcontext(ctx()):
        v = ONE / (ONE + rate)
        total, t = ZERO, 0
        for f in flows:
            if f.count == 1:
                total += f.amount * pw(v, t)
            elif v == ONE:
                total += f.amount * f.count
            else:
                total += f.amount * pw(v, t) * (ONE - pw(v, f.count)) / (ONE - v)
            t += f.count
        return total


def sign_changes(amounts: list[Decimal]) -> int:
    signs = [a > 0 for a in amounts if a != 0]
    return sum(1 for a, b in pairwise(signs) if a != b)


def irr_roots(f: Callable[[Decimal], Decimal], changes: int) -> list[Decimal]:
    """With one sign change there is exactly one IRR (Descartes), found by Newton from 10%; otherwise, or if
    Newton fails, every root on the scan grid."""
    if changes == 0:
        return []
    if changes == 1:
        root = newton(f, LO, HI, Decimal("0.1"))
        if root is not None:
            return [root]
    return all_roots(f, LO, HI, limit=10)


def _payback(amounts: list[Decimal], rate: Decimal | None) -> Decimal | None:
    """Periods until the running total (discounted when a rate is given) turns non-negative, with the last
    period counted in part. None when it never does."""
    with localcontext(ctx()):
        cum = ZERO
        for t, a in enumerate(amounts):
            pv = a if rate is None else a / pw(ONE + rate, t)
            before = cum
            cum += pv
            if t > 0 and before < 0 <= cum:
                return Decimal(t - 1) + (-before / pv if pv else ZERO)
        return None


def _profile(f: Callable[[Decimal], Decimal], top: Decimal, title: str) -> Chart:
    xs: list[str] = []
    ys: list[str] = []
    steps = 24
    with localcontext(ctx()):
        for k in range(steps + 1):
            r = top * k / steps
            xs.append(fmt(r * HUNDRED, "percent"))
            ys.append(fmt(f(r), "money"))
    return Chart("line", title, "Discount rate (%)", "money", xs, [{"name": "NPV", "values": ys}])


def _cash_flows(x: Inputs) -> Result:
    flows = x.flows("flows")
    rate = x.rate("rate")
    per_year = Decimal(x.choice("per_year"))
    finance = x.rate("finance_rate", default=rate)
    reinvest = x.rate("reinvest_rate", default=rate)
    amounts = expand(flows) if sum(f.count for f in flows) <= 120_000 else []
    periods = sum(f.count for f in flows) - 1
    with localcontext(ctx()):
        value_now = npv(rate, flows)
        r = Result(value("npv", "NPV", value_now, "money"))
        r.add("nfv", f"NFV (value at period {periods})", value_now * pw(ONE + rate, periods), "money")
        changes = sign_changes([f.amount for f in flows])
        roots = irr_roots(lambda q: npv(q, flows), changes)
        _add_irr(r, roots, changes, per_year)
        cf0 = flows[0].amount
        if cf0 < 0:
            r.add("pi", "Profitability index", (value_now - cf0) / -cf0, "ratio")
        if periods > 0 and rate != 0:
            eaa = value_now * rate / (ONE - pw(ONE + rate, -periods))
            r.add("eaa", "Equivalent annuity (per period)", eaa, "money")
        mirr = _mirr(flows, finance, reinvest, periods)
        if mirr is not None:
            r.add("mirr", "MIRR per period", mirr * HUNDRED, "percent")
        if amounts:
            pb = _payback(amounts, None)
            dpb = _payback(amounts, rate)
            r.add(
                "payback",
                "Payback (periods)",
                pb if pb is not None else "never",
                "periods" if pb is not None else "text",
            )
            r.add(
                "discounted_payback",
                "Discounted payback (periods)",
                dpb if dpb is not None else "never",
                "periods" if dpb is not None else "text",
            )
        r.add(
            "inflows",
            "Sum of inflows",
            sum((a.amount * a.count for a in flows if a.amount > 0), ZERO),
            "money",
        )
        r.add(
            "outflows",
            "Sum of outflows",
            sum((a.amount * a.count for a in flows if a.amount < 0), ZERO),
            "money",
        )
        if amounts and len(amounts) <= TABLE_MAX:
            r.tables.append(_period_table(amounts, rate))
        top = max([rate * TWO, Decimal("0.2"), *[q * TWO for q in roots if q > 0][:1]])
        r.chart = _profile(lambda q: npv(q, flows), min(top, Decimal(5)), "NPV profile")
        r.steps = [
            "NPV = Σ CFt / (1 + r)^t;  NFV = NPV × (1 + r)^N",
            "IRR: the rate where NPV = 0",
            "MIRR = (FV of inflows at the reinvestment rate / PV of outflows at the finance rate)^(1/N) − 1",
            "PI = PV of the later flows / initial outlay;  EAA = NPV × r / (1 − (1 + r)^−N)",
        ]
    return r


def _add_irr(r: Result, roots: list[Decimal], changes: int, per_year: Decimal) -> None:
    with localcontext(ctx()):
        if not roots:
            r.add(
                "irr",
                "IRR",
                "none",
                "text",
                "No rate makes NPV zero: the flows never change sign, or change in a way that has no root.",
            )
        else:
            irr = roots[0]
            r.add("irr", "IRR per period", irr * HUNDRED, "percent")
            if per_year != 1:
                r.add(
                    "irr_annual",
                    "IRR, effective annual",
                    (pw(ONE + irr, per_year) - ONE) * HUNDRED,
                    "percent",
                )
                r.add(
                    "irr_nominal",
                    "IRR, nominal annual (per period × periods a year)",
                    irr * per_year * HUNDRED,
                    "percent",
                )
            if len(roots) > 1:
                r.warnings.append(
                    f"The flows change sign {changes} times and have {len(roots)} IRRs: "
                    + ", ".join(fmt(q * HUNDRED, "percent") + "%" for q in roots)
                    + ". Use NPV or MIRR to decide."
                )
        if changes > 1 and len(roots) <= 1:
            r.warnings.append(f"The flows change sign {changes} times, so there may be more than one IRR.")


def _period_table(amounts: list[Decimal], rate: Decimal) -> TableOut:
    with localcontext(ctx()):
        rows, cum, cum_pv = [], ZERO, ZERO
        for t, a in enumerate(amounts):
            df = ONE / pw(ONE + rate, t)
            cum += a
            cum_pv += a * df
            rows.append(
                [
                    str(t),
                    fmt(a, "money"),
                    fmt(df, "number"),
                    fmt(a * df, "money"),
                    fmt(cum, "money"),
                    fmt(cum_pv, "money"),
                ]
            )
        return TableOut(
            "flows",
            "Each period",
            [
                {"key": "t", "label": "Period", "unit": "count"},
                {"key": "cf", "label": "Cash flow", "unit": "money"},
                {"key": "df", "label": "Discount factor", "unit": "number"},
                {"key": "pv", "label": "Present value", "unit": "money"},
                {"key": "cum", "label": "Cumulative", "unit": "money"},
                {"key": "cum_pv", "label": "Cumulative PV", "unit": "money"},
            ],
            rows,
        )


def _mirr(flows: list[Flow], finance: Decimal, reinvest: Decimal, periods: int) -> Decimal | None:
    if periods <= 0:
        return None
    with localcontext(ctx()):
        neg = [Flow(f.amount if f.amount < 0 else ZERO, f.count) for f in flows]
        pos = [Flow(f.amount if f.amount > 0 else ZERO, f.count) for f in flows]
        pv_neg = npv(finance, neg)
        fv_pos = npv(reinvest, pos) * pw(ONE + reinvest, periods)
        if pv_neg >= 0 or fv_pos <= 0:
            return None
        return pw(fv_pos / -pv_neg, ONE / Decimal(periods)) - ONE


register(
    Calculator(
        key="cash_flows",
        family="cashflow",
        title="Cash flow worksheet (NPV, IRR, MIRR)",
        description="CF0 now, then CF1, CF2 … one period apart, each repeated as many times as you say (Fj), "
        "as on a BA II Plus. NPV, NFV, IRR (every one, when there are several), MIRR, payback, discounted "
        "payback, profitability index and equivalent annuity.",
        keywords="npv irr mirr nfv payback discounted profitability index cash flow worksheet capital "
        "budgeting eaa",
        fields=[
            Field("flows", "Cash flows", "flows", "", "Paid out negative, received positive"),
            Field("rate", "Discount rate per period (%)", "percent", "10"),
            Field(
                "per_year",
                "Periods per year",
                "choice",
                "1",
                options=PER_YEAR,
                hint="To show IRR as an annual rate when the periods are months or quarters",
            ),
            Field(
                "finance_rate",
                "MIRR finance rate (%)",
                "percent",
                "",
                "Blank: the discount rate",
                optional=True,
            ),
            Field(
                "reinvest_rate",
                "MIRR reinvestment rate (%)",
                "percent",
                "",
                "Blank: the discount rate",
                optional=True,
            ),
        ],
        run=_cash_flows,
    )
)


# ------------------------------------------------------------------------------------------- dated flows


def xnpv(rate: Decimal, flows: list[tuple[dt.date, Decimal]]) -> Decimal:
    d0 = flows[0][0]
    with localcontext(ctx()):
        if rate <= -1:
            raise CalcError("The rate must be above −100%.", "rate")
        lr = (ONE + rate).ln()
        return sum(((a * (-lr * Decimal((d - d0).days) / D365).exp()) for d, a in flows), ZERO)


def _dated(x: Inputs) -> Result:
    flows = x.dated_flows("flows")
    rate = x.rate("rate")
    with localcontext(ctx()):
        v = xnpv(rate, flows)
        r = Result(value("xnpv", f"XNPV at {fmt(rate * HUNDRED, 'percent')}%", v, "money"))
        roots = irr_roots(lambda q: xnpv(q, flows), sign_changes([a for _, a in flows]))
        if roots:
            r.add("xirr", "XIRR (annual)", roots[0] * HUNDRED, "percent")
            if len(roots) > 1:
                r.warnings.append(
                    "More than one rate makes XNPV zero: "
                    + ", ".join(fmt(q * HUNDRED, "percent") + "%" for q in roots)
                    + "."
                )
        else:
            r.add("xirr", "XIRR (annual)", "none", "text", "No rate makes XNPV zero. Check the signs.")
        inflow = sum((a for _, a in flows if a > 0), ZERO)
        outflow = sum((a for _, a in flows if a < 0), ZERO)
        r.add("inflows", "Total received", inflow, "money")
        r.add("outflows", "Total paid", outflow, "money")
        r.add("net", "Net gain (received + paid)", inflow + outflow, "money")
        days = (flows[-1][0] - flows[0][0]).days
        r.add("days", "Days from first to last", Decimal(days), "days")
        if outflow < 0 and days > 0:
            r.add(
                "absolute", "Absolute return (net / paid)", (inflow + outflow) / -outflow * HUNDRED, "percent"
            )
        d0 = flows[0][0]
        rows = []
        for d, a in flows:
            t = Decimal((d - d0).days) / D365
            pv = a / pw(ONE + rate, t)
            rows.append([d.isoformat(), fmt(a, "money"), fmt(t, "years"), fmt(pv, "money")])
        r.tables.append(
            TableOut(
                "flows",
                "Each cash flow",
                [
                    {"key": "date", "label": "Date", "unit": "date"},
                    {"key": "amount", "label": "Amount", "unit": "money"},
                    {"key": "years", "label": "Years from the first", "unit": "years"},
                    {"key": "pv", "label": "Present value", "unit": "money"},
                ],
                rows,
            )
        )
        top = max([rate * TWO, Decimal("0.2"), *[q * TWO for q in roots if q > 0][:1]])
        r.chart = _profile(lambda q: xnpv(q, flows), min(top, Decimal(5)), "XNPV profile")
        r.steps = [
            "XNPV = Σ amount / (1 + r)^(days from the first date / 365)",
            "XIRR: the rate where XNPV = 0",
        ]
    return r


register(
    Calculator(
        key="dated_flows",
        family="cashflow",
        title="Dated cash flows (XNPV, XIRR)",
        description="Cash flows on any dates: SIP instalments and today's value, a property bought and sold, "
        "irregular deposits. Annual XIRR and XNPV as in Excel (Actual/365).",
        keywords="xirr xnpv dated irregular cash flows sip returns annualised",
        fields=[
            Field(
                "flows", "Dated cash flows", "dated_flows", "", "Paid out negative; today's value as received"
            ),
            Field("rate", "Discount rate for XNPV (annual %)", "percent", "10"),
        ],
        run=_dated,
    )
)
