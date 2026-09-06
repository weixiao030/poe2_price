#!/usr/bin/env python3
"""Read-only live contract audit for every market data source.

This command never reads or modifies game files and never builds a release.  It
uses the same stdlib HTTP client and parsers as the patch builder, but writes a
small, value-free schema report instead of a price patch.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urljoin, urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_poe1_price_patch as poe1_builder
import build_poe2scout_price_patch as builder
from price_sources.health import (
    PARTIAL,
    STALE,
    SourceHealth,
    evaluate_source_health,
    failed_source_health,
)
from price_sources.league import LeagueSelection, resolve_current_leagues


REPORT_VERSION = 2
DEFAULT_OUTPUT = Path("output") / "data-source-audit.json"
MAX_SOURCE_AGE_SECONDS = 48 * 60 * 60


class RecordingClient:
    """Record response metadata while preserving the builder client's API."""

    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.total_timeout = getattr(delegate, "total_timeout", 0)
        self._lock = threading.Lock()
        self.observations: list[dict[str, Any]] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        try:
            response = self.delegate.get(url, **kwargs)
        except Exception as exc:
            with self._lock:
                self.observations.append(
                    {
                        "url": url,
                        "status_code": None,
                        "content_type": "",
                        "content_bytes": None,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            raise
        content = getattr(response, "content", b"")
        with self._lock:
            self.observations.append(
                {
                    "url": str(getattr(response, "url", url) or url),
                    "status_code": getattr(response, "status_code", None),
                    "content_type": str(getattr(response, "content_type", "") or ""),
                    "content_bytes": len(content) if content is not None else None,
                }
            )
        return response

    def get_json(self, url: str) -> Any:
        return self.get(url).json()

    def latest_http(self, predicate: Callable[[str], bool]) -> dict[str, Any] | None:
        with self._lock:
            rows = list(self.observations)
        for row in reversed(rows):
            if predicate(str(row.get("url") or "")):
                return row
        return None


class TolerantNinjaClient:
    """Turn optional poe.ninja category failures into empty category payloads."""

    def __init__(self, client: RecordingClient) -> None:
        self.client = client
        self.total_timeout = client.total_timeout
        self._lock = threading.Lock()
        self.payloads: dict[str, Any] = {}
        self.failures: dict[str, str] = {}

    def get_json(self, url: str) -> Any:
        kind, item_type = _ninja_category(url)
        label = f"{kind}:{item_type}"
        try:
            payload = self.client.get_json(url)
            with self._lock:
                self.payloads[label] = payload
            _validate_ninja_payload(payload, label)
            return payload
        except Exception as exc:
            if label == "exchange:Currency":
                raise
            with self._lock:
                self.failures[label] = f"{type(exc).__name__}: {exc}"
            return {"core": {}, "lines": [], "items": []}


def _ninja_category(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    values = parse_qs(parsed.query).get("type") or ["unknown"]
    kind = "item" if "/stash/" in parsed.path else "exchange"
    return kind, str(values[0])


def _validate_ninja_payload(payload: Any, label: str) -> None:
    if not isinstance(payload, dict):
        raise ValueError(f"{label} root is not an object")
    if not isinstance(payload.get("core"), dict):
        raise ValueError(f"{label} core is not an object")
    if not isinstance(payload.get("lines"), list):
        raise ValueError(f"{label} lines is not an array")
    if not payload.get("lines"):
        raise ValueError(f"{label} lines is empty")
    if label.startswith("exchange:") and not isinstance(payload.get("items"), list):
        raise ValueError(f"{label} items is not an array")


def _canonical_item_names(prices: Mapping[str, Any]) -> list[str]:
    names = [
        str(getattr(observation, "en_name", "") or "")
        for observation in prices.values()
    ]
    if "divine" in prices:
        names.append("Divine Orb")
    if "exalted" in prices:
        names.append("Exalted Orb")
    return [name for name in names if name]


def _object_fields(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return sorted(str(key) for key in value)
    return []


def _array_item_fields(value: Any) -> list[str]:
    fields: set[str] = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, Mapping):
                fields.update(str(key) for key in item)
    return sorted(fields)


def _ninja_field_sets(payloads: Mapping[str, Any]) -> dict[str, list[str]]:
    root: set[str] = set()
    core: set[str] = set()
    lines: set[str] = set()
    items: set[str] = set()
    for payload in payloads.values():
        if not isinstance(payload, Mapping):
            continue
        root.update(str(key) for key in payload)
        core.update(_object_fields(payload.get("core")))
        lines.update(_array_item_fields(payload.get("lines")))
        items.update(_array_item_fields(payload.get("items")))
    return {
        "root": sorted(root),
        "core": sorted(core),
        "lines": sorted(lines),
        "items": sorted(items),
    }


POE_NINJA_VIEW_RE = re.compile(
    r"availableViews:\[(?P<views>[^\]]*)\]"
    r"(?:(?!availableViews:).)*?title:(?P<title_q>[\"'`])"
    r"(?P<title>(?:\\.|(?!(?P=title_q)).)*)(?P=title_q)"
    r",type:(?P<type_q>[\"'`])"
    r"(?P<type>(?:\\.|(?!(?P=type_q)).)*)(?P=type_q)"
    r",url:(?P<url_q>[\"'`])"
    r"(?P<url>(?:\\.|(?!(?P=url_q)).)*)(?P=url_q)",
    flags=re.S,
)
JS_STRING_RE = re.compile(
    r"(?P<quote>[\"'`])(?P<value>(?:\\.|(?!(?P=quote)).)*)(?P=quote)",
    flags=re.S,
)


def poe_ninja_economy_page_url(league_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", str(league_name).casefold())
    if not slug:
        return builder.DEFAULT_POE_NINJA_CURRENCY_URL
    return f"https://poe.ninja/poe2/economy/{slug}/currency"


def _html_attributes(tag: str) -> dict[str, str]:
    return {
        name.casefold(): html.unescape(value)
        for name, _quote, value in re.findall(
            r"([:\w-]+)\s*=\s*([\"'])(.*?)\2", tag, flags=re.S
        )
    }


def _js_string(value: str) -> str:
    try:
        return str(json.loads(f'\"{value}\"'))
    except (json.JSONDecodeError, TypeError):
        return value


def parse_poe_ninja_site_categories(source: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    by_type: dict[str, dict[str, Any]] = {}
    for match in POE_NINJA_VIEW_RE.finditer(source):
        views = [
            _js_string(item.group("value"))
            for item in JS_STRING_RE.finditer(match.group("views"))
        ]
        entry = {
            "available_views": views,
            "title": _js_string(match.group("title")),
            "type": _js_string(match.group("type")),
            "url": _js_string(match.group("url")),
        }
        item_type = str(entry["type"])
        if not item_type or not set(views).intersection({"exchange", "stash"}):
            continue
        old = by_type.get(item_type)
        if old is not None and old != entry:
            raise ValueError(f"poe.ninja site category {item_type} is defined twice")
        if old is None:
            by_type[item_type] = entry
            entries.append(entry)
    return entries


def discover_poe_ninja_site_categories(
    client: RecordingClient,
    league_name: str,
    *,
    max_workers: int = 8,
) -> dict[str, Any]:
    """Discover the site's current categories without pinning Astro hashes."""

    requested_page_url = poe_ninja_economy_page_url(league_name)
    page_urls = list(
        dict.fromkeys((requested_page_url, builder.DEFAULT_POE_NINJA_CURRENCY_URL))
    )
    page_url = ""
    component_url = ""
    page_errors: list[str] = []
    for candidate_url in page_urls:
        try:
            response = client.get(candidate_url)
            status_code = getattr(response, "status_code", 200)
            if status_code is not None and not 200 <= int(status_code) < 300:
                raise ValueError(f"HTTP {status_code}")
            for match in re.finditer(
                r"<astro-island\b[^>]*>", response.text, flags=re.I | re.S
            ):
                attributes = _html_attributes(match.group(0))
                if attributes.get("component-export") != "Poe2CurrencyOverviewPage":
                    continue
                page_url = candidate_url
                component_url = urljoin(
                    candidate_url, attributes.get("component-url", "")
                )
                break
            if component_url:
                break
            raise ValueError("Poe2CurrencyOverviewPage Astro component was not found")
        except Exception as exc:
            page_errors.append(f"{candidate_url}: {type(exc).__name__}: {exc}")
    if not component_url:
        raise ValueError("; ".join(page_errors))

    component_response = client.get(component_url)
    component_status = getattr(component_response, "status_code", 200)
    if component_status is not None and not 200 <= int(component_status) < 300:
        raise ValueError(f"Astro component returned HTTP {component_status}")
    component_source = component_response.text
    imports = sorted(
        {
            urljoin(component_url, path)
            for path in re.findall(
                r"[\"']([^\"']+\.mjs(?:\?[^\"']*)?)[\"']",
                component_source,
            )
        }
    )
    candidates: list[tuple[str, list[dict[str, Any]]]] = [
        (component_url, parse_poe_ninja_site_categories(component_source))
    ]
    import_errors: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(imports) or 1))) as pool:
        futures = {pool.submit(client.get, url): url for url in imports}
        for future in as_completed(futures):
            url = futures[future]
            try:
                response = future.result()
                status_code = getattr(response, "status_code", 200)
                if status_code is not None and not 200 <= int(status_code) < 300:
                    raise ValueError(f"HTTP {status_code}")
                categories = parse_poe_ninja_site_categories(response.text)
                if categories:
                    candidates.append((url, categories))
            except Exception as exc:
                import_errors.append(f"{url}: {type(exc).__name__}: {exc}")

    module_url, categories = max(candidates, key=lambda item: len(item[1]))
    if not categories:
        detail = f"; {len(import_errors)} imports failed" if import_errors else ""
        raise ValueError(f"no availableViews category contract found in Astro imports{detail}")
    return {
        "status": "ok",
        "page_url": page_url,
        "requested_page_url": requested_page_url,
        "used_default_page_fallback": page_url != requested_page_url,
        "component_url": component_url,
        "contract_module_url": module_url,
        "import_count": len(imports),
        "import_failure_count": len(import_errors),
        "categories": categories,
    }


def compare_poe_ninja_site_categories(
    discovered: Mapping[str, Any],
    configured_views: Mapping[str, str],
) -> dict[str, Any]:
    categories = discovered.get("categories")
    if not isinstance(categories, list):
        categories = []
    site_types = sorted(
        {
            str(item.get("type") or "")
            for item in categories
            if isinstance(item, Mapping) and str(item.get("type") or "")
        }
    )
    configured_types = sorted(str(value) for value in configured_views)
    site_only = sorted(set(site_types).difference(configured_types))
    configured_only = sorted(set(configured_types).difference(site_types))
    view_mismatches: list[dict[str, Any]] = []
    for item in categories:
        if not isinstance(item, Mapping):
            continue
        item_type = str(item.get("type") or "")
        expected = configured_views.get(item_type)
        views = sorted(str(value) for value in (item.get("available_views") or []))
        if expected and expected not in views:
            view_mismatches.append(
                {"type": item_type, "configured_view": expected, "site_views": views}
            )
    return {
        **dict(discovered),
        "discovered_count": len(site_types),
        "site_types": site_types,
        "configured_types": configured_types,
        "site_only": site_only,
        "configured_only": configured_only,
        "view_mismatches": view_mismatches,
        "has_drift": bool(site_only or configured_only or view_mismatches),
    }


def _baseline_contract(
    baseline: Mapping[str, Any] | None, source: str
) -> Mapping[str, Any] | None:
    if not isinstance(baseline, Mapping):
        return None
    sources = baseline.get("sources")
    if not isinstance(sources, Mapping):
        return None
    entry = sources.get(source)
    if not isinstance(entry, Mapping):
        return None
    contract = entry.get("contract")
    if isinstance(contract, Mapping):
        return contract
    if "categories" in entry or "field_sets" in entry:
        return entry
    metrics = entry.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    categories = metrics.get("contract_categories")
    if categories is None and isinstance(metrics.get("categories"), Mapping):
        categories = metrics["categories"].get("discovered")
    return {"categories": categories or [], "field_sets": metrics.get("field_sets") or {}}


def compare_contract(
    baseline_contract: Mapping[str, Any] | None,
    categories: Any,
    field_sets: Mapping[str, Any],
    *,
    baseline_expected: bool,
) -> dict[str, Any]:
    current_categories = sorted({str(value) for value in (categories or []) if str(value)})
    previous_categories: list[str] = []
    previous_fields: dict[str, set[str]] = {}
    baseline_present = isinstance(baseline_contract, Mapping)
    if baseline_present:
        previous_categories = sorted(
            {
                str(value)
                for value in (baseline_contract.get("categories") or [])
                if str(value)
            }
        )
        raw_fields = baseline_contract.get("field_sets") or {}
        if isinstance(raw_fields, Mapping):
            previous_fields = {
                str(group): {str(value) for value in (values or []) if str(value)}
                for group, values in raw_fields.items()
                if isinstance(values, (list, tuple, set))
            }
    current_fields = {
        str(group): {str(value) for value in (values or []) if str(value)}
        for group, values in field_sets.items()
        if isinstance(values, (list, tuple, set))
    }
    field_groups = sorted(set(previous_fields).union(current_fields))
    added_fields = [
        f"{group}.{field}"
        for group in field_groups
        for field in sorted(current_fields.get(group, set()) - previous_fields.get(group, set()))
    ]
    removed_fields = [
        f"{group}.{field}"
        for group in field_groups
        for field in sorted(previous_fields.get(group, set()) - current_fields.get(group, set()))
    ]
    added_categories = (
        sorted(set(current_categories).difference(previous_categories))
        if baseline_present
        else []
    )
    removed_categories = (
        sorted(set(previous_categories).difference(current_categories))
        if baseline_present
        else []
    )
    if not baseline_present:
        added_fields = []
        removed_fields = []
    baseline_missing = baseline_expected and not baseline_present
    return {
        "baseline_present": baseline_present,
        "baseline_missing": baseline_missing,
        "has_drift": bool(
            baseline_missing
            or added_categories
            or removed_categories
            or added_fields
            or removed_fields
        ),
        "added_categories": added_categories,
        "removed_categories": removed_categories,
        "added_fields": added_fields,
        "removed_fields": removed_fields,
    }


def _baseline_schema(baseline: Mapping[str, Any] | None, source: str) -> Any:
    if not isinstance(baseline, Mapping):
        return None
    sources = baseline.get("sources")
    if not isinstance(sources, Mapping):
        return None
    entry = sources.get(source)
    if not isinstance(entry, Mapping):
        return None
    health = entry.get("health")
    if not isinstance(health, Mapping):
        return None
    schema = health.get("schema")
    return schema if isinstance(schema, Mapping) else None


def _entry(
    health: SourceHealth,
    metrics: Mapping[str, Any],
    *,
    contract_drift: Mapping[str, Any] | None = None,
    partial_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    reasons = list(partial_reasons)
    if contract_drift and contract_drift.get("has_drift"):
        reasons.append("contract_drift")
    status = health.state
    if health.usable and reasons:
        status = PARTIAL
    return {
        "status": status,
        "health": health.to_dict(),
        "metrics": dict(metrics),
        "contract_drift": dict(contract_drift) if contract_drift is not None else None,
        "status_reasons": sorted(set(reasons)),
    }


def audit_poe2scout(
    client: RecordingClient,
    league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    max_workers: int,
) -> dict[str, Any]:
    api_base = builder.DEFAULT_SCOUT_API.rstrip("/")
    raw = builder.fetch_scout_data(client, api_base, league.scout)
    observations = builder.collect_price_observations(raw["snapshot_pairs"])
    prices = builder.choose_best_prices(observations, raw["reference_currencies"])

    categories: list[dict[str, Any]] = []
    unique_items: list[dict[str, Any]] = []
    succeeded_unique: list[str] = []
    failed_unique: dict[str, str] = {}
    try:
        discovered = builder.fetch_unique_categories(client, api_base, league.scout)
        categories = [
            category
            for category in discovered
            if isinstance(category, dict) and str(category.get("ApiId") or "").strip()
        ]
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(categories) or 1))) as pool:
            futures = {
                pool.submit(
                    builder.fetch_unique_category_items,
                    client,
                    api_base,
                    league.scout,
                    str(category["ApiId"]),
                ): str(category["ApiId"])
                for category in categories
            }
            for future in as_completed(futures):
                category = futures[future]
                try:
                    items = future.result()
                    if not items:
                        raise ValueError("category returned no unique items")
                    unique_items.extend(items)
                    succeeded_unique.append(category)
                except Exception as exc:
                    failed_unique[category] = f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        failed_unique["unique-category-discovery"] = f"{type(exc).__name__}: {exc}"

    if unique_items:
        builder.add_unique_observations(prices, unique_items)

    core_categories = [
        "core:exchange_snapshot",
        "core:reference_currencies",
        "core:snapshot_pairs",
    ]
    unique_categories = [str(category.get("ApiId")) for category in categories]
    currency_categories: list[str] = []
    category_health: dict[str, Any] = {}
    try:
        listed = builder.fetch_item_categories(client, api_base, league.scout)
        currency_categories = builder.category_api_ids(listed.get("currency") or [])
        category_health = builder.build_scout_category_health(
            listed.get("unique") or categories,
            listed.get("currency") or [],
        )
    except Exception as exc:
        category_health = {
            "has_alerts": True,
            "alerts": ["category_index_failed"],
            "index_error": f"{type(exc).__name__}: {exc}",
        }
    currency_labels = [f"currency:{item}" for item in currency_categories]
    discovered_categories = core_categories + currency_labels + (
        unique_categories or (["unique-category-discovery"] if failed_unique else [])
    )
    succeeded_categories = core_categories + succeeded_unique
    failed_categories = sorted(failed_unique)
    audit_payload = {
        "core": raw,
        "unique_categories": categories,
        "unique_items": unique_items,
    }
    snapshot = raw.get("exchange_snapshot") or {}
    health = evaluate_source_health(
        "poe2scout",
        audit_payload,
        expected_root="object",
        http=client.latest_http(lambda url: url.endswith("/SnapshotPairs")),
        item_count=len(prices),
        match_count=len(prices),
        item_names=_canonical_item_names(prices),
        discovered_categories=discovered_categories,
        enabled_categories=discovered_categories,
        succeeded_categories=succeeded_categories,
        failed_categories=failed_categories,
        freshness_timestamp=snapshot.get("Epoch") if isinstance(snapshot, Mapping) else None,
        max_age_seconds=MAX_SOURCE_AGE_SECONDS,
        key_fields=("ApiId", "Text", "RelativePrice", "ValueTraded"),
        baseline_schema=_baseline_schema(baseline, "poe2scout"),
    )
    field_sets = {
        "exchange_snapshot": _object_fields(raw.get("exchange_snapshot")),
        "reference_currency": _array_item_fields(raw.get("reference_currencies")),
        "snapshot_pair": _array_item_fields(raw.get("snapshot_pairs")),
        "unique_category": _array_item_fields(categories),
        "unique_item": _array_item_fields(unique_items),
    }
    metrics = {
        "league": league.scout,
        "snapshot_pairs": len(raw.get("snapshot_pairs") or []),
        "reference_currencies": len(raw.get("reference_currencies") or []),
        "price_items": len(prices),
        "unique_items": len(unique_items),
        "categories": {
            "discovered": discovered_categories,
            "succeeded": succeeded_categories,
            "failed": failed_unique,
        },
        "category_health": category_health,
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poe2scout"),
        discovered_categories,
        field_sets,
        baseline_expected=baseline is not None,
    )
    extra_reasons = []
    if category_health.get("has_alerts"):
        extra_reasons.append("scout_category_health")
    return _entry(
        health,
        metrics,
        contract_drift=contract_drift,
        partial_reasons=tuple(extra_reasons),
    )


def audit_poe_ninja(
    client: RecordingClient,
    league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    max_workers: int,
) -> dict[str, Any]:
    tolerant = TolerantNinjaClient(client)
    raw, prices = builder.build_poe_ninja_currency_prices(
        tolerant,
        builder.DEFAULT_POE_NINJA_CURRENCY_URL,
        builder.DEFAULT_POE_NINJA_API_URL,
        league.poe_ninja,
        builder.DEFAULT_POE_NINJA_ITEM_API_URL,
        builder.DEFAULT_POE_NINJA_UNIQUE_ARMOURS_URL,
    )
    enabled = [
        f"exchange:{name}" for name in builder.POE_NINJA_EXCHANGE_TYPES
    ] + [f"item:{name}" for name in builder.POE_NINJA_ITEM_TYPES]
    configured_views = {
        **{str(name): "exchange" for name in builder.POE_NINJA_EXCHANGE_TYPES},
        **{str(name): "stash" for name in builder.POE_NINJA_ITEM_TYPES},
    }
    site_partial_reasons: list[str] = []
    try:
        discovered_site = discover_poe_ninja_site_categories(
            client,
            league.poe_ninja,
            max_workers=max_workers,
        )
        site_contract = compare_poe_ninja_site_categories(
            discovered_site,
            configured_views,
        )
        if site_contract["has_drift"]:
            site_partial_reasons.append("site_category_drift")
        if site_contract.get("used_default_page_fallback"):
            site_partial_reasons.append("site_page_default_fallback")
        if int(site_contract.get("import_failure_count") or 0) > 0:
            site_partial_reasons.append("site_category_import_failures")
    except Exception as exc:
        site_contract = {
            "status": "failed",
            "page_url": poe_ninja_economy_page_url(league.poe_ninja),
            "component_url": "",
            "contract_module_url": "",
            "categories": [],
            "discovered_count": 0,
            "site_types": [],
            "configured_types": sorted(configured_views),
            "site_only": [],
            "configured_only": [],
            "view_mismatches": [],
            "has_drift": False,
            "discovery_error": f"{type(exc).__name__}: {exc}",
        }
        site_partial_reasons.append("site_category_discovery_failed")
    failed = sorted(tolerant.failures)
    succeeded = sorted(set(enabled).difference(failed))
    health = evaluate_source_health(
        "poe.ninja",
        tolerant.payloads,
        expected_root="object",
        http=client.latest_http(
            lambda url: "/exchange/" in url and "type=Currency" in url
        ),
        item_count=len(prices),
        match_count=len(prices),
        item_names=_canonical_item_names(prices),
        discovered_categories=enabled,
        enabled_categories=enabled,
        succeeded_categories=succeeded,
        failed_categories=failed,
        key_fields=("core", "lines", "items", "primaryValue"),
        baseline_schema=_baseline_schema(baseline, "poe.ninja"),
    )
    field_sets = _ninja_field_sets(tolerant.payloads)
    contract_categories = sorted(configured_views)
    metrics = {
        "league": league.poe_ninja,
        "price_items": len(prices),
        "lines": int(raw.get("lines") or 0),
        "items": int(raw.get("items") or 0),
        "reference_price_exalted": raw.get("divine_price_exalted"),
        "categories": {
            "discovered": enabled,
            "succeeded": succeeded,
            "failed": tolerant.failures,
        },
        "contract_categories": contract_categories,
        "site_contract": site_contract,
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poe.ninja"),
        contract_categories,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(
        health,
        metrics,
        contract_drift=contract_drift,
        partial_reasons=tuple(site_partial_reasons),
    )


def audit_poecurrency(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    _max_workers: int,
) -> dict[str, Any]:
    payload = client.get_json(builder.DEFAULT_POECURRENCY_SUMMARY_API)
    normalized = builder.normalize_poecurrency_summary(payload)
    prices, quality = builder.collect_poecurrency_observations_with_quality(payload)
    categories = [
        str(category.get("category_label") or "")
        for category in normalized
        if str(category.get("category_label") or "")
    ]
    succeeded: list[str] = []
    failed: list[str] = []
    for category in normalized:
        label = str(category.get("category_label") or "unnamed")
        items = category.get("items")
        (succeeded if isinstance(items, list) and items else failed).append(label)
    reference_units = sorted(
        {
            str(item.get("currency_unit") or "").strip().casefold()
            for category in normalized
            for item in (category.get("items") or [])
            if isinstance(item, Mapping)
            and str(item.get("currency_unit") or "").strip()
        }
    )

    health = evaluate_source_health(
        "poecurrency.top",
        payload,
        expected_root=("array", "object"),
        http=client.latest_http(lambda url: "poecurrency.top/api/summary" in url),
        item_count=int(quality.get("item_count") or 0),
        match_count=len(prices),
        item_names=_canonical_item_names(prices),
        # Exalted is this API's base denomination (currency_unit=e), not a
        # guaranteed item row.  A Divine/e quote is the required conversion.
        required_references=("Divine Orb",),
        discovered_categories=categories,
        enabled_categories=categories,
        succeeded_categories=succeeded,
        failed_categories=failed,
        freshness_timestamp=quality.get("source_timestamp_max") or None,
        max_age_seconds=MAX_SOURCE_AGE_SECONDS,
        key_fields=quality.get("field_set") or (),
        baseline_schema=_baseline_schema(baseline, "poecurrency.top"),
        minimum_match_ratio=0.5,
    )
    field_sets = {
        "category": _array_item_fields(normalized),
        "item": list(quality.get("field_set") or []),
    }
    metrics = {
        "price_items": len(prices),
        "reference_units": reference_units,
        "categories": {
            "discovered": categories,
            "succeeded": succeeded,
            "failed": failed,
        },
        "field_sets": field_sets,
        "quality": quality,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poecurrency.top"),
        categories,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


def audit_poe2db(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    _max_workers: int,
) -> dict[str, Any]:
    raw, prices = builder.build_poe2db_economy_prices(
        client,
        builder.DEFAULT_POE2DB_ECONOMY_US_URL,
        builder.DEFAULT_POE2DB_ECONOMY_CN_URL,
    )
    discovered = list(raw.get("discovered_categories") or raw.get("category_pages") or [])
    succeeded = list(raw.get("healthy_categories") or [])
    failed = list(raw.get("failed_categories") or [])
    health = evaluate_source_health(
        "poe2db",
        raw,
        expected_root="object",
        http=client.latest_http(
            lambda url: url.rstrip("/") == builder.DEFAULT_POE2DB_ECONOMY_US_URL
        ),
        item_count=int(raw.get("us_rows") or 0),
        match_count=len(prices),
        item_names=_canonical_item_names(prices),
        discovered_categories=discovered,
        enabled_categories=discovered,
        succeeded_categories=succeeded,
        failed_categories=failed,
        key_fields=("page", "us_rows", "cn_rows", "status"),
        baseline_schema=_baseline_schema(baseline, "poe2db"),
        minimum_match_ratio=0.5,
        accepted_content_types=("text/html",),
    )
    field_sets = {
        "summary": _object_fields(raw),
        "category_stat": _array_item_fields(raw.get("category_page_stats")),
    }
    metrics = {
        "price_items": len(prices),
        "us_rows": int(raw.get("us_rows") or 0),
        "cn_rows": int(raw.get("cn_rows") or 0),
        "categories": {
            "discovered": discovered,
            "succeeded": succeeded,
            "failed": failed,
        },
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poe2db"),
        discovered,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


def audit_poe1_ninja(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    _max_workers: int,
) -> dict[str, Any]:
    ninja_league, _source, warnings = poe1_builder.discover_poe_ninja_league(
        client,
        poe1_builder.DEFAULT_POE_NINJA_INDEX_URL,
        None,
    )
    raw, prices, divine_chaos = poe1_builder.fetch_poe_ninja_prices(
        client,
        poe1_builder.DEFAULT_POE_NINJA_EXCHANGE_API,
        poe1_builder.DEFAULT_POE_NINJA_ITEM_API,
        ninja_league,
        include_uniques=False,
    )
    discovered = [str(item) for item in poe1_builder.POE_NINJA_EXCHANGE_TYPES]
    failed = [str(item) for item in raw.get("failed_categories") or []]
    succeeded = [item for item in discovered if f"exchange:{item}" not in failed]
    field_sets = {
        "exchange": _array_item_fields(
            ((raw.get("exchange_payloads") or {}).get("Currency") or {}).get("lines")
        ),
        "root": _object_fields((raw.get("exchange_payloads") or {}).get("Currency")),
    }
    health = evaluate_source_health(
        "poe.ninja-poe1",
        raw,
        expected_root="object",
        http=client.latest_http(lambda url: "/poe1/api/economy/exchange/" in url),
        item_count=len(prices),
        match_count=len(prices),
        item_names=sorted({item.en_name for item in prices.values() if item.en_name}),
        discovered_categories=discovered,
        enabled_categories=discovered,
        succeeded_categories=succeeded,
        failed_categories=failed,
        key_fields=("lines", "items", "primaryValue"),
        baseline_schema=_baseline_schema(baseline, "poe.ninja-poe1"),
    )
    metrics = {
        "league": ninja_league,
        "league_warnings": list(warnings),
        "price_items": len(prices),
        "divine_price_chaos": str(divine_chaos),
        "categories": {
            "discovered": discovered,
            "succeeded": succeeded,
            "failed": failed,
        },
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poe.ninja-poe1"),
        discovered,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


def audit_poe1_poecurrency(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    _max_workers: int,
) -> dict[str, Any]:
    payload = client.get_json(poe1_builder.DEFAULT_POECURRENCY_SUMMARY_API)
    prices, divine_chaos, quality = poe1_builder.collect_poecurrency_prices(
        payload,
        Decimal("0"),
    )
    normalized = builder.normalize_poecurrency_summary(payload)
    categories = [
        str(category.get("category_label") or "")
        for category in normalized
        if str(category.get("category_label") or "")
    ]
    field_sets = {
        "category": ["category_label", "items"],
        "item": _array_item_fields(
            next((category.get("items") for category in normalized if category.get("items")), [])
        ),
    }
    health = evaluate_source_health(
        "poecurrency.top-poe1",
        payload if isinstance(payload, dict) else {"categories": payload},
        expected_root="object",
        http=client.latest_http(lambda url: "poecurrency.top" in url and "version=1" in url),
        item_count=len(prices),
        match_count=len(prices),
        item_names=sorted({item.en_name or item.localized_name for item in prices.values()}),
        discovered_categories=categories,
        enabled_categories=categories,
        succeeded_categories=categories,
        key_fields=("item_name", "engname", "latest_buy1", "latest_sell1"),
        baseline_schema=_baseline_schema(baseline, "poecurrency.top-poe1"),
    )
    metrics = {
        "price_items": len(prices),
        "divine_price_chaos": str(divine_chaos),
        "quality": quality,
        "categories": {
            "discovered": categories,
            "succeeded": categories,
            "failed": [],
        },
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poecurrency.top-poe1"),
        categories,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


def audit_poe1_scout(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    _max_workers: int,
) -> dict[str, Any]:
    raw, prices, divine_chaos = poe1_builder.fetch_poe2scout_poe1_prices(
        client,
        poe1_builder.DEFAULT_POE2SCOUT_API,
        "",
        poe1_builder.DEFAULT_POE2SCOUT_REALM,
    )
    categories = sorted(
        {
            str(item.category)
            for item in prices.values()
            if item.category
        }
    )
    field_sets = {
        "reference_currency": ["ApiId", "Text", "RelativePrice"],
        "price": ["api_id", "en_name", "category", "price_chaos"],
    }
    health = evaluate_source_health(
        "poe2scout-poe1",
        raw,
        expected_root="object",
        http=client.latest_http(lambda url: "/pc/Leagues/" in url and url.endswith("/SnapshotPairs")),
        item_count=len(prices),
        match_count=len(prices),
        item_names=sorted({item.en_name for item in prices.values() if item.en_name}),
        discovered_categories=categories,
        enabled_categories=categories,
        succeeded_categories=categories,
        key_fields=("ApiId", "Text", "RelativePrice"),
        baseline_schema=_baseline_schema(baseline, "poe2scout-poe1"),
    )
    metrics = {
        "league": raw.get("league"),
        "price_items": len(prices),
        "divine_price_chaos": str(divine_chaos),
        "snapshot_pairs": raw.get("snapshot_pair_count"),
        "categories": {
            "discovered": categories,
            "succeeded": categories,
            "failed": [],
        },
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poe2scout-poe1"),
        categories,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


def audit_poe1_poedb(
    client: RecordingClient,
    _league: LeagueSelection,
    baseline: Mapping[str, Any] | None,
    max_workers: int,
) -> dict[str, Any]:
    raw, prices, divine_chaos = poe1_builder.fetch_poedb_poe1_prices(
        client,
        poe1_builder.DEFAULT_POEDB_US_ECONOMY_URL,
        poe1_builder.DEFAULT_POEDB_CN_ECONOMY_URL,
    )
    discovered = [str(item) for item in raw.get("discovered_categories") or raw.get("category_pages") or []]
    if not discovered:
        discovered = [str(item.get("page") or "") for item in raw.get("category_page_stats") or [] if item.get("page")]
    failed = [str(item) for item in raw.get("failed_categories") or []]
    succeeded = [item for item in discovered if item and item not in set(failed)]
    field_sets = {
        "category_stat": _array_item_fields(raw.get("category_page_stats")),
        "summary": _object_fields(raw),
    }
    health = evaluate_source_health(
        "poedb-poe1",
        raw,
        expected_root="object",
        http=client.latest_http(lambda url: "poedb.tw" in url and "/Economy" in url),
        item_count=len(prices),
        match_count=len(prices),
        item_names=sorted({item.en_name for item in prices.values() if item.en_name}),
        discovered_categories=discovered,
        enabled_categories=discovered,
        succeeded_categories=succeeded,
        failed_categories=failed,
        key_fields=("page", "us_rows", "cn_rows"),
        baseline_schema=_baseline_schema(baseline, "poedb-poe1"),
    )
    metrics = {
        "price_items": len(prices),
        "divine_price_chaos": str(divine_chaos),
        "categories": {
            "discovered": discovered,
            "succeeded": succeeded,
            "failed": failed,
        },
        "field_sets": field_sets,
    }
    contract_drift = compare_contract(
        _baseline_contract(baseline, "poedb-poe1"),
        discovered,
        field_sets,
        baseline_expected=baseline is not None,
    )
    return _entry(health, metrics, contract_drift=contract_drift)


DEFAULT_AUDITORS: tuple[
    tuple[str, Callable[[RecordingClient, LeagueSelection, Mapping[str, Any] | None, int], dict[str, Any]]],
    ...,
] = (
    ("poe2scout", audit_poe2scout),
    ("poe.ninja", audit_poe_ninja),
    ("poecurrency.top", audit_poecurrency),
    ("poe2db", audit_poe2db),
    ("poe.ninja-poe1", audit_poe1_ninja),
    ("poecurrency.top-poe1", audit_poe1_poecurrency),
    ("poe2scout-poe1", audit_poe1_scout),
    ("poedb-poe1", audit_poe1_poedb),
)


def _overall(sources: Mapping[str, Any], league: LeagueSelection) -> dict[str, Any]:
    failed_sources = [
        name
        for name, entry in sources.items()
        if isinstance(entry, Mapping)
        and isinstance(entry.get("health"), Mapping)
        and bool(entry["health"].get("is_failure"))
    ]
    partial_sources = [
        name
        for name, entry in sources.items()
        if isinstance(entry, Mapping) and entry.get("status") in {PARTIAL, STALE}
    ]
    if failed_sources:
        status = "failed"
    elif partial_sources or league.used_fallback or league.warnings:
        status = "partial"
    else:
        status = "healthy"
    return {
        "status": status,
        "exit_code": 1 if failed_sources else 0,
        "failed_sources": failed_sources,
        "partial_sources": partial_sources,
    }


def run_audit(
    client: RecordingClient,
    *,
    baseline: Mapping[str, Any] | None = None,
    max_workers: int = 6,
    league_resolver: Callable[..., LeagueSelection] = resolve_current_leagues,
    auditors: tuple[tuple[str, Callable[..., dict[str, Any]]], ...] = DEFAULT_AUDITORS,
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    league = league_resolver(client, builder.DEFAULT_SCOUT_API)
    sources: dict[str, Any] = {}
    for name, auditor in auditors:
        print(f"[审计] {name}：开始", flush=True)
        try:
            sources[name] = auditor(client, league, baseline, max_workers)
        except Exception as exc:
            health = failed_source_health(name, exc)
            sources[name] = _entry(
                health,
                {"error": f"{type(exc).__name__}: {exc}"},
            )
        print(f"[审计] {name}：{sources[name]['status']}", flush=True)

    report = {
        "report_version": REPORT_VERSION,
        "checked_at": checked_at,
        "read_only": True,
        "league": {
            "poe2scout": league.scout,
            "poe_ninja": league.poe_ninja,
            "source": league.source,
            "used_fallback": league.used_fallback,
            "discovery_url": league.discovery_url,
            "warnings": list(league.warnings),
        },
        "sources": sources,
    }
    report["overall"] = _overall(sources, league)
    return report


def load_baseline(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError("baseline report root must be an object")
    return value


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审计全部实时物价数据源契约")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--max-workers", type=int, default=6)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument("--total-timeout", type=float, default=90.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    delegate = builder.RetryingRequests(
        max_retries=args.max_retries,
        timeout=args.timeout,
        total_timeout=args.total_timeout,
    )
    report = run_audit(
        RecordingClient(delegate),
        baseline=load_baseline(args.baseline),
        max_workers=max(1, args.max_workers),
    )
    write_report(args.output, report)
    print(
        f"[审计] 总体：{report['overall']['status']}；报告：{args.output}",
        flush=True,
    )
    return int(report["overall"]["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
