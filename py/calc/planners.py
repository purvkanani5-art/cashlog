"""Personal-finance planners for India (decision #120, family I): SIP (with a yearly step-up), goal, SWP,
retirement, FD, RD, PPF, EPF, NPS, Sukanya Samriddhi, ULIP against a term plan with a mutual fund, rent
against buy, and the cost of delay.

Every rate is the owner's input (a scheme's rate changes each quarter); defaults are only examples. Month by
month where money moves monthly, so step-ups and payments at the start of a month are exact.
"""

from __future__ import annotations

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
    pw,
    register,
    solve,
    value,
)

TWELVE = Decimal(12)
TIMING = (("begin", "Start of each month (as SIPs usually are)"), ("end", "End of each month"))
BASIS = (
    ("nominal", "Annual rate ÷ 12 (as most SIP calculators)"),
    ("effective", "Compounded to the annual rate exactly"),
)


def monthly_rate(annual: Decimal, basis: str) -> Decimal:
    with localcontext(ctx()):
        return annual / TWELVE if basis == "nominal" else pw(ONE + annual, ONE / TWELVE) - ONE


def grow_sip(
    first: Decimal,
    i: Decimal,
    months: int,
    *,
    step: Decimal = ZERO,
    step_amount: Decimal = ZERO,
    begin: bool = True,
    lump: Decimal = ZERO,
) -> tuple[Decimal, Decimal, list[tuple[int, Decimal, Decimal]]]:
    """Value after `months` of a monthly SIP that rises each year by `step` (a fraction) or `step_amount`,
    with an optional lump sum at the start. Returns (value, invested, [(year, invested to date, value)])."""
    value_, invested, sip = lump, lump, first
    years: list[tuple[int, Decimal, Decimal]] = []
    with localcontext(ctx()):
        for m in range(1, months + 1):
            if m > 1 and (m - 1) % 12 == 0:
                sip = sip * (ONE + step) + step_amount
            if begin:
                value_ += sip
            value_ *= ONE + i
            if not begin:
                value_ += sip
            invested += sip
            if m % 12 == 0 or m == months:
                years.append(((m + 11) // 12, invested, value_))
    return value_, invested, years


def _year_table(r: Result, rows: list[tuple[int, Decimal, Decimal]], label: str = "Value") -> None:
    r.tables.append(
        TableOut(
            "years",
            "Year by year",
            [
                {"key": "year", "label": "Year", "unit": "count"},
                {"key": "invested", "label": "Invested", "unit": "money"},
                {"key": "value", "label": label, "unit": "money"},
                {"key": "gain", "label": "Gain", "unit": "money"},
            ],
            [[str(y), fmt(inv, "money"), fmt(v, "money"), fmt(v - inv, "money")] for y, inv, v in rows],
        )
    )
    r.chart = Chart(
        "line",
        "Growth",
        "Year",
        "money",
        [str(y) for y, _, _ in rows],
        [
            {"name": "Invested", "values": [fmt(inv, "money") for _, inv, _ in rows]},
            {"name": label, "values": [fmt(v, "money") for _, _, v in rows]},
        ],
    )


def _months(x: Inputs, key: str = "years") -> int:
    years = x.num(key, above=ZERO, max_=Decimal(100))
    m = years * 12
    if m != m.to_integral_value():
        raise CalcError("Give the years in whole months (for example 2.5 or 2.25).", key)
    return int(m)


# ------------------------------------------------------------------------------------------- SIP


def _sip(x: Inputs) -> Result:
    amount = x.num("amount", min_=ZERO)
    annual = x.rate("rate")
    months = _months(x)
    i = monthly_rate(annual, x.choice("basis"))
    step = x.rate("step_up", default=ZERO)
    step_amount = x.num("step_amount", default=ZERO)
    lump = x.num("lump", default=ZERO, min_=ZERO)
    v, invested, years = grow_sip(
        amount, i, months, step=step, step_amount=step_amount, begin=x.choice("timing") == "begin", lump=lump
    )
    with localcontext(ctx()):
        r = Result(value("fv", "Value at the end", v, "money"))
        r.add("invested", "Total invested", invested, "money")
        r.add("gain", "Gain", v - invested, "money")
        r.add("multiple", "Money multiple", v / invested if invested else ZERO, "ratio")
        infl = x.opt("inflation")
        if infl is not None:
            real = v / pw(ONE + infl / HUNDRED, Decimal(months) / TWELVE)
            r.add("real", "Worth in today's money", real, "money")
        if step or step_amount:
            r.add("last_sip", "SIP in the last year", _last_sip(amount, step, step_amount, months), "money")
        r.steps = [
            f"Monthly rate i = {fmt(i * HUNDRED, 'percent')}%; each month the SIP is added and grows "
            "by (1 + i)",
            "The SIP rises at the start of each year by the step-up",
        ]
        _year_table(r, years)
    return r


def _last_sip(first: Decimal, step: Decimal, step_amount: Decimal, months: int) -> Decimal:
    sip = first
    with localcontext(ctx()):
        for _ in range((months - 1) // 12):
            sip = sip * (ONE + step) + step_amount
    return sip


register(
    Calculator(
        key="sip",
        family="planners",
        title="SIP with step-up",
        description="What a monthly SIP grows to, with an optional yearly increase and a lump sum at the "
        "start; "
        "year by year, and in today's money.",
        keywords="sip systematic investment plan step up top up mutual fund future value lump sum monthly",
        fields=[
            Field("amount", "Monthly SIP", "money", "10000"),
            Field("rate", "Expected return, annual (%)", "percent", "12"),
            Field("years", "Years", "number", "15"),
            Field("step_up", "Increase each year (%)", "percent", "10", optional=True),
            Field("step_amount", "…or increase each year by", "money", "0", optional=True),
            Field("lump", "Lump sum at the start", "money", "0", optional=True),
            Field("timing", "Invested at the", "choice", "begin", options=TIMING),
            Field("basis", "Monthly rate", "choice", "nominal", options=BASIS),
            Field("inflation", "Inflation (%), to show today's money", "percent", "6", optional=True),
        ],
        run=_sip,
    )
)


# ------------------------------------------------------------------------------------------- goal


def _goal(x: Inputs) -> Result:
    today = x.num("target", above=ZERO)
    months = _months(x)
    infl = x.rate("inflation", default=ZERO)
    annual = x.rate("rate")
    i = monthly_rate(annual, x.choice("basis"))
    have = x.num("have", default=ZERO, min_=ZERO)
    step = x.rate("step_up", default=ZERO)
    begin = x.choice("timing") == "begin"
    with localcontext(ctx()):
        target = today * pw(ONE + infl, Decimal(months) / TWELVE)
        have_fv = have * pw(ONE + i, months)
        gap = target - have_fv
        r = Result(value("sip", "Monthly SIP needed", ZERO, "money"))
        if gap <= 0:
            r.answer = value("sip", "Monthly SIP needed", ZERO, "money")
            r.warnings.append("What you have already will grow to the goal.")
            flat = stepped = ZERO
        else:
            unit, _, _ = grow_sip(ONE, i, months, begin=begin)
            flat = gap / unit
            unit_step, _, _ = grow_sip(ONE, i, months, step=step, begin=begin)
            stepped = gap / unit_step
            r.answer = value(
                "sip",
                "Monthly SIP needed" + (" (first year, rising yearly)" if step else ""),
                stepped,
                "money",
            )
            if step:
                r.add("flat", "Monthly SIP needed with no step-up", flat, "money")
        r.add("target", "The goal in future money", target, "money")
        r.add("have_fv", "What you have, grown", have_fv, "money")
        r.add("lump", "Or one lump sum today", max(gap, ZERO) / pw(ONE + i, months), "money")
        r.steps = [
            "Goal in future money = today's cost × (1 + inflation)^years",
            "SIP needed = (goal − savings grown) ÷ what a SIP of 1 grows to",
        ]
    return r


register(
    Calculator(
        key="goal",
        family="planners",
        title="Goal: SIP needed",
        description="A goal that costs a sum in today's money: what it will cost then, and the monthly "
        "SIP (flat or "
        "rising each year) or lump sum that gets there.",
        keywords="goal planning sip required target education marriage house down payment inflation lump sum",
        fields=[
            Field("target", "Cost of the goal in today's money", "money", "2500000"),
            Field("years", "Years to the goal", "number", "10"),
            Field("inflation", "Inflation for this goal (%)", "percent", "7"),
            Field("rate", "Expected return, annual (%)", "percent", "12"),
            Field("have", "Already saved for it", "money", "200000", optional=True),
            Field("step_up", "Raise the SIP each year by (%)", "percent", "0", optional=True),
            Field("timing", "Invested at the", "choice", "begin", options=TIMING),
            Field("basis", "Monthly rate", "choice", "nominal", options=BASIS),
        ],
        run=_goal,
    )
)


# ------------------------------------------------------------------------------------------- SWP


Years = list[tuple[int, Decimal, Decimal]]


def _drawdown_months(
    corpus: Decimal, i: Decimal, w: Decimal, g: Decimal, limit: int = 1200
) -> tuple[int | None, Years]:
    """Months a corpus lasts paying `w` at the start of each month, raised yearly by g. None if it outlasts
    the limit. Also (year, withdrawn that year, balance at year end)."""
    bal, pay, years, drawn = corpus, w, [], ZERO
    with localcontext(ctx()):
        for m in range(1, limit + 1):
            if m > 1 and (m - 1) % 12 == 0:
                pay *= ONE + g
            if bal < pay:
                drawn += bal
                years.append(((m + 11) // 12, drawn, ZERO))
                return m, years
            bal = (bal - pay) * (ONE + i)
            drawn += pay
            if m % 12 == 0:
                years.append((m // 12, drawn, bal))
                drawn = ZERO
    return None, years


def _swp(x: Inputs) -> Result:
    corpus = x.num("corpus", above=ZERO)
    annual = x.rate("rate")
    i = monthly_rate(annual, "effective")
    g = x.rate("increase", default=ZERO)
    mode = x.choice("mode")
    with localcontext(ctx()):
        if mode == "last":
            w = x.num("withdrawal", above=ZERO)
            months, years = _drawdown_months(corpus, i, w, g)
            if months is None:
                r = Result(value("months", "The money lasts", ZERO, "text"))
                r.answer.value = r.answer.exact = "more than 100 years"
            else:
                r = Result(value("months", "The money lasts (months)", Decimal(months), "count"))
                y, mm = divmod(months, 12)
                r.add("tenure", "That is", f"{y} years {mm} months", "text")
        else:
            want = _months(x, "years")

            def left(wd: Decimal) -> Decimal:
                bal, pay = corpus, wd
                for m in range(1, want + 1):
                    if m > 1 and (m - 1) % 12 == 0:
                        pay *= ONE + g
                    bal = (bal - pay) * (ONE + i)
                return bal

            # The balance falls in a straight line as the withdrawal rises, so two points find the root.
            b0, b1 = left(ZERO), left(ONE)
            w = b0 / (b0 - b1)
            _, years = _drawdown_months(corpus, i, w, g, limit=want)
            r = Result(value("withdrawal", "Monthly withdrawal it supports (first year)", w, "money"))
        r.add("rate_m", "Monthly growth", i * HUNDRED, "percent")
        r.tables.append(
            TableOut(
                "years",
                "Year by year",
                [
                    {"key": "year", "label": "Year", "unit": "count"},
                    {"key": "drawn", "label": "Withdrawn", "unit": "money"},
                    {"key": "bal", "label": "Left at the end", "unit": "money"},
                ],
                [[str(y), fmt(d, "money"), fmt(b, "money")] for y, d, b in years],
            )
        )
        r.steps = [
            "Each month: take the withdrawal at the start, then the rest grows a month",
            "The withdrawal rises at the start of each year by the increase",
        ]
    return r


register(
    Calculator(
        key="swp",
        family="planners",
        title="SWP: how long a corpus lasts",
        description="Monthly withdrawals from a corpus that keeps earning: how long it lasts, or how much "
        "it can "
        "pay for a number of years. Withdrawals can rise each year with inflation.",
        keywords="swp systematic withdrawal plan corpus pension last how long sustainable withdrawal "
        "retirement",
        fields=[
            Field(
                "mode",
                "Find",
                "choice",
                "last",
                options=(("last", "How long it lasts"), ("amount", "The withdrawal")),
            ),
            Field("corpus", "Corpus", "money", "10000000"),
            Field("rate", "Return, annual (%)", "percent", "8"),
            Field("withdrawal", "Monthly withdrawal", "money", "60000", show_when={"mode": ["last"]}),
            Field("years", "For how many years", "number", "25", show_when={"mode": ["amount"]}),
            Field("increase", "Raise the withdrawal each year by (%)", "percent", "6", optional=True),
        ],
        run=_swp,
    )
)


# ------------------------------------------------------------------------------------------- retirement


def _retire(x: Inputs) -> Result:
    age = x.num("age", above=ZERO)
    retire = x.num("retire_age", above=age)
    life = x.num("life", above=retire)
    expense = x.num("expense", above=ZERO)
    infl = x.rate("inflation")
    pre = x.rate("pre_return")
    post = x.rate("post_return")
    have = x.num("have", default=ZERO, min_=ZERO)
    step = x.rate("step_up", default=ZERO)
    with localcontext(ctx()):
        to_retire = int(((retire - age) * 12).to_integral_value())
        in_retire = int(((life - retire) * 12).to_integral_value())
        start_expense = expense * pw(ONE + infl, Decimal(to_retire) / TWELVE)
        g = pw(ONE + infl, ONE / TWELVE) - ONE
        rm = pw(ONE + post, ONE / TWELVE) - ONE
        q = (ONE + g) / (ONE + rm)
        factor = Decimal(in_retire) if q == ONE else (ONE - pw(q, in_retire)) / (ONE - q)
        corpus = start_expense * factor  # paid at the start of each month
        i = pw(ONE + pre, ONE / TWELVE) - ONE
        have_fv = have * pw(ONE + i, to_retire)
        gap = corpus - have_fv
        r = Result(value("corpus", "Corpus needed at retirement", corpus, "money"))
        r.add("expense_then", "Monthly expense in the first month of retirement", start_expense, "money")
        r.add("have_fv", "What you have, grown to retirement", have_fv, "money")
        if gap > 0 and to_retire > 0:
            unit, _, _ = grow_sip(ONE, i, to_retire, step=step)
            r.add(
                "sip",
                "Monthly SIP needed from now" + (" (first year, rising)" if step else ""),
                gap / unit,
                "money",
            )
            r.add("lump", "Or one lump sum today", gap / pw(ONE + i, to_retire), "money")
        elif gap <= 0:
            r.warnings.append("What you have already will grow to the corpus needed.")
        r.add("years_to", "Years to retirement", Decimal(to_retire) / TWELVE, "years")
        r.add("years_in", "Years in retirement", Decimal(in_retire) / TWELVE, "years")
        r.steps = [
            "Expense at retirement = today's expense × (1 + inflation)^years to retirement",
            "Corpus = the present value at retirement of monthly expenses rising with inflation and paid "
            "at the "
            "start of each month, discounted at the return after retirement",
        ]
    return r


register(
    Calculator(
        key="retirement",
        family="planners",
        title="Retirement corpus",
        description="How big a corpus retirement needs, with expenses rising with inflation for as long "
        "as you "
        "live, and the SIP or lump sum that builds it.",
        keywords="retirement corpus planning pension fire early retirement expenses inflation sip needed",
        fields=[
            Field("age", "Age now", "number", "35"),
            Field("retire_age", "Retire at", "number", "60"),
            Field("life", "Plan until age", "number", "85"),
            Field("expense", "Monthly expenses today", "money", "60000"),
            Field("inflation", "Inflation (%)", "percent", "6"),
            Field("pre_return", "Return until retirement (%)", "percent", "11"),
            Field("post_return", "Return after retirement (%)", "percent", "7"),
            Field("have", "Saved for retirement already", "money", "1500000", optional=True),
            Field("step_up", "Raise the SIP each year by (%)", "percent", "0", optional=True),
        ],
        run=_retire,
    )
)


# ------------------------------------------------------------------------------------------- FD and RD


def _fd(x: Inputs) -> Result:
    p = x.num("principal", above=ZERO)
    annual = x.rate("rate")
    months = x.int_("months", default=0, min_=0, max_=1200)
    days = x.int_("days", default=0, min_=0, max_=3650)
    per = Decimal(x.choice("compounding"))
    payout = x.choice("payout")
    with localcontext(ctx()):
        years = Decimal(months) / TWELVE + Decimal(days) / Decimal(365)
        if years <= 0:
            raise CalcError("Give the tenure in months and/or days.", "months")
        simple = months * 30 + days < 181  # deposits under six months earn simple interest
        if payout == "cumulative":
            amount = p * (ONE + annual * years) if simple else p * pw(ONE + annual / per, per * years)
            r = Result(value("maturity", "Maturity amount", amount, "money"))
            r.add("interest", "Interest earned", amount - p, "money")
            r.add("yield", "Effective annual yield", (pw(amount / p, ONE / years) - ONE) * HUNDRED, "percent")
            if simple:
                r.warnings.append("Deposits under six months earn simple interest.")
        elif payout == "quarterly":
            q = p * annual / 4
            r = Result(value("payout", "Interest paid each quarter", q, "money"))
            r.add("total", "Interest over the tenure", q * years * 4, "money")
        else:
            m = p * (pw(ONE + annual / 4, ONE / 3) - ONE)
            r = Result(value("payout", "Interest paid each month", m, "money"))
            r.add("simple", "Simple monthly (rate ÷ 12), for comparison", p * annual / TWELVE, "money")
            r.add("total", "Interest over the tenure", m * years * 12, "money")
            r.warnings.append(
                "Monthly payout is worked out to match quarterly compounding; banks round it their own "
                "way, so it may differ by a few rupees."
            )
        tds = x.opt("tds")
        if tds is not None and payout == "cumulative":
            r.add(
                "after_tds",
                f"Interest after {fmt(tds, 'number')}% TDS",
                (amount - p) * (ONE - tds / HUNDRED),
                "money",
            )
        r.steps = ["Cumulative: P × (1 + r/n)^(n × years); under six months: P × (1 + r × years)"]
    return r


register(
    Calculator(
        key="fd",
        family="planners",
        title="Fixed deposit",
        description="Maturity value of a bank FD (cumulative, compounded quarterly), or the interest paid "
        "out each "
        "quarter or month.",
        keywords="fd fixed deposit bank maturity interest quarterly compounding payout tds senior citizen",
        fields=[
            Field("principal", "Deposit", "money", "500000"),
            Field("rate", "Interest rate (%)", "percent", "7.1"),
            Field("months", "Tenure: months", "int", "36"),
            Field("days", "…and days", "int", "0", optional=True),
            Field(
                "compounding",
                "Compounded",
                "choice",
                "4",
                options=(
                    ("4", "Quarterly (most banks)"),
                    ("12", "Monthly"),
                    ("2", "Half-yearly"),
                    ("1", "Yearly"),
                ),
            ),
            Field(
                "payout",
                "Interest",
                "choice",
                "cumulative",
                options=(
                    ("cumulative", "Added to the deposit"),
                    ("quarterly", "Paid each quarter"),
                    ("monthly", "Paid each month"),
                ),
            ),
            Field("tds", "TDS rate (%)", "number", "", optional=True),
        ],
        run=_fd,
    )
)


def _rd(x: Inputs) -> Result:
    m = x.num("monthly", above=ZERO)
    annual = x.rate("rate")
    n = x.int_("months", min_=1, max_=1200)
    with localcontext(ctx()):
        q = ONE + annual / 4
        maturity = sum((m * pw(q, Decimal(n - k + 1) / 3) for k in range(1, n + 1)), ZERO)
        r = Result(value("maturity", "Maturity amount", maturity, "money"))
        r.add("invested", "Total deposited", m * n, "money")
        r.add("interest", "Interest earned", maturity - m * n, "money")

        def fv(rate: Decimal) -> Decimal:
            return (
                sum((m * pw(ONE + rate, Decimal(n - k + 1) / 12) for k in range(1, n + 1)), ZERO) - maturity
            )

        r.add("yield", "Effective annual yield", solve(fv, Decimal("-0.5"), ONE, annual) * HUNDRED, "percent")
        r.steps = ["Each instalment grows quarterly for the months it stays: R × (1 + r/4)^(months left / 3)"]
    return r


register(
    Calculator(
        key="rd",
        family="planners",
        title="Recurring deposit",
        description="Maturity value of a bank RD: a monthly instalment, compounded quarterly as Indian "
        "banks do.",
        keywords="rd recurring deposit monthly instalment bank post office maturity quarterly",
        fields=[
            Field("monthly", "Monthly instalment", "money", "5000"),
            Field("rate", "Interest rate (%)", "percent", "6.8"),
            Field("months", "Months", "int", "60"),
        ],
        run=_rd,
    )
)


# ------------------------------------------------------------------------------------------- PPF, SSY, EPF, N


def _yearly(
    deposit: Decimal, rate: Decimal, years: int, pay_years: int | None = None
) -> list[tuple[int, Decimal, Decimal]]:
    """Deposits at the start of each year (for `pay_years`), interest compounded yearly."""
    rows, bal, invested = [], ZERO, ZERO
    with localcontext(ctx()):
        for y in range(1, years + 1):
            if pay_years is None or y <= pay_years:
                bal += deposit
                invested += deposit
            bal *= ONE + rate
            rows.append((y, invested, bal))
    return rows


def _ppf(x: Inputs) -> Result:
    deposit = x.num("deposit", above=ZERO)
    rate = x.rate("rate")
    years = x.int_("years", min_=15, max_=50)
    if (years - 15) % 5:
        raise CalcError("PPF runs 15 years, then extends in blocks of 5 (20, 25, 30 …).", "years")
    rows = _yearly(deposit, rate, years)
    _, invested, bal = rows[-1]
    r = Result(value("maturity", "Maturity value", bal, "money"))
    r.add("invested", "Total deposited", invested, "money")
    r.add("interest", "Interest earned (tax-free)", bal - invested, "money")
    if deposit > Decimal(150000):
        r.warnings.append("PPF takes at most ₹1,50,000 a year; the excess earns nothing.")
    r.steps = ["Deposited by 5 April each year, so it earns the full year; interest is compounded yearly"]
    _year_table(r, rows, "Balance")
    return r


register(
    Calculator(
        key="ppf",
        family="planners",
        title="PPF",
        description="Public Provident Fund: a yearly deposit for 15 years (or extended in 5-year blocks), "
        "interest "
        "compounded yearly and tax-free.",
        keywords="ppf public provident fund 15 years extension tax free 80c maturity",
        fields=[
            Field("deposit", "Yearly deposit", "money", "150000"),
            Field("rate", "Interest rate (%)", "percent", "7.1", "The rate is set each quarter; use today's"),
            Field("years", "Years (15, 20, 25 …)", "int", "15"),
        ],
        run=_ppf,
    )
)


def _ssy(x: Inputs) -> Result:
    deposit = x.num("deposit", above=ZERO)
    rate = x.rate("rate")
    rows = _yearly(deposit, rate, 21, pay_years=15)
    _, invested, bal = rows[-1]
    r = Result(value("maturity", "Maturity value (21 years from opening)", bal, "money"))
    r.add("invested", "Total deposited (15 years)", invested, "money")
    r.add("interest", "Interest earned (tax-free)", bal - invested, "money")
    age = x.opt("age")
    if age is not None:
        r.add("age_then", "Daughter's age at maturity", age + 21, "number")
    if deposit > Decimal(150000):
        r.warnings.append("Sukanya Samriddhi takes at most ₹1,50,000 a year.")
    r.steps = ["Deposits for the first 15 years; interest compounds yearly until year 21"]
    _year_table(r, rows, "Balance")
    return r


register(
    Calculator(
        key="ssy",
        family="planners",
        title="Sukanya Samriddhi",
        description="Deposits for 15 years, maturity 21 years after opening, interest compounded yearly.",
        keywords="sukanya samriddhi ssy girl child daughter scheme maturity 21 years",
        fields=[
            Field("deposit", "Yearly deposit", "money", "150000"),
            Field("rate", "Interest rate (%)", "percent", "8.2", "The rate is set each quarter; use today's"),
            Field("age", "Daughter's age at opening", "number", "", optional=True),
        ],
        run=_ssy,
    )
)


def _epf(x: Inputs) -> Result:
    basic = x.num("basic", above=ZERO)
    emp = x.rate("employee", default=Decimal("0.12"))
    er = x.rate("employer", default=Decimal("0.0367"))
    rate = x.rate("rate")
    years = x.int_("years", min_=1, max_=50)
    growth = x.rate("growth", default=ZERO)
    bal = x.num("opening", default=ZERO, min_=ZERO)
    rows: list[tuple[int, Decimal, Decimal]] = []
    invested = bal
    with localcontext(ctx()):
        salary = basic
        for y in range(1, years + 1):
            running, interest_base = bal, ZERO
            for _ in range(12):
                contrib = salary * (emp + er)
                running += contrib
                invested += contrib
                interest_base += running
            bal = running + interest_base * rate / TWELVE
            rows.append((y, invested, bal))
            salary *= ONE + growth
        r = Result(value("corpus", "EPF balance at the end", bal, "money"))
        r.add("invested", "Contributions (with the opening balance)", invested, "money")
        r.add("interest", "Interest earned", bal - invested, "money")
        r.add("monthly_now", "Contribution each month now", basic * (emp + er), "money")
        r.steps = [
            "Each month: employee + employer EPF share is added; interest = Σ monthly balances × rate / 12, "
            "credited at the year end (as EPFO works it)"
        ]
        _year_table(r, rows, "Balance")
    return r


register(
    Calculator(
        key="epf",
        family="planners",
        title="EPF",
        description="Employees' Provident Fund: 12% of basic + DA from you and 3.67% from the employer "
        "(the rest of "
        "the employer's 12% goes to EPS), interest on monthly balances credited yearly.",
        keywords="epf provident fund pf employer employee contribution basic salary retirement corpus",
        fields=[
            Field("basic", "Basic + DA a month", "money", "50000"),
            Field("growth", "Salary rise each year (%)", "percent", "6", optional=True),
            Field("rate", "EPF interest rate (%)", "percent", "8.25"),
            Field("years", "Years", "int", "25"),
            Field("opening", "Balance now", "money", "0", optional=True),
            Field("employee", "Your share (%)", "percent", "12", optional=True),
            Field("employer", "Employer's EPF share (%)", "percent", "3.67", optional=True),
        ],
        run=_epf,
    )
)


def _nps(x: Inputs) -> Result:
    monthly = x.num("monthly", above=ZERO)
    months = _months(x)
    annual = x.rate("rate")
    step = x.rate("step_up", default=ZERO)
    share = x.rate("annuity_share", default=Decimal("0.4"))
    if share < Decimal("0.4") or share > 1:
        raise CalcError("At least 40% of the corpus must buy an annuity.", "annuity_share")
    ann_rate = x.rate("annuity_rate")
    with localcontext(ctx()):
        corpus, invested, rows = grow_sip(monthly, pw(ONE + annual, ONE / TWELVE) - ONE, months, step=step)
        r = Result(
            value("pension", "Monthly pension from the annuity", corpus * share * ann_rate / TWELVE, "money")
        )
        r.add("corpus", "Corpus at 60", corpus, "money")
        r.add("lump", "Lump sum you can take (tax-free up to 60%)", corpus * (ONE - share), "money")
        r.add("annuity", "Used to buy the annuity", corpus * share, "money")
        r.add("invested", "Total contributed", invested, "money")
        r.steps = ["Pension = corpus × annuity share × annuity rate ÷ 12 (a level annuity for life)"]
        _year_table(r, rows)
    return r


register(
    Calculator(
        key="nps",
        family="planners",
        title="NPS pension",
        description="National Pension System: the corpus at 60, the lump sum, and the monthly pension the "
        "annuity "
        "pays.",
        keywords="nps national pension system annuity pension corpus tier 1 80ccd retirement",
        fields=[
            Field("monthly", "Monthly contribution", "money", "10000"),
            Field("years", "Years to 60", "number", "25"),
            Field("rate", "Expected return (%)", "percent", "10"),
            Field("step_up", "Raise it each year by (%)", "percent", "5", optional=True),
            Field("annuity_share", "Share used for the annuity (%)", "percent", "40"),
            Field("annuity_rate", "Annuity rate (%)", "percent", "6.5"),
        ],
        run=_nps,
    )
)


# ------------------------------------------------------------------------------------------- ULIP


def _annual_irr(premiums: list[Decimal], final: Decimal) -> Decimal:
    """Rate at which premiums paid at the start of each year grow to `final` at the end of the last year."""
    n = len(premiums)

    def f(r: Decimal) -> Decimal:
        return sum((p * pw(ONE + r, n - k) for k, p in enumerate(premiums)), ZERO) - final

    return solve(f, Decimal("-0.99"), Decimal(10), Decimal("0.08"), what="the yield")


def _ulip(x: Inputs) -> Result:
    premium = x.num("premium", above=ZERO)
    years = x.int_("years", min_=1, max_=50)
    a1, a25, a6 = x.rate("alloc_1"), x.rate("alloc_2_5"), x.rate("alloc_6")
    admin = x.num("admin", default=ZERO, min_=ZERO)
    mortality = x.num("mortality", default=ZERO, min_=ZERO)
    fmc = x.rate("fmc")
    gross = x.rate("gross")
    term = x.num("term", default=ZERO, min_=ZERO)
    ter = x.rate("ter", default=ZERO)
    with localcontext(ctx()):
        gm = pw(ONE + gross, ONE / TWELVE) - ONE
        fund = ZERO
        charges = ZERO
        rows = []
        for y in range(1, years + 1):
            alloc = a1 if y == 1 else a25 if y <= 5 else a6
            fund += premium * (ONE - alloc)
            charges += premium * alloc
            for _ in range(12):
                fund -= admin + mortality / TWELVE
                charges += admin + mortality / TWELVE
                fund *= ONE + gm
                fee = fund * fmc / TWELVE
                fund -= fee
                charges += fee
            rows.append((y, premium * y, fund))
        if fund <= 0:
            raise CalcError("The charges use up the whole fund.", "premium")
        ulip_irr = _annual_irr([premium] * years, fund)
        alt_net = premium - term
        mf = ZERO
        for _ in range(years):
            mf = (mf + alt_net) * (ONE + gross - ter)
        r = Result(value("fund", "ULIP fund value at the end", fund, "money"))
        r.add("irr", "ULIP yield after charges", ulip_irr * HUNDRED, "percent")
        r.add("charges", "Charges deducted (allocation, admin, mortality, fund management)", charges, "money")
        r.add("paid", "Premiums paid", premium * years, "money")
        if alt_net > 0:
            r.add("mf", "Term plan + mutual fund: the fund at the end", mf, "money")
            r.add(
                "mf_irr",
                "…its yield on the whole premium",
                _annual_irr([premium] * years, mf) * HUNDRED,
                "percent",
            )
            r.add("diff", "Term plan + mutual fund minus ULIP", mf - fund, "money")
        r.steps = [
            "Each year the premium less the allocation charge goes in; each month admin and mortality "
            "charges come "
            "out, the fund grows, and the fund management charge is taken",
            "Comparison: the same premium, less a term plan's premium, in a mutual fund earning the same "
            "gross "
            "return less its expense ratio",
        ]
        _year_table(r, rows, "Fund value")
    return r


register(
    Calculator(
        key="ulip",
        family="planners",
        title="ULIP against term plan + mutual fund",
        description="What a ULIP's charges leave you, from the figures in its benefit illustration, "
        "beside buying a "
        "term plan and investing the rest in a mutual fund.",
        keywords="ulip unit linked insurance plan charges allocation mortality fmc term plan mutual fund "
        "buy term "
        "invest rest irr",
        fields=[
            Field("premium", "Yearly premium", "money", "100000"),
            Field("years", "Policy years", "int", "15"),
            Field("gross", "Fund return before charges (%)", "percent", "10"),
            Field("alloc_1", "Allocation charge, year 1 (%)", "percent", "6"),
            Field("alloc_2_5", "Allocation charge, years 2–5 (%)", "percent", "4"),
            Field("alloc_6", "Allocation charge, after year 5 (%)", "percent", "2"),
            Field("admin", "Policy admin charge a month", "money", "500"),
            Field("mortality", "Mortality charge a year", "money", "3000"),
            Field("fmc", "Fund management charge a year (%)", "percent", "1.35"),
            Field("term", "Term plan premium a year (for the comparison)", "money", "12000", optional=True),
            Field("ter", "Mutual fund expense ratio (%)", "percent", "0.5", optional=True),
        ],
        run=_ulip,
    )
)


# ------------------------------------------------------------------------------------------- rent or buy


def _rent_buy(x: Inputs) -> Result:
    price = x.num("price", above=ZERO)
    down = x.rate("down")
    loan_rate = x.rate("loan_rate")
    tenure = x.int_("tenure", min_=1, max_=40) * 12
    costs = x.rate("costs", default=ZERO)
    maint = x.rate("maintenance", default=ZERO)
    appre = x.rate("appreciation")
    rent = x.num("rent", above=ZERO)
    rent_up = x.rate("rent_increase", default=ZERO)
    ret = x.rate("invest_return")
    horizon = x.int_("horizon", min_=1, max_=40) * 12
    with localcontext(ctx()):
        loan = price * (ONE - down)
        i = loan_rate / TWELVE
        emi_ = loan * i / (ONE - pw(ONE + i, -tenure)) if i else loan / tenure
        inv_m = pw(ONE + ret, ONE / TWELVE) - ONE
        upfront = price * down + price * costs
        renter = upfront  # the renter invests what the buyer paid up front
        bal = loan
        rent_now = rent
        buyer_extra = ZERO  # when renting costs more, the buyer invests the difference
        value_now = price
        for m in range(1, horizon + 1):
            if m > 1 and (m - 1) % 12 == 0:
                rent_now *= ONE + rent_up
            interest = bal * i
            pay = min(emi_, bal + interest) if bal > 0 else ZERO
            bal = bal + interest - pay
            own_cost = pay + value_now * maint / TWELVE
            diff = own_cost - rent_now
            renter = renter * (ONE + inv_m) + max(diff, ZERO)
            buyer_extra = buyer_extra * (ONE + inv_m) + max(-diff, ZERO)
            if m % 12 == 0:
                value_now *= ONE + appre
        buy_worth = value_now - max(bal, ZERO) + buyer_extra
        r = Result(value("better", "Better after the period", ZERO, "text"))
        r.answer.value = r.answer.exact = "Buying" if buy_worth > renter else "Renting and investing"
        r.add("buy", "Buyer's wealth: home value − loan left (+ savings invested)", buy_worth, "money")
        r.add("rent", "Renter's wealth: the down payment and savings invested", renter, "money")
        r.add("gap", "Difference", abs(buy_worth - renter), "money")
        r.add("emi", "EMI", emi_, "money")
        r.add("home", "Home value at the end", value_now, "money")
        r.steps = [
            "Each month the cheaper side invests the difference between owning (EMI + maintenance) and rent",
            "The renter starts by investing the down payment and purchase costs",
        ]
    return r


register(
    Calculator(
        key="rent_buy",
        family="planners",
        title="Rent or buy a home",
        description="Wealth after some years if you buy with a loan, against renting and investing what "
        "buying would have cost.",
        keywords="rent vs buy home house property emi down payment appreciation rent increase invest "
        "difference",
        fields=[
            Field("price", "Home price", "money", "10000000"),
            Field("down", "Down payment (%)", "percent", "20"),
            Field("costs", "Stamp duty, registration and other costs (%)", "percent", "7"),
            Field("loan_rate", "Loan rate (%)", "percent", "8.5"),
            Field("tenure", "Loan years", "int", "20"),
            Field("maintenance", "Maintenance and tax a year (% of value)", "percent", "1", optional=True),
            Field("appreciation", "Home value rises a year (%)", "percent", "5"),
            Field("rent", "Rent a month now", "money", "30000"),
            Field("rent_increase", "Rent rises a year (%)", "percent", "6", optional=True),
            Field("invest_return", "Return on money invested (%)", "percent", "11"),
            Field("horizon", "Compare after (years)", "int", "20"),
        ],
        run=_rent_buy,
    )
)


# ------------------------------------------------------------------------------------------- cost of delay


def _delay(x: Inputs) -> Result:
    amount = x.num("amount", above=ZERO)
    annual = x.rate("rate")
    months = _months(x)
    delay = x.int_("delay", min_=1, max_=600)
    if delay >= months:
        raise CalcError("The delay must be shorter than the time to the goal.", "delay")
    i = monthly_rate(annual, "nominal")
    with localcontext(ctx()):
        now, inv_now, _ = grow_sip(amount, i, months)
        later, inv_later, _ = grow_sip(amount, i, months - delay)
        unit, _, _ = grow_sip(ONE, i, months - delay)
        r = Result(value("cost", "Cost of waiting", now - later, "money"))
        r.add("now", "Starting now", now, "money")
        r.add("later", f"Starting {delay} months later", later, "money")
        r.add("catch_up", "SIP needed later to end with the same", now / unit, "money")
        r.add("invested_now", "Invested, starting now", inv_now, "money")
        r.add("invested_later", "Invested, starting later", inv_later, "money")
    return r


register(
    Calculator(
        key="delay",
        family="planners",
        title="Cost of delay",
        description="What waiting to start a SIP costs by the end, and how much bigger the SIP must be to "
        "catch up.",
        keywords="cost of delay start early sip wait procrastination catch up",
        fields=[
            Field("amount", "Monthly SIP", "money", "10000"),
            Field("rate", "Expected return (%)", "percent", "12"),
            Field("years", "Years to the goal (from now)", "number", "25"),
            Field("delay", "Months of delay", "int", "24"),
        ],
        run=_delay,
    )
)
