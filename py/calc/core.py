"""The financial calculator's shared pieces (docs/decisions.md #120): decimal arithmetic, reading what the
owner typed, root finding, and the shape of every answer.

Separate from the books: nothing here reads or writes entries. All arithmetic is `decimal.Decimal` at 40
significant digits (rule R3: no float for money or rates). Inputs arrive as text and answers leave as decimal
strings, so the browser only parses and formats text.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Context, Decimal, InvalidOperation, localcontext
from typing import Any, Literal

PREC = 40
ZERO, ONE, TWO, HUNDRED = Decimal(0), Decimal(1), Decimal(2), Decimal(100)
TOL = Decimal("1e-24")


class CalcError(Exception):
    """Something typed cannot be calculated. The message says which field and why. The package imports nothing
    else from the app, so the same files run on the phone (Cash Log, under Pyodide); the API turns this into
    an AppError."""

    def __init__(self, message: str, field_key: str | None = None, code: str = "calc_input") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field_key


def ctx() -> Context:
    c = Context(prec=PREC)
    c.traps[InvalidOperation] = True
    return c


# ------------------------------------------------------------------------------------------- numbers in

_SUFFIX = {
    "k": Decimal(1_000),
    "thousand": Decimal(1_000),
    "l": Decimal(100_000),
    "lac": Decimal(100_000),
    "lakh": Decimal(100_000),
    "lakhs": Decimal(100_000),
    "cr": Decimal(10_000_000),
    "crore": Decimal(10_000_000),
    "crores": Decimal(10_000_000),
    "m": Decimal(1_000_000),
    "mn": Decimal(1_000_000),
    "million": Decimal(1_000_000),
    "bn": Decimal(1_000_000_000),
    "billion": Decimal(1_000_000_000),
}
_NUMBER = re.compile(r"^([+-]?)(\d+(?:\.\d*)?|\.\d+)(?:e([+-]?\d+))?([a-z]*)(%?)$")


def parse_number(text: str) -> Decimal | None:
    """'1,25,000', '₹ 2.5L', '12.5%', '(500)', '−3', '1.2cr', '4e3' -> Decimal; None if it is not a number.
    A trailing % is dropped: percentage fields already hold percents."""
    t = text.strip().lower().replace("₹", "").replace("rs.", "").replace("rs", "")
    t = t.replace(",", "").replace(" ", "").replace("_", "").replace("−", "-")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    m = _NUMBER.match(t)
    if not m:
        return None
    sign, digits, exp, suffix, _pct = m.groups()
    if suffix and suffix not in _SUFFIX:
        return None
    with localcontext(ctx()):
        v = Decimal(digits)
        if exp:
            v = v.scaleb(int(exp))
        if suffix:
            v *= _SUFFIX[suffix]
        if (sign == "-") != neg:
            v = -v
    return v


# ------------------------------------------------------------------------------------------- the form

Kind = Literal["number", "money", "percent", "int", "choice", "date", "flows", "dated_flows", "text", "solve"]


@dataclass(frozen=True)
class Field:
    """One input. `show_when` hides it unless another field has one of the listed values. A calculator with a
    `solve` field shows the field named by its value as the answer instead of an input."""

    key: str
    label: str
    kind: Kind = "number"
    default: str = ""
    hint: str = ""
    options: Sequence[tuple[str, str]] = ()
    show_when: Mapping[str, Sequence[str]] = field(default_factory=dict)
    optional: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "kind": self.kind,
            "default": self.default,
            "hint": self.hint,
            "options": [{"value": v, "label": lab} for v, lab in self.options],
            "show_when": {k: list(v) for k, v in self.show_when.items()},
            "optional": self.optional,
        }


Unit = Literal["money", "percent", "number", "periods", "years", "days", "date", "text", "count", "ratio"]

_PLACES: dict[str, int] = {
    "money": 2,
    "percent": 4,
    "number": 6,
    "periods": 4,
    "years": 4,
    "days": 0,
    "count": 0,
    "ratio": 4,
}


def fmt(v: Decimal, unit: str) -> str:
    """Rounded for showing: money to paise, percents to 4 places, other numbers to 6 places, trailing zeros
    trimmed except on money."""
    places = _PLACES.get(unit, 6)
    with localcontext(ctx()):
        q = (
            v.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
            if places
            else v.quantize(ONE, rounding=ROUND_HALF_UP)
        )
    if q == 0:
        q = abs(q)  # no "-0.00"
    s = f"{q:f}"
    if unit != "money" and "." in s:
        s = s.rstrip("0").rstrip(".")
    return s


def exact(v: Decimal) -> str:
    """Full value, 20 significant digits, for registers and copying."""
    with localcontext(Context(prec=20)):
        r = +v
    s = f"{r:f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


@dataclass
class Value:
    key: str
    label: str
    value: str
    unit: str
    exact: str = ""
    note: str = ""


@dataclass
class TableOut:
    key: str
    title: str
    columns: list[dict[str, str]]  # {key, label, unit}
    rows: list[list[str]]


@dataclass
class Chart:
    kind: Literal["line", "bar"]
    title: str
    x_label: str
    y_unit: str
    x: list[str]
    series: list[dict[str, Any]]  # {name, values: [str]}
    marks: list[dict[str, str]] = field(default_factory=list)  # {x, label}


@dataclass
class Result:
    answer: Value
    values: list[Value] = field(default_factory=list)
    tables: list[TableOut] = field(default_factory=list)
    chart: Chart | None = None
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, key: str, label: str, v: Decimal | str, unit: str = "number", note: str = "") -> None:
        if isinstance(v, Decimal):
            self.values.append(Value(key, label, fmt(v, unit), unit, exact(v), note))
        else:
            self.values.append(Value(key, label, v, unit, v, note))


def value(key: str, label: str, v: Decimal, unit: str, note: str = "") -> Value:
    return Value(key, label, fmt(v, unit), unit, exact(v), note)


# ------------------------------------------------------------------------------------------- reading inputs


@dataclass(frozen=True)
class Flow:
    amount: Decimal
    count: int


class Inputs:
    """What the owner typed, read field by field with messages that name the field."""

    def __init__(self, raw: Mapping[str, Any], fields: Sequence[Field]) -> None:
        self.raw = raw
        self.fields = {f.key: f for f in fields}

    def _label(self, key: str) -> str:
        f = self.fields.get(key)
        return f.label if f else key

    def text(self, key: str) -> str:
        v = self.raw.get(key)
        if v is None:
            f = self.fields.get(key)
            return f.default if f else ""
        return str(v).strip()

    def has(self, key: str) -> bool:
        return self.text(key) != ""

    def num(
        self,
        key: str,
        *,
        default: Decimal | None = None,
        min_: Decimal | None = None,
        max_: Decimal | None = None,
        above: Decimal | None = None,
    ) -> Decimal:
        t = self.text(key)
        if t == "":
            if default is not None:
                return default
            raise CalcError(f"Enter {self._label(key)}.", key)
        v = parse_number(t)
        if v is None:
            raise CalcError(f"{self._label(key)}: '{t}' is not a number.", key)
        if min_ is not None and v < min_:
            raise CalcError(f"{self._label(key)} cannot be less than {fmt(min_, 'number')}.", key)
        if max_ is not None and v > max_:
            raise CalcError(f"{self._label(key)} cannot be more than {fmt(max_, 'number')}.", key)
        if above is not None and v <= above:
            raise CalcError(f"{self._label(key)} must be more than {fmt(above, 'number')}.", key)
        return v

    def opt(self, key: str) -> Decimal | None:
        return self.num(key) if self.has(key) else None

    def rate(self, key: str, *, default: Decimal | None = None, above: Decimal = Decimal(-100)) -> Decimal:
        """A percentage as a fraction: '12' -> 0.12. Must be above -100%."""
        pct = self.num(key, default=None if default is None else default * HUNDRED, above=above)
        with localcontext(ctx()):
            return pct / HUNDRED

    def int_(self, key: str, *, default: int | None = None, min_: int = 0, max_: int = 1_000_000) -> int:
        v = self.num(key, default=None if default is None else Decimal(default))
        if v != v.to_integral_value():
            raise CalcError(f"{self._label(key)} must be a whole number.", key)
        n = int(v)
        if n < min_ or n > max_:
            raise CalcError(f"{self._label(key)} must be from {min_:,} to {max_:,}.", key)
        return n

    def choice(self, key: str) -> str:
        f = self.fields[key]
        t = self.text(key) or f.default
        allowed = [v for v, _ in f.options]
        if t not in allowed:
            raise CalcError(f"{f.label}: choose one of {', '.join(allowed)}.", key)
        return t

    def date(self, key: str, *, default: dt.date | None = None) -> dt.date:
        t = self.text(key)
        if t == "" and default is not None:
            return default
        try:
            return dt.date.fromisoformat(t)
        except ValueError:
            raise CalcError(f"{self._label(key)}: give a date like 2026-04-01.", key) from None

    def _rows(self, key: str) -> list[Mapping[str, Any]]:
        v = self.raw.get(key)
        if v is None or v == "":
            return []
        if not isinstance(v, list) or not all(isinstance(r, Mapping) for r in v):
            raise CalcError(f"{self._label(key)}: send a list of rows.", key)
        return v

    def flows(self, key: str) -> list[Flow]:
        """Rows of {amount, count}; blank rows are skipped, but the first row is CF0 even when zero."""
        out: list[Flow] = []
        for i, row in enumerate(self._rows(key)):
            a_text = str(row.get("amount", "")).strip()
            c_text = str(row.get("count", "") or "1").strip()
            if a_text == "" and i > 0:
                continue
            a = parse_number(a_text or "0")
            c = parse_number(c_text)
            name = "CF0" if i == 0 else f"CF{i}"
            if a is None:
                raise CalcError(f"{name}: '{a_text}' is not a number.", key)
            if c is None or c != c.to_integral_value() or not 1 <= c <= 9_999 or (i == 0 and c != 1):
                raise CalcError(f"{name}: the count must be a whole number from 1 to 9,999 (CF0 once).", key)
            out.append(Flow(a, int(c)))
        if len(out) < 2:
            raise CalcError("Enter CF0 and at least one later cash flow.", key)
        return out

    def dated_flows(self, key: str) -> list[tuple[dt.date, Decimal]]:
        out: list[tuple[dt.date, Decimal]] = []
        for i, row in enumerate(self._rows(key), start=1):
            d_text = str(row.get("date", "")).strip()
            a_text = str(row.get("amount", "")).strip()
            if not d_text and not a_text:
                continue
            try:
                d = dt.date.fromisoformat(d_text)
            except ValueError:
                raise CalcError(f"Row {i}: give the date like 2026-04-01.", key) from None
            a = parse_number(a_text)
            if a is None:
                raise CalcError(f"Row {i}: '{a_text}' is not an amount.", key)
            out.append((d, a))
        if len(out) < 2:
            raise CalcError("Enter at least two dated cash flows.", key)
        return sorted(out, key=lambda x: x[0])


# ------------------------------------------------------------------------------------------- arithmetic


def pw(base: Decimal, exponent: Decimal | int) -> Decimal:
    """base ** exponent inside the 40-digit context; a whole exponent stays exact."""
    with localcontext(ctx()):
        if isinstance(exponent, int) or exponent == exponent.to_integral_value():
            return base ** int(exponent)
        if base <= 0:
            raise CalcError(
                "This needs a fractional power of a number that is not positive.", code="no_solution"
            )
        return (exponent * base.ln()).exp()


def ln(x: Decimal) -> Decimal:
    if x <= 0:
        raise CalcError("This needs the logarithm of a number that is not positive.", code="no_solution")
    with localcontext(ctx()):
        return x.ln()


def exp(x: Decimal) -> Decimal:
    with localcontext(ctx()):
        return x.exp()


def sqrt(x: Decimal) -> Decimal:
    if x < 0:
        raise CalcError("This needs the square root of a negative number.", code="no_solution")
    with localcontext(ctx()):
        return x.sqrt()


def dec(n: int | str) -> Decimal:
    return Decimal(n)


def newton(f: Callable[[Decimal], Decimal], lo: Decimal, hi: Decimal, guess: Decimal) -> Decimal | None:
    """Newton's method with a numerical slope; None if it leaves (lo, hi) or stalls."""
    with localcontext(ctx()):
        x = guess
        for _ in range(80):
            try:
                fx = f(x)
                h = max(abs(x), ONE) * Decimal("1e-15")
                d = (f(x + h) - fx) / h
            except InvalidOperation, ZeroDivisionError, CalcError, OverflowError:
                return None
            if d == 0:
                return None
            step = fx / d
            nx = x - step
            if not lo < nx < hi:
                return None
            if abs(step) <= TOL * max(abs(nx), ONE):
                # polish: confirm a sign change (or zero) right around the root
                return nx
            x = nx
    return None


def solve(
    f: Callable[[Decimal], Decimal],
    lo: Decimal,
    hi: Decimal,
    guess: Decimal,
    *,
    what: str = "the rate",
) -> Decimal:
    """A root of f in (lo, hi): Newton's method from `guess`, then bisection on the first bracket found by
    scanning. Raises a CalcError naming `what` when there is none."""
    with localcontext(ctx()):
        root = newton(f, lo, hi, guess)
        if root is not None:
            return root
        roots = all_roots(f, lo, hi, limit=1)
        if roots:
            return roots[0]
    raise CalcError(
        f"No value of {what} solves this. Check the signs: money paid out is negative.", code="no_solution"
    )


def bisect(f: Callable[[Decimal], Decimal], a: Decimal, b: Decimal) -> Decimal:
    with localcontext(ctx()):
        fa = f(a)
        for _ in range(200):
            m = (a + b) / 2
            fm = f(m)
            if fm == 0 or (b - a) / 2 <= TOL * max(abs(m), ONE):
                return m
            if (fm > 0) == (fa > 0):
                a, fa = m, fm
            else:
                b = m
        return (a + b) / 2


def scan_points(lo: Decimal, hi: Decimal) -> list[Decimal]:
    """Grid for finding sign changes of a rate function: fine near zero, coarse for large rates."""
    pts: set[Decimal] = {lo, hi}
    fine = [Decimal(n) / 1000 for n in range(-999, 1001, 5)]  # -99.9% to 100% by 0.5%
    coarse = [Decimal(n) / 10 for n in range(11, 101)] + [Decimal(n) for n in range(11, 101, 1)]
    for p in fine + coarse:
        if lo < p < hi:
            pts.add(p)
    return sorted(pts)


def all_roots(f: Callable[[Decimal], Decimal], lo: Decimal, hi: Decimal, *, limit: int = 10) -> list[Decimal]:
    """Every root found between grid points where f changes sign (or is zero)."""
    out: list[Decimal] = []
    prev_x: Decimal | None = None
    prev_f: Decimal | None = None
    with localcontext(ctx()):
        for x in scan_points(lo, hi):
            try:
                fx = f(x)
            except InvalidOperation, ZeroDivisionError, CalcError, OverflowError:
                prev_x = prev_f = None
                continue
            if fx == 0:
                out.append(x)
            elif prev_f is not None and prev_x is not None and prev_f != 0 and (prev_f > 0) != (fx > 0):
                out.append(bisect(f, prev_x, x))
            if len(out) >= limit:
                break
            prev_x, prev_f = x, fx
    return out


# ------------------------------------------------------------------------------------------- the registry


@dataclass(frozen=True)
class Calculator:
    key: str
    family: str
    title: str
    description: str
    keywords: str
    fields: Sequence[Field]
    run: Callable[[Inputs], Result]

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "family": self.family,
            "title": self.title,
            "description": self.description,
            "keywords": self.keywords,
            "fields": [f.as_dict() for f in self.fields],
        }


FAMILIES: list[tuple[str, str]] = [
    ("tvm", "Time value of money"),
    ("rates", "Interest rates"),
    ("cashflow", "Cash flows: NPV and IRR"),
    ("utils", "Utilities"),
]

REGISTRY: dict[str, Calculator] = {}


def register(c: Calculator) -> Calculator:
    if c.key in REGISTRY:
        raise ValueError(f"calculator {c.key} registered twice")
    REGISTRY[c.key] = c
    return c


def result_dict(r: Result) -> dict[str, Any]:
    def v(x: Value) -> dict[str, str]:
        return {
            "key": x.key,
            "label": x.label,
            "value": x.value,
            "unit": x.unit,
            "exact": x.exact,
            "note": x.note,
        }

    return {
        "answer": v(r.answer),
        "values": [v(x) for x in r.values],
        "tables": [t.__dict__ for t in r.tables],
        "chart": None if r.chart is None else r.chart.__dict__,
        "steps": r.steps,
        "warnings": r.warnings,
    }
