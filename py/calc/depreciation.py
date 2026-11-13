"""Depreciation (decision #120, family N), year by year, as Excel works it: SLN, SYD, DDB (any factor), the
written-down value method (a fixed rate, given or worked out from the salvage value, as the Companies Act and
the Income-tax Act use), and units of production. A calculator only: posting depreciation stays a parked
idea."""

from __future__ import annotations

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
    value,
)

METHODS = (
    ("sln", "Straight line (SLN)"),
    ("wdv", "Written-down value (fixed rate)"),
    ("ddb", "Declining balance (DDB, factor)"),
    ("syd", "Sum-of-years' digits (SYD)"),
    ("units", "Units of production"),
)


def _charges(x: Inputs, method: str, cost: Decimal, salvage: Decimal) -> tuple[list[Decimal], str]:
    """Each year's depreciation by the method, and a note on a rate worked out."""
    with localcontext(ctx()):
        charges: list[Decimal] = []
        note = ""
        if method == "units":
            unit_rows = x.table("units", min_rows=1)
            total = x.num("total_units", above=ZERO)
            used = sum((rr["u"] for rr in unit_rows), ZERO)
            if used > total:
                raise CalcError("The units used add up to more than the total the asset makes.", "units")
            charges = [(cost - salvage) * rr["u"] / total for rr in unit_rows]
        else:
            life = x.int_("life", min_=1, max_=100)
            if method == "sln":
                charges = [(cost - salvage) / life] * life
            elif method == "syd":
                s = Decimal(life * (life + 1)) / 2
                charges = [(cost - salvage) * (life - k) / s for k in range(life)]
            elif method == "ddb":
                factor = x.num("factor", default=Decimal(2), above=ZERO)
                book = cost
                for _ in range(life):
                    d = min(book * factor / life, max(book - salvage, ZERO))
                    charges.append(d)
                    book -= d
            else:
                given = x.opt("wdv_rate")
                if given is not None:
                    rate = given / HUNDRED
                else:
                    if salvage <= 0:
                        raise CalcError("Give a salvage value above zero, or the rate.", "salvage")
                    rate = ONE - pw(salvage / cost, ONE / Decimal(life))
                    pct = fmt(rate * HUNDRED, "percent")
                    note = f"Rate from the salvage value: 1 − (salvage / cost)^(1/life) = {pct}%"
                book = cost
                for _ in range(life):
                    d = book * rate
                    charges.append(d)
                    book -= d
    return charges, note


def _dep(x: Inputs) -> Result:
    cost = x.num("cost", above=ZERO)
    salvage = x.num("salvage", default=ZERO, min_=ZERO)
    if salvage >= cost:
        raise CalcError("The salvage value must be less than the cost.", "salvage")
    method = x.choice("method")
    with localcontext(ctx()):
        charges, note = _charges(x, method, cost, salvage)
        r = Result(value("first", "Depreciation in year 1", charges[0], "money"))
        rows_out, book, acc = [], cost, ZERO
        for y, d in enumerate(charges, start=1):
            acc += d
            book -= d
            rows_out.append([str(y), fmt(d, "money"), fmt(acc, "money"), fmt(book, "money")])
        r.add("total", "Total depreciation", acc, "money")
        r.add("book", "Book value at the end", book, "money")
        if note:
            r.steps.append(note)
        r.steps.append(
            {
                "sln": "SLN = (cost − salvage) / life",
                "syd": "SYD year y = (cost − salvage) × (life − y + 1) / (life(life + 1)/2)",
                "ddb": "DDB = min(book value × factor / life, book value − salvage) (Excel DDB)",
                "wdv": "WDV = book value at the start of the year × rate",
                "units": "Units of production = (cost − salvage) × units this year / total units",
            }[method]
        )
        r.tables.append(
            TableOut(
                "years",
                "Year by year",
                [
                    {"key": "year", "label": "Year", "unit": "count"},
                    {"key": "dep", "label": "Depreciation", "unit": "money"},
                    {"key": "acc", "label": "Accumulated", "unit": "money"},
                    {"key": "book", "label": "Book value", "unit": "money"},
                ],
                rows_out,
            )
        )
        r.chart = Chart(
            "bar",
            "Depreciation each year",
            "Year",
            "money",
            [row[0] for row in rows_out],
            [{"name": "Depreciation", "values": [fmt(d, "money") for d in charges]}],
        )
    return r


register(
    Calculator(
        key="depreciation",
        family="utils",
        title="Depreciation schedule",
        description="Year-by-year depreciation and book value by straight line, written-down value, "
        "declining "
        "balance, sum-of-years' digits or units of production, as Excel's SLN, DDB and SYD work them out.",
        keywords="depreciation sln straight line wdv written down value ddb declining balance syd units of "
        "production book value companies act",
        fields=[
            Field("method", "Method", "choice", "sln", options=METHODS),
            Field("cost", "Cost", "money", "30000"),
            Field("salvage", "Salvage value", "money", "7500"),
            Field(
                "life", "Useful life (years)", "int", "10", show_when={"method": ["sln", "wdv", "ddb", "syd"]}
            ),
            Field("factor", "Factor (2 for double declining)", "number", "2", show_when={"method": ["ddb"]}),
            Field(
                "wdv_rate",
                "Rate (%), blank to work it out from the salvage",
                "number",
                "",
                show_when={"method": ["wdv"]},
                optional=True,
            ),
            Field(
                "total_units",
                "Units it makes in its life",
                "number",
                "100000",
                show_when={"method": ["units"]},
            ),
            Field(
                "units",
                "Units made each year",
                "table",
                columns=(Column("u", "Units"),),
                rows=[{"u": "30000"}, {"u": "25000"}, {"u": "20000"}, {"u": "15000"}, {"u": "10000"}],
                show_when={"method": ["units"]},
            ),
        ],
        run=_dep,
    )
)
