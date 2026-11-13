"""Equity valuation (decision #120, family K): dividend discount models (Gordon, two-stage, H-model), a DCF of
free cash flows with a terminal value by growth or exit multiple, the cost of capital (WACC), DuPont analysis,
and justified multiples with sustainable growth and PVGO."""

from __future__ import annotations

from decimal import Decimal, localcontext

from .core import (
    HUNDRED,
    ONE,
    ZERO,
    CalcError,
    Calculator,
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

DDM = (("gordon", "Gordon growth (constant)"), ("two_stage", "Two-stage"), ("h", "H-model"))


def _ddm_value(x: Inputs, model: str, d0: Decimal, r: Decimal) -> tuple[Decimal, Decimal, str]:
    """(value, next dividend, how it was worked out) for the chosen model."""
    with localcontext(ctx()):
        if model == "gordon":
            g = x.rate("g")
            if r <= g:
                raise CalcError("The required return must be above the growth rate.", "g", code="no_solution")
            d1 = d0 * (ONE + g)
            return d1 / (r - g), d1, "V₀ = D₁ / (r − g), D₁ = D₀ (1 + g)"
        g1, g2 = x.rate("g1"), x.rate("g2")
        if r <= g2:
            raise CalcError(
                "The required return must be above the long-run growth.", "g2", code="no_solution"
            )
        if model == "two_stage":
            n = x.int_("n", min_=1, max_=100)
            v, d = ZERO, d0
            for t in range(1, n + 1):
                d *= ONE + g1
                v += d / pw(ONE + r, t)
            v += d * (ONE + g2) / (r - g2) / pw(ONE + r, n)
            how = (
                f"Dividends grow {fmt(g1 * HUNDRED, 'percent')}% for {n} years, then a Gordon value at "
                f"year {n}: D_{n + 1} / (r − g₂), all discounted at r"
            )
            return v, d0 * (ONE + g1), how
        h = x.num("h", above=ZERO)
        v = (d0 * (ONE + g2) + d0 * h * (g1 - g2)) / (r - g2)
        return v, d0 * (ONE + g1), "H-model: V₀ = [D₀(1 + gL) + D₀ H (gS − gL)] / (r − gL)"


def _ddm(x: Inputs) -> Result:
    model = x.choice("model")
    d0 = x.num("d0", above=ZERO)
    r = x.rate("r")
    with localcontext(ctx()):
        v, d1, how = _ddm_value(x, model, d0, r)
        res = Result(value("value", "Value per share", v, "money"))
        res.add("d1", "Next dividend (D₁)", d1, "money")
        res.add("yield", "Dividend yield at that value (D₁ / V₀)", d1 / v * HUNDRED, "percent")
        price = x.opt("price")
        if price is not None and price > 0:
            res.add("mos", "Margin of safety against the price", (v - price) / v * HUNDRED, "percent")
            if model == "gordon":
                implied = (d1 / price + x.rate("g")) * HUNDRED
                res.add("implied_r", "Return implied by the price (D₁ / P + g)", implied, "percent")
        eps = x.opt("eps")
        if eps is not None and eps > 0:
            res.add("pvgo", "PVGO (value − E₁ / r)", v - eps / r, "money")
            res.add("pe", "Justified P/E (value ÷ next year's EPS)", v / eps, "ratio")
        res.steps = [how]
    return res


register(
    Calculator(
        key="ddm",
        family="equity",
        title="Dividend discount model",
        description="A share's value from its dividends: Gordon growth, two-stage, or the H-model; with the "
        "margin of safety against the price, implied return and PVGO.",
        keywords="ddm dividend discount model gordon growth two stage h model intrinsic value share pvgo",
        fields=[
            Field("model", "Model", "choice", "gordon", options=DDM),
            Field("d0", "Dividend just paid (D₀)", "money", "10"),
            Field("r", "Required return (%)", "percent", "12"),
            Field("g", "Growth (%)", "percent", "6", show_when={"model": ["gordon"]}),
            Field("g1", "Growth now (%)", "percent", "15", show_when={"model": ["two_stage", "h"]}),
            Field("n", "Years of that growth", "int", "5", show_when={"model": ["two_stage"]}),
            Field(
                "h", "H: half the years over which growth falls", "number", "5", show_when={"model": ["h"]}
            ),
            Field("g2", "Long-run growth (%)", "percent", "6", show_when={"model": ["two_stage", "h"]}),
            Field("price", "Market price (optional)", "money", "", optional=True),
            Field("eps", "Next year's EPS (optional, for PVGO and P/E)", "money", "", optional=True),
        ],
        run=_ddm,
    )
)


# ------------------------------------------------------------------------------------------- DCF

FLOWS = (Column("year", "Year"), Column("fcf", "Free cash flow", "money"))


def _dcf(x: Inputs) -> Result:
    rows = sorted(x.table("fcf", min_rows=1), key=lambda rr: rr["year"])
    rate = x.rate("rate", above=ZERO)
    firm = x.choice("basis") == "fcff"
    with localcontext(ctx()):
        pv_flows = ZERO
        table = []
        for rr in rows:
            df = ONE / pw(ONE + rate, rr["year"])
            pv_flows += rr["fcf"] * df
            table.append(
                [
                    fmt(rr["year"], "number"),
                    fmt(rr["fcf"], "money"),
                    fmt(df, "number"),
                    fmt(rr["fcf"] * df, "money"),
                ]
            )
        last_t = rows[-1]["year"]
        if x.choice("terminal") == "growth":
            g = x.rate("g")
            if rate <= g:
                raise CalcError(
                    "The discount rate must be above the terminal growth.", "g", code="no_solution"
                )
            tv = rows[-1]["fcf"] * (ONE + g) / (rate - g)
        else:
            tv = x.num("multiple", above=ZERO) * x.num("metric", above=ZERO)
        pv_tv = tv / pw(ONE + rate, last_t)
        ev = pv_flows + pv_tv
        r = Result(value("ev", "Enterprise value" if firm else "Equity value", ev, "money"))
        r.add("pv_flows", "Present value of the forecast cash flows", pv_flows, "money")
        r.add("tv", "Terminal value at the last year", tv, "money")
        r.add("pv_tv", "…its present value", pv_tv, "money")
        r.add(
            "tv_share", "Terminal value's share of the total", pv_tv / ev * HUNDRED if ev else ZERO, "percent"
        )
        equity = ev - x.num("net_debt", default=ZERO) if firm else ev
        if firm:
            r.add("equity", "Equity value (EV − net debt)", equity, "money")
        shares = x.opt("shares")
        if shares is not None and shares > 0:
            per = equity / shares
            r.add("per_share", "Value per share", per, "money")
            price = x.opt("price")
            if price is not None and price > 0:
                r.add("mos", "Margin of safety against the price", (per - price) / per * HUNDRED, "percent")
        r.tables.append(
            TableOut(
                "pv",
                "Discounted cash flows",
                [
                    {"key": "year", "label": "Year", "unit": "number"},
                    {"key": "fcf", "label": "Free cash flow", "unit": "money"},
                    {"key": "df", "label": "Discount factor", "unit": "number"},
                    {"key": "pv", "label": "Present value", "unit": "money"},
                ],
                table,
            )
        )
        r.steps = [
            "Value = Σ FCFₜ / (1 + r)^t + TV / (1 + r)^N",
            "TV by growth = FCF_N (1 + g) / (r − g); by multiple = multiple × the metric at year N",
        ]
    return r


register(
    Calculator(
        key="dcf",
        family="equity",
        title="DCF valuation",
        description="Forecast free cash flows, a terminal value by growth or by an exit multiple, discounted "
        "at WACC (FCFF, giving enterprise value) or the cost of equity (FCFE, giving equity value).",
        keywords="dcf discounted cash flow fcff fcfe enterprise value terminal value exit multiple intrinsic",
        fields=[
            Field(
                "basis",
                "Cash flows are",
                "choice",
                "fcff",
                options=(
                    ("fcff", "To the firm (FCFF), discount at WACC"),
                    ("fcfe", "To equity (FCFE), at Ke"),
                ),
            ),
            Field(
                "fcf",
                "Forecast free cash flows",
                "table",
                columns=FLOWS,
                rows=[
                    {"year": "1", "fcf": "1200"},
                    {"year": "2", "fcf": "1380"},
                    {"year": "3", "fcf": "1560"},
                    {"year": "4", "fcf": "1720"},
                    {"year": "5", "fcf": "1850"},
                ],
            ),
            Field("rate", "Discount rate (%)", "percent", "11"),
            Field(
                "terminal",
                "Terminal value by",
                "choice",
                "growth",
                options=(("growth", "Perpetual growth"), ("multiple", "Exit multiple")),
            ),
            Field("g", "Terminal growth (%)", "percent", "5", show_when={"terminal": ["growth"]}),
            Field("multiple", "Exit multiple", "number", "12", show_when={"terminal": ["multiple"]}),
            Field(
                "metric",
                "…applied to (EBITDA in the last year)",
                "money",
                "2600",
                show_when={"terminal": ["multiple"]},
            ),
            Field("net_debt", "Net debt (debt − cash)", "money", "3000", show_when={"basis": ["fcff"]}),
            Field("shares", "Shares outstanding", "number", "100", optional=True),
            Field("price", "Market price per share", "money", "", optional=True),
        ],
        run=_dcf,
    )
)


# ------------------------------------------------------------------------------------------- WACC


def _wacc(x: Inputs) -> Result:
    e = x.num("equity", min_=ZERO)
    d = x.num("debt", min_=ZERO)
    p = x.num("preferred", default=ZERO, min_=ZERO)
    tax = x.rate("tax")
    kd = x.rate("kd")
    with localcontext(ctx()):
        ke = x.rate("rf") + x.num("beta") * x.rate("mrp") if x.choice("ke_by") == "capm" else x.rate("ke")
        kp = x.rate("kp", default=ZERO)
        v = e + d + p
        if v <= 0:
            raise CalcError("Give the values of equity and debt.", "equity")
        wacc = e / v * ke + d / v * kd * (ONE - tax) + p / v * kp
        r = Result(value("wacc", "WACC", wacc * HUNDRED, "percent"))
        r.add("ke", "Cost of equity", ke * HUNDRED, "percent")
        r.add("kd_after", "Cost of debt after tax", kd * (ONE - tax) * HUNDRED, "percent")
        r.add("we", "Weight of equity", e / v * HUNDRED, "percent")
        r.add("wd", "Weight of debt", d / v * HUNDRED, "percent")
        if p:
            r.add("wp", "Weight of preference capital", p / v * HUNDRED, "percent")
        r.steps = ["WACC = E/V·Ke + D/V·Kd(1 − t) + P/V·Kp", "Ke by CAPM = Rf + β × market risk premium"]
    return r


register(
    Calculator(
        key="wacc",
        family="equity",
        title="Cost of capital (WACC)",
        description="Weighted average cost of capital from market values, with the cost of equity from CAPM "
        "or given, and the after-tax cost of debt.",
        keywords="wacc weighted average cost of capital cost of equity cost of debt capm beta tax shield",
        fields=[
            Field("equity", "Market value of equity", "money", "6000"),
            Field("debt", "Market value of debt", "money", "4000"),
            Field("preferred", "Preference capital", "money", "0", optional=True),
            Field(
                "ke_by",
                "Cost of equity",
                "choice",
                "capm",
                options=(("capm", "From CAPM"), ("given", "I know it")),
            ),
            Field(
                "rf",
                "Risk-free rate (%)",
                "percent",
                "7",
                show_when={"ke_by": ["capm"]},
                default_from="risk_free",
            ),
            Field("beta", "Beta", "number", "1.1", show_when={"ke_by": ["capm"]}),
            Field("mrp", "Market risk premium (%)", "percent", "6", show_when={"ke_by": ["capm"]}),
            Field("ke", "Cost of equity (%)", "percent", "13.6", show_when={"ke_by": ["given"]}),
            Field("kd", "Cost of debt before tax (%)", "percent", "9"),
            Field("tax", "Tax rate (%)", "percent", "25.17"),
            Field("kp", "Cost of preference capital (%)", "percent", "", optional=True),
        ],
        run=_wacc,
    )
)


# ------------------------------------------------------------------------------------------- DuPont


def _dupont(x: Inputs) -> Result:
    ni = x.num("net_income")
    sales = x.num("sales", above=ZERO)
    assets = x.num("assets", above=ZERO)
    equity = x.num("equity", above=ZERO)
    with localcontext(ctx()):
        r = Result(value("roe", "Return on equity", ni / equity * HUNDRED, "percent"))
        r.add("margin", "Net profit margin (NI / sales)", ni / sales * HUNDRED, "percent")
        r.add("turnover", "Asset turnover (sales / assets)", sales / assets, "ratio")
        r.add("leverage", "Equity multiplier (assets / equity)", assets / equity, "ratio")
        r.add("roa", "Return on assets", ni / assets * HUNDRED, "percent")
        ebt, ebit = x.opt("ebt"), x.opt("ebit")
        if ebt and ebit:
            r.add("tax_burden", "Tax burden (NI / EBT)", ni / ebt, "ratio")
            r.add("interest_burden", "Interest burden (EBT / EBIT)", ebt / ebit, "ratio")
            r.add("ebit_margin", "EBIT margin (EBIT / sales)", ebit / sales * HUNDRED, "percent")
        r.steps = [
            "ROE = margin × turnover × equity multiplier",
            "Five-step: ROE = (NI/EBT)(EBT/EBIT)(EBIT/sales)(sales/assets)(assets/equity)",
        ]
    return r


register(
    Calculator(
        key="dupont",
        family="equity",
        title="DuPont analysis (ROE)",
        description="Return on equity split into margin, asset turnover and leverage, and into five steps "
        "when EBT and EBIT are given.",
        keywords="dupont roe return on equity margin asset turnover leverage equity multiplier roa",
        fields=[
            Field("net_income", "Net income", "money", "1200"),
            Field("sales", "Sales", "money", "15000"),
            Field("assets", "Total assets (average)", "money", "12000"),
            Field("equity", "Shareholders' equity (average)", "money", "6000"),
            Field("ebt", "Profit before tax (for five steps)", "money", "1600", optional=True),
            Field("ebit", "EBIT (for five steps)", "money", "2000", optional=True),
        ],
        run=_dupont,
    )
)


# ------------------------------------------------------------------------------------------- multiples


def _multiples(x: Inputs) -> Result:
    roe = x.rate("roe")
    payout = x.rate("payout")
    r_req = x.rate("r")
    with localcontext(ctx()):
        g = (ONE - payout) * roe
        if r_req <= g:
            raise CalcError(
                "The required return must be above the sustainable growth (retention × ROE).",
                "r",
                code="no_solution",
            )
        res = Result(value("g", "Sustainable growth (retention × ROE)", g * HUNDRED, "percent"))
        res.add("pe_lead", "Justified forward P/E: payout / (r − g)", payout / (r_req - g), "ratio")
        trailing = payout * (ONE + g) / (r_req - g)
        res.add("pe_trail", "Justified trailing P/E: payout (1 + g) / (r − g)", trailing, "ratio")
        res.add("pb", "Justified P/B: (ROE − g) / (r − g)", (roe - g) / (r_req - g), "ratio")
        eps, price = x.opt("eps"), x.opt("price")
        if eps is not None and price is not None and eps > 0 and price > 0:
            res.add("pe_now", "P/E at the market price", price / eps, "ratio")
            res.add("ey", "Earnings yield", eps / price * HUNDRED, "percent")
            res.add("pvgo", "PVGO at the price (P − E / r)", price - eps / r_req, "money")
        ev, ebitda = x.opt("ev"), x.opt("ebitda")
        if ev is not None and ebitda:
            res.add("ev_ebitda", "EV / EBITDA", ev / ebitda, "ratio")
        res.steps = ["g = b × ROE;  forward P/E = (1 − b) / (r − g);  P/B = (ROE − g) / (r − g)"]
    return res


register(
    Calculator(
        key="multiples",
        family="equity",
        title="Justified P/E, P/B and growth",
        description="Sustainable growth from ROE and retention, the P/E and P/B a share justifies, and PVGO "
        "and earnings yield at a market price.",
        keywords="justified pe pb price to earnings price to book sustainable growth retention roe pvgo "
        "earnings yield ev ebitda multiples",
        fields=[
            Field("roe", "ROE (%)", "percent", "16"),
            Field("payout", "Dividend payout (%)", "percent", "40"),
            Field("r", "Required return (%)", "percent", "12"),
            Field("eps", "EPS (optional)", "money", "", optional=True),
            Field("price", "Market price (optional)", "money", "", optional=True),
            Field("ev", "Enterprise value (optional)", "money", "", optional=True),
            Field("ebitda", "EBITDA (optional)", "money", "", optional=True),
        ],
        run=_multiples,
    )
)
