"""The keypad: arithmetic on what the owner types, in 40-digit decimals (decision #120).

A small recursive-descent parser (never eval). It reads numbers (grouped like 1,25,000 or 10,000, or 2.5L,
1cr), + − × ÷ ^, a trailing % (divide by 100), brackets, the memory registers M0 to M9, ANS (the last
answer), pi and e, and the functions sqrt, ln, log (base 10), exp, abs, round(x, places), fact(n), and
comb(n, r) and perm(n, r) for nCr and nPr. Function arguments are separated by commas or semicolons.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal, localcontext

from .core import ONE, ZERO, CalcError, ctx, exact, exp, ln, parse_number, pw, sqrt

_TOKEN = re.compile(
    r"\s*(?:(?P<num>(?:(?:\d{1,3}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?(?:cr|crore|lakh|lac|l|k|mn|m|bn)?(?![a-z]))"
    r"|(?P<name>[a-z_][a-z_0-9]*)|(?P<op>\*\*|[-+*/^%(),;×÷−]))",
    re.IGNORECASE,
)

PI = Decimal("3.141592653589793238462643383279502884197")
E = Decimal("2.718281828459045235360287471352662497757")


def _fact(n: Decimal) -> Decimal:
    if n != n.to_integral_value() or n < 0 or n > 1000:
        raise CalcError("fact() takes a whole number from 0 to 1,000.")
    return Decimal(math.factorial(int(n)))


def _whole(n: Decimal, what: str) -> int:
    if n != n.to_integral_value() or n < 0 or n > 100_000:
        raise CalcError(f"{what} takes whole numbers from 0 to 1,00,000.")
    return int(n)


def _round(x: Decimal, places: Decimal = ZERO) -> Decimal:
    return x.quantize(ONE.scaleb(-_whole(places, "round")), rounding=ROUND_HALF_UP)


def _log10(x: Decimal) -> Decimal:
    if x <= 0:
        raise CalcError("log needs a positive number.")
    with localcontext(ctx()):
        return x.log10()


FUNCS: dict[str, tuple[int, int, Callable[..., Decimal]]] = {
    "sqrt": (1, 1, sqrt),
    "ln": (1, 1, ln),
    "log": (1, 1, _log10),
    "exp": (1, 1, exp),
    "abs": (1, 1, abs),
    "round": (1, 2, _round),
    "fact": (1, 1, _fact),
    "comb": (2, 2, lambda n, r: Decimal(math.comb(_whole(n, "comb"), _whole(r, "comb")))),
    "perm": (2, 2, lambda n, r: Decimal(math.perm(_whole(n, "perm"), _whole(r, "perm")))),
}


class _Parser:
    def __init__(self, text: str, names: Mapping[str, Decimal]) -> None:
        self.tokens: list[tuple[str, str]] = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos:
                raise CalcError(f"Cannot read '{text[pos : pos + 10]}'.")
            kind = m.lastgroup or ""
            tok = m.group(kind)
            tok = {"×": "*", "÷": "/", "−": "-", "**": "^"}.get(tok, tok)
            self.tokens.append((kind, tok.lower() if kind == "name" else tok))
            pos = m.end()
            while pos < len(text) and text[pos].isspace():
                pos += 1
        self.i = 0
        self.names = names

    def peek(self) -> str | None:
        return self.tokens[self.i][1] if self.i < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        if self.i >= len(self.tokens):
            raise CalcError("The expression ends too soon.")
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect(self, tok: str) -> None:
        if self.take()[1] != tok:
            raise CalcError(f"Expected '{tok}'.")

    def expr(self) -> Decimal:
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()[1]
            rhs = self.term()
            v = v + rhs if op == "+" else v - rhs
        return v

    def term(self) -> Decimal:
        v = self.unary()
        while self.peek() in ("*", "/"):
            op = self.take()[1]
            rhs = self.unary()
            if op == "/" and rhs == 0:
                raise CalcError("Division by zero.")
            v = v * rhs if op == "*" else v / rhs
        return v

    def unary(self) -> Decimal:
        if self.peek() == "-":
            self.take()
            return -self.unary()
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self) -> Decimal:
        base = self.postfix()
        if self.peek() == "^":
            self.take()
            ex = self.unary()  # right-associative: 2^3^2 = 2^9
            if base == 0 and ex < 0:
                raise CalcError("Zero cannot be raised to a negative power.")
            if base < 0 and ex != ex.to_integral_value():
                raise CalcError("A negative number cannot be raised to a fractional power.")
            if base == 0:
                return ZERO if ex > 0 else ONE
            if abs(ex) > 100_000:
                raise CalcError("The power is too large.")
            return pw(base, ex)
        return base

    def postfix(self) -> Decimal:
        v = self.atom()
        while self.peek() == "%":
            self.take()
            v = v / 100
        return v

    def atom(self) -> Decimal:
        kind, tok = self.take()
        if kind == "num":
            v = parse_number(tok)
            if v is None:
                raise CalcError(f"'{tok}' is not a number.")
            return v
        if tok == "(":
            v = self.expr()
            self.expect(")")
            return v
        if kind == "name":
            if tok in FUNCS:
                lo, hi, fn = FUNCS[tok]
                self.expect("(")
                args = [self.expr()]
                while self.peek() in (",", ";"):
                    self.take()
                    args.append(self.expr())
                self.expect(")")
                if not lo <= len(args) <= hi:
                    raise CalcError(f"{tok}() takes {lo if lo == hi else f'{lo} or {hi}'} value(s).")
                return Decimal(fn(*args))
            if tok == "pi":
                return PI
            if tok == "e":
                return E
            if tok in self.names:
                return self.names[tok]
            raise CalcError(f"'{tok}' is not known. Registers are M0 to M9 and ANS.")
        raise CalcError(f"Unexpected '{tok}'.")


def evaluate(text: str, registers: Mapping[str, str] | None = None) -> str:
    """The value of `text` as an exact string (20 significant digits). Registers come as {'m0': '12.5', 'ans':
    '3'}; a blank register is zero."""
    if not text.strip():
        raise CalcError("Type something to calculate.")
    names: dict[str, Decimal] = {f"m{i}": ZERO for i in range(10)}
    names["ans"] = ZERO
    for k, v in (registers or {}).items():
        key = k.lower()
        if key in names and str(v).strip():
            n = parse_number(str(v))
            if n is None:
                raise CalcError(f"Register {k.upper()} holds '{v}', which is not a number.")
            names[key] = n
    with localcontext(ctx()):
        p = _Parser(text, names)
        out = p.expr()
        if p.i != len(p.tokens):
            raise CalcError(f"Unexpected '{p.tokens[p.i][1]}'.")
        return exact(out)
