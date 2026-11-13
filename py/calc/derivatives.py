"""Derivatives and currency (decision #120, family M): Black-Scholes (with dividends) and its Greeks and
implied volatility, the binomial tree (European and American), put-call parity, the payoff of option
strategies at expiry, forward and futures fair value with cost of carry, and currency cross rates and forwards
(covered interest parity). The normal distribution is the decimal one in stats.py."""

from __future__ import annotations

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
    exp,
    fmt,
    ln,
    pw,
    register,
    solve,
    sqrt,
    value,
)
from .stats import norm_cdf, norm_pdf

D365 = Decimal(365)


def _years(x: Inputs) -> Decimal:
    if x.choice("time_in") == "days":
        return x.num("days", above=ZERO) / D365
    return x.num("years", above=ZERO)


def bs(s: Decimal, k: Decimal, t: Decimal, *, r: Decimal, q: Decimal, sigma: Decimal) -> dict[str, Decimal]:
    """Black-Scholes-Merton with a continuous dividend yield; rates continuously compounded."""
    with localcontext(ctx()):
        st = sigma * sqrt(t)
        d1 = (ln(s / k) + (r - q + sigma * sigma / 2) * t) / st
        d2 = d1 - st
        dq, dr = exp(-q * t), exp(-r * t)
        call = s * dq * norm_cdf(d1) - k * dr * norm_cdf(d2)
        put = k * dr * norm_cdf(-d2) - s * dq * norm_cdf(-d1)
        pdf = norm_pdf(d1)
        decay = -s * dq * pdf * sigma / (2 * sqrt(t))
        return {
            "d1": d1,
            "d2": d2,
            "call": call,
            "put": put,
            "delta_c": dq * norm_cdf(d1),
            "delta_p": dq * (norm_cdf(d1) - ONE),
            "gamma": dq * pdf / (s * st),
            "vega": s * dq * pdf * sqrt(t) / HUNDRED,
            "theta_c": (decay - r * k * dr * norm_cdf(d2) + q * s * dq * norm_cdf(d1)) / D365,
            "theta_p": (decay + r * k * dr * norm_cdf(-d2) - q * s * dq * norm_cdf(-d1)) / D365,
            "rho_c": k * t * dr * norm_cdf(d2) / HUNDRED,
            "rho_p": -k * t * dr * norm_cdf(-d2) / HUNDRED,
        }


def _cont(x: Inputs, key: str) -> Decimal:
    """A rate as typed, made continuous if it was given as an ordinary annual rate."""
    v = x.rate(key, default=ZERO)
    return ln(ONE + v) if x.choice("rate_type") == "annual" else v


def _bs(x: Inputs) -> Result:
    s, k = x.num("spot", above=ZERO), x.num("strike", above=ZERO)
    t = _years(x)
    r, q = _cont(x, "r"), _cont(x, "q")
    with localcontext(ctx()):
        if x.choice("solve") == "price":
            sigma = x.rate("vol", above=ZERO)
        else:
            target = x.num("market", above=ZERO)
            kind = x.choice("option")
            sigma = solve(
                lambda v: bs(s, k, t, r=r, q=q, sigma=v)[kind] - target,
                Decimal("0.0001"),
                Decimal(10),
                Decimal("0.3"),
                what="the volatility",
            )
        g = bs(s, k, t, r=r, q=q, sigma=sigma)
        res = Result(value("call", "Call value", g["call"], "money"))
        res.add("put", "Put value", g["put"], "money")
        if x.choice("solve") == "iv":
            res.add("iv", "Implied volatility", sigma * HUNDRED, "percent")
        res.add("d1", "d1", g["d1"], "number")
        res.add("d2", "d2", g["d2"], "number")
        res.add("delta_c", "Delta, call", g["delta_c"], "number")
        res.add("delta_p", "Delta, put", g["delta_p"], "number")
        res.add("gamma", "Gamma", g["gamma"], "number")
        res.add("vega", "Vega (per 1% of volatility)", g["vega"], "number")
        res.add("theta_c", "Theta, call (per day)", g["theta_c"], "number")
        res.add("theta_p", "Theta, put (per day)", g["theta_p"], "number")
        res.add("rho_c", "Rho, call (per 1% rate)", g["rho_c"], "number")
        res.add("rho_p", "Rho, put (per 1% rate)", g["rho_p"], "number")
        res.steps = [
            "d1 = [ln(S/K) + (r − q + σ²/2) T] / (σ√T);  d2 = d1 − σ√T",
            "Call = S e^(−qT) N(d1) − K e^(−rT) N(d2);  put = K e^(−rT) N(−d2) − S e^(−qT) N(−d1)",
        ]
    return res


def _time_fields(years: str = "0.5") -> list[Field]:
    return [
        Field(
            "time_in", "Time to expiry in", "choice", "years", options=(("years", "Years"), ("days", "Days"))
        ),
        Field("years", "Years to expiry", "number", years, show_when={"time_in": ["years"]}),
        Field("days", "Days to expiry", "number", "30", show_when={"time_in": ["days"]}),
    ]


RATE_TYPE = Field(
    "rate_type",
    "Rates are",
    "choice",
    "continuous",
    options=(("continuous", "Continuously compounded"), ("annual", "Ordinary annual rates")),
)

register(
    Calculator(
        key="black_scholes",
        family="derivatives",
        title="Black-Scholes option value and Greeks",
        description="European call and put values with a dividend yield, the Greeks, and implied "
        "volatility from a market price.",
        keywords="black scholes option pricing call put greeks delta gamma vega theta rho implied "
        "volatility iv nifty options european",
        fields=[
            Field(
                "solve",
                "Find",
                "choice",
                "price",
                options=(("price", "Option values"), ("iv", "Implied volatility")),
            ),
            Field("spot", "Spot price (S)", "money", "42"),
            Field("strike", "Strike (K)", "money", "40"),
            *_time_fields(),
            Field("r", "Risk-free rate (%)", "percent", "10"),
            Field("q", "Dividend yield (%)", "percent", "0", optional=True),
            RATE_TYPE,
            Field("vol", "Volatility (%)", "percent", "20", show_when={"solve": ["price"]}),
            Field(
                "option",
                "The price is of a",
                "choice",
                "call",
                options=(("call", "Call"), ("put", "Put")),
                show_when={"solve": ["iv"]},
            ),
            Field("market", "Market price of the option", "money", "4.76", show_when={"solve": ["iv"]}),
        ],
        run=_bs,
    )
)


# ------------------------------------------------------------------------------------------- binomial


def _binomial(x: Inputs) -> Result:
    s, k = x.num("spot", above=ZERO), x.num("strike", above=ZERO)
    t = _years(x)
    r, q = _cont(x, "r"), _cont(x, "q")
    sigma = x.rate("vol", above=ZERO)
    n = x.int_("steps", min_=1, max_=500)
    call = x.choice("option") == "call"
    american = x.choice("style") == "american"
    with localcontext(ctx()):
        dt_ = t / n
        u = exp(sigma * sqrt(dt_))
        d = ONE / u
        a = exp((r - q) * dt_)
        p = (a - d) / (u - d)
        if not ZERO < p < ONE:
            raise CalcError("These inputs give no valid risk-neutral probability; use more steps.", "steps")
        disc = exp(-r * dt_)

        def payoff(price: Decimal) -> Decimal:
            return max(price - k, ZERO) if call else max(k - price, ZERO)

        vals = [payoff(s * pw(u, n - j) * pw(d, j)) for j in range(n + 1)]
        early = 0
        for step in range(n - 1, -1, -1):
            nxt = []
            for j in range(step + 1):
                cont = disc * (p * vals[j] + (ONE - p) * vals[j + 1])
                if american:
                    ex = payoff(s * pw(u, step - j) * pw(d, j))
                    if ex > cont:
                        early += 1
                        cont = ex
                nxt.append(cont)
            vals = nxt
        style = "American" if american else "European"
        kind = "call" if call else "put"
        res = Result(value("value", f"{style} {kind} value", vals[0], "money"))
        res.add("u", "Up factor (u)", u, "number")
        res.add("d", "Down factor (d)", d, "number")
        res.add("p", "Risk-neutral probability of up (p)", p, "number")
        if american:
            res.add("early", "Nodes where early exercise is better", Decimal(early), "count")
        res.steps = [
            "u = e^(σ√Δt), d = 1/u, p = (e^((r−q)Δt) − d)/(u − d) (Cox-Ross-Rubinstein)",
            "Work back from expiry: value = e^(−rΔt)[p·up + (1−p)·down], or exercise if worth more",
        ]
    return res


register(
    Calculator(
        key="binomial",
        family="derivatives",
        title="Binomial option value (American or European)",
        description="A Cox-Ross-Rubinstein tree: European or American calls and puts, with early exercise.",
        keywords="binomial tree option american european early exercise crr cox ross rubinstein put call",
        fields=[
            Field("option", "Option", "choice", "put", options=(("call", "Call"), ("put", "Put"))),
            Field(
                "style",
                "Style",
                "choice",
                "american",
                options=(("american", "American"), ("european", "European")),
            ),
            Field("spot", "Spot price (S)", "money", "50"),
            Field("strike", "Strike (K)", "money", "50"),
            *_time_fields("0.4166666667"),
            Field("r", "Risk-free rate (%)", "percent", "10"),
            Field("q", "Dividend yield (%)", "percent", "0", optional=True),
            RATE_TYPE,
            Field("vol", "Volatility (%)", "percent", "40"),
            Field("steps", "Steps", "int", "5"),
        ],
        run=_binomial,
    )
)


# ------------------------------------------------------------------------------------------- parity


def _parity(x: Inputs) -> Result:
    k = x.num("strike", above=ZERO)
    t = _years(x)
    r = _cont(x, "r")
    q = _cont(x, "q")
    missing = x.choice("find")
    with localcontext(ctx()):
        pvk = k * exp(-r * t)
        s_adj = exp(-q * t)
        c, p, s = (x.num(n) if missing != n else ZERO for n in ("call", "put", "spot"))
        if missing == "call":
            c = p + s * s_adj - pvk
            res = Result(value("call", "Call value by parity", c, "money"))
        elif missing == "put":
            p = c - s * s_adj + pvk
            res = Result(value("put", "Put value by parity", p, "money"))
        elif missing == "spot":
            s = (c - p + pvk) / s_adj
            res = Result(value("spot", "Spot implied by parity", s, "money"))
        else:
            gap = c - p - (s * s_adj - pvk)
            res = Result(value("gap", "Call − put − (S − PV(K)): the mispricing", gap, "money"))
            if abs(gap) < Decimal("0.005"):
                trade = "none: the prices agree with parity"
            elif gap > 0:
                trade = "sell the call, buy the put and the share, borrow PV(K)"
            else:
                trade = "buy the call, sell the put and the share, lend PV(K)"
            res.add("trade", "Arbitrage", trade, "text")
        res.add("pvk", "Present value of the strike", pvk, "money")
        res.steps = ["C + K e^(−rT) = P + S e^(−qT)"]
    return res


register(
    Calculator(
        key="parity",
        family="derivatives",
        title="Put-call parity",
        description="Find a call, put or spot price from the other two, or check prices for a mispricing.",
        keywords="put call parity arbitrage synthetic options",
        fields=[
            Field(
                "find",
                "Find",
                "choice",
                "check",
                options=(
                    ("check", "Check for mispricing"),
                    ("call", "Call"),
                    ("put", "Put"),
                    ("spot", "Spot"),
                ),
            ),
            Field("call", "Call price", "money", "4.76"),
            Field("put", "Put price", "money", "0.81"),
            Field("spot", "Spot price", "money", "42"),
            Field("strike", "Strike", "money", "40"),
            *_time_fields(),
            Field("r", "Risk-free rate (%)", "percent", "10"),
            Field("q", "Dividend yield (%)", "percent", "0", optional=True),
            RATE_TYPE,
        ],
        run=_parity,
    )
)


# ------------------------------------------------------------------------------------------- payoff

LEGS = (
    Column("kind", "Call, put or stock", "text"),
    Column("side", "Long or short", "text"),
    Column("strike", "Strike (blank for stock)", "money", optional=True),
    Column("premium", "Premium (or stock cost)", "money"),
    Column("qty", "Quantity"),
)


def _leg_value(leg: dict[str, Any], price: Decimal) -> Decimal:
    kind, sign = leg["kind"], ONE if leg["side"] == "long" else -ONE
    if kind == "stock":
        return Decimal(sign * (price - leg["premium"]) * leg["qty"])
    k = leg["strike"]
    intrinsic = max(price - k, ZERO) if kind == "call" else max(k - price, ZERO)
    return Decimal(sign * (intrinsic - leg["premium"]) * leg["qty"])


def _payoff(x: Inputs) -> Result:
    legs = x.table("legs", min_rows=1)
    for i, leg in enumerate(legs, start=1):
        leg["kind"] = str(leg["kind"]).strip().lower()
        leg["side"] = str(leg["side"]).strip().lower()
        if leg["kind"] not in ("call", "put", "stock") or leg["side"] not in ("long", "short"):
            raise CalcError(f"Row {i}: type call, put or stock, and long or short.", "legs")
        if leg["kind"] != "stock" and leg["strike"] is None:
            raise CalcError(f"Row {i}: an option needs a strike.", "legs")
    with localcontext(ctx()):
        strikes = [leg["strike"] or leg["premium"] for leg in legs]
        lo, hi = min(strikes) * Decimal("0.6"), max(strikes) * Decimal("1.4")
        grid = sorted({lo + (hi - lo) * j / 80 for j in range(81)} | set(strikes))
        pnl = [(pr, sum((_leg_value(leg, pr) for leg in legs), ZERO)) for pr in grid]
        best = max(v for _, v in pnl)
        worst = min(v for _, v in pnl)
        # Above the grid the payoff runs on in a straight line: unlimited if its slope is not flat.
        slope_hi = sum(
            ((ONE if leg["side"] == "long" else -ONE) * leg["qty"] for leg in legs if leg["kind"] != "put"),
            ZERO,
        )
        # A price where the profit is exactly zero, or a crossing between two prices with opposite signs.
        found = {pr for pr, v in pnl if v == 0}
        for (p1, v1), (p2, v2) in pairwise(pnl):
            if v1 and v2 and (v1 < 0) != (v2 < 0):
                found.add(p1 + (p2 - p1) * (-v1) / (v2 - v1))
        breakevens = sorted(found)
        res = Result(value("max_profit", "Maximum profit at expiry", best, "money"))
        if slope_hi > 0:
            res.answer.value = res.answer.exact = "unlimited"
            res.answer.unit = "text"
        if slope_hi < 0:
            res.add("max_loss", "Maximum loss at expiry", "unlimited", "text")
        else:
            res.add("max_loss", "Maximum loss at expiry", worst, "money")
        res.add(
            "breakeven", "Break-even prices", ", ".join(fmt(b, "money") for b in breakevens) or "none", "text"
        )
        net = sum(
            (
                (ONE if leg["side"] == "short" else -ONE) * leg["premium"] * leg["qty"]
                for leg in legs
                if leg["kind"] != "stock"
            ),
            ZERO,
        )
        res.add("net_premium", "Net premium received (+) or paid (−)", net, "money")
        res.chart = Chart(
            "line",
            "Profit or loss at expiry",
            "Price at expiry",
            "money",
            [fmt(pr, "money") for pr, _ in pnl],
            [{"name": "Profit", "values": [fmt(v, "money") for _, v in pnl]}],
        )
        res.tables.append(
            TableOut(
                "pnl",
                "Profit at each price",
                [
                    {"key": "price", "label": "Price at expiry", "unit": "money"},
                    {"key": "pnl", "label": "Profit or loss", "unit": "money"},
                ],
                [[fmt(pr, "money"), fmt(v, "money")] for pr, v in pnl[::4]],
            )
        )
    return res


register(
    Calculator(
        key="payoff",
        family="derivatives",
        title="Option strategy payoff",
        description="Legs of calls, puts and stock, long or short: profit or loss at expiry across prices, "
        "the maximum profit and loss, and break-evens. Covered calls, protective puts, spreads, straddles.",
        keywords="option strategy payoff diagram covered call protective put spread straddle strangle iron "
        "condor breakeven max profit loss",
        fields=[
            Field(
                "legs",
                "Legs",
                "table",
                columns=LEGS,
                rows=[
                    {"kind": "call", "side": "long", "strike": "22000", "premium": "180", "qty": "75"},
                    {"kind": "call", "side": "short", "strike": "22300", "premium": "70", "qty": "75"},
                ],
            )
        ],
        run=_payoff,
    )
)


# ------------------------------------------------------------------------------------------- forwards and FX


def _forward(x: Inputs) -> Result:
    s = x.num("spot", above=ZERO)
    t = _years(x)
    r = x.rate("r")
    carry = x.rate("yield", default=ZERO)
    store = x.rate("storage", default=ZERO)
    with localcontext(ctx()):
        if x.choice("compounding") == "continuous":
            f = s * exp((r - carry + store) * t)
        else:
            f = s * pw((ONE + r + store) / (ONE + carry), t)
        res = Result(value("forward", "Fair forward / futures price", f, "money"))
        res.add("basis", "Basis (fair price − spot)", f - s, "money")
        res.add("basis_pct", "…as a share of spot, a year", (f / s - ONE) / t * HUNDRED, "percent")
        mkt = x.opt("market")
        if mkt is not None:
            res.add("mispricing", "Market price − fair price", mkt - f, "money")
            if mkt > f:
                trade = "sell the future, buy spot, borrow"
            elif mkt < f:
                trade = "buy the future, sell spot, lend"
            else:
                trade = "none: fairly priced"
            res.add("trade", "Cash-and-carry", trade, "text")
        res.steps = ["Continuous: F = S e^((r − y + u)T);  discrete: F = S [(1 + r + u)/(1 + y)]^T"]
    return res


register(
    Calculator(
        key="forward",
        family="derivatives",
        title="Forward and futures fair value",
        description="The fair price of a forward or future from spot, interest, dividend yield and storage "
        "cost, and the cash-and-carry trade against a market price.",
        keywords="forward futures fair value cost of carry basis dividend yield storage cash and carry "
        "arbitrage nifty futures",
        fields=[
            Field("spot", "Spot price", "money", "22000"),
            *_time_fields(),
            Field("r", "Interest rate (%)", "percent", "7"),
            Field("yield", "Dividend or income yield (%)", "percent", "1.3", optional=True),
            Field("storage", "Storage cost (%, for commodities)", "percent", "0", optional=True),
            Field(
                "compounding",
                "Rates are",
                "choice",
                "continuous",
                options=(("continuous", "Continuously compounded"), ("discrete", "Annual")),
            ),
            Field("market", "Market futures price (optional)", "money", "", optional=True),
        ],
        run=_forward,
    )
)


def _fx(x: Inputs) -> Result:
    spot = x.num("spot", above=ZERO)
    rd, rf = x.rate("domestic"), x.rate("foreign")
    days = x.num("days", above=ZERO)
    basis_d = Decimal(x.choice("basis_d"))
    basis_f = Decimal(x.choice("basis_f"))
    with localcontext(ctx()):
        fwd = spot * (ONE + rd * days / basis_d) / (ONE + rf * days / basis_f)
        res = Result(value("forward", "Forward rate (covered interest parity)", fwd, "number"))
        res.add("points", "Forward points (forward − spot)", fwd - spot, "number")
        res.add(
            "premium",
            "Annualised forward premium (+) or discount (−) of the foreign currency",
            (fwd / spot - ONE) * D365 / days * HUNDRED,
            "percent",
        )
        cross = x.opt("cross")
        if cross is not None and cross > 0:
            res.add("cross_rate", "Cross rate: spot × the second quote", spot * cross, "number")
        res.steps = ["F = S × (1 + r_domestic × days/basis) / (1 + r_foreign × days/basis)"]
    return res


register(
    Calculator(
        key="fx",
        family="derivatives",
        title="Currency forward and cross rates",
        description="A currency's forward rate from spot and the two interest rates (covered interest "
        "parity), the forward points and premium, and a cross rate.",
        keywords="fx forex currency forward covered interest parity forward points premium discount cross "
        "rate usd inr",
        fields=[
            Field("spot", "Spot (domestic units per foreign unit, e.g. ₹ per $)", "number", "84.20"),
            Field("domestic", "Domestic interest rate (%)", "percent", "6.75"),
            Field("foreign", "Foreign interest rate (%)", "percent", "4.5"),
            Field("days", "Days to delivery", "number", "90"),
            Field("basis_d", "Domestic day basis", "choice", "365", options=(("365", "365"), ("360", "360"))),
            Field("basis_f", "Foreign day basis", "choice", "360", options=(("360", "360"), ("365", "365"))),
            Field(
                "cross",
                "Second quote for a cross rate (foreign per third currency)",
                "number",
                "",
                optional=True,
            ),
        ],
        run=_fx,
    )
)
