"""Plain-language "why" from calculation traces (NF-09, spec AI-08 without an LLM).

English only for now; translation happens from the same facts later.
"""

from __future__ import annotations

from handel.domain.rules.landed_cost import Component, LandedCost
from handel.domain.rules.ranking import RankedEntry

_NAMES = {
    "base": "Rate",
    "freight": "Freight",
    "charges": "Charges",
    "tax": "Tax",
    "money": "Cost of money",
}


def _component_line(name: str, c: Component) -> str:
    labels = ", ".join(sorted(label.value for label in c.labels))
    note = f"; {c.note}" if c.note else ""
    return f"{_NAMES[name]}: {c.per_kg}/kg ({labels}{note})"


def explain_landed_cost(lc: LandedCost) -> str:
    lines = [_component_line(name, c) for name, c in lc.components.items()]
    lines.append(f"Effective landed cost: {lc.effective}/kg")
    if lc.flags:
        lines.append("Warnings: " + ", ".join(sorted(f.value for f in lc.flags)))
    return "\n".join(lines)


def explain_step(lc: LandedCost, rule: str) -> str:
    """One step, e.g. RULE-L5, with its inputs: the answer to "why is this figure X?"."""
    s = lc.trace.step(rule)
    inputs = "; ".join(f"{k} = {v}" for k, v in s.inputs) or "none"
    return f"{s.what} ({s.rule}): {s.formula}. Inputs: {inputs}. Result: {s.result}."


def explain_entry(entry: RankedEntry, supplier_name: str) -> str:
    return f"#{entry.position} {supplier_name}: {entry.reason}."
