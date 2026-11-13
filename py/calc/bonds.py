"""Bonds and fixed income (decision #120, family J), as Excel's PRICE, YIELD, ACCRINT, DURATION and MDURATION
work them out from settlement and maturity dates, with every day-count basis: clean and dirty price, accrued
interest, yield to maturity and to call, current yield, Macaulay and modified duration, convexity, PVBP and
the price change for a yield change; zero-coupon bonds; spot rates bootstrapped from par yields, and forward
rates."""

from __future__ import annotations

import calendar
import datetime as dt
from dataclasses import dataclass
from decimal import Decimal, localcontext

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
    solve,
    value,
)
from .utils import add_months, days_30_360_us, days_30e_360

BASES = (
    ("0", "30/360 US (Excel basis 0)"),
    ("1", "Actual/actual (basis 1)"),
    ("2", "Actual/360 (basis 2)"),
    ("3", "Actual/365 (basis 3, Indian bonds)"),
    ("4", "30/360 European (basis 4)"),
)
FREQS = (("2", "Half-yearly (2)"), ("1", "Yearly (1)"), ("4", "Quarterly (4)"), ("12", "Monthly (12)"))


def _eom(d: dt.date) -> bool:
    return d.day == calendar.monthrange(d.year, d.month)[1]


def coupon_dates(settle: dt.date, maturity: dt.date, f: int) -> tuple[dt.date, dt.date, int]:
    """Previous and next coupon dates around settlement, and the number of coupons left (Excel COUPPCD,
    COUPNCD, COUPNUM). Dates step back from maturity; a month-end maturity keeps coupons at month ends."""
    if settle >= maturity:
        raise CalcError("Settlement must be before maturity.", "settlement")
    step = 12 // f
    k, nxt = 0, maturity
    while True:
        prev = add_months(maturity, -step * (k + 1))
        if _eom(maturity):
            prev = prev.replace(day=calendar.monthrange(prev.year, prev.month)[1])
        if prev <= settle:
            return prev, nxt, k + 1
        k += 1
        nxt = prev


@dataclass
class Bond:
    settle: dt.date
    maturity: dt.date
    rate: Decimal  # coupon rate, a fraction
    redemption: Decimal  # per 100 of face
    f: int
    basis: str

    def frame(self) -> tuple[int, Decimal, Decimal, Decimal]:
        """(N coupons left, A days accrued, DSC days to the next coupon, E days in the period), as Excel."""
        pcd, ncd, n = coupon_dates(self.settle, self.maturity, self.f)
        b = self.basis
        if b == "0":
            e = Decimal(360) / self.f
            a = Decimal(days_30_360_us(pcd, self.settle))
            dsc = e - a
        elif b == "4":
            e = Decimal(360) / self.f
            a = Decimal(days_30e_360(pcd, self.settle))
            dsc = Decimal(days_30e_360(self.settle, ncd))
        else:
            e = Decimal((ncd - pcd).days) if b == "1" else Decimal(360 if b == "2" else 365) / self.f
            a = Decimal((self.settle - pcd).days)
            dsc = Decimal((ncd - self.settle).days)
        return n, a, dsc, e

    def price(self, y: Decimal) -> Decimal:
        """Clean price per 100 (Excel PRICE)."""
        n, a, dsc, e = self.frame()
        cpn = HUNDRED * self.rate / self.f
        with localcontext(ctx()):
            if n == 1:
                dsr = e - a
                t = dsr / e
                return (self.redemption + cpn) / (ONE + t * y / self.f) - cpn * a / e
            v = ONE + y / self.f
            frac = dsc / e
            pv = self.redemption / pw(v, Decimal(n - 1) + frac)
            pv += sum((cpn / pw(v, Decimal(k - 1) + frac) for k in range(1, n + 1)), ZERO)
            return pv - cpn * a / e

    def accrued(self) -> Decimal:
        n, a, dsc, e = self.frame()
        del n, dsc
        with localcontext(ctx()):
            return HUNDRED * self.rate / self.f * a / e

    def yield_from(self, clean: Decimal) -> Decimal:
        """Excel YIELD: closed form with one coupon left, else the rate whose PRICE is the price."""
        n, a, _, e = self.frame()
        cpn = HUNDRED * self.rate / self.f
        with localcontext(ctx()):
            if n == 1:
                dsr = e - a
                num = (self.redemption / HUNDRED + self.rate / self.f) - (
                    clean / HUNDRED + a / e * self.rate / self.f
                )
                return num / (clean / HUNDRED + a / e * self.rate / self.f) * self.f * e / dsr
            del cpn
            return solve(lambda q: self.price(q) - clean, Decimal("-0.99") * self.f, Decimal(10), self.rate
                         + ONE / 100, what="the yield")  # fmt: skip

    def measures(self, y: Decimal) -> tuple[Decimal, Decimal, Decimal]:
        """(Macaulay duration in years, modified duration, convexity in years²) on the dirty price."""
        n, _, dsc, e = self.frame()
        cpn = HUNDRED * self.rate / self.f
        with localcontext(ctx()):
            v = ONE + y / self.f
            frac = dsc / e
            pvs, wt, conv = ZERO, ZERO, ZERO
            for k in range(1, n + 1):
                cf = cpn + (self.redemption if k == n else ZERO)
                periods = Decimal(k - 1) + frac
                pv = cf / pw(v, periods)
                t = periods / self.f
                pvs += pv
                wt += t * pv
                conv += pv * periods * (periods + 1)
            mac = wt / pvs
            return mac, mac / v, conv / (pvs * v * v * self.f * self.f)


def _bond(x: Inputs) -> Result:
    b = Bond(
        settle=x.date("settlement"),
        maturity=x.date("maturity"),
        rate=x.rate("coupon"),
        redemption=x.num("redemption", default=HUNDRED, above=ZERO),
        f=int(x.choice("frequency")),
        basis=x.choice("basis"),
    )
    face = x.num("face", default=HUNDRED, above=ZERO)
    scale = face / HUNDRED
    with localcontext(ctx()):
        if x.choice("solve") == "price":
            y = x.rate("ytm")
            clean = b.price(y)
            r = Result(value("price", "Clean price per 100", clean, "number"))
            r.add("ytm", "Yield to maturity", y * HUNDRED, "percent")
        else:
            clean = x.num("price", above=ZERO)
            y = b.yield_from(clean)
            r = Result(value("ytm", "Yield to maturity (YIELD)", y * HUNDRED, "percent"))
            r.add("price", "Clean price per 100", clean, "number")
        acc = b.accrued()
        mac, mod, conv = b.measures(y)
        dirty = clean + acc
        r.add("accrued", "Accrued interest per 100", acc, "number")
        r.add("dirty", "Dirty (invoice) price per 100", dirty, "number")
        r.add("invoice", f"Invoice amount for face {fmt(face, 'money')}", dirty * scale, "money")
        r.add(
            "current", "Current yield (coupon ÷ clean price)", b.rate * HUNDRED / clean * HUNDRED, "percent"
        )
        r.add("mac", "Macaulay duration (DURATION), years", mac, "years")
        r.add("mod", "Modified duration (MDURATION)", mod, "number")
        r.add("conv", "Convexity", conv, "number")
        r.add("pvbp", "Price value of a basis point, per 100", mod * dirty / 10_000, "number")
        n, *_ = b.frame()
        r.add("coupons", "Coupons left", Decimal(n), "count")
        shift = x.opt("shift_bp")
        if shift is not None:
            dy = shift / 10_000
            est = (-mod * dy + conv * dy * dy / 2) * HUNDRED
            exact_new = b.price(y + dy) + b.accrued()
            r.add(
                "est",
                f"Price change for {fmt(shift, 'number')} bp: duration + convexity estimate",
                est,
                "percent",
            )
            r.add("exact", "…by repricing", (exact_new / dirty - ONE) * HUNDRED, "percent")
        call_date = x.date("call_date") if x.has("call_date") else None
        if call_date is not None:
            if not b.settle < call_date < b.maturity:
                raise CalcError("The call date must fall between settlement and maturity.", "call_date")
            called = Bond(
                b.settle, call_date, b.rate, x.num("call_price", default=HUNDRED, above=ZERO), b.f, b.basis
            )
            ytc = called.yield_from(clean)
            r.add("ytc", "Yield to call", ytc * HUNDRED, "percent")
            r.add("ytw", "Yield to worst", min(ytc, y) * HUNDRED, "percent")
        r.steps = [
            "Price = redemption/(1+y/f)^(N−1+DSC/E) + Σ coupon/(1+y/f)^(k−1+DSC/E) − coupon × A/E (Excel "
            "PRICE)",
            "Accrued = coupon × A/E;  dirty = clean + accrued",
            "Macaulay = Σ t·PV / Σ PV;  modified = Macaulay / (1 + y/f)",
            "ΔP/P ≈ −modified × Δy + ½ × convexity × Δy²",
        ]
    return r


register(Calculator(
    key="bond",
    family="bonds",
    title="Bond price, yield and duration",
    description="From settlement and maturity dates, as Excel's PRICE, YIELD, DURATION and MDURATION: "
    "clean and "
                "dirty price, accrued interest, yield to maturity, to call and to worst, current yield, "
                "durations, convexity, PVBP and the price change for a move in yield.",
    keywords="bond price yield ytm ytc yield to call worst duration modified macaulay convexity pvbp dv01 "
    "accrued "
             "interest clean dirty g-sec ncd debenture coupon",
    fields=[
        Field("solve", "Find", "solve", "price", options=(("price", "Price"), ("ytm", "Yield"))),
        Field("settlement", "Settlement date", "date", "2008-02-15"),
        Field("maturity", "Maturity date", "date", "2017-11-15"),
        Field("coupon", "Coupon rate (%)", "percent", "5.75"),
        Field("ytm", "Yield to maturity (%)", "percent", "6.5"),
        Field("price", "Clean price per 100", "number", "94.634361"),
        Field("redemption", "Redemption per 100", "number", "100", optional=True),
        Field("frequency", "Coupons a year", "choice", "2", options=FREQS),
        Field("basis", "Day count", "choice", "0", options=BASES),
        Field("face", "Face value held", "money", "100000", optional=True),
        Field("shift_bp", "Yield change to test (basis points)", "number", "100", optional=True),
        Field("call_date", "Call date (optional)", "date", "", optional=True),
        Field("call_price", "Call price per 100", "number", "100", optional=True),
    ],
    run=_bond,
))  # fmt: skip


# ------------------------------------------------------------------------------------------- zero coupon


def _zero(x: Inputs) -> Result:
    face = x.num("face", above=ZERO)
    years = x.num("years", above=ZERO)
    m = Decimal(x.choice("compounding"))
    with localcontext(ctx()):
        if x.choice("solve") == "price":
            y = x.rate("yield")
            price = face / pw(ONE + y / m, m * years)
            r = Result(value("price", "Price", price, "money"))
        else:
            price = x.num("price", above=ZERO)
            y = m * (pw(face / price, ONE / (m * years)) - ONE)
            r = Result(value("yield", "Yield", y * HUNDRED, "percent"))
        r.add("discount", "Discount (face − price)", face - price, "money")
        r.add("mac", "Macaulay duration (years) — the maturity", years, "years")
        r.add("mod", "Modified duration", years / (ONE + y / m), "number")
        r.steps = ["Price = face / (1 + y/m)^(m × years)"]
    return r


register(Calculator(
    key="zero",
    family="bonds",
    title="Zero-coupon bond",
    description="Price from yield or yield from price for a bond that pays only at maturity, with its "
                "duration.",
    keywords="zero coupon bond strips deep discount price yield",
    fields=[
        Field("solve", "Find", "choice", "price", options=(("price", "Price"), ("yield", "Yield"))),
        Field("face", "Face value", "money", "100000"),
        Field("years", "Years to maturity", "number", "5"),
        Field("yield", "Yield (%)", "percent", "7.2", show_when={"solve": ["price"]}),
        Field("price", "Price", "money", "70000", show_when={"solve": ["yield"]}),
        Field("compounding", "Yield compounded", "choice", "2", options=(("1", "Yearly"), ("2",
        "Half-yearly"))),
    ],
    run=_zero,
))  # fmt: skip


# ------------------------------------------------------------------------------------------- spot and forward

CURVE = (Column("year", "Year"), Column("rate", "Rate %", "percent"))


def _curve(x: Inputs) -> Result:
    rows = sorted(x.table("curve", min_rows=1), key=lambda rr: rr["year"])
    years = [rr["year"] for rr in rows]
    if years != [Decimal(i) for i in range(1, len(rows) + 1)]:
        raise CalcError("Give one rate for each year: 1, 2, 3 … with no gaps.", "curve")
    given = x.choice("given")
    with localcontext(ctx()):
        if given == "par":
            spots: list[Decimal] = []
            for i, rr in enumerate(rows):
                c = rr["rate"]
                pv_coupons = sum((c / pw(ONE + s, k + 1) for k, s in enumerate(spots)), ZERO)
                spots.append(pw((ONE + c) / (ONE - pv_coupons), ONE / Decimal(i + 1)) - ONE)
            pars = [rr["rate"] for rr in rows]
        else:
            spots = [rr["rate"] for rr in rows]
            pars = []
            for n in range(1, len(spots) + 1):
                dfs = [ONE / pw(ONE + s, k + 1) for k, s in enumerate(spots[:n])]
                pars.append((ONE - dfs[-1]) / sum(dfs, ZERO))
        fwd = [spots[0]] + [
            pw(ONE + spots[n], n + 1) / pw(ONE + spots[n - 1], n) - ONE for n in range(1, len(spots))
        ]
        r = Result(value("spot_last", f"Spot rate, year {len(spots)}", spots[-1] * HUNDRED, "percent"))
        a, b = x.opt("from_year"), x.opt("to_year")
        if a is not None and b is not None:
            ai, bi = int(a), int(b)
            if not 0 <= ai < bi <= len(spots):
                raise CalcError(f"Choose years with 0 ≤ from < to ≤ {len(spots)}.", "from_year")
            grow_b = pw(ONE + spots[bi - 1], bi)
            grow_a = pw(ONE + spots[ai - 1], ai) if ai else ONE
            r.add("fwd_ab", f"Forward rate from year {ai} to {bi} (a year)",
                  (pw(grow_b / grow_a, ONE / Decimal(bi - ai)) - ONE) * HUNDRED, "percent")  # fmt: skip
        r.tables.append(TableOut("curve", "The curve", [
            {"key": "year", "label": "Year", "unit": "count"},
            {"key": "par", "label": "Par yield", "unit": "percent"},
            {"key": "spot", "label": "Spot (zero) rate", "unit": "percent"},
            {"key": "fwd", "label": "One-year forward starting the year before", "unit": "percent"},
            {"key": "df", "label": "Discount factor", "unit": "number"},
        ], [[str(i + 1), fmt(pars[i] * HUNDRED, "percent"), fmt(s * HUNDRED, "percent"), fmt(fwd[i] * HUNDRED,
             "percent"), fmt(ONE / pw(ONE + s, i + 1), "number")] for i, s in enumerate(spots)]))  # fmt: skip
        r.chart = Chart("line", "Yield curve", "Year", "percent", [str(i + 1) for i in range(len(spots))], [
            {"name": "Spot", "values": [fmt(s * HUNDRED, "percent") for s in spots]},
            {"name": "Forward", "values": [fmt(f * HUNDRED, "percent") for f in fwd]},
        ])  # fmt: skip
        r.steps = [
            "Bootstrapping: 100 = c·100 Σ 1/(1+sₖ)^k + 100/(1+sₙ)^n, solved year by year for sₙ",
            "Forward from a to b: [(1+s_b)^b / (1+s_a)^a]^(1/(b−a)) − 1",
        ]
    return r


register(Calculator(
    key="curve",
    family="bonds",
    title="Spot and forward rates",
    description="Bootstrap spot (zero) rates from yearly par yields, or par yields from spot rates, with the "
                "implied forward rates and discount factors.",
    keywords="spot rate zero rate bootstrapping par yield forward rate yield curve term structure "
    "discount factor",
    fields=[
        Field("given", "I have", "choice", "par", options=(("par", "Par yields"), ("spot", "Spot rates"))),
        Field("curve", "Rates by year", "table", columns=CURVE, rows=[
            {"year": "1", "rate": "6.5"}, {"year": "2", "rate": "6.8"}, {"year": "3", "rate": "7.0"},
            {"year": "4", "rate": "7.1"}, {"year": "5", "rate": "7.2"},
        ]),
        Field("from_year", "Forward from year", "int", "2", optional=True),
        Field("to_year", "…to year", "int", "5", optional=True),
    ],
    run=_curve,
))  # fmt: skip
