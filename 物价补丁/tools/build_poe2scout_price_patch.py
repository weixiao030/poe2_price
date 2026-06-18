#!/usr/bin/env python3
"""
Fetch POE2 Scout exchange prices and build a PoE2 item-name price patch.

Network fetching uses requests + ThreadPoolExecutor + retry/backoff. Playwright
is only useful for discovering the endpoints; this script performs the real
data collection.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_SCOUT_API = "https://api.poe2scout.com"
DEFAULT_LEAGUE = "runes"
SCRIPT_DIR = Path(__file__).resolve().parent
PATCH_ROOT = SCRIPT_DIR.parent
DEFAULT_EN_BASEITEMS = (
    PATCH_ROOT / "output" / "dat_files_latest" / "data" / "data_balance_baseitemtypes.datc64"
)
DEFAULT_TC_BASEITEMS = (
    PATCH_ROOT
    / "output"
    / "dat_files_latest"
    / "data"
    / "data_balance_traditional chinese_baseitemtypes.datc64"
)
DEFAULT_PATCH_SCRIPT = Path(__file__).with_name("poe2_name_price_patch.py")
DISPLAY_NAME_FIELD_INDEX = 8


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


@dataclass(frozen=True)
class DatLayout:
    row_count: int
    row_size: int
    string_base: int


class RetryingRequests:
    def __init__(
        self,
        max_retries: int = 4,
        backoff: float = 0.8,
        timeout: float = 25.0,
        user_agent: str = "Mozilla/5.0 poe2-price-patch/1.0",
    ) -> None:
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout
        self.user_agent = user_agent
        self._local = threading.local()

    def session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            retry = Retry(
                total=self.max_retries,
                connect=self.max_retries,
                read=self.max_retries,
                status=self.max_retries,
                backoff_factor=self.backoff,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset(["GET"]),
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retry, pool_connections=64, pool_maxsize=64)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            session.headers.update(
                {
                    "User-Agent": self.user_agent,
                    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
                }
            )
            self._local.session = session
        return session

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session().get(url, timeout=self.timeout, **kwargs)
                if response.status_code < 400:
                    return response
                last_error = requests.HTTPError(
                    f"{response.status_code} {response.reason}: {url}"
                )
            except Exception as exc:  # requests can raise several transient errors
                last_error = exc
            if attempt < self.max_retries:
                time.sleep(self.backoff * (2**attempt))
        assert last_error is not None
        raise last_error

    def get_json(self, url: str) -> Any:
        response = self.get(url)
        return response.json()


def read_utf16le_z(data: bytes, start: int) -> tuple[str, int]:
    pos = start
    chars: list[int] = []
    while pos + 1 < len(data):
        code = data[pos] | (data[pos + 1] << 8)
        if code == 0:
            return "".join(chr(c) for c in chars), pos
        chars.append(code)
        pos += 2
    raise ValueError(f"unterminated UTF-16LE string at 0x{start:x}")


def skip_utf16le_zeroes(data: bytes, start: int) -> int:
    pos = start
    while pos + 1 < len(data) and data[pos] == 0 and data[pos + 1] == 0:
        pos += 2
    return pos


def detect_base_item_layout(data: bytes) -> DatLayout:
    if len(data) < 16:
        raise ValueError("BaseItemTypes.datc64 is too small")

    row_count = struct.unpack_from("<I", data, 0)[0]
    first_name_rel = struct.unpack_from("<I", data, 4)[0]
    marker = "Metadata/Items/".encode("utf-16-le")
    first_metadata = data.find(marker)
    if first_metadata < 0:
        raise ValueError("cannot find Metadata/Items marker in BaseItemTypes.datc64")

    string_base = first_metadata - first_name_rel
    row_bytes = string_base - 4
    if row_count <= 0 or string_base <= 4 or row_bytes % row_count != 0:
        raise ValueError("cannot detect BaseItemTypes row layout")

    row_size = row_bytes // row_count
    if row_size <= DISPLAY_NAME_FIELD_INDEX * 4 or row_size % 4 != 0:
        raise ValueError(f"unexpected BaseItemTypes row size: {row_size}")

    return DatLayout(row_count=row_count, row_size=row_size, string_base=string_base)


def read_string_offset(data: bytes, layout: DatLayout, offset: int) -> str:
    absolute = layout.string_base + offset
    if offset < 0 or offset % 2 != 0 or absolute + 1 >= len(data):
        raise ValueError(f"invalid string offset: 0x{offset:x}")
    text, _end = read_utf16le_z(data, absolute)
    return text


def scan_base_items(path: Path) -> dict[str, str]:
    data = path.read_bytes()
    layout = detect_base_item_layout(data)
    items: dict[str, str] = {}

    for row_index in range(layout.row_count):
        row_start = 4 + row_index * layout.row_size
        try:
            metadata_offset = struct.unpack_from("<I", data, row_start)[0]
            name_offset = struct.unpack_from(
                "<I", data, row_start + DISPLAY_NAME_FIELD_INDEX * 4
            )[0]
            metadata_path = read_string_offset(data, layout, metadata_offset)
            name = read_string_offset(data, layout, name_offset)
        except (struct.error, ValueError):
            continue
        if (
            metadata_path.startswith("Metadata/Items/")
            and name
            and not name.startswith("Metadata/")
            and len(name) <= 160
        ):
            items[metadata_path] = name
    return items


def load_base_item_pairs(en_path: Path, tc_path: Path) -> list[BaseItemPair]:
    en = scan_base_items(en_path)
    tc = scan_base_items(tc_path)
    pairs = []
    for metadata_path, en_name in en.items():
        tc_name = tc.get(metadata_path)
        if tc_name:
            pairs.append(BaseItemPair(metadata_path, en_name, tc_name))
    return pairs


def normalize_name(value: str) -> str:
    value = html.unescape(value).lower()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def slug_candidates(en_name: str) -> list[str]:
    cleaned = html.unescape(en_name).replace("’", "'")
    candidates = []
    forms = [
        cleaned,
        cleaned.replace("'", ""),
        cleaned.replace("'", "_"),
        cleaned.replace("-", "_"),
        cleaned.replace("'", "").replace("-", "_"),
    ]
    for form in forms:
        slug = re.sub(r"\s+", "_", form.strip())
        slug = urllib.parse.quote(slug, safe="_")
        if slug and slug not in candidates:
            candidates.append(slug)
    return candidates


def parse_poe2db_title(text: str) -> str | None:
    match = re.search(r"<title>(.*?)</title>", text, flags=re.I | re.S)
    if not match:
        return None
    title = html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    for sep in [" - PoE2DB", " - 流亡2編年史"]:
        if sep in title:
            return title.split(sep, 1)[0].strip()
    return title or None


def fetch_poe2db_translation(
    client: RetryingRequests, en_name: str, max_slug_attempts: int = 6
) -> str | None:
    for slug in slug_candidates(en_name)[:max_slug_attempts]:
        try:
            us = client.get(f"https://poe2db.tw/us/{slug}")
            if us.status_code == 404 or not parse_poe2db_title(us.text):
                continue
            tw = client.get(f"https://poe2db.tw/tw/{slug}")
            if tw.status_code == 404:
                continue
            tw_title = parse_poe2db_title(tw.text)
            if tw_title:
                return tw_title
        except Exception:
            continue
    return None


def fetch_scout_data(client: RetryingRequests, api_base: str, league: str) -> dict[str, Any]:
    endpoints = {
        "exchange_snapshot": f"{api_base}/poe2/Leagues/{league}/ExchangeSnapshot",
        "reference_currencies": f"{api_base}/poe2/Leagues/{league}/ReferenceCurrencies",
        "snapshot_pairs": f"{api_base}/poe2/Leagues/{league}/SnapshotPairs",
    }
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        future_to_name = {
            pool.submit(client.get_json, url): name for name, url in endpoints.items()
        }
        for future in as_completed(future_to_name):
            name = future_to_name[future]
            results[name] = future.result()
    return results


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def collect_price_observations(snapshot_pairs: list[dict[str, Any]]) -> dict[str, list[PriceObservation]]:
    by_api_id: dict[str, list[PriceObservation]] = {}
    for pair in snapshot_pairs:
        c1 = pair["CurrencyOne"]
        c2 = pair["CurrencyTwo"]
        pair_name = f"{c1['Text']} / {c2['Text']}"
        for currency_key, data_key in [
            ("CurrencyOne", "CurrencyOneData"),
            ("CurrencyTwo", "CurrencyTwoData"),
        ]:
            currency = pair[currency_key]
            side_data = pair[data_key]
            price = to_decimal(side_data.get("RelativePrice"))
            if price <= 0:
                continue
            value_traded = to_decimal(side_data.get("ValueTraded"))
            api_id = currency["ApiId"]
            by_api_id.setdefault(api_id, []).append(
                PriceObservation(
                    api_id=api_id,
                    en_name=currency["Text"],
                    category=currency.get("CategoryApiId") or "",
                    price_exalted=price,
                    value_traded=value_traded,
                    source_pair=pair_name,
                )
            )
    return by_api_id


def choose_best_prices(
    observations: dict[str, list[PriceObservation]],
    reference_currencies: list[dict[str, Any]],
) -> dict[str, PriceObservation]:
    best: dict[str, PriceObservation] = {}
    for api_id, items in observations.items():
        # Highest traded value tends to match the visible high-confidence market rows.
        best[api_id] = max(items, key=lambda item: (item.value_traded, item.price_exalted))

    for ref in reference_currencies:
        api_id = ref["ApiId"]
        if api_id not in best:
            best[api_id] = PriceObservation(
                api_id=api_id,
                en_name=ref["Text"],
                category="currency",
                price_exalted=to_decimal(ref.get("RelativePrice"), Decimal("1")),
                value_traded=Decimal("0"),
                source_pair="ReferenceCurrencies",
            )
        elif to_decimal(ref.get("RelativePrice")) == Decimal("1"):
            best[api_id] = PriceObservation(
                api_id=api_id,
                en_name=ref["Text"],
                category="currency",
                price_exalted=Decimal("1"),
                value_traded=Decimal("0"),
                source_pair="ReferenceCurrencies",
            )
    return best


def divine_price_exalted(best: dict[str, PriceObservation]) -> Decimal:
    obs = best.get("divine")
    if obs and obs.price_exalted > 0:
        return obs.price_exalted
    return Decimal("1")


def format_price(price_exalted: Decimal, divine_exalted: Decimal) -> str:
    if price_exalted <= 0:
        return ""
    price_divine = price_exalted / divine_exalted if divine_exalted else Decimal("0")
    if price_divine >= Decimal("0.01"):
        return f"{price_divine.quantize(Decimal('0.01'))}D"
    if price_exalted >= Decimal("10"):
        return f"{price_exalted.quantize(Decimal('0.1'))}E"
    return f"{price_exalted.quantize(Decimal('0.01'))}E"


def match_prices_to_base_items(
    prices: dict[str, PriceObservation],
    base_pairs: list[BaseItemPair],
    client: RetryingRequests,
    use_poe2db: bool,
    max_workers: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_en = {pair.en_name: pair for pair in base_pairs}
    by_en_norm = {normalize_name(pair.en_name): pair for pair in base_pairs}
    by_tc = {pair.tc_name: pair for pair in base_pairs}

    matched: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    pending_poe2db: list[PriceObservation] = []

    divine_exalted = divine_price_exalted(prices)
    for obs in prices.values():
        pair = by_en.get(obs.en_name) or by_en_norm.get(normalize_name(obs.en_name))
        price = format_price(obs.price_exalted, divine_exalted)
        if pair and price:
            matched.append(
                {
                    "metadata_path": pair.metadata_path,
                    "name": pair.tc_name,
                    "price": price,
                    "new_name": "",
                    "en_name": obs.en_name,
                    "api_id": obs.api_id,
                    "price_exalted": str(obs.price_exalted),
                    "source_pair": obs.source_pair,
                }
            )
        elif use_poe2db and price:
            pending_poe2db.append(obs)
        else:
            missing.append(
                {
                    "api_id": obs.api_id,
                    "en_name": obs.en_name,
                    "reason": "not found in local BaseItemTypes",
                }
            )

    if pending_poe2db:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_obs = {
                pool.submit(fetch_poe2db_translation, client, obs.en_name): obs
                for obs in pending_poe2db
            }
            for future in as_completed(future_to_obs):
                obs = future_to_obs[future]
                price = format_price(obs.price_exalted, divine_exalted)
                try:
                    tc_name = future.result()
                except Exception:
                    tc_name = None
                pair = by_tc.get(tc_name or "")
                if pair and price:
                    matched.append(
                        {
                            "metadata_path": pair.metadata_path,
                            "name": pair.tc_name,
                            "price": price,
                            "new_name": "",
                            "en_name": obs.en_name,
                            "api_id": obs.api_id,
                            "price_exalted": str(obs.price_exalted),
                            "source_pair": f"{obs.source_pair}; poe2db={tc_name}",
                        }
                    )
                else:
                    missing.append(
                        {
                            "api_id": obs.api_id,
                            "en_name": obs.en_name,
                            "poe2db_tw": tc_name or "",
                            "reason": "not found by poe2db/local TC name",
                        }
                    )

    # Same metadata can appear through several API ids; keep the highest price.
    dedup: dict[str, dict[str, str]] = {}
    for row in matched:
        old = dedup.get(row["metadata_path"])
        if old is None or Decimal(row["price_exalted"]) > Decimal(old["price_exalted"]):
            dedup[row["metadata_path"]] = row
    return sorted(dedup.values(), key=lambda r: r["name"]), missing


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def run_patch_builder(
    patch_script: Path,
    tc_baseitems: Path,
    prices_csv: Path,
    output_zip: Path,
    report: Path,
    mode: str,
    patched_dat: Path | None,
) -> None:
    cmd = [
        sys.executable,
        str(patch_script),
        "build",
        "--source",
        str(tc_baseitems),
        "--prices",
        str(prices_csv),
        "--output-zip",
        str(output_zip),
        "--report",
        str(report),
        "--mode",
        mode,
        "--keep-existing-price",
    ]
    if patched_dat:
        cmd.extend(["--patched-dat", str(patched_dat)])
    subprocess.run(cmd, check=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch poe2scout prices and generate a PoE2 name-price patch."
    )
    parser.add_argument("--api-base", default=DEFAULT_SCOUT_API)
    parser.add_argument("--league", default=DEFAULT_LEAGUE)
    parser.add_argument("--en-baseitems", type=Path, default=DEFAULT_EN_BASEITEMS)
    parser.add_argument("--tc-baseitems", type=Path, default=DEFAULT_TC_BASEITEMS)
    parser.add_argument("--out-dir", type=Path, default=Path("output/poe2_price_patch_latest"))
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--backoff", type=float, default=0.8)
    parser.add_argument("--poe2db-fallback", action="store_true")
    parser.add_argument("--no-build-patch", action="store_true")
    parser.add_argument("--patch-script", type=Path, default=DEFAULT_PATCH_SCRIPT)
    parser.add_argument("--output-zip", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--patched-dat", type=Path)
    parser.add_argument(
        "--mode",
        choices=["append", "fixed"],
        default="append",
        help="patch build mode passed to poe2_name_price_patch.py",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    client = RetryingRequests(max_retries=args.retries, backoff=args.backoff)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    scout = fetch_scout_data(client, args.api_base.rstrip("/"), args.league)
    (args.out_dir / "poe2scout_raw.json").write_text(
        json.dumps(scout, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    base_pairs = load_base_item_pairs(args.en_baseitems, args.tc_baseitems)
    observations = collect_price_observations(scout["snapshot_pairs"])
    best = choose_best_prices(observations, scout["reference_currencies"])
    rows, missing = match_prices_to_base_items(
        best,
        base_pairs,
        client=client,
        use_poe2db=args.poe2db_fallback,
        max_workers=max(1, args.max_workers),
    )

    prices_csv = args.out_dir / "prices.csv"
    matched_csv = args.out_dir / "matched_prices_detail.csv"
    missing_csv = args.out_dir / "missing_prices.csv"
    write_csv(prices_csv, rows, ["metadata_path", "name", "price", "new_name"])
    write_csv(
        matched_csv,
        rows,
        [
            "metadata_path",
            "name",
            "price",
            "new_name",
            "en_name",
            "api_id",
            "price_exalted",
            "source_pair",
        ],
    )
    write_csv(
        missing_csv,
        missing,
        ["api_id", "en_name", "poe2db_tw", "reason"],
    )

    summary = {
        "league": args.league,
        "snapshot_epoch": scout["exchange_snapshot"].get("Epoch"),
        "base_currency": scout["exchange_snapshot"].get("BaseCurrencyText"),
        "unique_scout_items": len(best),
        "matched_items": len(rows),
        "missing_items": len(missing),
        "divine_price_exalted": str(divine_price_exalted(best)),
        "poe2db_fallback": bool(args.poe2db_fallback),
    }
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if not args.no_build_patch:
        run_patch_builder(
            patch_script=args.patch_script,
            tc_baseitems=args.tc_baseitems,
            prices_csv=prices_csv,
            output_zip=args.output_zip or (args.out_dir / "物价补丁.zip"),
            report=args.report or (args.out_dir / "price_patch.report.json"),
            mode=args.mode,
            patched_dat=args.patched_dat,
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"prices: {prices_csv}")
    if not args.no_build_patch:
        print(f"patch: {args.output_zip or (args.out_dir / '物价补丁.zip')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
