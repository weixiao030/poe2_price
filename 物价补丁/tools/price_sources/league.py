"""Discover and resolve softcore leagues shared by poe2scout and poe.ninja.

Provider identities stay paired by league. A missing directory must never
silently select a hard-coded historical league.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping, Sequence


DEFAULT_SCOUT_LEAGUE = "runes"
DEFAULT_POE_NINJA_LEAGUE = "Runes of Aldur"


@dataclass(frozen=True)
class LeagueSelection:
    """League identifiers selected for both providers.

    ``source`` is intentionally small and stable so it can be written to a
    health report without exposing exception types:

    - ``auto``: both values came from the discovery endpoint;
    - ``explicit``: both values were supplied by the caller;
    - ``explicit+auto``: one value was supplied and the other was discovered;
    - ``ninja``: the independent Ninja directory supplied the league;
    - ``explicit+fallback``: only the supplied provider identity is available.
    """

    scout: str
    poe_ninja: str
    source: str
    warnings: tuple[str, ...] = ()
    discovery_url: str = ""

    @property
    def used_fallback(self) -> bool:
        return "fallback" in self.source


@dataclass(frozen=True)
class LeagueOption:
    """One dynamically discovered softcore league and its provider IDs."""

    scout: str
    poe_ninja: str
    is_current: bool
    order: int = 0
    is_latest: bool = False

    @property
    def label(self) -> str:
        return f"{self.poe_ninja}（最新）" if self.is_latest else self.poe_ninja


def discover_league_options(
    client: Any, api_base: str, *, realm: str = "poe2"
) -> tuple[LeagueOption, ...]:
    """Return all deduplicated softcore leagues from the live poe2scout realm."""

    url = f"{str(api_base).rstrip('/')}/{realm.strip('/')}/Leagues"
    rows = _league_rows(client.get_json(url))
    options: list[LeagueOption] = []
    seen: set[tuple[str, str]] = set()
    for order, row in enumerate(rows):
        if not isinstance(row, Mapping) or _is_hardcore(row):
            continue
        scout = _clean_text(_field(row, "ShortName", "short_name", "short", "slug"))
        ninja = _clean_text(_field(row, "Value", "value", "Name", "name", "league"))
        if not scout or not ninja:
            continue
        key = (scout.casefold(), ninja.casefold())
        if key in seen:
            continue
        seen.add(key)
        options.append(
            LeagueOption(
                scout=scout,
                poe_ninja=ninja,
                is_current=_as_bool(_field(row, "IsCurrent", "is_current", "current")),
                order=order,
            )
        )
    if not options:
        raise ValueError("赛季响应中没有可用的软核赛季")
    # poe2scout returns the newest league first. Keep that provider order so
    # a response that briefly marks more than one softcore league as current
    # still presents the newest one first instead of reviving an older league.
    ordered = sorted(options, key=lambda item: (not item.is_current, item.order))
    return tuple(
        replace(item, is_latest=index == 0 and item.is_current)
        for index, item in enumerate(ordered)
    )


def discover_realm_league_options(client: Any, api_base: str, realm: str) -> tuple[LeagueOption, ...]:
    """Discover a realm-specific list, e.g. ``pc`` for POE1."""

    return discover_league_options(client, api_base, realm=realm)


def resolve_current_leagues(
    client: Any,
    api_base: str,
    explicit_scout: str | None = None,
    explicit_ninja: str | None = None,
) -> LeagueSelection:
    """Resolve provider-specific identifiers for the current softcore league.

    Explicit identities are retained during outages. Partial identities are
    completed only from a matching league, never from another current league.
    """

    scout_override = _clean_text(explicit_scout) or ""
    ninja_override = _clean_text(explicit_ninja) or ""
    url = f"{str(api_base).rstrip('/')}/poe2/Leagues"

    if scout_override and ninja_override:
        return LeagueSelection(
            scout=scout_override,
            poe_ninja=ninja_override,
            source="explicit",
            discovery_url=url,
        )

    try:
        options = discover_league_options(client, api_base, realm="poe2")
        if scout_override or ninja_override:
            matches = [item for item in options if
                       (scout_override and item.scout.casefold() == scout_override.casefold()) or
                       (ninja_override and item.poe_ninja.casefold() == ninja_override.casefold())]
        else:
            matches = [item for item in options if item.is_current]
        if not matches:
            raise ValueError("赛季目录没有匹配的赛季")
        selected = matches[0]
        return LeagueSelection(
            scout=scout_override or selected.scout,
            poe_ninja=ninja_override or selected.poe_ninja,
            source="explicit+auto" if scout_override or ninja_override else "auto",
            discovery_url=url,
        )
    except Exception as exc:
        warning = f"Scout 赛季目录暂不可用：{exc}"
        if scout_override or ninja_override:
            return LeagueSelection(
                scout=scout_override, poe_ninja=ninja_override, source="explicit+fallback",
                warnings=(warning,), discovery_url=url,
            )
    ninja_url = "https://poe.ninja/poe2/api/data/index-state"
    try:
        payload = client.get_json(ninja_url)
        for row in payload["economyLeagues"]:
            name = _clean_text(row.get("name"))
            if not name or _is_hardcore(row) or any(
                marker in name.casefold() for marker in ("hardcore", "ssf", "ruthless", "standard")
            ):
                continue
            return LeagueSelection(scout="", poe_ninja=name, source="ninja",
                                   warnings=(warning,), discovery_url=ninja_url)
    except Exception as exc:
        raise ValueError(f"赛季目录暂不可用，请稍后重试：{exc}") from exc
    raise ValueError("当前赛季尚未公布，请稍后重试")


def _current_softcore_pair(payload: Any) -> tuple[str, str]:
    rows = _league_rows(payload)
    current_rows: list[Mapping[str, Any]] = []

    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not _as_bool(_field(row, "IsCurrent", "is_current", "current")):
            continue
        if _is_hardcore(row):
            continue
        current_rows.append(row)

    # Duplicate records with identical provider identifiers are harmless, but
    # two distinct current softcore leagues are unsafe to guess between.
    pairs: list[tuple[str, str]] = []
    for row in current_rows:
        short_name = _clean_text(
            _field(row, "ShortName", "short_name", "short", "slug")
        )
        value = _clean_text(
            _field(row, "Value", "value", "Name", "name", "league")
        )
        if not short_name or not value:
            raise ValueError("当前软核赛季记录缺少 ShortName 或 Value")
        pair = (short_name, value)
        if pair not in pairs:
            pairs.append(pair)

    if not pairs:
        raise ValueError("赛季响应中没有可用的当前软核赛季")
    if len(pairs) != 1:
        raise ValueError("赛季响应包含多个不同的当前软核赛季")
    return pairs[0]


def _league_rows(payload: Any) -> Sequence[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        raise ValueError("赛季响应根节点不是数组或对象")

    for name in ("Value", "value", "Leagues", "leagues", "Data", "data", "Items", "items"):
        candidate = _field(payload, name)
        if isinstance(candidate, list):
            return candidate
    raise ValueError("赛季响应中找不到赛季数组")


def _is_hardcore(row: Mapping[str, Any]) -> bool:
    explicit = _field(row, "IsHardcore", "is_hardcore", "Hardcore", "hardcore")
    if explicit is not None:
        return _as_bool(explicit)

    value = (_clean_text(_field(row, "Value", "value", "Name", "name")) or "").casefold()
    short_name = (
        _clean_text(_field(row, "ShortName", "short_name", "short", "slug")) or ""
    ).casefold()
    return (
        value == "hardcore"
        or value.startswith("hc ")
        or value.startswith("hardcore ")
        or short_name == "hardcore"
        or short_name.endswith("hc")
    )


def _field(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_normalize_field_name(str(key)): value for key, value in row.items()}
    for alias in aliases:
        key = _normalize_field_name(alias)
        if key in normalized:
            return normalized[key]
    return None


def _normalize_field_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _as_bool(value: Any) -> bool:
    if value is True or value == 1:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "1", "yes", "current"}
    return False
