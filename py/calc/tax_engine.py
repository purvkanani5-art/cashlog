"""Income tax under the new regime: the arithmetic alone (docs/decisions.md #103, #120).

Moved here from pb.services.income_tax so the same code runs in Kuberlekha and on the phone (Cash Log, under
Pyodide). It imports nothing else from the app: rules are any objects with the RuleSet attributes (the
pydantic models in Kuberlekha, plain dataclasses built by `rules_from_dict` on the phone). Money is integer
paise and rates are basis points (rule R3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from .core import CalcError

BP = 10_000  # basis points in 100%


class SlabLike(Protocol):
    @property
    def upto_paise(self) -> int | None: ...
    @property
    def rate_bp(self) -> int: ...


class SurchargeLike(Protocol):
    @property
    def above_paise(self) -> int: ...
    @property
    def rate_bp(self) -> int: ...


class KindLike(Protocol):
    @property
    def key(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def group(self) -> str: ...
    @property
    def treatment(self) -> str: ...
    @property
    def rate_bp(self) -> int: ...
    @property
    def exemption_paise(self) -> int: ...
    @property
    def surcharge_cap_bp(self) -> int | None: ...
    @property
    def standard_deduction(self) -> bool: ...
    @property
    def use_basic_exemption(self) -> bool: ...


class RulesLike(Protocol):
    @property
    def fy(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def slabs(self) -> Sequence[SlabLike]: ...
    @property
    def standard_deduction_paise(self) -> int: ...
    @property
    def rebate_limit_paise(self) -> int: ...
    @property
    def rebate_max_paise(self) -> int: ...
    @property
    def rebate_on_special(self) -> bool: ...
    @property
    def surcharges(self) -> Sequence[SurchargeLike]: ...
    @property
    def cess_bp(self) -> int: ...
    @property
    def round_to_paise(self) -> int: ...
    @property
    def kinds(self) -> Sequence[KindLike]: ...


@dataclass(frozen=True)
class PlainSlab:
    upto_paise: int | None
    rate_bp: int


@dataclass(frozen=True)
class PlainSurcharge:
    above_paise: int
    rate_bp: int


@dataclass(frozen=True)
class PlainKind:
    key: str
    label: str
    group: str = "Other"
    treatment: str = "slab"
    rate_bp: int = 0
    exemption_paise: int = 0
    surcharge_cap_bp: int | None = None
    standard_deduction: bool = False
    use_basic_exemption: bool = False
    note: str = ""


@dataclass(frozen=True)
class PlainRules:
    fy: str
    name: str
    slabs: Sequence[PlainSlab]
    standard_deduction_paise: int
    rebate_limit_paise: int
    rebate_max_paise: int
    rebate_on_special: bool
    surcharges: Sequence[PlainSurcharge]
    cess_bp: int
    round_to_paise: int
    kinds: Sequence[PlainKind]
    note: str = ""


def rules_from_dict(d: Mapping[str, Any]) -> PlainRules:
    """A rule set as Kuberlekha sends it (GET /income-tax/rules, or the Cash Log list) as plain objects. The
    phone trusts Kuberlekha, which validated the rules when they were saved."""
    kinds = [PlainKind(**{k: v for k, v in x.items() if k in PlainKind.__dataclass_fields__})
             for x in d["kinds"]]  # fmt: skip
    return PlainRules(
        fy=d["fy"],
        name=d["name"],
        slabs=[PlainSlab(s.get("upto_paise"), s["rate_bp"]) for s in d["slabs"]],
        standard_deduction_paise=d["standard_deduction_paise"],
        rebate_limit_paise=d["rebate_limit_paise"],
        rebate_max_paise=d["rebate_max_paise"],
        rebate_on_special=d.get("rebate_on_special", False),
        surcharges=[PlainSurcharge(s["above_paise"], s["rate_bp"]) for s in d.get("surcharges", [])],
        cess_bp=d["cess_bp"],
        round_to_paise=d.get("round_to_paise", 10_00),
        kinds=kinds,
        note=d.get("note", ""),
    )


# ---------------------------------------------------------------------------------------------- calculation


@dataclass
class SlabLine:
    from_paise: int
    upto_paise: int | None
    rate_bp: int
    income_paise: int
    tax_paise: int


@dataclass
class KindLine:
    key: str
    label: str
    group: str
    treatment: str
    amount_paise: int
    deduction_paise: int  # the standard deduction, or the exempt part of a gain
    basic_exemption_used_paise: int
    taxable_paise: int
    rate_bp: int | None  # special rate; None for slab-rate income
    tax_paise: int  # special-rate tax; for slab income, its share of slab tax after the rebate
    surcharge_rate_bp: int = 0  # the rate for this income: the total-income rate, or its cap
    surcharge_paise: int = 0  # before marginal relief


@dataclass
class Result:
    fy: str
    name: str
    gross_paise: int
    total_income_paise: int  # after the standard deduction; what the rebate and surcharge look at
    slab_income_paise: int
    slab_tax_paise: int
    special_tax_paise: int
    rebate_paise: int
    tax_after_rebate_paise: int
    surcharge_rate_bp: int
    surcharge_paise: int  # after marginal relief
    surcharge_relief_paise: int
    cess_paise: int
    total_tax_paise: int
    rounded_tax_paise: int
    effective_rate_bp: int  # of gross income
    kinds: list[KindLine] = field(default_factory=list)
    slabs: list[SlabLine] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class _Base:
    """What tax is charged on: each slab-rate income and each special-rate income after exemptions."""

    slab_by_kind: dict[str, int]
    special: dict[str, int]
    total: int  # total income, for the rebate and surcharge tests

    @property
    def slab(self) -> int:
        return sum(self.slab_by_kind.values())


@dataclass
class _Tax:
    slab: int
    special: int
    rebate: int
    surcharge: int
    by_kind: dict[str, tuple[int, int, int]]  # key -> (its tax, its surcharge rate, its surcharge)

    @property
    def before_surcharge(self) -> int:
        return self.slab + self.special - self.rebate


def _pct(amount: int, bp: int) -> int:
    """amount x rate, rounded half up to the paisa."""
    return (amount * bp + BP // 2) // BP


def _cap(rate: int, cap: int | None) -> int:
    return rate if cap is None else min(rate, cap)


def _slab_tax(rules: RulesLike, income: int) -> tuple[int, list[SlabLine]]:
    lines, lower, tax = [], 0, 0
    for s in rules.slabs:
        top = s.upto_paise
        part = max(0, (income if top is None else min(income, top)) - lower)
        t = _pct(part, s.rate_bp)
        lines.append(SlabLine(lower, top, s.rate_bp, part, t))
        tax += t
        if top is None:
            break
        lower = top
    return tax, lines


def _surcharge_rate(rules: RulesLike, total: int) -> int:
    return max((s.rate_bp for s in rules.surcharges if total > s.above_paise), default=0)


def _tax(rules: RulesLike, kinds: dict[str, KindLike], base: _Base) -> _Tax:
    slab_tax, _ = _slab_tax(rules, base.slab)
    special_tax = sum(_pct(v, kinds[k].rate_bp) for k, v in base.special.items())
    rebate = 0
    if base.total <= rules.rebate_limit_paise:
        rebate = min(slab_tax + (special_tax if rules.rebate_on_special else 0), rules.rebate_max_paise)
    elif base.total - rules.rebate_limit_paise < slab_tax:
        # Marginal relief under 87A: just above the limit, tax on slab income cannot exceed the excess.
        rebate = slab_tax - (base.total - rules.rebate_limit_paise)
    rebate = min(rebate, slab_tax + special_tax)
    # Surcharge rises with total income and is charged on each kind's own tax, at that kind's cap where the
    # law caps it (15% on equity gains and dividends). The rebate comes off slab tax first; slab tax is shared
    # among slab-rate kinds in proportion to their income.
    rate = _surcharge_rate(rules, base.total)
    slab_after = max(0, slab_tax - rebate)
    special_after = (
        slab_tax + special_tax - rebate - slab_after
    )  # the rebate may reach special tax if allowed
    by_kind: dict[str, tuple[int, int, int]] = {}
    shared, slab_total = 0, base.slab
    slab_keys = [k for k, v in base.slab_by_kind.items() if v]
    for i, k in enumerate(slab_keys):
        part = (
            slab_after - shared
            if i == len(slab_keys) - 1
            else slab_after * base.slab_by_kind[k] // slab_total
        )
        shared += part
        r = _cap(rate, kinds[k].surcharge_cap_bp)
        by_kind[k] = (part, r, _pct(part, r))
    special_raw = {k: _pct(v, kinds[k].rate_bp) for k, v in base.special.items()}
    for k, raw in special_raw.items():
        t = raw * special_after // special_tax if special_tax else 0
        r = _cap(rate, kinds[k].surcharge_cap_bp)
        by_kind[k] = (t, r, _pct(t, r))
    surcharge = sum(x[2] for x in by_kind.values()) if rate else 0
    return _Tax(slab_tax, special_tax, rebate, surcharge, by_kind)


def _surcharge_relief(rules: RulesLike, kinds: dict[str, KindLike], base: _Base, tax: _Tax) -> int:
    """Marginal relief: crossing a surcharge threshold cannot cost more than the income above it."""
    if not tax.surcharge:
        return 0
    threshold = max(s.above_paise for s in rules.surcharges if base.total > s.above_paise)
    excess = base.total - threshold
    # The same income cut down to the threshold: slab income first, then the lowest-taxed special income.
    left = excess
    slab = max(0, base.slab - left)
    left -= base.slab - slab
    scale = (lambda v: v * slab // base.slab) if base.slab else (lambda v: 0)
    slab_by_kind = {k: scale(v) for k, v in base.slab_by_kind.items()}
    special = dict(base.special)
    for k in sorted(special, key=lambda key: kinds[key].rate_bp):
        cut = min(special[k], left)
        special[k] -= cut
        left -= cut
    at = _tax(rules, kinds, _Base(slab_by_kind, special, threshold))
    over = (tax.before_surcharge + tax.surcharge) - (at.before_surcharge + at.surcharge + excess)
    return min(max(0, over), tax.surcharge)


def _lines(rules: RulesLike, amounts: dict[str, int]) -> tuple[dict[str, KindLine], _Base]:
    lines: dict[str, KindLine] = {}
    slab_by_kind: dict[str, int] = {}
    total = 0
    special: dict[str, int] = {}
    for k in rules.kinds:
        amt = amounts.get(k.key, 0)
        if k.treatment == "slab":
            ded = min(amt, rules.standard_deduction_paise) if k.standard_deduction else 0
            slab_by_kind[k.key] = amt - ded
            total += amt - ded
            lines[k.key] = KindLine(k.key, k.label, k.group, k.treatment, amt, ded, 0, amt - ded, None, 0)
        else:
            ded = min(amt, k.exemption_paise)
            special[k.key] = amt - ded
            total += amt
            lines[k.key] = KindLine(
                k.key, k.label, k.group, k.treatment, amt, ded, 0, amt - ded, k.rate_bp, 0
            )
    return lines, _Base(slab_by_kind, special, total)


def _use_basic_exemption(
    rules: RulesLike, kinds: dict[str, KindLike], base: _Base, lines: dict[str, KindLine]
) -> None:
    """A resident may set basic exemption left unused by slab income against some special-rate gains; it goes
    to the highest-taxed of them first, which is best for the taxpayer."""
    first = rules.slabs[0]
    basic = first.upto_paise if first.rate_bp == 0 and first.upto_paise else 0
    shortfall = max(0, basic - base.slab)
    for key in sorted(base.special, key=lambda x: -kinds[x].rate_bp):
        if not kinds[key].use_basic_exemption or not shortfall:
            continue
        use = min(base.special[key], shortfall)
        shortfall -= use
        base.special[key] -= use
        lines[key].basic_exemption_used_paise = use
        lines[key].taxable_paise -= use


def calculate(rules: RulesLike, amounts: dict[str, int]) -> Result:
    kinds = {k.key: k for k in rules.kinds}
    if unknown := set(amounts) - set(kinds):
        raise CalcError(f"Unknown kind of income: {', '.join(sorted(unknown))}.", code="bad_kind")
    if any(v < 0 for v in amounts.values()):
        raise CalcError(
            "Enter each kind of income as zero or more (net of its own losses).", code="negative_income"
        )
    lines, base = _lines(rules, amounts)
    _use_basic_exemption(rules, kinds, base, lines)
    tax = _tax(rules, kinds, base)
    for key, (its_tax, rate, its_surcharge) in tax.by_kind.items():
        lines[key].tax_paise = its_tax
        if tax.surcharge:
            lines[key].surcharge_rate_bp = rate
            lines[key].surcharge_paise = its_surcharge
    relief = _surcharge_relief(rules, kinds, base, tax)
    surcharge = tax.surcharge - relief
    cess = _pct(tax.before_surcharge + surcharge, rules.cess_bp)
    total = tax.before_surcharge + surcharge + cess
    step = rules.round_to_paise
    rounded = (total + step // 2) // step * step
    gross = sum(amounts.values())
    _, slab_lines = _slab_tax(rules, base.slab)
    notes = []
    if tax.rebate:
        marginal = base.total > rules.rebate_limit_paise
        notes.append("Rebate under section 87A" + (", with marginal relief." if marginal else "."))
    if any(line.basic_exemption_used_paise for line in lines.values()):
        notes.append("Basic exemption left unused by slab income is set against special-rate gains.")
    if relief:
        notes.append("Marginal relief on surcharge applied.")
    return Result(
        fy=rules.fy,
        name=rules.name,
        gross_paise=gross,
        total_income_paise=base.total,
        slab_income_paise=base.slab,
        slab_tax_paise=tax.slab,
        special_tax_paise=tax.special,
        rebate_paise=tax.rebate,
        tax_after_rebate_paise=tax.before_surcharge,
        surcharge_rate_bp=_surcharge_rate(rules, base.total),
        surcharge_paise=surcharge,
        surcharge_relief_paise=relief,
        cess_paise=cess,
        total_tax_paise=total,
        rounded_tax_paise=rounded,
        effective_rate_bp=(rounded * BP // gross) if gross else 0,
        kinds=[lines[k.key] for k in rules.kinds],
        slabs=slab_lines,
        notes=notes,
    )
