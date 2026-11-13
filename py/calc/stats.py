"""Statistics (decision #120, family F), with Excel's definitions so answers can be checked there: AVERAGE,
MEDIAN, MODE.SNGL, VAR.S/VAR.P, STDEV.S/STDEV.P, SKEW, KURT, PERCENTILE.INC, QUARTILE.INC, COVARIANCE.S/P,
CORREL, SLOPE, INTERCEPT, RSQ, STEYX, FORECAST.LINEAR, NORM.DIST and NORM.INV. The normal distribution is
worked in decimals too (a series with only positive terms), not through floating point."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
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
    exp,
    fmt,
    register,
    sqrt,
    value,
)

PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494459")


# ------------------------------------------------------------------------------------------- the maths


def mean(xs: Sequence[Decimal]) -> Decimal:
    with localcontext(ctx()):
        return sum(xs, ZERO) / len(xs)


def _ss(xs: Sequence[Decimal]) -> Decimal:
    m = mean(xs)
    with localcontext(ctx()):
        return sum(((x - m) ** 2 for x in xs), ZERO)


def var_s(xs: Sequence[Decimal]) -> Decimal:
    if len(xs) < 2:
        raise CalcError("A sample variance needs at least two values.")
    with localcontext(ctx()):
        return _ss(xs) / (len(xs) - 1)


def var_p(xs: Sequence[Decimal]) -> Decimal:
    with localcontext(ctx()):
        return _ss(xs) / len(xs)


def sd_s(xs: Sequence[Decimal]) -> Decimal:
    return sqrt(var_s(xs))


def median(xs: Sequence[Decimal]) -> Decimal:
    s = sorted(xs)
    n = len(s)
    with localcontext(ctx()):
        return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def percentile_inc(xs: Sequence[Decimal], p: Decimal) -> Decimal:
    """Excel PERCENTILE.INC: rank (n - 1) p, interpolated."""
    if not ZERO <= p <= ONE:
        raise CalcError("The percentile must be from 0 to 100.")
    s = sorted(xs)
    with localcontext(ctx()):
        rank = (len(s) - 1) * p
        lo = int(rank)
        frac = rank - lo
        if lo + 1 >= len(s):
            return s[-1]
        return s[lo] + frac * (s[lo + 1] - s[lo])


def skew(xs: Sequence[Decimal]) -> Decimal | None:
    """Excel SKEW: n / ((n-1)(n-2)) Σ((x - mean)/s)^3; needs three values and some spread."""
    n = len(xs)
    if n < 3:
        return None
    s = sd_s(xs)
    if s == 0:
        return None
    m = mean(xs)
    with localcontext(ctx()):
        return Decimal(n) / ((n - 1) * (n - 2)) * sum((((x - m) / s) ** 3 for x in xs), ZERO)


def kurt(xs: Sequence[Decimal]) -> Decimal | None:
    """Excel KURT (excess kurtosis): n(n+1)/((n-1)(n-2)(n-3)) Σ((x-m)/s)^4 - 3(n-1)^2/((n-2)(n-3))."""
    n = len(xs)
    if n < 4:
        return None
    s = sd_s(xs)
    if s == 0:
        return None
    m = mean(xs)
    with localcontext(ctx()):
        d = Decimal(n)
        four = sum((((x - m) / s) ** 4 for x in xs), ZERO)
        return d * (d + 1) / ((d - 1) * (d - 2) * (d - 3)) * four - 3 * (d - 1) ** 2 / ((d - 2) * (d - 3))


def cov(xs: Sequence[Decimal], ys: Sequence[Decimal], *, sample: bool = True) -> Decimal:
    mx, my = mean(xs), mean(ys)
    with localcontext(ctx()):
        total = sum(((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)), ZERO)
        return total / (len(xs) - 1 if sample else len(xs))


def norm_pdf(z: Decimal) -> Decimal:
    with localcontext(ctx()):
        return exp(-z * z / 2) / sqrt(2 * PI)


def norm_cdf(z: Decimal) -> Decimal:
    """Φ(z) = 1/2 + φ(z) Σ z^(2n+1) / (1·3·5···(2n+1)) for z ≥ 0 (Marsaglia); every term is positive, so no
    digits are lost to cancellation. Worked at 90 digits; Φ(-z) = 1 - Φ(z)."""
    if z < 0:
        with localcontext(ctx()):
            return ONE - norm_cdf(-z)
    if z > 40:
        return ONE
    if z == 0:
        return Decimal("0.5")
    with localcontext(ctx()) as c:
        c.prec = 90
        term, total, k = z, z, 1
        z2 = z * z
        while True:
            k += 2
            term = term * z2 / k
            total += term
            if term <= Decimal("1e-85") * total or k > 100_000:
                break
        result = Decimal("0.5") + norm_pdf(z) * total
    with localcontext(ctx()):
        return +result


def norm_inv(p: Decimal) -> Decimal:
    """The z with Φ(z) = p (Excel NORM.S.INV), by Newton's method from a bisection start."""
    if not ZERO < p < ONE:
        raise CalcError("The probability must be between 0 and 100% (not either end).")
    with localcontext(ctx()):
        lo, hi = Decimal(-40), Decimal(40)
        for _ in range(30):  # bisection to a good start
            mid = (lo + hi) / 2
            if norm_cdf(mid) < p:
                lo = mid
            else:
                hi = mid
        z = (lo + hi) / 2
        for _ in range(50):
            step = (norm_cdf(z) - p) / norm_pdf(z)
            z -= step
            if abs(step) < Decimal("1e-30"):
                break
        return z


# ------------------------------------------------------------------------------------------- one series

SERIES = (Column("x", "Value"),)
EXAMPLE = [
    {"x": v}
    for v in ("12.5", "-3.2", "8.1", "4.7", "-1.9", "15.3", "6.6", "2.4", "9.8", "-6.1", "7.2", "3.5")
]


def _one_extras(x: Inputs, r: Result, xs: list[Decimal], m: Decimal) -> None:
    """Semideviation below a target, a percentile, a z-score and Chebyshev's bound, when asked for."""
    n = len(xs)
    with localcontext(ctx()):
        target = x.num("target", default=ZERO)
        below = [v - target for v in xs if v < target]
        if n >= 2:
            semi = sum((d * d for d in below), ZERO) / (n - 1)
            r.add(
                "semivariance", f"Target semivariance below {fmt(target, 'number')} (n − 1)", semi, "number"
            )
            r.add("semideviation", "Target semideviation", sqrt(semi), "number")
        pct = x.opt("percentile")
        if pct is not None:
            r.add(
                "percentile",
                f"{fmt(pct, 'number')}th percentile (PERCENTILE.INC)",
                percentile_inc(xs, pct / HUNDRED),
                "number",
            )
        z_of = x.opt("z_of")
        if z_of is not None and n >= 2 and var_s(xs) > 0:
            r.add("z", f"z-score of {fmt(z_of, 'number')}", (z_of - m) / sd_s(xs), "number")
        k = x.opt("chebyshev_k")
        if k is not None and k > 1:
            r.add(
                "chebyshev",
                f"Chebyshev: at least this share lies within {fmt(k, 'number')} SD",
                (ONE - ONE / (k * k)) * HUNDRED,
                "percent",
            )


def _one(x: Inputs) -> Result:
    xs = [r["x"] for r in x.table("data")]
    n = len(xs)
    with localcontext(ctx()):
        m = mean(xs)
        r = Result(value("mean", "Mean (average)", m, "number"))
        r.add("count", "Count", Decimal(n), "count")
        r.add("sum", "Sum", sum(xs, ZERO), "number")
        r.add("median", "Median", median(xs), "number")
        counts = Counter(xs).most_common()
        if counts[0][1] > 1:
            best = counts[0][1]
            first = next(v for v in xs if Counter(xs)[v] == best)  # Excel MODE.SNGL: the first most frequent
            r.add("mode", "Mode", first, "number")
        else:
            r.add("mode", "Mode", "none (no value repeats)", "text")
        r.add("min", "Minimum", min(xs), "number")
        r.add("max", "Maximum", max(xs), "number")
        r.add("range", "Range", max(xs) - min(xs), "number")
        q1, q3 = percentile_inc(xs, Decimal("0.25")), percentile_inc(xs, Decimal("0.75"))
        r.add("q1", "First quartile (Q1)", q1, "number")
        r.add("q3", "Third quartile (Q3)", q3, "number")
        r.add("iqr", "Interquartile range", q3 - q1, "number")
        if n >= 2:
            vs, vp = var_s(xs), var_p(xs)
            r.add("var_s", "Variance, sample (VAR.S)", vs, "number")
            r.add("var_p", "Variance, population (VAR.P)", vp, "number")
            s = sqrt(vs)
            r.add("sd_s", "Standard deviation, sample (STDEV.S)", s, "number")
            r.add("sd_p", "Standard deviation, population (STDEV.P)", sqrt(vp), "number")
            if m != 0:
                r.add("cv", "Coefficient of variation (sample SD / mean)", s / abs(m), "ratio")
            r.add("se", "Standard error of the mean", s / sqrt(Decimal(n)), "number")
        sk, ku = skew(xs), kurt(xs)
        if sk is not None:
            r.add("skew", "Skewness (SKEW)", sk, "number")
        if ku is not None:
            r.add("kurt", "Excess kurtosis (KURT)", ku, "number")
        _one_extras(x, r, xs, m)
        r.steps = [
            "Sample variance s² = Σ(x − x̄)² / (n − 1); population σ² = Σ(x − x̄)² / n",
            "Skewness = n / ((n − 1)(n − 2)) · Σ((x − x̄)/s)³ (Excel SKEW)",
            "Target semivariance = Σ over x < B of (x − B)² / (n − 1) (CFA)",
        ]
    return r


register(
    Calculator(
        key="stats_one",
        family="stats",
        title="Statistics of a series",
        description="Mean, median, mode, quartiles, variance and standard deviation (sample and population), "
        "skewness, kurtosis, semideviation below a target, percentiles and z-scores, as Excel works "
        "them out. Paste a column straight from Excel.",
        keywords="mean average median mode variance standard deviation stdev skew kurtosis quartile "
        "percentile "
        "z-score semivariance downside chebyshev coefficient of variation",
        fields=[
            Field(
                "data", "Values", "table", columns=SERIES, rows=EXAMPLE, hint="Returns in % or any numbers"
            ),
            Field("target", "Target for semideviation", "number", "0", optional=True),
            Field("percentile", "Percentile to find (0 to 100)", "number", "90", optional=True),
            Field("z_of", "z-score of this value", "number", "", optional=True),
            Field("chebyshev_k", "Chebyshev: within k standard deviations", "number", "2", optional=True),
        ],
        run=_one,
    )
)


# ------------------------------------------------------------------------------------------- two series

PAIRS = (Column("x", "X"), Column("y", "Y"))
PAIR_EXAMPLE = [
    {"x": a, "y": b}
    for a, b in (
        ("1.2", "1.9"),
        ("-0.8", "-1.4"),
        ("2.5", "3.1"),
        ("0.4", "0.2"),
        ("-1.6", "-2.3"),
        ("3.1", "3.8"),
        ("0.9", "1.5"),
        ("-0.3", "-0.1"),
    )
]


def _two(x: Inputs) -> Result:
    rows = x.table("data", min_rows=3)
    xs = [r["x"] for r in rows]
    ys = [r["y"] for r in rows]
    n = len(xs)
    with localcontext(ctx()):
        vx, vy = var_s(xs), var_s(ys)
        if vx == 0:
            raise CalcError("X does not vary, so there is no line to fit.", "data")
        c = cov(xs, ys)
        slope = c / vx
        intercept = mean(ys) - slope * mean(xs)
        corr = c / sqrt(vx * vy) if vy != 0 else ZERO
        r2 = corr * corr
        r = Result(value("corr", "Correlation (CORREL)", corr, "number"))
        r.add("cov_s", "Covariance, sample (COVARIANCE.S)", c, "number")
        r.add("cov_p", "Covariance, population (COVARIANCE.P)", cov(xs, ys, sample=False), "number")
        r.add("slope", "Slope (SLOPE): Y per unit of X", slope, "number")
        r.add("intercept", "Intercept (INTERCEPT)", intercept, "number")
        r.add("r2", "R squared (RSQ)", r2, "number")
        if n > 2:
            sse = sum(((y - intercept - slope * xx) ** 2 for xx, y in zip(xs, ys, strict=True)), ZERO)
            steyx = sqrt(sse / (n - 2))
            r.add("steyx", "Standard error of the estimate (STEYX)", steyx, "number")
            se_slope = steyx / sqrt(vx * (n - 1))
            if se_slope != 0:
                r.add(
                    "t_slope",
                    f"t-statistic of the slope ({n - 2} degrees of freedom)",
                    slope / se_slope,
                    "number",
                )
            if abs(corr) < 1:
                r.add(
                    "t_corr",
                    "t-statistic of the correlation",
                    corr * sqrt(Decimal(n - 2)) / sqrt(ONE - r2),
                    "number",
                )
        r.add("mean_x", "Mean of X", mean(xs), "number")
        r.add("mean_y", "Mean of Y", mean(ys), "number")
        r.add("sd_x", "Standard deviation of X (sample)", sqrt(vx), "number")
        r.add("sd_y", "Standard deviation of Y (sample)", sqrt(vy), "number")
        x0 = x.opt("x0")
        if x0 is not None:
            r.add(
                "forecast",
                f"Forecast of Y at X = {fmt(x0, 'number')} (FORECAST.LINEAR)",
                intercept + slope * x0,
                "number",
            )
        r.steps = [
            "Covariance = Σ(x − x̄)(y − ȳ) / (n − 1);  correlation = cov / (sₓ s_y)",
            "Slope = cov / sₓ²;  intercept = ȳ − slope · x̄;  R² = correlation²",
            "STEYX = √(Σ(y − ŷ)² / (n − 2))",
        ]
    return r


register(
    Calculator(
        key="stats_two",
        family="stats",
        title="Correlation and regression (two series)",
        description="Covariance, correlation, the least-squares line (slope, intercept, R squared, "
        "standard error, "
        "t-statistics) and a forecast, as Excel works them out.",
        keywords="covariance correlation regression slope intercept r squared beta forecast linear steyx "
        "t-stat",
        fields=[
            Field("data", "Pairs", "table", columns=PAIRS, rows=PAIR_EXAMPLE),
            Field("x0", "Forecast Y at this X", "number", "", optional=True),
        ],
        run=_two,
    )
)


# ------------------------------------------------------------------------------------------- probability

SCENARIOS = (
    Column("label", "Scenario", "text", optional=True),
    Column("p", "Probability %", "percent"),
    Column("x", "Outcome"),
)
SCENARIO_EXAMPLE = [
    {"label": "Boom", "p": "25", "x": "24"},
    {"label": "Normal", "p": "50", "x": "11"},
    {"label": "Slump", "p": "25", "x": "-8"},
]


def _scenarios(x: Inputs) -> Result:
    rows = x.table("data", min_rows=2)
    with localcontext(ctx()):
        total = sum((rr["p"] for rr in rows), ZERO)
        if abs(total - ONE) > Decimal("1e-12"):
            raise CalcError(
                f"The probabilities add up to {fmt(total * HUNDRED, 'percent')}%, not 100%.", "data"
            )
        if any(rr["p"] < 0 for rr in rows):
            raise CalcError("A probability cannot be negative.", "data")
        ev = sum((rr["p"] * rr["x"] for rr in rows), ZERO)
        var = sum((rr["p"] * (rr["x"] - ev) ** 2 for rr in rows), ZERO)
        r = Result(value("ev", "Expected value", ev, "number"))
        r.add("var", "Variance", var, "number")
        r.add("sd", "Standard deviation", sqrt(var), "number")
        if ev != 0:
            r.add("cv", "Coefficient of variation", sqrt(var) / abs(ev), "ratio")
        r.steps = ["E(X) = Σ p·x;  Var = Σ p·(x − E(X))²"]
        r.tables.append(
            TableOut(
                "rows",
                "Each scenario",
                [
                    {"key": "label", "label": "Scenario", "unit": "text"},
                    {"key": "p", "label": "Probability", "unit": "percent"},
                    {"key": "x", "label": "Outcome", "unit": "number"},
                    {"key": "px", "label": "p × outcome", "unit": "number"},
                    {"key": "dev", "label": "p × (x − E)²", "unit": "number"},
                ],
                [
                    [
                        rr["label"] or str(i + 1),
                        fmt(rr["p"] * HUNDRED, "percent"),
                        fmt(rr["x"], "number"),
                        fmt(rr["p"] * rr["x"], "number"),
                        fmt(rr["p"] * (rr["x"] - ev) ** 2, "number"),
                    ]
                    for i, rr in enumerate(rows)
                ],
            )
        )
    return r


register(
    Calculator(
        key="scenarios",
        family="stats",
        title="Expected value from scenarios",
        description="Outcomes with their probabilities: the expected value, variance and standard deviation.",
        keywords="expected value probability scenario variance standard deviation weighted outcome",
        fields=[Field("data", "Scenarios", "table", columns=SCENARIOS, rows=SCENARIO_EXAMPLE)],
        run=_scenarios,
    )
)


# ------------------------------------------------------------------------------------------- normal

NORMAL_MODES = (
    ("prob", "Probability below and above a value"),
    ("between", "Probability between two values"),
    ("value", "Value for a probability"),
    ("interval", "Confidence interval"),
)


def _normal(x: Inputs) -> Result:
    mode = x.choice("mode")
    mu = x.num("mean", default=ZERO)
    sd = x.num("sd", default=ONE, above=ZERO)
    with localcontext(ctx()):
        if mode == "prob":
            v = x.num("x")
            z = (v - mu) / sd
            below = norm_cdf(z)
            r = Result(value("below", f"P(X < {fmt(v, 'number')})", below * HUNDRED, "percent"))
            r.add("above", f"P(X > {fmt(v, 'number')})", (ONE - below) * HUNDRED, "percent")
            r.add("z", "z", z, "number")
            r.add("pdf", "Density at the value (NORM.DIST, FALSE)", norm_pdf(z) / sd, "number")
        elif mode == "between":
            a, b = x.num("x"), x.num("x2")
            lo, hi = min(a, b), max(a, b)
            p = norm_cdf((hi - mu) / sd) - norm_cdf((lo - mu) / sd)
            r = Result(
                value("between", f"P({fmt(lo, 'number')} < X < {fmt(hi, 'number')})", p * HUNDRED, "percent")
            )
            r.add("outside", "Probability outside", (ONE - p) * HUNDRED, "percent")
        elif mode == "value":
            p = x.rate("p")
            z = norm_inv(p)
            r = Result(
                value(
                    "x",
                    f"Value with {fmt(p * HUNDRED, 'percent')}% below it (NORM.INV)",
                    mu + z * sd,
                    "number",
                )
            )
            r.add("z", "z", z, "number")
        else:
            c = x.rate("confidence")
            if not ZERO < c < ONE:
                raise CalcError("Confidence must be between 0 and 100%.", "confidence")
            z = norm_inv((ONE + c) / 2)
            n = x.int_("n", default=1, min_=1, max_=10_000_000)
            half = z * sd / sqrt(Decimal(n))
            r = Result(value("half", "Half-width (± from the mean)", half, "number"))
            r.add("lo", "Lower limit", mu - half, "number")
            r.add("hi", "Upper limit", mu + half, "number")
            r.add("z", "z (two-sided)", z, "number")
        r.steps = [
            "z = (x − μ) / σ;  Φ(z) = ½ + φ(z) · Σ z^(2n+1) / (1·3·5···(2n+1))",
            "Interval: mean ± z · σ / √n",
        ]
    return r


register(
    Calculator(
        key="normal",
        family="stats",
        title="Normal distribution",
        description="Probabilities below, above or between values; the value for a probability; confidence "
        "intervals. Worked in decimals to Excel's NORM.DIST and NORM.INV.",
        keywords="normal distribution probability z table norm.dist norm.inv confidence interval bell curve",
        fields=[
            Field("mode", "Find", "choice", "prob", options=NORMAL_MODES),
            Field("mean", "Mean (μ)", "number", "0"),
            Field("sd", "Standard deviation (σ)", "number", "1"),
            Field("x", "Value", "number", "1.96", show_when={"mode": ["prob", "between"]}),
            Field("x2", "Second value", "number", "-1.96", show_when={"mode": ["between"]}),
            Field("p", "Probability below (%)", "percent", "95", show_when={"mode": ["value"]}),
            Field("confidence", "Confidence (%)", "percent", "95", show_when={"mode": ["interval"]}),
            Field("n", "Sample size (1 for one observation)", "int", "1", show_when={"mode": ["interval"]}),
        ],
        run=_normal,
    )
)
