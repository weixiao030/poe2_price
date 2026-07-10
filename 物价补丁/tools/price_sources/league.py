"""Resolve the current softcore league shared by poe2scout and poe.ninja.

The discovery endpoint belongs to poe2scout.  Callers may override either
provider independently; an unavailable or incompatible endpoint must never
prevent the existing, known-good defaults from being used.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    - ``fallback`` / ``explicit+fallback``: discovery was unusable.
    """

    scout: str
    poe_ninja: str
    source: str
    warnings: tuple[str, ...] = ()
    discovery_url: str = ""

    @property
    def used_fallback(self) -> bool:
        return "fallback" in self.source


def resolve_current_leagues(
    client: Any,
    api_base: str,
    explicit_scout: str | None = None,
    explicit_ninja: str | None = None,
    *,
    fallback_scout: str = DEFAULT_SCOUT_LEAGUE,
    fallback_ninja: str = DEFAULT_POE_NINJA_LEAGUE,
) -> LeagueSelection:
    """Resolve provider-specific identifiers for the current softcore league.

    Explicit non-empty values always win.  If both are explicit no network
    request is made.  Discovery failures are converted to a warning and the
    known-good fallback identifiers, keeping offline/manual use functional.
    """

    scout_override = _clean_text(explicit_scout)
    ninja_override = _clean_text(explicit_ninja)
    fallback_scout_value = _clean_text(fallback_scout) or DEFAULT_SCOUT_LEAGUE
    fallback_ninja_value = _clean_text(fallback_ninja) or DEFAULT_POE_NINJA_LEAGUE
    url = f"{str(api_base).rstrip('/')}/poe2/Leagues"

    if scout_override and ninja_override:
        return LeagueSelection(
            scout=scout_override,
            poe_ninja=ninja_override,
            source="explicit",
            discovery_url=url,
        )

    warnings: list[str] = []
    discovered: tuple[str, str] | None = None
    try:
        payload = client.get_json(url)
        discovered = _current_softcore_pair(payload)
    except Exception as exc:  # Discovery is advisory; preserve the old path.
        detail = str(exc).strip()
        if detail:
            warnings.append(f"当前赛季自动发现失败，已使用内置回退值：{detail}")
        else:
            warnings.append("当前赛季自动发现失败，已使用内置回退值")

    used_explicit = bool(scout_override or ninja_override)
    if discovered is None:
        source = "explicit+fallback" if used_explicit else "fallback"
        return LeagueSelection(
            scout=scout_override or fallback_scout_value,
            poe_ninja=ninja_override or fallback_ninja_value,
            source=source,
            warnings=tuple(warnings),
            discovery_url=url,
        )

    discovered_scout, discovered_ninja = discovered
    source = "explicit+auto" if used_explicit else "auto"
    return LeagueSelection(
        scout=scout_override or discovered_scout,
        poe_ninja=ninja_override or discovered_ninja,
        source=source,
        warnings=tuple(warnings),
        discovery_url=url,
    )


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
