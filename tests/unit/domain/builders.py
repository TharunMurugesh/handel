"""Small builders so tests state only what matters to them."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from handel.domain.model.entities import (
    FreightTerms,
    Material,
    Need,
    PaymentKind,
    PaymentTerms,
    Quote,
    Supplier,
    SupplierMode,
    Unit,
)
from handel.domain.model.money import Money
from handel.domain.model.quantity import RateUnit, Weight

TODAY = date(2026, 12, 1)
NOW = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)


def unit(**kw: Any) -> Unit:
    base: dict[str, Any] = {
        "id": "U1",
        "name": "Demo Fabricators",
        "itc_eligible": True,
        "cost_of_money_monthly": Decimal("0.015"),
    }
    return Unit(**(base | kw))


def material(**kw: Any) -> Material:
    return Material(**({"id": "MS-SHEET-2", "category": "MS sheet 2 mm"} | kw))


def need(**kw: Any) -> Need:
    base: dict[str, Any] = {
        "id": "N1",
        "unit_id": "U1",
        "material_id": "MS-SHEET-2",
        "spec": "MS sheet 2 mm, 8×4",
        "quantity": Weight.of("2000"),
        "needed_by": date(2026, 12, 10),
        "location": "Demo industrial estate",
    }
    return Need(**(base | kw))


def supplier(sid: str, name: str | None = None, **kw: Any) -> Supplier:
    return Supplier(id=sid, name=name or f"Supplier {sid}", **kw)


def compete(sid: str, name: str | None = None, **kw: Any) -> Supplier:
    return supplier(sid, name, mode=SupplierMode.COMPETE, **kw)


def relationship(sid: str, name: str | None = None, **kw: Any) -> Supplier:
    return supplier(sid, name, mode=SupplierMode.RELATIONSHIP, **kw)


def quote(qid: str = "Q1", supplier_id: str = "S1", **kw: Any) -> Quote:
    base: dict[str, Any] = {
        "id": qid,
        "case_id": "C1",
        "supplier_id": supplier_id,
        "received_at": NOW,
        "rate": Money.rupees("62.00"),
        "rate_unit": RateUnit.PER_KG,
        "quantity": Weight.of("2000"),
        "gst_pct": Decimal(18),
        "tax_invoice": True,
        "freight_terms": FreightTerms.DELIVERED,
        "payment": PaymentTerms(kind=PaymentKind.ON_DELIVERY),
        "delivery_date": date(2026, 12, 8),
        "valid_until": date(2026, 12, 5),
    }
    return Quote(**(base | kw))
