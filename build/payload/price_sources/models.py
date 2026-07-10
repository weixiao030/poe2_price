"""Shared data models for price-source adapters and the patch builder."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BaseItemPair:
    metadata_path: str
    en_name: str
    tc_name: str


@dataclass
class PriceObservation:
    api_id: str
    en_name: str
    category: str
    price_exalted: Decimal
    value_traded: Decimal
    source_pair: str
    display_price: str = ""
    english_name: str = ""
    source_timestamp: str = ""
    quality_flags: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PriceSourceResult:
    source: str
    raw: dict[str, Any] | None = None
    prices: dict[str, PriceObservation] | None = None
    unique_categories: list[dict[str, Any]] | None = None
    unique_items: list[dict[str, Any]] | None = None
    status: str = "skipped"
    warning: str = ""
    health_state: str = ""
    health: dict[str, Any] = field(default_factory=dict)
