"""Calculation traces: every engine records inputs, formula and result (architecture §8, NF-09).

Traces drive the plain-language explanations and the case page, so an explanation is
always the calculation that actually happened.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class TraceStep:
    rule: str  # e.g. "RULE-L5"
    what: str  # e.g. "cost of money"
    formula: str  # e.g. "(base + freight + charges) × r × d_pay/30"
    inputs: tuple[tuple[str, str], ...]  # ordered (name, rendered value)
    result: str


@dataclass(frozen=True, slots=True)
class Trace:
    steps: tuple[TraceStep, ...] = field(default_factory=tuple)

    def step(self, rule: str) -> TraceStep:
        for s in self.steps:
            if s.rule == rule:
                return s
        raise KeyError(rule)
