#!/usr/bin/env python3
"""Fetch POE1 prices and build an isolated BaseItemTypes/Words patch."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_poe2scout_price_patch as shared
from price_sources.http_client import DEFAULT_REQUEST_TIME_BUDGET, RetryingRequests
from price_sources.models import BaseItemPair, PriceObservation


DEFAULT_POECURRENCY_SUMMARY_API = "https://poecurrency.top/api/summary?version=1"
DEFAULT_POE_NINJA_INDEX_URL = "https://poe.ninja/poe1/api/data/index-state"
DEFAULT_POE_NINJA_EXCHANGE_API = (
    "https://poe.ninja/poe1/api/economy/exchange/current/overview"
)
DEFAULT_POE_NINJA_ITEM_API = (
    "https://poe.ninja/poe1/api/economy/stash/current/item/overview"
)
DEFAULT_POE_NINJA_LEAGUE = "Standard"
PATCH_SCOPES = ("all", "currency", "uniques", "none")
PRICE_SOURCES = ("poe-ninja", "poecurrency-cn")
UNIQUE_PRICE_LABEL_MODES = ("markup", "overlay", "newline", "off")

POE_NINJA_EXCHANGE_TYPES = (
    "Currency",
    "Fragment",
    "DivinationCard",
    "Essence",
    "Scarab",
    "Fossil",
    "Resonator",
    "Oil",
    "DeliriumOrb",
    "Artifact",
    "AllflameEmber",
    "Omen",
    "Tattoo",
)
POE_NINJA_UNIQUE_TYPES = (
    "UniqueWeapon",
    "UniqueArmour",
    "UniqueAccessory",
    "UniqueFlask",
    "UniqueJewel",
    "UniqueTincture",
    "UniqueRelic",
    "UniqueMap",
)

PATCH_ROOT = SCRIPT_DIR.parent
DEFAULT_EN_BASEITEMS = (
    PATCH_ROOT / "output" / "poe1_dat_files_latest" / "data" / "data_baseitemtypes.datc64"
)
DEFAULT_TC_BASEITEMS = (
    PATCH_ROOT
    / "output"
    / "poe1_dat_files_latest"
    / "data"
    / "data_simplified chinese_baseitemtypes.datc64"
)
DEFAULT_EN_WORDS = (
    PATCH_ROOT / "output" / "poe1_dat_files_latest" / "data" / "data_words.datc64"
)
DEFAULT_TC_WORDS = (
    PATCH_ROOT
    / "output"
    / "poe1_dat_files_latest"
    / "data"
    / "data_simplified chinese_words.datc64"
)
DEFAULT_PATCH_SCRIPT = SCRIPT_DIR / "poe2_name_price_patch.py"

REFERENCE_NAMES = {
    "chaosorb": "chaos",
    "divineorb": "divine",
}
CN_CHAOS_NAMES = {"混沌石", "混沌宝珠", "Chaos Orb"}
CN_DIVINE_NAMES = {"神圣石", "神圣宝珠", "Divine Orb"}


def progress(message: str) -> None:
    print(f"[进度] {message}", flush=True)


@dataclass
class Poe1Price:
    api_id: str
    en_name: str
    localized_name: str
    category: str
    price_chaos: Decimal
    volume: Decimal
    source_pair: str
    is_unique: bool = False
    display_price: str = ""


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or isinstance(value, bool):
        return default
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return default
    if not result.is_finite():
        return default
    return result


def decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def normalize_english(value: str) -> str:
    return shared.normalize_name(shared.strip_existing_price(str(value or "")))


def normalize_localized(value: str) -> str:
    return shared.normalize_market_name(
        shared.strip_existing_price(str(value or ""))
    )


def format_price(price_chaos: Decimal, divine_chaos: Decimal) -> str:
    if price_chaos <= 0:
        return ""
    if divine_chaos > 0 and price_chaos / divine_chaos >= Decimal("0.1"):
        return f"{decimal_text((price_chaos / divine_chaos).quantize(Decimal('0.01')))}D"
    if price_chaos < Decimal("1"):
        return "<1C"
    quantum = Decimal("0.1") if price_chaos >= Decimal("10") else Decimal("0.01")
    return f"{decimal_text(price_chaos.quantize(quantum))}C"


def apply_display_prices(prices: dict[str, Poe1Price], divine_chaos: Decimal) -> None:
    for price in prices.values():
        if price.api_id in {"chaos", "divine"}:
            price.display_price = ""
        else:
            price.display_price = format_price(price.price_chaos, divine_chaos)


def api_url(base: str, league: str, item_type: str) -> str:
    separator = "&" if "?" in base else "?"
    query = urllib.parse.urlencode({"league": league, "type": item_type})
    return f"{base}{separator}{query}"


def discover_poe_ninja_league(
    client: RetryingRequests,
    index_url: str,
    explicit: str | None,
) -> tuple[str, str, list[str]]:
    if explicit and explicit.strip():
        return explicit.strip(), "explicit", []

    warnings: list[str] = []
    try:
        payload = client.get_json(index_url)
        if not isinstance(payload, dict):
            raise ValueError("league index root is not an object")
        leagues = payload.get("economyLeagues")
        if not isinstance(leagues, list):
            raise ValueError("economyLeagues is not an array")
        for row in leagues:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("displayName") or "").strip()
            if not name:
                continue
            lowered = name.lower()
            if any(
                marker in lowered
                for marker in ("hardcore", "ruthless", "ssf", "standard")
            ):
                continue
            return name, "poe.ninja-index", warnings
        for row in leagues:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or row.get("displayName") or "").strip()
            if name and "hardcore" not in name.lower():
                return name, "poe.ninja-index-fallback", warnings
        raise ValueError("no usable economy league was listed")
    except Exception as exc:
        warning = (
            "poe.ninja league discovery failed; using Standard: "
            f"{type(exc).__name__}: {exc}"
        )
        warnings.append(warning)
        return DEFAULT_POE_NINJA_LEAGUE, "known-fallback", warnings


def _validate_exchange_payload(payload: Any, item_type: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"poe.ninja {item_type} root is not an object")
    lines = payload.get("lines")
    items = payload.get("items")
    core = payload.get("core")
    if not isinstance(lines, list) or not lines:
        raise ValueError(f"poe.ninja {item_type} lines is empty or invalid")
    if not isinstance(items, list):
        raise ValueError(f"poe.ninja {item_type} items is not an array")
    if not isinstance(core, dict):
        raise ValueError(f"poe.ninja {item_type} core is not an object")
    return payload


def _validate_unique_payload(payload: Any, item_type: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError(f"poe.ninja {item_type} root is not an object")
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError(f"poe.ninja {item_type} lines is empty or invalid")
    return payload


def _divine_chaos_from_currency(payload: dict[str, Any]) -> Decimal:
    divine_line = next(
        (
            line
            for line in payload.get("lines") or []
            if isinstance(line, dict) and str(line.get("id") or "") == "divine"
        ),
        None,
    )
    if divine_line:
        value = to_decimal(divine_line.get("primaryValue"))
        if value > 0:
            return value
    rate = to_decimal((payload.get("core") or {}).get("rates", {}).get("divine"))
    if rate > 0:
        return Decimal("1") / rate
    raise ValueError("cannot determine poe.ninja Divine/Chaos ratio")


def _parse_exchange_prices(
    payloads: dict[str, dict[str, Any]], divine_chaos: Decimal
) -> dict[str, Poe1Price]:
    prices: dict[str, Poe1Price] = {
        "chaos": Poe1Price(
            api_id="chaos",
            en_name="Chaos Orb",
            localized_name="",
            category="currency",
            price_chaos=Decimal("1"),
            volume=Decimal("0"),
            source_pair="poe.ninja/reference/chaos",
        ),
        "divine": Poe1Price(
            api_id="divine",
            en_name="Divine Orb",
            localized_name="",
            category="currency",
            price_chaos=divine_chaos,
            volume=Decimal("0"),
            source_pair="poe.ninja/reference/divine",
        ),
    }
    for item_type, payload in payloads.items():
        items_by_id: dict[str, dict[str, Any]] = {}
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                items_by_id[str(item.get("id") or "")] = item
        for item in (payload.get("core") or {}).get("items") or []:
            if isinstance(item, dict):
                items_by_id.setdefault(str(item.get("id") or ""), item)
        for line in payload.get("lines") or []:
            if not isinstance(line, dict):
                continue
            item_id = str(line.get("id") or "").strip()
            item = items_by_id.get(item_id) or {}
            name = str(item.get("name") or "").strip()
            value = to_decimal(line.get("primaryValue"))
            if not item_id or not name or value <= 0:
                continue
            reference_id = REFERENCE_NAMES.get(normalize_english(name))
            api_id_value = reference_id or f"ninja:{item_type.lower()}:{item_id}"
            prices[api_id_value] = Poe1Price(
                api_id=api_id_value,
                en_name=name,
                localized_name="",
                category=str(item.get("category") or item_type),
                price_chaos=value,
                volume=to_decimal(line.get("volumePrimaryValue")),
                source_pair=f"poe.ninja/{item_type}/{name}",
            )
    return prices


def _parse_unique_prices(
    payloads: dict[str, dict[str, Any]], divine_chaos: Decimal
) -> dict[str, Poe1Price]:
    by_name: dict[str, tuple[Poe1Price, Decimal]] = {}
    for item_type, payload in payloads.items():
        for line in payload.get("lines") or []:
            if not isinstance(line, dict):
                continue
            name = str(line.get("name") or "").strip()
            normalized = normalize_english(name)
            if not normalized:
                continue
            value = to_decimal(line.get("chaosValue"))
            if value <= 0:
                value = to_decimal(line.get("divineValue")) * divine_chaos
            if value <= 0:
                continue
            volume = to_decimal(line.get("listingCount") or line.get("count"))
            observation = Poe1Price(
                api_id=f"unique:{normalized}",
                en_name=name,
                localized_name="",
                category=f"unique:{item_type}",
                price_chaos=value,
                volume=volume,
                source_pair=(
                    f"poe.ninja/{item_type}/{name}; "
                    f"detailsId={line.get('detailsId') or ''}"
                ),
                is_unique=True,
            )
            previous = by_name.get(normalized)
            if previous is None or (volume, -value) > (previous[1], -previous[0].price_chaos):
                by_name[normalized] = (observation, volume)
    return {item.api_id: item for item, _volume in by_name.values()}


def fetch_poe_ninja_prices(
    client: RetryingRequests,
    exchange_api: str,
    item_api: str,
    league: str,
    include_uniques: bool,
    exchange_types: Iterable[str] = POE_NINJA_EXCHANGE_TYPES,
    unique_types: Iterable[str] = POE_NINJA_UNIQUE_TYPES,
) -> tuple[dict[str, Any], dict[str, Poe1Price], Decimal]:
    specs = [("exchange", item_type, api_url(exchange_api, league, item_type)) for item_type in exchange_types]
    if include_uniques:
        specs.extend(
            ("unique", item_type, api_url(item_api, league, item_type))
            for item_type in unique_types
        )
    progress(f"poe.ninja：开始抓取 {len(specs)} 个 POE1 分类")

    exchange_payloads: dict[str, dict[str, Any]] = {}
    unique_payloads: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    stats: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(specs)))) as pool:
        futures = {
            pool.submit(client.get_json, url): (kind, item_type, url)
            for kind, item_type, url in specs
        }
        completed = 0
        for future in as_completed(futures):
            kind, item_type, url = futures[future]
            key = f"{kind}:{item_type}"
            try:
                payload = future.result()
                if kind == "exchange":
                    exchange_payloads[item_type] = _validate_exchange_payload(payload, item_type)
                else:
                    unique_payloads[item_type] = _validate_unique_payload(payload, item_type)
                line_count = len(payload.get("lines") or [])
                stats.append(
                    {
                        "kind": kind,
                        "type": item_type,
                        "url": url,
                        "status": "ok",
                        "lines": line_count,
                    }
                )
                state = f"完成 ({line_count} 条)"
            except Exception as exc:
                errors[key] = f"{type(exc).__name__}: {exc}"
                stats.append(
                    {
                        "kind": kind,
                        "type": item_type,
                        "url": url,
                        "status": "failed",
                        "lines": 0,
                        "error": errors[key],
                    }
                )
                state = "失败"
            completed += 1
            progress(f"poe.ninja：{completed}/{len(specs)} {item_type} {state}")

    currency = exchange_payloads.get("Currency")
    if currency is None:
        raise ValueError(
            "poe.ninja required Currency category failed: "
            + errors.get("exchange:Currency", "missing response")
        )
    divine_chaos = _divine_chaos_from_currency(currency)
    prices = _parse_exchange_prices(exchange_payloads, divine_chaos)
    prices.update(_parse_unique_prices(unique_payloads, divine_chaos))
    if len(prices) < 20:
        raise ValueError(f"poe.ninja returned too few usable POE1 prices: {len(prices)}")

    failed = [key for key in errors]
    raw = {
        "source": "poe-ninja-poe1",
        "status": "partial" if failed else "ok",
        "league": league,
        "divine_price_chaos": str(divine_chaos),
        "price_count": len(prices),
        "failed_categories": failed,
        "category_stats": sorted(stats, key=lambda row: (row["kind"], row["type"])),
        "exchange_payloads": exchange_payloads,
        "unique_payloads": unique_payloads,
    }
    return raw, prices, divine_chaos


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _choose_pair(left: Decimal, right: Decimal) -> Decimal:
    if left > 0 and right > 0:
        high = max(left, right)
        low = min(left, right)
        if high / low <= Decimal("5"):
            return (left * right).sqrt()
        return low
    return left if left > 0 else right


def _poecurrency_raw_price(item: dict[str, Any]) -> tuple[Decimal, str]:
    is_error = _bool_value(item.get("error"))
    candidate_pairs: list[tuple[str, str]] = []
    if not is_error:
        candidate_pairs.append(("latest_buy1", "latest_sell1"))
    candidate_pairs.extend(
        (
            ("buy_avg_12h", "sell_avg_12h"),
            ("buy_avg", "sell_avg"),
            ("buy_avg_yesterday", "sell_avg_yesterday"),
        )
    )
    for buy_key, sell_key in candidate_pairs:
        value = _choose_pair(to_decimal(item.get(buy_key)), to_decimal(item.get(sell_key)))
        if value > 0:
            return value, f"{buy_key}/{sell_key}"
    return Decimal("0"), ""


def _poecurrency_unit(item: dict[str, Any]) -> str:
    unit = str(item.get("currency_unit") or item.get("unit") or "").strip().lower()
    if unit in {"c", "chaos", "chaos orb", "混沌石", "混沌宝珠"}:
        return "c"
    if unit in {"d", "divine", "divine orb", "神圣石", "神圣宝珠"}:
        return "d"
    return ""


def collect_poecurrency_prices(
    payload: Any,
    fallback_divine_chaos: Decimal,
) -> tuple[dict[str, Poe1Price], Decimal, dict[str, Any]]:
    categories = shared.normalize_poecurrency_summary(payload)
    flattened: list[tuple[str, dict[str, Any]]] = []
    for category in categories:
        label = str(category.get("category_label") or "")
        for item in category.get("items") or []:
            if isinstance(item, dict):
                flattened.append((label, item))
    if len(flattened) < 10:
        raise ValueError(f"poecurrency version=1 returned too few rows: {len(flattened)}")

    divine_chaos = Decimal("0")
    for _category, item in flattened:
        en_name = str(item.get("engname") or "").strip()
        localized = str(item.get("item_name") or "").strip()
        if normalize_english(en_name) != "divineorb" and localized not in CN_DIVINE_NAMES:
            continue
        raw_value, _field = _poecurrency_raw_price(item)
        if _poecurrency_unit(item) == "c" and raw_value > 0:
            divine_chaos = raw_value
            break
    if divine_chaos <= 0:
        divine_chaos = fallback_divine_chaos
    if divine_chaos <= 0:
        raise ValueError("cannot determine poecurrency Divine/Chaos ratio")

    prices: dict[str, Poe1Price] = {}
    skipped_errors = 0
    missing_units = 0
    for category, item in flattened:
        en_name = str(item.get("engname") or "").strip()
        localized = str(item.get("item_name") or "").strip()
        if not en_name and not localized:
            continue
        raw_value, field = _poecurrency_raw_price(item)
        unit = _poecurrency_unit(item)
        if not unit:
            missing_units += 1
            continue
        if raw_value <= 0:
            if _bool_value(item.get("error")):
                skipped_errors += 1
            continue
        price_chaos = raw_value * divine_chaos if unit == "d" else raw_value
        normalized_en = normalize_english(en_name)
        reference_id = REFERENCE_NAMES.get(normalized_en)
        if not reference_id and localized in CN_CHAOS_NAMES:
            reference_id = "chaos"
        if not reference_id and localized in CN_DIVINE_NAMES:
            reference_id = "divine"
        api_id_value = reference_id or f"cn:{normalized_en or normalize_localized(localized)}"
        if api_id_value == "chaos":
            price_chaos = Decimal("1")
        elif api_id_value == "divine":
            price_chaos = divine_chaos
        prices[api_id_value] = Poe1Price(
            api_id=api_id_value,
            en_name=en_name,
            localized_name=localized,
            category=category,
            price_chaos=price_chaos,
            volume=Decimal("0"),
            source_pair=f"poecurrency.top/{category}/{field}; unit={unit}",
        )
    if len(prices) < 10:
        raise ValueError(f"poecurrency version=1 produced too few prices: {len(prices)}")
    quality = {
        "category_count": len(categories),
        "source_items": len(flattened),
        "price_count": len(prices),
        "missing_unit_items": missing_units,
        "skipped_error_items": skipped_errors,
        "divine_price_chaos": str(divine_chaos),
    }
    return prices, divine_chaos, quality


def match_base_items(
    prices: dict[str, Poe1Price],
    base_pairs: list[BaseItemPair],
    prefer_localized: bool,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_en: dict[str, list[BaseItemPair]] = {}
    by_localized: dict[str, list[BaseItemPair]] = {}
    for pair in base_pairs:
        if pair.en_name:
            by_en.setdefault(normalize_english(pair.en_name), []).append(pair)
        if pair.tc_name:
            by_localized.setdefault(normalize_localized(pair.tc_name), []).append(pair)

    matched: dict[str, dict[str, str]] = {}
    missing: list[dict[str, str]] = []
    for price in prices.values():
        if price.is_unique or price.api_id in {"chaos", "divine"}:
            continue
        if price.price_chaos < Decimal("1") or not price.display_price:
            continue
        candidates: list[BaseItemPair] = []
        if prefer_localized and price.localized_name:
            candidates = by_localized.get(normalize_localized(price.localized_name), [])
        if not candidates and price.en_name:
            candidates = by_en.get(normalize_english(price.en_name), [])
        if not candidates:
            missing.append(
                {
                    "api_id": price.api_id,
                    "en_name": price.en_name,
                    "localized_name": price.localized_name,
                    "reason": "not found in local POE1 BaseItemTypes",
                }
            )
            continue
        for pair in candidates:
            row = {
                "metadata_path": pair.metadata_path,
                "name": pair.tc_name,
                "price": price.display_price,
                "new_name": "",
                "en_name": price.en_name,
                "localized_name": price.localized_name,
                "api_id": price.api_id,
                "price_chaos": str(price.price_chaos),
                "source_pair": price.source_pair,
            }
            previous = matched.get(pair.metadata_path)
            if previous is None or price.price_chaos > to_decimal(previous["price_chaos"]):
                matched[pair.metadata_path] = row
    return sorted(matched.values(), key=lambda row: (row["name"], row["metadata_path"])), missing


def merge_fallback_rows(
    primary: list[dict[str, str]], fallback: list[dict[str, str]]
) -> tuple[list[dict[str, str]], int]:
    by_path = {row["metadata_path"]: row for row in primary}
    added = 0
    for row in fallback:
        if row["metadata_path"] in by_path:
            continue
        by_path[row["metadata_path"]] = row
        added += 1
    return sorted(by_path.values(), key=lambda row: (row["name"], row["metadata_path"])), added


def load_all_word_names(en_words: Path, localized_words: Path) -> dict[str, shared.UniqueName]:
    en_data = en_words.read_bytes()
    localized_data = localized_words.read_bytes()
    en_layout = shared.detect_words_layout(en_data)
    localized_layout = shared.detect_words_layout(localized_data)
    row_count = min(en_layout.row_count, localized_layout.row_count)
    minimum_rows = max(1, int(max(en_layout.row_count, localized_layout.row_count) * 0.95))
    if row_count < minimum_rows:
        raise ValueError(
            "POE1 English/localized Words row counts are incompatible: "
            f"english={en_layout.row_count}, localized={localized_layout.row_count}"
        )
    names: dict[str, shared.UniqueName] = {}
    readable = 0
    for row_index in range(row_count):
        en_entry = shared.read_words_row(en_data, en_layout, row_index)
        localized_entry = shared.read_words_row(localized_data, localized_layout, row_index)
        if not en_entry or not localized_entry:
            continue
        readable += 1
        normalized = normalize_english(en_entry.en_name)
        if not normalized:
            continue
        names[normalized] = shared.UniqueName(
            row_index=row_index,
            en_name=en_entry.en_name,
            display_name=localized_entry.display_name,
        )
    if readable < max(1, int(row_count * 0.95)):
        raise ValueError(
            f"POE1 Words scan is incomplete: readable={readable}, rows={row_count}"
        )
    return names


def to_shared_unique_observations(prices: dict[str, Poe1Price]) -> dict[str, PriceObservation]:
    result: dict[str, PriceObservation] = {}
    for price in prices.values():
        if not price.is_unique:
            continue
        result[price.api_id] = PriceObservation(
            api_id=price.api_id,
            en_name=price.en_name,
            category=price.category,
            price_exalted=price.price_chaos,
            value_traded=price.volume,
            source_pair=price.source_pair,
            display_price=price.display_price,
        )
    return result


def convert_unique_report_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    converted: list[dict[str, str]] = []
    for original in rows:
        row = dict(original)
        row["price_chaos"] = row.pop("price_exalted", "")
        if row.get("reason") == "not found in UniqueGoldPrices/Words":
            row["reason"] = "not found in POE1 Words"
        converted.append(row)
    return converted


def run_base_patch_builder(
    patch_script: Path,
    source: Path,
    prices_csv: Path,
    output_zip: Path,
    report: Path,
    mode: str,
    patched_dat: Path | None,
    game_path: str,
    preserve_unmatched: bool,
) -> None:
    command = [
        sys.executable,
        str(patch_script),
        "build",
        "--source",
        str(source),
        "--prices",
        str(prices_csv),
        "--output-zip",
        str(output_zip),
        "--report",
        str(report),
        "--mode",
        mode,
        "--game-path",
        game_path,
        "--keep-existing-price",
    ]
    if preserve_unmatched:
        command.append("--preserve-unmatched-existing-price")
    if patched_dat:
        command.extend(("--patched-dat", str(patched_dat)))
    subprocess.run(command, check=True)


def derive_words_game_path(base_items_game_path: str) -> str:
    normalized = str(base_items_game_path or "").replace("\\", "/")
    return re.sub(
        r"baseitemtypes\.datc64$",
        "words.datc64",
        normalized,
        flags=re.IGNORECASE,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch POE1 prices and generate a C/D item-name patch."
    )
    parser.add_argument("--price-source", choices=PRICE_SOURCES, default="poe-ninja")
    parser.add_argument("--poecurrency-summary-url", default=DEFAULT_POECURRENCY_SUMMARY_API)
    parser.add_argument("--poe-ninja-index-url", default=DEFAULT_POE_NINJA_INDEX_URL)
    parser.add_argument("--poe-ninja-exchange-api", default=DEFAULT_POE_NINJA_EXCHANGE_API)
    parser.add_argument("--poe-ninja-item-api", default=DEFAULT_POE_NINJA_ITEM_API)
    parser.add_argument("--league")
    parser.add_argument("--en-baseitems", type=Path, default=DEFAULT_EN_BASEITEMS)
    parser.add_argument("--tc-baseitems", type=Path, default=DEFAULT_TC_BASEITEMS)
    parser.add_argument("--en-words", type=Path, default=DEFAULT_EN_WORDS)
    parser.add_argument("--tc-words", type=Path, default=DEFAULT_TC_WORDS)
    parser.add_argument("--out-dir", type=Path, default=Path("output/poe1_price_patch_latest"))
    parser.add_argument("--patch-scope", choices=PATCH_SCOPES, default="all")
    parser.add_argument("--no-uniques", action="store_true")
    parser.add_argument("--no-build-patch", action="store_true")
    parser.add_argument("--strict-feature-cleanup", action="store_true")
    parser.add_argument(
        "--unique-price-label-mode",
        choices=UNIQUE_PRICE_LABEL_MODES,
        default="markup",
    )
    parser.add_argument("--patch-script", type=Path, default=DEFAULT_PATCH_SCRIPT)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--patched-dat", type=Path)
    parser.add_argument("--patched-words", type=Path)
    parser.add_argument("--game-path", default="")
    parser.add_argument("--words-game-path", default="")
    parser.add_argument("--mode", choices=("append", "fixed"), default="append")
    parser.add_argument("--max-workers", type=int, default=8)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--request-time-budget", type=float, default=DEFAULT_REQUEST_TIME_BUDGET)
    parser.add_argument("--check-words", type=Path)
    parser.add_argument("--clean-words", type=Path)
    parser.add_argument("--clean-words-output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if args.check_words and args.clean_words:
        raise SystemExit("--check-words and --clean-words cannot be combined")
    if args.check_words:
        print(
            json.dumps(
                {"path": str(args.check_words), **shared.inspect_words_price_labels(args.check_words)},
                ensure_ascii=False,
            )
        )
        return 0
    if args.clean_words:
        if not args.clean_words_output:
            raise SystemExit("--clean-words-output is required with --clean-words")
        cleaned = shared.clean_word_price_labels_file(args.clean_words, args.clean_words_output)
        print(
            json.dumps(
                {
                    "source": str(args.clean_words),
                    "output": str(args.clean_words_output),
                    "cleaned_count": len(cleaned),
                    **shared.inspect_words_price_labels(args.clean_words_output),
                },
                ensure_ascii=False,
            )
        )
        return 0

    patch_base_items = args.patch_scope in {"all", "currency"}
    patch_unique_words = args.patch_scope in {"all", "uniques"} and not args.no_uniques
    fetch_prices = patch_base_items or patch_unique_words
    if not args.tc_baseitems.exists():
        raise SystemExit(f"localized BaseItemTypes not found: {args.tc_baseitems}")
    if args.price_source == "poe-ninja" and fetch_prices and not args.en_baseitems.exists():
        raise SystemExit(f"English BaseItemTypes not found: {args.en_baseitems}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    client = RetryingRequests(
        max_retries=max(0, args.retries),
        backoff=max(0.0, args.backoff),
        timeout=max(1.0, args.timeout),
        total_timeout=max(1.0, args.request_time_budget),
    )
    league, league_source, league_warnings = discover_poe_ninja_league(
        client, args.poe_ninja_index_url, args.league
    )
    progress(f"当前 POE1 软核赛季：{league} ({league_source})")
    for warning in league_warnings:
        print(f"[警告] {warning}", file=sys.stderr)

    ninja_raw: dict[str, Any] = {}
    ninja_prices: dict[str, Poe1Price] = {}
    ninja_error = ""
    ninja_divine_chaos = Decimal("0")
    if fetch_prices:
        try:
            ninja_raw, ninja_prices, ninja_divine_chaos = fetch_poe_ninja_prices(
                client,
                args.poe_ninja_exchange_api,
                args.poe_ninja_item_api,
                league,
                include_uniques=patch_unique_words,
            )
            (args.out_dir / "poe_ninja_raw.json").write_text(
                json.dumps(ninja_raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            ninja_error = f"{type(exc).__name__}: {exc}"
            (args.out_dir / "poe_ninja_error.json").write_text(
                json.dumps({"status": "failed", "error": ninja_error}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if args.price_source == "poe-ninja" or patch_unique_words:
                raise
            print(f"warning: POE1 poe.ninja unavailable: {ninja_error}", file=sys.stderr)

    primary_prices = ninja_prices
    primary_divine_chaos = ninja_divine_chaos
    primary_status = "ok" if ninja_prices else "disabled"
    primary_warning = ninja_error
    poecurrency_quality: dict[str, Any] = {}
    poecurrency_raw: Any = None
    if fetch_prices and args.price_source == "poecurrency-cn":
        try:
            poecurrency_raw = client.get_json(args.poecurrency_summary_url)
            (args.out_dir / "poecurrency_cn_raw.json").write_text(
                json.dumps(poecurrency_raw, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            primary_prices, primary_divine_chaos, poecurrency_quality = collect_poecurrency_prices(
                poecurrency_raw, ninja_divine_chaos
            )
            primary_status = "ok"
            primary_warning = ""
        except Exception as exc:
            primary_status = "fallback"
            primary_warning = f"poecurrency version=1 failed: {type(exc).__name__}: {exc}"
            print(f"warning: {primary_warning}", file=sys.stderr)
            if not ninja_prices:
                raise
            primary_prices = ninja_prices
            primary_divine_chaos = ninja_divine_chaos

    if fetch_prices and not primary_prices:
        raise ValueError("all enabled POE1 price sources failed")
    divine_chaos = primary_divine_chaos or ninja_divine_chaos
    apply_display_prices(primary_prices, divine_chaos)
    if ninja_prices is not primary_prices:
        apply_display_prices(ninja_prices, ninja_divine_chaos or divine_chaos)

    if args.en_baseitems.exists():
        base_pairs = shared.load_base_item_pairs(args.en_baseitems, args.tc_baseitems)
    else:
        base_pairs = shared.load_localized_base_item_pairs(args.tc_baseitems)
    rows: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    fallback_rows_added = 0
    if patch_base_items:
        rows, missing = match_base_items(
            primary_prices,
            base_pairs,
            prefer_localized=args.price_source == "poecurrency-cn" and primary_status == "ok",
        )
        if args.price_source == "poecurrency-cn" and ninja_prices and primary_prices is not ninja_prices:
            ninja_rows, ninja_missing = match_base_items(
                ninja_prices, base_pairs, prefer_localized=False
            )
            rows, fallback_rows_added = merge_fallback_rows(rows, ninja_rows)
            missing.extend(ninja_missing)
        if len(base_pairs) >= 100 and len(rows) < 10:
            raise ValueError(
                f"POE1 local match gate failed: matched={len(rows)}, base_items={len(base_pairs)}"
            )
        if not rows:
            raise ValueError("POE1 price source did not match any local BaseItemTypes rows")

    prices_csv = args.out_dir / "prices.csv"
    matched_csv = args.out_dir / "matched_prices_detail.csv"
    missing_csv = args.out_dir / "missing_prices.csv"
    shared.write_csv(prices_csv, rows, ["metadata_path", "name", "price", "new_name"])
    shared.write_csv(
        matched_csv,
        rows,
        [
            "metadata_path",
            "name",
            "price",
            "new_name",
            "en_name",
            "localized_name",
            "api_id",
            "price_chaos",
            "source_pair",
        ],
    )
    shared.write_csv(
        missing_csv,
        missing,
        ["api_id", "en_name", "localized_name", "reason"],
    )

    output_zip = args.output_zip or (args.out_dir / "POE1物价补丁.zip")
    report = args.report or (args.out_dir / "price_patch.report.json")
    unique_rows: list[dict[str, str]] = []
    unique_missing: list[dict[str, str]] = []
    unique_words_available = 0
    unique_words_patched = 0
    feature_degradations: list[dict[str, str]] = []
    if not args.no_build_patch:
        if not args.game_path:
            raise SystemExit("--game-path is required when building a POE1 patch")
        progress("生成 POE1 BaseItemTypes C/D 补丁")
        run_base_patch_builder(
            patch_script=args.patch_script,
            source=args.tc_baseitems,
            prices_csv=prices_csv,
            output_zip=output_zip,
            report=report,
            mode=args.mode,
            patched_dat=args.patched_dat,
            game_path=args.game_path,
            preserve_unmatched=patch_base_items,
        )

        words_game_path = args.words_game_path or derive_words_game_path(args.game_path)
        if words_game_path and args.tc_words.exists():
            patched_words = args.patched_words or (args.out_dir / "words.patched.datc64")
            try:
                if args.en_words.exists():
                    unique_names = load_all_word_names(args.en_words, args.tc_words)
                else:
                    unique_names = {}
                unique_words_available = len(unique_names)
                if patch_unique_words and unique_names and args.unique_price_label_mode != "off":
                    unique_observations = to_shared_unique_observations(ninja_prices)
                    unique_words_patched, raw_rows, raw_missing = shared.patch_unique_word_prices(
                        tc_words_path=args.tc_words,
                        unique_names=unique_names,
                        prices=unique_observations,
                        patched_words=patched_words,
                        label_mode=args.unique_price_label_mode,
                    )
                    unique_rows = convert_unique_report_rows(raw_rows)
                    unique_missing = convert_unique_report_rows(raw_missing)
                    if raw_rows:
                        shared.upsert_zip_entry(output_zip, words_game_path, patched_words.read_bytes())
                    else:
                        shared.upsert_zip_entry(output_zip, words_game_path, args.tc_words.read_bytes())
                else:
                    cleaned = shared.clean_word_price_labels_file(args.tc_words, patched_words)
                    unique_rows = convert_unique_report_rows(cleaned)
                    shared.upsert_zip_entry(output_zip, words_game_path, patched_words.read_bytes())
            except Exception as exc:
                if args.strict_feature_cleanup:
                    raise
                feature_degradations.append(
                    {
                        "feature": "unique-words",
                        "status": "preserved",
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                )
                shared.upsert_zip_entry(output_zip, words_game_path, args.tc_words.read_bytes())
        elif patch_unique_words:
            feature_degradations.append(
                {
                    "feature": "unique-words",
                    "status": "unavailable",
                    "reason": "localized POE1 Words.datc64 was not supplied",
                }
            )

    shared.write_csv(
        args.out_dir / "unique_word_prices_detail.csv",
        unique_rows,
        [
            "words_row_index",
            "en_name",
            "old_name",
            "new_name",
            "price",
            "api_id",
            "price_chaos",
            "source_pair",
            "status",
            "reason",
        ],
    )
    shared.write_csv(
        args.out_dir / "missing_unique_word_prices.csv",
        unique_missing,
        ["api_id", "en_name", "reason"],
    )

    summary = {
        "game_version": "poe1",
        "price_source": args.price_source,
        "primary_source_status": primary_status,
        "primary_source_warning": primary_warning,
        "patch_scope": args.patch_scope,
        "league": league,
        "league_selection_source": league_source,
        "league_warnings": league_warnings,
        "base_currency": "Chaos Orb",
        "divine_price_chaos": str(divine_chaos),
        "display_units": ["C", "D"],
        "source_prices": len(primary_prices),
        "ninja_prices": len(ninja_prices),
        "matched_items": len(rows),
        "missing_items": len(missing),
        "fallback_matched_items": fallback_rows_added,
        "unique_words_available": unique_words_available,
        "unique_words_patched": unique_words_patched,
        "missing_unique_word_prices": len(unique_missing),
        "unique_price_label_mode": args.unique_price_label_mode,
        "poecurrency_quality": poecurrency_quality,
        "poe_ninja_status": ninja_raw.get("status") if ninja_raw else "failed",
        "poe_ninja_error": ninja_error,
        "feature_degradations": feature_degradations,
        "http_request_count": len(client.request_metrics()),
        "http_requests": client.request_metrics(),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"prices: {prices_csv}")
    if not args.no_build_patch:
        print(f"patch: {output_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
