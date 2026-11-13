"""Utilities (decision #120, family N): dates (BA II Plus DATE worksheet) and percentages."""

from __future__ import annotations

import calendar
import datetime as dt
from decimal import Decimal, localcontext

from .core import HUNDRED, CalcError, Calculator, Field, Inputs, Result, ctx, register, value

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def add_months(d: dt.date, months: int) -> dt.date:
    """Same day of the month, or the month's last day when it is shorter (31 Jan + 1 month = 28/29 Feb)."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    if not 1 <= year <= 9999:
        raise CalcError("The date is out of range.", "months")
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _last_feb(d: dt.date) -> bool:
    return d.month == 2 and d.day == calendar.monthrange(d.year, 2)[1]


def days_30_360_us(a: dt.date, b: dt.date) -> int:
    """30/360 US (NASD), as the BA II Plus and Excel DAYS360(..., FALSE)."""
    d1, d2 = a.day, b.day
    if _last_feb(a) and _last_feb(b):
        d2 = 30
    if _last_feb(a):
        d1 = 30
    if d2 == 31 and d1 >= 30:
        d2 = 30
    if d1 == 31:
        d1 = 30
    return (b.year - a.year) * 360 + (b.month - a.month) * 30 + (d2 - d1)


def days_30e_360(a: dt.date, b: dt.date) -> int:
    """30E/360 (European), as Excel DAYS360(..., TRUE)."""
    d1, d2 = min(a.day, 30), min(b.day, 30)
    return (b.year - a.year) * 360 + (b.month - a.month) * 30 + (d2 - d1)


def _dates(x: Inputs) -> Result:
    mode = x.choice("mode")
    start = x.date("start")
    if mode == "between":
        end = x.date("end")
        days = (end - start).days
        r = Result(value("days", "Days between (actual)", Decimal(days), "days"))
        lo, hi = (start, end) if start <= end else (end, start)
        months = (hi.year - lo.year) * 12 + hi.month - lo.month
        if hi.day < lo.day and add_months(lo, months) > hi:
            months -= 1
        rest = (hi - add_months(lo, months)).days
        y, m = divmod(months, 12)
        r.add("ymd", "Years, months and days", f"{y} years, {m} months, {rest} days", "text")
        with localcontext(ctx()):
            r.add("weeks", "Weeks", Decimal(days) / 7, "number")
            r.add("years365", "Years (Actual/365)", Decimal(days) / 365, "years")
        r.add("d360", "Days on 30/360 (US)", Decimal(days_30_360_us(start, end)), "days")
        r.add("d360e", "Days on 30E/360 (European)", Decimal(days_30e_360(start, end)), "days")
        r.add("start_day", "Start falls on", WEEKDAYS[start.weekday()], "text")
        r.add("end_day", "End falls on", WEEKDAYS[end.weekday()], "text")
        return r
    days = x.int_("days", default=0, min_=-3_650_000, max_=3_650_000)
    months = x.int_("months", default=0, min_=-120_000, max_=120_000)
    try:
        out = add_months(start, months) + dt.timedelta(days=days)
    except OverflowError:
        raise CalcError("The date is out of range.", "days") from None
    r = Result(value("date", "Date", Decimal(0), "date"))
    r.answer.value = r.answer.exact = out.isoformat()
    r.add("weekday", "Falls on", WEEKDAYS[out.weekday()], "text")
    r.add("actual", "Actual days from the start", Decimal((out - start).days), "days")
    return r


register(
    Calculator(
        key="dates",
        family="utils",
        title="Days between dates",
        description="Actual days, years-months-days and 30/360 day counts between two dates, or a date some "
        "months and days away (31 Jan + 1 month is the end of February).",
        keywords="date days between 30/360 day count calendar add months maturity",
        fields=[
            Field(
                "mode",
                "Find",
                "choice",
                "between",
                options=(("between", "Days between two dates"), ("add", "A date after some time")),
            ),
            Field("start", "Start date", "date", ""),
            Field("end", "End date", "date", "", show_when={"mode": ["between"]}),
            Field("months", "Months to add (negative to go back)", "int", "0", show_when={"mode": ["add"]}),
            Field("days", "Days to add (negative to go back)", "int", "0", show_when={"mode": ["add"]}),
        ],
        run=_dates,
    )
)


PCT_MODES = (
    ("change", "Change from A to B"),
    ("of", "A% of B"),
    ("share", "A is what % of B"),
    ("markup", "Cost and price: markup and margin"),
    ("add_tax", "Add tax (GST) to an amount"),
    ("remove_tax", "Take tax out of an amount that includes it"),
)


def _percent(x: Inputs) -> Result:
    mode = x.choice("mode")
    a = x.num("a")
    b = x.num("b")
    with localcontext(ctx()):
        if mode == "change":
            if a == 0:
                raise CalcError("A cannot be zero for a percentage change.", "a")
            r = Result(value("pct", "Change", (b - a) / abs(a) * HUNDRED, "percent"))
            r.add("diff", "Difference (B − A)", b - a, "money")
            r.add("times", "B is this many times A", b / a, "ratio")
        elif mode == "of":
            r = Result(value("v", "A% of B", a * b / HUNDRED, "money"))
        elif mode == "share":
            if b == 0:
                raise CalcError("B cannot be zero.", "b")
            r = Result(value("pct", "A as a percentage of B", a / b * HUNDRED, "percent"))
        elif mode == "markup":
            if a <= 0 or b == 0:
                raise CalcError("Give a cost above zero and a price.", "a")
            r = Result(value("profit", "Profit (price − cost)", b - a, "money"))
            r.add("markup", "Markup on cost", (b - a) / a * HUNDRED, "percent")
            r.add("margin", "Margin on price", (b - a) / b * HUNDRED, "percent")
        elif mode == "add_tax":
            r = Result(value("total", "Amount with tax", a * (HUNDRED + b) / HUNDRED, "money"))
            r.add("tax", "Tax", a * b / HUNDRED, "money")
        else:
            if b <= -100:
                raise CalcError("The rate must be above −100%.", "b")
            base = a * HUNDRED / (HUNDRED + b)
            r = Result(value("base", "Amount before tax", base, "money"))
            r.add("tax", "Tax included", a - base, "money")
    return r


register(
    Calculator(
        key="percent",
        family="utils",
        title="Percentages, markup and GST",
        description="Percentage change, a percentage of a number, markup on cost against margin on price, "
        "and tax added to or taken out of an amount.",
        keywords="percent percentage change markup margin gst tax inclusive exclusive",
        fields=[
            Field("mode", "Find", "choice", "change", options=PCT_MODES),
            Field("a", "A (or cost, or amount)", "number", "100"),
            Field("b", "B (or price, or tax rate %)", "number", "118"),
        ],
        run=_percent,
    )
)
