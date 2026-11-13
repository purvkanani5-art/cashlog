"""Time value of money (decision #120, family A): the BA II Plus TVM worksheet, and annuities and
perpetuities.

Sign convention, as on a BA II Plus or in Excel: money you receive is positive, money you pay is negative. A
loan of 10 lakh taken is PV +10,00,000 and its EMI is PMT negative.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, localcontext

from .core import (
    HUNDRED,
    ONE,
    ZERO,
    CalcError,
    Calculator,
    Chart,
    Field,
    Inputs,
    Result,
    TableOut,
    ctx,
    fmt,
    ln,
    pw,
    register,
    solve,
    value,
)

FREQ = (
    ("1", "Yearly (1)"),
    ("2", "Half-yearly (2)"),
    ("4", "Quarterly (4)"),
    ("12", "Monthly (12)"),
    ("52", "Weekly (52)"),
    ("365", "Daily (365)"),
)
TIMING = (
    ("end", "End of each period (ordinary annuity)"),
    ("begin", "Beginning of each period (annuity due)"),
)
SCHEDULE_MAX = 1_200


def periodic_rate(annual: Decimal, p_y: Decimal, c_y: Decimal) -> Decimal:
    """Rate per payment period from a nominal annual rate compounded c_y times a year (BA II Plus I/Y)."""
    with localcontext(ctx()):
        return pw(ONE + annual / c_y, c_y / p_y) - ONE


def annual_from_periodic(i: Decimal, p_y: Decimal, c_y: Decimal) -> Decimal:
    with localcontext(ctx()):
        return c_y * (pw(ONE + i, p_y / c_y) - ONE)


@dataclass
class Tvm:
    """The five TVM values, with i the rate per payment period."""

    n: Decimal
    i: Decimal
    pv: Decimal
    pmt: Decimal
    fv: Decimal
    begin: bool

    def balance(self, i: Decimal | None = None) -> Decimal:
        """PV(1+i)^n + PMT(1+ik)((1+i)^n - 1)/i + FV, which is zero when the five agree."""
        r = self.i if i is None else i
        with localcontext(ctx()):
            if r == 0:
                return self.pv + self.pmt * self.n + self.fv
            g = pw(ONE + r, self.n)
            k = ONE + r if self.begin else ONE
            return self.pv * g + self.pmt * k * (g - ONE) / r + self.fv


def _solve_rate(t: Tvm) -> None:
    if (t.pv >= 0 and t.pmt >= 0 and t.fv >= 0) or (t.pv <= 0 and t.pmt <= 0 and t.fv <= 0):
        raise CalcError(
            "To find the rate, at least one of PV, PMT and FV must be negative (paid) and one positive "
            "(received).",
            "pv",
            code="no_solution",
        )
    t.i = solve(t.balance, Decimal("-0.9999"), Decimal(100), Decimal("0.01"))


def _solve_n(t: Tvm) -> None:
    with localcontext(ctx()):
        if t.i == 0:
            if t.pmt == 0:
                raise CalcError("With no interest, PMT cannot be zero when finding N.", "pmt")
            t.n = -(t.pv + t.fv) / t.pmt
        else:
            k = ONE + t.i if t.begin else ONE
            top, bottom = t.pmt * k - t.fv * t.i, t.pmt * k + t.pv * t.i
            if bottom == 0 or top / bottom <= 0:
                raise CalcError(
                    "No number of periods solves this. Check the signs of PV, PMT and FV.",
                    "n",
                    code="no_solution",
                )
            t.n = ln(top / bottom) / ln(ONE + t.i)
    if t.n <= 0:
        raise CalcError(
            "No positive number of periods solves this. Check the signs.", "n", code="no_solution"
        )


def _solve_amount(t: Tvm, which: str) -> None:
    with localcontext(ctx()):
        g = pw(ONE + t.i, t.n)
        k = ONE + t.i if t.begin else ONE
        annuity = t.n if t.i == 0 else k * (g - ONE) / t.i
        if which == "pmt":
            if annuity == 0:
                raise CalcError("PMT cannot be found for these inputs.", "pmt", code="no_solution")
            t.pmt = -(t.fv + t.pv * g) / annuity
        elif which == "pv":
            t.pv = -(t.fv + t.pmt * annuity) / g
        else:
            t.fv = -(t.pv * g + t.pmt * annuity)


ANSWERS = {
    "n": ("N (number of payments)", "periods", "N = ln[(PMT(1+ik) − FV·i) / (PMT(1+ik) + PV·i)] / ln(1+i)"),
    "i_y": (
        "I/Y (annual rate)",
        "percent",
        "I/Y: the rate where PV(1+i)^N + PMT(1+ik)((1+i)^N − 1)/i + FV = 0",
    ),
    "pv": ("PV (present value)", "money", "PV = −[FV + PMT(1+ik)((1+i)^N − 1)/i] / (1+i)^N"),
    "pmt": ("PMT (payment each period)", "money", "PMT = −(FV + PV(1+i)^N) · i / [(1+ik)((1+i)^N − 1)]"),
    "fv": ("FV (future value)", "money", "FV = −[PV(1+i)^N + PMT(1+ik)((1+i)^N − 1)/i]"),
}


def _tvm(x: Inputs) -> Result:
    solve_for = x.choice("solve")
    p_y = x.num("p_y", above=ZERO)
    c_y = x.num("c_y", above=ZERO)
    annual = x.rate("i_y") if solve_for != "i_y" else ZERO
    if annual <= -c_y:
        raise CalcError("I/Y is too low for this compounding.", "i_y")
    t = Tvm(
        n=x.num("n", above=ZERO) if solve_for != "n" else ZERO,
        i=periodic_rate(annual, p_y, c_y) if solve_for != "i_y" else ZERO,
        pv=x.num("pv") if solve_for != "pv" else ZERO,
        pmt=x.num("pmt") if solve_for != "pmt" else ZERO,
        fv=x.num("fv") if solve_for != "fv" else ZERO,
        begin=x.choice("timing") == "begin",
    )
    if solve_for == "i_y":
        _solve_rate(t)
        annual = annual_from_periodic(t.i, p_y, c_y)
    elif solve_for == "n":
        _solve_n(t)
    else:
        _solve_amount(t, solve_for)
    label, unit, formula = ANSWERS[solve_for]
    with localcontext(ctx()):
        answer = annual * HUNDRED if solve_for == "i_y" else getattr(t, solve_for)
        r = Result(value(solve_for, label, answer, unit))
        r.steps = [
            f"Rate per period i = (1 + {fmt(annual * HUNDRED, 'percent')}% / {fmt(c_y, 'number')})"
            f"^({fmt(c_y, 'number')}/{fmt(p_y, 'number')}) − 1 = {fmt(t.i * HUNDRED, 'percent')}%",
            formula,
        ]
        r.add("i", "Rate per period", t.i * HUNDRED, "percent")
        r.add("ear", "Effective annual rate", (pw(ONE + t.i, p_y) - ONE) * HUNDRED, "percent")
        r.add("years", "Term in years", t.n / p_y, "years")
        total_pmt = t.pmt * t.n
        r.add("total_pmt", "Total of all payments (PMT × N)", total_pmt, "money")
        r.add("interest", "Total interest (paid or earned)", abs(t.pv + total_pmt + t.fv), "money")
    _schedule(r, t)
    return r


def _schedule(r: Result, t: Tvm) -> None:
    """Period-by-period balance (BA II Plus AMORT): shown when N is a whole number up to 1,200."""
    n, i, pmt, begin = t.n, t.i, t.pmt, t.begin
    if n != n.to_integral_value() or not 1 <= n <= SCHEDULE_MAX:
        if n > 0:
            r.warnings.append("The schedule is shown only when N is a whole number up to 1,200.")
        return
    rows: list[list[str]] = []
    xs: list[str] = []
    bal_series: list[str] = []
    bal = t.pv
    with localcontext(ctx()):
        for p in range(1, int(n) + 1):
            opening = bal
            if begin:
                bal += pmt
            interest = bal * i
            bal += interest
            if not begin:
                bal += pmt
            rows.append(
                [
                    str(p),
                    fmt(opening, "money"),
                    fmt(pmt, "money"),
                    fmt(interest, "money"),
                    fmt(pmt + interest, "money"),
                    fmt(bal, "money"),
                ]
            )
            xs.append(str(p))
            bal_series.append(fmt(bal, "money"))
    r.tables.append(
        TableOut(
            "schedule",
            "Schedule",
            [
                {"key": "period", "label": "Period", "unit": "count"},
                {"key": "opening", "label": "Opening balance", "unit": "money"},
                {"key": "payment", "label": "Payment", "unit": "money"},
                {"key": "interest", "label": "Interest", "unit": "money"},
                {"key": "change", "label": "Payment + interest", "unit": "money"},
                {"key": "closing", "label": "Closing balance", "unit": "money"},
            ],
            rows,
        )
    )
    r.chart = Chart(
        "line",
        "Balance after each period",
        "Period",
        "money",
        xs,
        [{"name": "Balance", "values": bal_series}],
    )


register(
    Calculator(
        key="tvm",
        family="tvm",
        title="TVM worksheet (N, I/Y, PV, PMT, FV)",
        description="Fill any four and solve the fifth, as on a BA II Plus. Money received is positive, "
        "money paid is negative: a loan taken is PV +, its EMI is PMT −. Covers lump sums, SIPs, loans, "
        "annuities and annuities due.",
        keywords="tvm pv fv pmt nper rate emi sip lump sum annuity due present future value ba ii plus",
        fields=[
            Field(
                "solve",
                "Solve for",
                "solve",
                "fv",
                options=(("n", "N"), ("i_y", "I/Y"), ("pv", "PV"), ("pmt", "PMT"), ("fv", "FV")),
            ),
            Field("n", "N (number of payments)", "number", "120", "Years × payments per year"),
            Field("i_y", "I/Y (annual rate, %)", "percent", "12", "Nominal annual rate"),
            Field("pv", "PV (present value)", "money", "0", "Received +, paid −"),
            Field("pmt", "PMT (payment each period)", "money", "-10000", "Received +, paid −"),
            Field("fv", "FV (future value)", "money", "0", "Received +, paid −"),
            Field("p_y", "Payments per year (P/Y)", "choice", "12", options=FREQ),
            Field("c_y", "Compounding per year (C/Y)", "choice", "12", options=FREQ),
            Field("timing", "Payments at", "choice", "end", options=TIMING),
        ],
        run=_tvm,
    )
)


# ------------------------------------------------------------------------------- annuities and perpetuities

ANNUITY_KINDS = (
    ("level", "Level annuity"),
    ("growing_annuity", "Growing annuity"),
    ("perpetuity", "Perpetuity"),
    ("growing_perpetuity", "Growing perpetuity"),
    ("deferred", "Deferred annuity"),
)


def _annuities(x: Inputs) -> Result:
    kind = x.choice("kind")
    p = x.num("payment")
    r = x.rate("rate", above=ZERO)
    begin = x.choice("timing") == "begin"
    g = x.rate("growth") if kind in ("growing_annuity", "growing_perpetuity") else ZERO
    n = x.int_("n", min_=1, max_=100_000) if kind not in ("perpetuity", "growing_perpetuity") else 0
    d = x.int_("deferral", min_=0, max_=100_000) if kind == "deferred" else 0
    res_steps: list[str] = []
    with localcontext(ctx()):
        if kind in ("level", "deferred"):
            pv = p * (ONE - pw(ONE + r, -n)) / r
            res_steps.append("PV = P × [1 − (1+r)^−n] / r")
        elif kind == "growing_annuity":
            if r == g:
                pv = p * n / (ONE + r)
                res_steps.append("r = g, so PV = P × n / (1+r)")
            else:
                pv = p / (r - g) * (ONE - pw((ONE + g) / (ONE + r), n))
                res_steps.append("PV = P / (r − g) × [1 − ((1+g)/(1+r))^n]")
        elif kind == "perpetuity":
            pv = p / r
            res_steps.append("PV = P / r")
        else:
            if r <= g:
                raise CalcError(
                    "A growing perpetuity needs the rate above the growth rate.", "growth", code="no_solution"
                )
            pv = p / (r - g)
            res_steps.append("PV = P / (r − g)  (Gordon growth)")
        if begin:
            pv *= ONE + r
            res_steps.append("Payments at the beginning: × (1 + r)")
        if kind == "deferred":
            pv = pv / pw(ONE + r, d)
            res_steps.append(f"Deferred {d} periods: ÷ (1 + r)^{d}")
        out = Result(value("pv", "Present value", pv, "money"))
        if n:
            out.add("fv", "Future value at the end of the payments", pv * pw(ONE + r, n + d), "money")
            out.add("total", "Sum of the payments", _sum_payments(p, g, n), "money")
            out.add("last", "Last payment", p * pw(ONE + g, n - 1), "money")
        out.steps = res_steps
    return out


def _sum_payments(p: Decimal, g: Decimal, n: int) -> Decimal:
    with localcontext(ctx()):
        if g == 0:
            return p * n
        return p * (pw(ONE + g, n) - ONE) / g


register(
    Calculator(
        key="annuities",
        family="tvm",
        title="Annuities and perpetuities",
        description="Present and future value of level, growing and deferred annuities, perpetuities and "
        "growing perpetuities. The rate and growth are per payment period.",
        keywords="annuity perpetuity growing gordon deferred present value pension",
        fields=[
            Field("kind", "Kind", "choice", "level", options=ANNUITY_KINDS),
            Field("payment", "Payment (first payment for a growing one)", "money", "10000"),
            Field("rate", "Discount rate per period (%)", "percent", "8"),
            Field(
                "growth",
                "Growth per period (%)",
                "percent",
                "5",
                show_when={"kind": ["growing_annuity", "growing_perpetuity"]},
            ),
            Field(
                "n",
                "Number of payments",
                "int",
                "20",
                show_when={"kind": ["level", "growing_annuity", "deferred"]},
            ),
            Field(
                "deferral",
                "Periods before the first payment period",
                "int",
                "5",
                "First payment at the end of period deferral + 1",
                show_when={"kind": ["deferred"]},
            ),
            Field("timing", "Payments at", "choice", "end", options=TIMING),
        ],
        run=_annuities,
    )
)
