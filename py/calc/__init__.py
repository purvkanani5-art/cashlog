"""Financial calculator (docs/decisions.md #120).

Self-contained: this package imports nothing else from the app, only the standard library, so the very same
files run in Kuberlekha (behind /api/v1/calc) and on the phone in Cash Log (under Pyodide). Every answer is
worked in 40-digit decimals.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import cashflow, rates, tvm, utils  # noqa: F401  (each module registers its calculators)
from .core import FAMILIES, REGISTRY, CalcError, Inputs, result_dict
from .expr import evaluate

ENGINE_VERSION = "1"

__all__ = ["ENGINE_VERSION", "CalcError", "catalogue", "evaluate", "run"]


def catalogue() -> dict[str, Any]:
    """Every calculator and its fields, grouped by family, for the screens to draw the forms."""
    return {
        "version": ENGINE_VERSION,
        "families": [
            {"key": k, "title": t, "calculators": [c.as_dict() for c in REGISTRY.values() if c.family == k]}
            for k, t in FAMILIES
        ],
    }


def run(key: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
    calc = REGISTRY.get(key)
    if calc is None:
        raise CalcError(f"There is no calculator called {key}.", code="no_calculator")
    return result_dict(calc.run(Inputs(inputs, calc.fields)))
