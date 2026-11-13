"""Loans and amortisation (decision #120, family C): EMI, rate or tenure with the full schedule, interest and
principal between two payments (Excel CUMIPMT and CUMPRINC), prepayment (shorter tenure or lower EMI), the
true cost of a loan with fees (its APR), comparing offers, and a balance transfer.

Monthly reducing balance, as Indian lenders work an EMI: interest each month = balance x annual rate / 12."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, localcontext

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
    ln,
    pw,
    register,
    solve,
    value,
)
from .utils import add_months

TWELVE = Decimal(12)


def emi(principal: Decimal, monthly: Decimal, months: int | Decimal) -> Decimal:
    with localcontext(ctx()):
        n = Decimal(months)
        if monthly == 0:
            return principal / n
        return principal * monthly / (ONE - pw(ONE + monthly, -n))


@dataclass
class Month:
    n: int
    opening: Decimal
    payment: Decimal
    interest: Decimal
    principal: Decimal
    closing: Decimal


def schedule(
    principal: Decimal,
    monthly: Decimal,
    payment: Decimal,
    *,
    extra: Decimal = ZERO,
    lump: dict[int, Decimal] | None = None,
    limit: int = 1200,
) -> list[Month]:
    """Month by month until the balance is paid (the last payment is just what is left)."""
    rows: list[Month] = []
    bal = principal
    with localcontext(ctx()):
        for n in range(1, limit + 1):
            if bal <= Decimal("0.005"):
                break
            interest = bal * monthly
            pay = min(payment + extra + (lump or {}).get(n, ZERO), bal + interest)
            if pay <= interest and n > 1:
                raise CalcError(
                    "The payment does not cover the interest, so the loan never ends.",
                    "emi",
                    code="no_solution",
                )
            principal_part = pay - interest
            rows.append(Month(n, bal, pay, interest, principal_part, bal - principal_part))
            bal -= principal_part
    return rows


def _months_label(months: int) -> str:
    y, m = divmod(months, 12)
    return f"{y} years {m} months" if y and m else (f"{y} years" if y else f"{m} months")


def _schedule_out(r: Result, rows: list[Month], start: dt.date | None) -> None:
    def when(n: int) -> str:
        return add_months(start, n - 1).isoformat() if start else str(n)

    r.tables.append(
        TableOut(
            "schedule",
            "Schedule",
            [
                {"key": "n", "label": "Month" if not start else "Date", "unit": "date" if start else "count"},
                {"key": "opening", "label": "Opening balance", "unit": "money"},
                {"key": "payment", "label": "Payment", "unit": "money"},
                {"key": "interest", "label": "Interest", "unit": "money"},
                {"key": "principal", "label": "Principal", "unit": "money"},
                {"key": "closing", "label": "Closing balance", "unit": "money"},
            ],
            [
                [
                    when(m.n),
                    fmt(m.opening, "money"),
                    fmt(m.payment, "money"),
                    fmt(m.interest, "money"),
                    fmt(m.principal, "money"),
                    fmt(max(m.closing, ZERO), "money"),
                ]
                for m in rows
            ],
        )
    )
    years: dict[str, list[Decimal]] = {}
    for m in rows:
        key = str(add_months(start, m.n - 1).year) if start else str((m.n - 1) // 12 + 1)
        y = years.setdefault(key, [ZERO, ZERO, ZERO])
        y[0] += m.interest
        y[1] += m.principal
        y[2] = m.closing
    r.tables.append(
        TableOut(
            "years",
            "By year" + (" (calendar)" if start else ""),
            [
                {"key": "year", "label": "Year", "unit": "text"},
                {"key": "interest", "label": "Interest", "unit": "money"},
                {"key": "principal", "label": "Principal", "unit": "money"},
                {"key": "closing", "label": "Balance at the end", "unit": "money"},
            ],
            [
                [k, fmt(v[0], "money"), fmt(v[1], "money"), fmt(max(v[2], ZERO), "money")]
                for k, v in years.items()
            ],
        )
    )
    r.chart = Chart(
        "bar",
        "Interest and principal by year",
        "Year",
        "money",
        list(years),
        [
            {"name": "Interest", "values": [fmt(v[0], "money") for v in years.values()]},
            {"name": "Principal", "values": [fmt(v[1], "money") for v in years.values()]},
        ],
    )


# ------------------------------------------------------------------------------------------- EMI


def _loan(x: Inputs) -> Result:
    find = x.choice("solve")
    p = x.num("principal", above=ZERO)
    start = x.date("start") if x.has("start") else None
    with localcontext(ctx()):
        if find == "emi":
            annual = x.rate("rate", above=Decimal(-1) / 100)
            months = x.int_("months", min_=1, max_=1200)
            pay = emi(p, annual / TWELVE, months)
            r = Result(value("emi", "EMI", pay, "money"))
        elif find == "rate":
            months = x.int_("months", min_=1, max_=1200)
            pay = x.num("emi", above=ZERO)
            if pay * months < p:
                raise CalcError(
                    "These EMIs add up to less than the loan, so the rate would be negative.", "emi"
                )
            i = solve(
                lambda q: emi(p, q, months) - pay, Decimal("-0.5"), ONE, Decimal("0.008"), what="the rate"
            )
            annual = i * TWELVE
            r = Result(value("rate", "Interest rate (annual)", annual * HUNDRED, "percent"))
        else:
            annual = x.rate("rate", above=Decimal(-1) / 100)
            pay = x.num("emi", above=ZERO)
            i = annual / TWELVE
            if i > 0 and pay <= p * i:
                raise CalcError(
                    "The EMI does not cover the first month's interest, so the loan never ends.",
                    "emi",
                    code="no_solution",
                )
            exact_n = p / pay if i == 0 else -ln(ONE - p * i / pay) / ln(ONE + i)
            months = int(exact_n.to_integral_value(rounding=ROUND_CEILING))
            r = Result(value("months", "Months to repay", exact_n, "periods"))
            r.add("tenure", "That is", _months_label(months), "text")
        i = annual / TWELVE
        rows = schedule(p, i, pay)
        total = sum((m.payment for m in rows), ZERO)
        if find != "emi":
            r.add("emi", "EMI", pay, "money")
        r.add("interest", "Total interest", total - p, "money")
        r.add("total", "Total paid", total, "money")
        r.add("ratio", "Interest as a share of the loan", (total - p) / p * HUNDRED, "percent")
        r.add("ear", "Effective annual rate", (pw(ONE + i, 12) - ONE) * HUNDRED, "percent")
        if rows and rows[-1].payment < pay - Decimal("0.005"):
            r.add("last", "Last payment (smaller)", rows[-1].payment, "money")
        k1, k2 = x.opt("from_month"), x.opt("to_month")
        if k1 is not None and k2 is not None:
            a, b = int(k1), int(k2)
            if not 1 <= a <= b <= len(rows):
                raise CalcError(
                    f"Choose months from 1 to {len(rows)}, the first not after the second.", "from_month"
                )
            part = rows[a - 1 : b]
            r.add(
                "cum_int",
                f"Interest paid in months {a} to {b} (CUMIPMT)",
                sum((m.interest for m in part), ZERO),
                "money",
            )
            r.add(
                "cum_prin",
                f"Principal repaid in months {a} to {b} (CUMPRINC)",
                sum((m.principal for m in part), ZERO),
                "money",
            )
            r.add("bal_after", f"Balance after month {b}", max(part[-1].closing, ZERO), "money")
        r.steps = [
            "EMI = P · i / (1 − (1 + i)^−n), i = annual rate / 12",
            "Each month: interest = balance × i; principal = EMI − interest",
        ]
        _schedule_out(r, rows, start)
    return r


register(
    Calculator(
        key="loan",
        family="loans",
        title="Loan EMI, rate or tenure",
        description="EMI from the loan, rate and months; or the rate from an EMI; or how long an EMI "
        "takes to repay. "
        "Full schedule by month and by year, and interest and principal between any two months.",
        keywords="emi loan home loan car loan personal loan amortisation schedule tenure rate cumipmt "
        "cumprinc "
        "interest principal outstanding balance",
        fields=[
            Field(
                "solve",
                "Find",
                "solve",
                "emi",
                options=(("emi", "EMI"), ("rate", "Rate"), ("months", "Tenure")),
            ),
            Field("principal", "Loan amount", "money", "5000000"),
            Field("rate", "Interest rate, annual (%)", "percent", "8.5"),
            Field("months", "Tenure (months)", "int", "240"),
            Field("emi", "EMI", "money", "43391.16"),
            Field("start", "First EMI on (optional, for dates)", "date", "", optional=True),
            Field("from_month", "Sum interest from month", "int", "", optional=True),
            Field("to_month", "…to month", "int", "", optional=True),
        ],
        run=_loan,
    )
)


# ------------------------------------------------------------------------------------------- prepayment


def _prepay(x: Inputs) -> Result:
    p = x.num("principal", above=ZERO)
    annual = x.rate("rate", above=ZERO)
    months = x.int_("months", min_=1, max_=1200)
    i = annual / TWELVE
    lump = x.num("lump", default=ZERO, min_=ZERO)
    at = x.int_("lump_month", default=12, min_=1, max_=1200)
    extra = x.num("extra", default=ZERO, min_=ZERO)
    mode = x.choice("mode")
    with localcontext(ctx()):
        pay = emi(p, i, months)
        base = schedule(p, i, pay)
        base_int = sum((m.interest for m in base), ZERO)
        if mode == "tenure":
            new = schedule(p, i, pay, extra=extra, lump={at: lump} if lump else None)
            new_emi = pay
        else:
            # Lower EMI: after the lump sum, the EMI is worked out again on the same end date.
            first = schedule(p, i, pay, extra=extra, limit=at)
            bal = first[-1].closing - lump if first else p
            left = months - len(first)
            if bal <= 0 or left <= 0:
                new, new_emi = first, pay
            else:
                new_emi = emi(bal, i, left)
                new = first + [
                    Month(m.n + len(first), m.opening, m.payment, m.interest, m.principal, m.closing)
                    for m in schedule(bal, i, new_emi, extra=extra)
                ]
        new_int = sum((m.interest for m in new), ZERO)
        r = Result(value("saved", "Interest saved", base_int - new_int, "money"))
        r.add("emi", "EMI now", pay, "money")
        if mode == "emi":
            r.add("new_emi", f"EMI after month {at}", new_emi, "money")
        r.add("months_now", "Months, as it is", Decimal(len(base)), "count")
        r.add("months_new", "Months, with prepayment", Decimal(len(new)), "count")
        r.add("sooner", "Paid off sooner by", _months_label(len(base) - len(new)), "text")
        r.add("int_now", "Total interest, as it is", base_int, "money")
        r.add("int_new", "Total interest, with prepayment", new_int, "money")
        paid_extra = lump + extra * len(new)
        if paid_extra:
            r.add("per_rupee", "Interest saved per rupee prepaid", (base_int - new_int) / paid_extra, "ratio")
        r.steps = [
            "Reduce tenure: the EMI stays; the prepayment cuts the balance, so it ends sooner",
            "Reduce EMI: after the lump sum the EMI is worked out again for the months left",
        ]
        _schedule_out(r, new, None)
    return r


register(
    Calculator(
        key="prepayment",
        family="loans",
        title="Loan prepayment",
        description="A lump sum, or something extra every month: how much interest it saves, and whether to "
        "shorten the loan or lower the EMI.",
        keywords="prepayment part payment foreclosure reduce tenure reduce emi interest saved home loan",
        fields=[
            Field("principal", "Loan amount (or balance now)", "money", "5000000"),
            Field("rate", "Interest rate, annual (%)", "percent", "8.5"),
            Field("months", "Months left", "int", "240"),
            Field("lump", "Lump sum prepayment", "money", "500000", optional=True),
            Field("lump_month", "…paid in month", "int", "12", optional=True),
            Field("extra", "Extra every month", "money", "0", optional=True),
            Field(
                "mode",
                "Use it to",
                "choice",
                "tenure",
                options=(("tenure", "Shorten the loan (same EMI)"), ("emi", "Lower the EMI (same end)")),
            ),
        ],
        run=_prepay,
    )
)


# ------------------------------------------------------------------------------------------- true cost


def apr_of(net: Decimal, pay: Decimal, months: int) -> Decimal:
    """Monthly rate at which `months` payments of `pay` repay `net` received."""
    return solve(lambda q: emi(net, q, months) - pay, Decimal("-0.5"), ONE, Decimal("0.01"), what="the APR")


def _cost(x: Inputs) -> Result:
    p = x.num("principal", above=ZERO)
    annual = x.rate("rate")
    months = x.int_("months", min_=1, max_=1200)
    fee_pct = x.rate("fee_pct", default=ZERO)
    gst = x.rate("gst", default=Decimal("0.18"))
    fixed = x.num("charges", default=ZERO, min_=ZERO)
    financed = x.num("financed", default=ZERO, min_=ZERO)
    with localcontext(ctx()):
        fee = p * fee_pct * (ONE + gst)
        borrowed = p + financed
        pay = emi(borrowed, annual / TWELVE, months)
        net = p - fee - fixed
        if net <= 0:
            raise CalcError("The fees take the whole loan.", "fee_pct")
        i = apr_of(net, pay, months)
        r = Result(value("apr", "True annual rate (APR, monthly × 12)", i * TWELVE * HUNDRED, "percent"))
        r.add("ear", "Effective annual rate", (pw(ONE + i, 12) - ONE) * HUNDRED, "percent")
        r.add("quoted", "Quoted rate", annual * HUNDRED, "percent")
        r.add("emi", "EMI", pay, "money")
        r.add("fees", "Fees and charges paid up front (with GST)", fee + fixed, "money")
        r.add("received", "Money actually received", net, "money")
        r.add("total", "Total of the EMIs", pay * months, "money")
        r.add("cost", "Cost of borrowing (EMIs − money received)", pay * months - net, "money")
        r.steps = [
            "APR: the rate at which the EMIs repay only the money you actually got (the loan less fees)",
            "Financed extras (such as insurance added to the loan) raise the EMI but not the money received",
        ]
    return r


register(
    Calculator(
        key="loan_cost",
        family="loans",
        title="True cost of a loan with fees (APR)",
        description="Processing fees, charges and insurance added to the loan make it dearer than the "
        "quoted rate. "
        "This finds the rate you really pay.",
        keywords="apr true cost processing fee charges insurance effective rate loan comparison",
        fields=[
            Field("principal", "Loan amount", "money", "1000000"),
            Field("rate", "Quoted interest rate (%)", "percent", "10.5"),
            Field("months", "Tenure (months)", "int", "60"),
            Field("fee_pct", "Processing fee (% of the loan)", "percent", "2"),
            Field("gst", "GST on the fee (%)", "percent", "18", optional=True),
            Field("charges", "Other charges paid up front", "money", "5000", optional=True),
            Field("financed", "Added to the loan (such as insurance)", "money", "0", optional=True),
        ],
        run=_cost,
    )
)


# ------------------------------------------------------------------------------------------- compare

OFFERS = (
    Column("name", "Lender", "text"),
    Column("amount", "Loan", "money"),
    Column("rate", "Rate %", "percent"),
    Column("months", "Months"),
    Column("fees", "Fees paid up front", "money", optional=True),
)


def _compare(x: Inputs) -> Result:
    rows = x.table("offers", min_rows=1)
    out = []
    with localcontext(ctx()):
        for rr in rows:
            m = rr["months"]
            if m != m.to_integral_value() or not 1 <= m <= 1200:
                raise CalcError(f"{rr['name']}: months must be a whole number up to 1,200.", "offers")
            months = int(m)
            pay = emi(rr["amount"], rr["rate"] / TWELVE, months)
            fees = rr["fees"] or ZERO
            i = apr_of(rr["amount"] - fees, pay, months)
            out.append((rr, pay, pay * months - rr["amount"], fees, i * TWELVE))
        best = min(out, key=lambda t: t[4])
        r = Result(value("best", "Cheapest by true rate", ZERO, "text"))
        r.answer.value = r.answer.exact = str(best[0]["name"])
        r.add("best_apr", "Its true rate (APR)", best[4] * HUNDRED, "percent")
        r.tables.append(
            TableOut(
                "offers",
                "Every offer",
                [
                    {"key": "name", "label": "Lender", "unit": "text"},
                    {"key": "emi", "label": "EMI", "unit": "money"},
                    {"key": "interest", "label": "Total interest", "unit": "money"},
                    {"key": "fees", "label": "Fees", "unit": "money"},
                    {"key": "cost", "label": "Interest + fees", "unit": "money"},
                    {"key": "apr", "label": "True rate (APR)", "unit": "percent"},
                ],
                [
                    [
                        str(rr["name"]),
                        fmt(pay, "money"),
                        fmt(intr, "money"),
                        fmt(fees, "money"),
                        fmt(intr + fees, "money"),
                        fmt(apr * HUNDRED, "percent"),
                    ]
                    for rr, pay, intr, fees, apr in out
                ],
            )
        )
        r.steps = ["Offers are ranked by APR: the rate at which the EMIs repay the loan less its fees"]
    return r


register(
    Calculator(
        key="loan_compare",
        family="loans",
        title="Compare loan offers",
        description="Several offers side by side: EMI, total interest, fees and the true rate of each.",
        keywords="compare loan offers lenders emi apr fees cheapest",
        fields=[
            Field(
                "offers",
                "Offers",
                "table",
                columns=OFFERS,
                rows=[
                    {"name": "Bank A", "amount": "5000000", "rate": "8.5", "months": "240", "fees": "10000"},
                    {"name": "Bank B", "amount": "5000000", "rate": "8.35", "months": "240", "fees": "59000"},
                    {"name": "Bank C", "amount": "5000000", "rate": "8.65", "months": "240", "fees": "0"},
                ],
            )
        ],
        run=_compare,
    )
)


# ------------------------------------------------------------------------------------------- balance transfer


def _transfer(x: Inputs) -> Result:
    bal = x.num("balance", above=ZERO)
    months = x.int_("months", min_=1, max_=1200)
    old = x.rate("old_rate")
    new = x.rate("new_rate")
    cost = x.num("cost", default=ZERO, min_=ZERO)
    with localcontext(ctx()):
        e_old = emi(bal, old / TWELVE, months)
        e_new = emi(bal, new / TWELVE, months)
        int_old = e_old * months - bal
        int_new = e_new * months - bal
        r = Result(
            value("saving", "Net saving (interest saved − switching cost)", int_old - int_new - cost, "money")
        )
        r.add("emi_old", "EMI now", e_old, "money")
        r.add("emi_new", "EMI after the transfer", e_new, "money")
        r.add("monthly", "Saved each month", e_old - e_new, "money")
        r.add("int_saved", "Interest saved", int_old - int_new, "money")
        if e_old > e_new:
            be = cost / (e_old - e_new)
            r.add("breakeven", "Months for the saving to cover the cost", be, "periods")
        else:
            r.warnings.append("The new rate is not lower, so the transfer does not pay for itself.")
        r.steps = ["Both EMIs are worked out on the same balance and the same months left"]
    return r


register(
    Calculator(
        key="balance_transfer",
        family="loans",
        title="Loan balance transfer",
        description="Moving a loan to a lower rate: the new EMI, the interest saved, and how soon the "
        "switching "
        "cost is recovered.",
        keywords="balance transfer refinance switch lender lower rate home loan saving breakeven",
        fields=[
            Field("balance", "Balance outstanding", "money", "4000000"),
            Field("months", "Months left", "int", "180"),
            Field("old_rate", "Rate now (%)", "percent", "9.25"),
            Field("new_rate", "New rate (%)", "percent", "8.4"),
            Field("cost", "Cost of switching (fees, legal, stamp duty)", "money", "25000"),
        ],
        run=_transfer,
    )
)
