"""Cash Log's bridge to the calculator engine, run under Pyodide on the phone.

The engine in calc/ is copied unchanged from Kuberlekha (scripts/export_calc.py there), so every answer here is
the one Kuberlekha gives. Each function takes and returns JSON text, which keeps the JavaScript side simple:
{"ok": true, "value": ...} or {"ok": false, "code", "message", "field"}.
"""

from __future__ import annotations

import dataclasses
import json
import traceback
from collections.abc import Callable
from typing import Any

from calc import CalcError, catalogue, evaluate, run, tax_engine
from calc.core import parse_number


def _wrap(fn: Callable[[], Any]) -> str:
    try:
        return json.dumps({"ok": True, "value": fn()}, ensure_ascii=False)
    except CalcError as e:
        return json.dumps({"ok": False, "code": e.code, "message": e.message, "field": e.field}, ensure_ascii=False)
    except Exception as e:  # a bug, not a typing mistake: say so plainly
        traceback.print_exc()
        return json.dumps({"ok": False, "code": "internal", "message": f"The calculator failed: {e}", "field": None})


def catalogue_json() -> str:
    return _wrap(catalogue)


def run_json(key: str, inputs: str) -> str:
    return _wrap(lambda: run(key, json.loads(inputs)))


def evaluate_json(expression: str, registers: str) -> str:
    return _wrap(lambda: evaluate(expression, json.loads(registers)))


def tax_json(rules: str, amounts: str) -> str:
    def go() -> dict[str, Any]:
        plain = tax_engine.rules_from_dict(json.loads(rules))
        return dataclasses.asdict(tax_engine.calculate(plain, json.loads(amounts)))

    return _wrap(go)


def tax_text_json(rules: str, amounts: str) -> str:
    """Like tax_json, with each amount as typed (1,25,000 or 12.75L); a wrong one is named by its field."""

    def go() -> dict[str, Any]:
        plain = tax_engine.rules_from_dict(json.loads(rules))
        labels = {k.key: k.label for k in plain.kinds}
        paise: dict[str, int] = {}
        for key, text in json.loads(amounts).items():
            if key not in labels or not str(text).strip():
                continue
            v = parse_number(str(text))
            if v is None:
                raise CalcError(f"{labels[key]}: '{text}' is not an amount.", key)
            if v < 0:
                raise CalcError(f"{labels[key]}: enter zero or more, net of its own losses.", key)
            p = v * 100
            if p != p.to_integral_value():
                raise CalcError(f"{labels[key]}: at most two decimals (paise).", key)
            paise[key] = int(p)
        return dataclasses.asdict(tax_engine.calculate(plain, paise))

    return _wrap(go)
