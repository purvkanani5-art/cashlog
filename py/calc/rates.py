"""Interest rates and conversions (decision #120, family B)."""

from __future__ import annotations

from decimal import Decimal, localcontext

from .core import (
    HUNDRED,
    ONE,
    TWO,
    ZERO,
    CalcError,
    Calculator,
    Field,
    Inputs,
    Result,
    TableOut,
    ctx,
    exp,
    fmt,
    ln,
    pw,
    register,
    solve,
    value,
)

D365, D360 = Decimal(365), Decimal(360)
COMPOUNDING = (
    ("1", "Yearly"),
    ("2", "Half-yearly"),
    ("4", "Quarterly"),
    ("12", "Monthly"),
    ("52", "Weekly"),
    ("365", "Daily"),
    ("continuous", "Continuously"),
)
PERIODS = (
    ("365", "Day"),
    ("52", "Week"),
    ("12", "Month"),
    ("4", "Quarter"),
    ("2", "Half-year"),
    ("1", "Year"),
)


def growth(rate: Decimal, m: str, years: Decimal) -> Decimal:
    """Growth factor for a nominal annual rate compounded m times a year (or continuously) over `years`."""
    with localcontext(ctx()):
        if m == "continuous":
            return exp(rate * years)
        mm = Decimal(m)
        return pw(ONE + rate / mm, mm * years)


def ear_from(rate: Decimal, m: str) -> Decimal:
    return growth(rate, m, ONE) - ONE


def nominal_from_ear(ear: Decimal, m: str) -> Decimal:
    with localcontext(ctx()):
        if m == "continuous":
            return ln(ONE + ear)
        mm = Decimal(m)
        return mm * (pw(ONE + ear, ONE / mm) - ONE)


# ------------------------------------------------------------------------------------ simple and compound


def _interest(x: Inputs) -> Result:
    p = x.num("principal")
    rate = x.rate("rate")
    years = x.num("years", min_=ZERO)
    m = x.choice("compounding")
    with localcontext(ctx()):
        amount = p * growth(rate, m, years)
        simple = p * rate * years
        r = Result(value("amount", "Amount with compound interest", amount, "money"))
        r.add("interest", "Compound interest", amount - p, "money")
        r.add("simple", "Simple interest", simple, "money")
        r.add("simple_amount", "Amount with simple interest", p + simple, "money")
        r.add("difference", "Compound minus simple", amount - p - simple, "money")
        r.add("ear", "Effective annual rate", ear_from(rate, m) * HUNDRED, "percent")
        rows = []
        for key, label in COMPOUNDING:
            a = p * growth(rate, key, years)
            rows.append(
                [label, fmt(ear_from(rate, key) * HUNDRED, "percent"), fmt(a, "money"), fmt(a - p, "money")]
            )
        r.tables.append(
            TableOut(
                "by_compounding",
                "Same rate, every compounding",
                [
                    {"key": "compounding", "label": "Compounding", "unit": "text"},
                    {"key": "ear", "label": "Effective annual rate", "unit": "percent"},
                    {"key": "amount", "label": "Amount", "unit": "money"},
                    {"key": "interest", "label": "Interest", "unit": "money"},
                ],
                rows,
            )
        )
        r.steps = ["Simple: I = P × r × t", "Compound: A = P × (1 + r/m)^(m×t); continuous: A = P × e^(r×t)"]
    return r


register(
    Calculator(
        key="interest",
        family="rates",
        title="Simple and compound interest",
        description="Interest on a sum for any number of years, simple and compound, with the same rate "
        "under every compounding side by side.",
        keywords="simple compound interest continuous compounding amount fd",
        fields=[
            Field("principal", "Principal", "money", "100000"),
            Field("rate", "Annual rate (%)", "percent", "8"),
            Field("years", "Years", "number", "5", "Decimals allowed: 2.5 is two and a half years"),
            Field("compounding", "Compounding", "choice", "4", options=COMPOUNDING),
        ],
        run=_interest,
    )
)


# ------------------------------------------------------------------------------------ rate conversion

RATE_KINDS = (
    ("nominal", "Nominal annual rate (APR) with compounding"),
    ("effective", "Effective annual rate (EAR)"),
    ("periodic", "Rate for one period"),
    ("days", "Rate for a number of days (holding period)"),
)


def _convert(x: Inputs) -> Result:
    kind = x.choice("from")
    rate = x.rate("rate")
    with localcontext(ctx()):
        if kind == "nominal":
            m = x.choice("compounding")
            ear = ear_from(rate, m)
        elif kind == "effective":
            ear = rate
        elif kind == "periodic":
            per_year = Decimal(x.choice("period"))
            ear = pw(ONE + rate, per_year) - ONE
        else:
            days = x.num("days", above=ZERO)
            ear = pw(ONE + rate, D365 / days) - ONE
        if ear <= -1:
            raise CalcError("The rate is too low to convert.", "rate")
        r = Result(value("ear", "Effective annual rate", ear * HUNDRED, "percent"))
        r.add("continuous", "Continuously compounded rate", ln(ONE + ear) * HUNDRED, "percent")
        target_days = x.num("target_days", default=Decimal(90), above=ZERO)
        r.add(
            "for_days",
            f"Rate for {fmt(target_days, 'number')} days",
            (pw(ONE + ear, target_days / D365) - ONE) * HUNDRED,
            "percent",
        )
        rows = []
        for key, label in PERIODS:
            per_year = Decimal(key)
            periodic = pw(ONE + ear, ONE / per_year) - ONE
            rows.append(
                [label, fmt(periodic * HUNDRED, "percent"), fmt(per_year * periodic * HUNDRED, "percent")]
            )
        r.tables.append(
            TableOut(
                "equivalents",
                "Equivalent rates",
                [
                    {"key": "period", "label": "Period", "unit": "text"},
                    {"key": "periodic", "label": "Rate per period", "unit": "percent"},
                    {
                        "key": "nominal",
                        "label": "Nominal annual (APR) compounded each period",
                        "unit": "percent",
                    },
                ],
                rows,
            )
        )
        r.steps = [
            "EAR = (1 + APR/m)^m − 1;  APR = m × [(1 + EAR)^(1/m) − 1]",
            "Rate for t days = (1 + EAR)^(t/365) − 1;  continuous = ln(1 + EAR)",
        ]
    return r


register(
    Calculator(
        key="rate_convert",
        family="rates",
        title="Effective rate for any period",
        description="Convert between nominal (APR), effective annual (EAR), continuous, and rates per day, "
        "week, month, quarter, half-year or any number of days.",
        keywords="effective annual rate ear apr nominal convert monthly quarterly daily periodic continuous",
        fields=[
            Field("from", "I have", "choice", "nominal", options=RATE_KINDS),
            Field("rate", "Rate (%)", "percent", "12"),
            Field(
                "compounding",
                "Compounded",
                "choice",
                "12",
                options=COMPOUNDING,
                show_when={"from": ["nominal"]},
            ),
            Field(
                "period", "The period is a", "choice", "12", options=PERIODS, show_when={"from": ["periodic"]}
            ),
            Field("days", "Number of days", "number", "90", show_when={"from": ["days"]}),
            Field("target_days", "Also show the rate for (days)", "number", "90", optional=True),
        ],
        run=_convert,
    )
)


# ------------------------------------------------------------------------------------ real and nominal


def _fisher(x: Inputs) -> Result:
    nominal = x.rate("nominal")
    inflation = x.rate("inflation")
    with localcontext(ctx()):
        real = (ONE + nominal) / (ONE + inflation) - ONE
        r = Result(value("real", "Real rate (exact)", real * HUNDRED, "percent"))
        r.add(
            "approx",
            "Real rate (approximate: nominal − inflation)",
            (nominal - inflation) * HUNDRED,
            "percent",
        )
        amount = x.opt("amount")
        if amount is not None:
            years = x.num("years", min_=ZERO)
            g = pw(ONE + inflation, years)
            r.add("future_cost", f"Cost after {fmt(years, 'number')} years of inflation", amount * g, "money")
            r.add(
                "today_value",
                f"Worth in today's money after {fmt(years, 'number')} years",
                amount / g,
                "money",
            )
            r.add("grown", "The amount grown at the nominal rate", amount * pw(ONE + nominal, years), "money")
            r.add("grown_real", "…in today's money", amount * pw(ONE + real, years), "money")
        r.steps = [
            "(1 + nominal) = (1 + real)(1 + inflation)  (Fisher)",
            "Real = (1 + nominal) / (1 + inflation) − 1",
        ]
    return r


register(
    Calculator(
        key="fisher",
        family="rates",
        title="Real and nominal rates, inflation",
        description="The real return after inflation (Fisher), and what an amount costs, or is worth in "
        "today's money, after some years of inflation.",
        keywords="real nominal inflation fisher purchasing power cost future today money",
        fields=[
            Field("nominal", "Nominal rate (%)", "percent", "10"),
            Field("inflation", "Inflation (%)", "percent", "6"),
            Field("amount", "Amount (optional)", "money", "100000", optional=True),
            Field("years", "Years", "number", "10", optional=True),
        ],
        run=_fisher,
    )
)


# ------------------------------------------------------------------------------------ money market yields

MM_FROM = (
    ("price", "Price"),
    ("bdy", "Bank discount yield"),
    ("mmy", "Money market yield (CD-equivalent)"),
    ("hpy", "Holding period yield"),
    ("eay", "Effective annual yield"),
    ("bey", "Bond-equivalent yield (365-day)"),
)


def _money_market(x: Inputs) -> Result:
    face = x.num("face", above=ZERO)
    days = x.num("days", above=ZERO)
    known = x.choice("from")
    with localcontext(ctx()):
        if known == "price":
            price = x.num("price", above=ZERO)
            hpy = (face - price) / price
        else:
            y = x.rate("yield")
            if known == "bdy":
                price = face * (ONE - y * days / D360)
                if price <= 0:
                    raise CalcError("That discount yield gives no positive price.", "yield")
                hpy = (face - price) / price
            elif known == "mmy":
                hpy = y * days / D360
            elif known == "hpy":
                hpy = y
            elif known == "eay":
                hpy = pw(ONE + y, days / D365) - ONE
            else:
                hpy = y * days / D365
            price = face / (ONE + hpy)
        r = Result(value("price", "Price", price, "money"))
        r.add("hpy", "Holding period yield", hpy * HUNDRED, "percent")
        r.add(
            "bdy",
            "Bank discount yield (360 days, on face)",
            (face - price) / face * D360 / days * HUNDRED,
            "percent",
        )
        r.add("mmy", "Money market yield (360 days, on price)", hpy * D360 / days * HUNDRED, "percent")
        r.add("bey", "Bond-equivalent yield (365 days, on price)", hpy * D365 / days * HUNDRED, "percent")
        r.add("eay", "Effective annual yield", (pw(ONE + hpy, D365 / days) - ONE) * HUNDRED, "percent")
        r.add("discount", "Discount (face − price)", face - price, "money")
        r.steps = [
            "HPY = (Face − Price) / Price",
            "BDY = (Face − Price)/Face × 360/t;  MMY = HPY × 360/t;  BEY = HPY × 365/t",
            "EAY = (1 + HPY)^(365/t) − 1",
        ]
    return r


register(
    Calculator(
        key="money_market",
        family="rates",
        title="Money market yields (T-bills, CDs, CPs)",
        description="From the price, or any one yield, get every other: holding period, bank discount, money "
        "market, bond-equivalent and effective annual yield.",
        keywords="t-bill treasury bill cd commercial paper discount yield bdy mmy hpy eay bey money market",
        fields=[
            Field("face", "Face value", "money", "100"),
            Field("days", "Days to maturity", "number", "91"),
            Field("from", "I know the", "choice", "price", options=MM_FROM),
            Field("price", "Price", "money", "98.25", show_when={"from": ["price"]}),
            Field(
                "yield",
                "That yield (%)",
                "percent",
                "7",
                show_when={"from": ["bdy", "mmy", "hpy", "eay", "bey"]},
            ),
        ],
        run=_money_market,
    )
)


# ------------------------------------------------------------------------------------ flat vs reducing


def emi(principal: Decimal, monthly: Decimal, months: int) -> Decimal:
    with localcontext(ctx()):
        if monthly == 0:
            return principal / months
        return principal * monthly / (ONE - pw(ONE + monthly, -months))


def _flat(x: Inputs) -> Result:
    mode = x.choice("mode")
    p = x.num("principal", above=ZERO)
    months = x.int_("months", min_=1, max_=1200)
    rate = x.rate("rate", above=Decimal(-1) * ZERO - ONE / HUNDRED * 0)
    with localcontext(ctx()):
        if mode == "flat":
            interest = p * rate * months / 12
            payment = (p + interest) / months
            monthly = solve(
                lambda i: emi(p, i, months) - payment,
                Decimal("-0.99"),
                ONE,
                rate / 12 * TWO,
                what="the reducing rate",
            )
            reducing = monthly * 12
            r = Result(
                value("reducing", "Equivalent reducing-balance rate (annual)", reducing * HUNDRED, "percent")
            )
            r.add("flat", "Flat rate", rate * HUNDRED, "percent")
        else:
            payment = emi(p, rate / 12, months)
            interest = payment * months - p
            flat = interest / p * 12 / months
            r = Result(value("flat", "Equivalent flat rate (annual)", flat * HUNDRED, "percent"))
            r.add("reducing", "Reducing-balance rate", rate * HUNDRED, "percent")
            monthly = rate / 12
        r.add("emi", "EMI", payment, "money")
        r.add("interest", "Total interest", interest, "money")
        r.add("total", "Total paid", payment * months, "money")
        r.add("ear", "Effective annual rate", (pw(ONE + monthly, 12) - ONE) * HUNDRED, "percent")
        r.steps = [
            "Flat: interest = P × rate × months/12 on the full principal throughout; EMI = (P + interest)/n",
            "Reducing: EMI = P·i / (1 − (1+i)^−n), i = annual rate / 12",
        ]
    return r


register(
    Calculator(
        key="flat_rate",
        family="rates",
        title="Flat rate vs reducing-balance rate",
        description="A flat rate charges interest on the full loan for the whole term. See the reducing-"
        "balance rate it really costs, or the flat rate that matches a reducing rate.",
        keywords="flat rate reducing balance consumer loan personal loan emi true rate add-on",
        fields=[
            Field(
                "mode",
                "I have a",
                "choice",
                "flat",
                options=(("flat", "Flat rate"), ("reducing", "Reducing rate")),
            ),
            Field("principal", "Loan amount", "money", "100000"),
            Field("rate", "Annual rate (%)", "percent", "10"),
            Field("months", "Months", "int", "36"),
        ],
        run=_flat,
    )
)


# ------------------------------------------------------------------------------------ doubling


def _doubling(x: Inputs) -> Result:
    multiple = x.num("multiple", default=TWO, above=ONE)
    mode = x.choice("mode")
    with localcontext(ctx()):
        if mode == "time":
            rate = x.rate("rate", above=ZERO)
            years = ln(multiple) / ln(ONE + rate)
            r = Result(value("years", f"Years to grow {fmt(multiple, 'number')} times", years, "years"))
            if multiple == 2:
                pct = rate * HUNDRED
                r.add("rule72", "Rule of 72", Decimal(72) / pct, "years")
                r.add("rule69", "Rule of 69.3 (continuous)", Decimal("69.3") / pct, "years")
                r.add("rule69_adj", "Rule of 69 + 0.35", Decimal(69) / pct + Decimal("0.35"), "years")
            r.add("months", "In months", years * 12, "periods")
            r.steps = [f"t = ln({fmt(multiple, 'number')}) / ln(1 + r)"]
        else:
            years = x.num("years", above=ZERO)
            rate = pw(multiple, ONE / years) - ONE
            r = Result(
                value(
                    "rate",
                    f"Annual return to grow {fmt(multiple, 'number')} times",
                    rate * HUNDRED,
                    "percent",
                )
            )
            if multiple == 2:
                r.add("rule72", "Rule of 72", Decimal(72) / years, "percent")
            r.steps = [f"r = {fmt(multiple, 'number')}^(1/t) − 1"]
    return r


register(
    Calculator(
        key="doubling",
        family="rates",
        title="Doubling time (rule of 72)",
        description="How long money takes to double (or grow any number of times) at a rate, or the rate "
        "needed to do it in a given time, with the rules of thumb beside the exact answer.",
        keywords="rule of 72 69 double doubling time triple grow multiple",
        fields=[
            Field("mode", "Find the", "choice", "time", options=(("time", "Time"), ("rate", "Rate"))),
            Field("rate", "Annual return (%)", "percent", "12", show_when={"mode": ["time"]}),
            Field("years", "Years", "number", "6", show_when={"mode": ["rate"]}),
            Field("multiple", "Grow how many times", "number", "2"),
        ],
        run=_doubling,
    )
)
