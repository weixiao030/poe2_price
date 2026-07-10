"""Serializable health and schema-drift contracts for price sources.

The module deliberately has no dependency on the patch builder.  An adapter
can feed it the response metadata and the counts it already knows, then write
``SourceHealth.to_dict()`` directly into a JSON report.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Iterable, Mapping, Sequence


HEALTHY = "healthy"
PARTIAL = "partial"
STALE = "stale"
EMPTY = "empty"
INCOMPATIBLE = "incompatible"
FAILED = "failed"
SKIPPED = "skipped"

HEALTH_STATES = frozenset(
    {HEALTHY, PARTIAL, STALE, EMPTY, INCOMPATIBLE, FAILED, SKIPPED}
)
USABLE_STATES = frozenset({HEALTHY, PARTIAL, STALE})
TERMINAL_STATES = frozenset({EMPTY, INCOMPATIBLE, FAILED})

DEFAULT_REQUIRED_REFERENCES = ("Divine Orb", "Exalted Orb")
SCHEMA_FINGERPRINT_VERSION = 1


@dataclass(frozen=True)
class HttpObservation:
    """Small, provider-neutral subset of an HTTP response."""

    status_code: int | None = None
    content_type: str = ""
    url: str = ""
    elapsed_ms: int | None = None
    content_bytes: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "elapsed_ms": self.elapsed_ms,
            "content_bytes": self.content_bytes,
        }


@dataclass(frozen=True)
class HealthIssue:
    """Stable issue code plus a human-readable diagnostic."""

    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class CategoryMetrics:
    discovered: int
    enabled: int
    succeeded: int
    failed: int
    discovered_names: tuple[str, ...] = ()
    enabled_names: tuple[str, ...] = ()
    succeeded_names: tuple[str, ...] = ()
    failed_names: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "discovered": self.discovered,
            "enabled": self.enabled,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "names": {
                "discovered": list(self.discovered_names),
                "enabled": list(self.enabled_names),
                "succeeded": list(self.succeeded_names),
                "failed": list(self.failed_names),
            },
        }


@dataclass(frozen=True)
class ReferenceMetrics:
    checked: bool
    required: tuple[str, ...]
    present: tuple[str, ...]
    missing: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "required": list(self.required),
            "present": list(self.present),
            "missing": list(self.missing),
        }


@dataclass(frozen=True)
class FreshnessObservation:
    source_timestamp: str
    checked_at: str
    age_seconds: float | None
    max_age_seconds: float | None
    stale: bool
    parse_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_timestamp": self.source_timestamp,
            "checked_at": self.checked_at,
            "age_seconds": self.age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "stale": self.stale,
            "parse_error": self.parse_error,
        }


@dataclass(frozen=True)
class SchemaFingerprint:
    """Value-free description of a JSON document's shape.

    ``fields`` stores JSON-pointer-like paths and the JSON types observed at
    each path.  Array indexes are represented by ``*`` so item values and
    collection length never affect the digest.
    """

    root_kind: str
    fields: tuple[tuple[str, tuple[str, ...]], ...]
    key_fields: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    version: int = SCHEMA_FINGERPRINT_VERSION

    @property
    def digest(self) -> str:
        encoded = json.dumps(
            self._body(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _body(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "root_kind": self.root_kind,
            "fields": {path: list(types) for path, types in self.fields},
            "key_fields": list(self.key_fields),
            "categories": list(self.categories),
        }

    def to_dict(self) -> dict[str, Any]:
        result = self._body()
        result["digest"] = self.digest
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SchemaFingerprint":
        raw_fields = value.get("fields", {})
        fields: list[tuple[str, tuple[str, ...]]] = []
        if isinstance(raw_fields, Mapping):
            for path, types in raw_fields.items():
                if isinstance(types, str):
                    type_names = (types,)
                elif isinstance(types, Sequence):
                    type_names = tuple(sorted({str(item) for item in types}))
                else:
                    type_names = (str(types),)
                fields.append((str(path), type_names))
        else:
            raise TypeError("schema fingerprint fields must be an object")

        return cls(
            root_kind=str(value.get("root_kind", "unknown")),
            fields=tuple(sorted(fields)),
            key_fields=_normalized_labels(value.get("key_fields", ())),
            categories=_normalized_labels(value.get("categories", ())),
            version=int(value.get("version", SCHEMA_FINGERPRINT_VERSION)),
        )


@dataclass(frozen=True)
class SchemaDrift:
    root_kind_changed: bool = False
    previous_root_kind: str = ""
    current_root_kind: str = ""
    added_fields: tuple[str, ...] = ()
    removed_fields: tuple[str, ...] = ()
    changed_field_types: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...]], ...
    ] = ()
    added_key_fields: tuple[str, ...] = ()
    removed_key_fields: tuple[str, ...] = ()
    added_categories: tuple[str, ...] = ()
    removed_categories: tuple[str, ...] = ()

    @property
    def has_drift(self) -> bool:
        return any(
            (
                self.root_kind_changed,
                self.added_fields,
                self.removed_fields,
                self.changed_field_types,
                self.added_key_fields,
                self.removed_key_fields,
                self.added_categories,
                self.removed_categories,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_drift": self.has_drift,
            "root_kind_changed": self.root_kind_changed,
            "previous_root_kind": self.previous_root_kind,
            "current_root_kind": self.current_root_kind,
            "added_fields": list(self.added_fields),
            "removed_fields": list(self.removed_fields),
            "changed_field_types": {
                path: {"before": list(before), "after": list(after)}
                for path, before, after in self.changed_field_types
            },
            "added_key_fields": list(self.added_key_fields),
            "removed_key_fields": list(self.removed_key_fields),
            "added_categories": list(self.added_categories),
            "removed_categories": list(self.removed_categories),
        }


@dataclass(frozen=True)
class SourceHealth:
    source: str
    state: str
    root_kind: str
    expected_root_kinds: tuple[str, ...]
    item_count: int | None
    match_count: int | None
    categories: CategoryMetrics
    references: ReferenceMetrics
    http: HttpObservation | None = None
    freshness: FreshnessObservation | None = None
    schema: SchemaFingerprint | None = None
    drift: SchemaDrift | None = None
    issues: tuple[HealthIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.state not in HEALTH_STATES:
            raise ValueError(f"unknown health state: {self.state}")

    @property
    def usable(self) -> bool:
        return self.state in USABLE_STATES

    @property
    def is_failure(self) -> bool:
        """Whether the source is unusable; ``partial`` is deliberately false."""

        return self.state in TERMINAL_STATES

    @property
    def is_failed(self) -> bool:
        """Whether transport/execution itself failed (not merely incompatible)."""

        return self.state == FAILED

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "state": self.state,
            "usable": self.usable,
            "is_failure": self.is_failure,
            "is_failed": self.is_failed,
            "root_kind": self.root_kind,
            "expected_root_kinds": list(self.expected_root_kinds),
            "counts": {
                "items": self.item_count,
                "matches": self.match_count,
                "categories": self.categories.to_dict(),
            },
            "references": self.references.to_dict(),
            "http": self.http.to_dict() if self.http is not None else None,
            "freshness": (
                self.freshness.to_dict() if self.freshness is not None else None
            ),
            "schema": self.schema.to_dict() if self.schema is not None else None,
            "schema_drift": self.drift.to_dict() if self.drift is not None else None,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def schema_fingerprint(
    payload: Any,
    *,
    key_fields: Iterable[str] = (),
    categories: Iterable[str] = (),
    max_depth: int = 32,
) -> SchemaFingerprint:
    """Build a deterministic schema fingerprint without retaining data values."""

    if max_depth < 0:
        raise ValueError("max_depth must be non-negative")

    field_types: dict[str, set[str]] = {}
    pending: list[tuple[Any, str, int]] = [(payload, "#", 0)]
    while pending:
        value, path, depth = pending.pop()
        kind = json_kind(value)
        field_types.setdefault(path, set()).add(kind)
        if depth >= max_depth:
            continue
        if isinstance(value, Mapping):
            for key, child in value.items():
                child_path = f"{path}/{_escape_pointer_token(str(key))}"
                pending.append((child, child_path, depth + 1))
        elif isinstance(value, (list, tuple)):
            child_path = f"{path}/*"
            for child in value:
                pending.append((child, child_path, depth + 1))

    fields = tuple(
        (path, tuple(sorted(types))) for path, types in sorted(field_types.items())
    )
    return SchemaFingerprint(
        root_kind=json_kind(payload),
        fields=fields,
        key_fields=_normalized_labels(key_fields),
        categories=_normalized_labels(categories),
    )


def compare_schema(
    baseline: SchemaFingerprint | Mapping[str, Any],
    current: SchemaFingerprint | Mapping[str, Any],
) -> SchemaDrift:
    """Compare two fingerprints and return stable added/removed/type deltas."""

    before = _coerce_schema_fingerprint(baseline)
    after = _coerce_schema_fingerprint(current)
    before_fields = dict(before.fields)
    after_fields = dict(after.fields)
    common_paths = set(before_fields).intersection(after_fields)
    changed_types = tuple(
        (path, before_fields[path], after_fields[path])
        for path in sorted(common_paths)
        if before_fields[path] != after_fields[path]
    )

    return SchemaDrift(
        root_kind_changed=before.root_kind != after.root_kind,
        previous_root_kind=before.root_kind,
        current_root_kind=after.root_kind,
        added_fields=tuple(sorted(set(after_fields).difference(before_fields))),
        removed_fields=tuple(sorted(set(before_fields).difference(after_fields))),
        changed_field_types=changed_types,
        added_key_fields=tuple(
            sorted(set(after.key_fields).difference(before.key_fields))
        ),
        removed_key_fields=tuple(
            sorted(set(before.key_fields).difference(after.key_fields))
        ),
        added_categories=tuple(
            sorted(set(after.categories).difference(before.categories))
        ),
        removed_categories=tuple(
            sorted(set(before.categories).difference(after.categories))
        ),
    )


def evaluate_source_health(
    source: str,
    payload: Any,
    *,
    expected_root: str | Iterable[str] = ("object", "array"),
    http: HttpObservation | Mapping[str, Any] | Any | None = None,
    item_count: int | None = None,
    match_count: int | None = None,
    item_names: Iterable[str] | None = None,
    required_references: Iterable[str] = DEFAULT_REQUIRED_REFERENCES,
    discovered_categories: Iterable[str] | int = (),
    enabled_categories: Iterable[str] | int = (),
    succeeded_categories: Iterable[str] | int = (),
    failed_categories: Iterable[str] | int = (),
    freshness_timestamp: datetime | int | float | str | None = None,
    max_age_seconds: float | None = None,
    now: datetime | int | float | str | None = None,
    timestamp_timezone: tzinfo = timezone.utc,
    key_fields: Iterable[str] = (),
    baseline_schema: SchemaFingerprint | Mapping[str, Any] | None = None,
    minimum_match_ratio: float | None = None,
    degrade_on_schema_drift: bool = True,
    accepted_content_types: Iterable[str] = (),
    error: BaseException | str | None = None,
) -> SourceHealth:
    """Evaluate one source and return a JSON-ready, provider-neutral report.

    Category failures, a parseable non-JSON content type, low match coverage,
    and schema drift produce ``partial`` rather than ``failed``.  Transport or
    execution errors are the only route to ``failed``.
    """

    expected_roots = _expected_root_kinds(expected_root)
    http_observation = _coerce_http_observation(http)
    categories = _category_metrics(
        discovered_categories,
        enabled_categories,
        succeeded_categories,
        failed_categories,
    )
    references = _reference_metrics(item_names, required_references)
    freshness = _freshness_observation(
        freshness_timestamp,
        max_age_seconds=max_age_seconds,
        now=now,
        default_timezone=timestamp_timezone,
    )
    current_schema = schema_fingerprint(
        payload,
        key_fields=key_fields,
        categories=categories.discovered_names,
    )
    drift = (
        compare_schema(baseline_schema, current_schema)
        if baseline_schema is not None
        else None
    )
    issues: list[HealthIssue] = []

    _validate_count("item_count", item_count)
    _validate_count("match_count", match_count)
    if max_age_seconds is not None and max_age_seconds < 0:
        raise ValueError("max_age_seconds must be non-negative")
    if minimum_match_ratio is not None and not 0 <= minimum_match_ratio <= 1:
        raise ValueError("minimum_match_ratio must be between 0 and 1")

    state = HEALTHY
    if error is not None:
        detail = str(error).strip() or error.__class__.__name__
        issues.append(HealthIssue("request_failed", detail))
        state = FAILED
    elif (
        http_observation is not None
        and http_observation.status_code is not None
        and not 200 <= http_observation.status_code < 300
    ):
        issues.append(
            HealthIssue(
                "http_status",
                f"HTTP status {http_observation.status_code} is not successful",
            )
        )
        state = FAILED
    elif current_schema.root_kind not in expected_roots:
        issues.append(
            HealthIssue(
                "unexpected_root",
                f"expected {', '.join(expected_roots)}, got {current_schema.root_kind}",
            )
        )
        state = INCOMPATIBLE
    elif item_count == 0 or (match_count == 0 and item_count != 0):
        code = "empty_items" if item_count == 0 else "empty_matches"
        issues.append(HealthIssue(code, "source returned no usable rows"))
        state = EMPTY
    elif references.checked and references.missing:
        issues.append(
            HealthIssue(
                "missing_references",
                "missing required reference currencies: "
                + ", ".join(references.missing),
            )
        )
        state = INCOMPATIBLE
    elif freshness is not None and freshness.stale:
        issues.append(HealthIssue("stale", "source timestamp exceeds maximum age"))
        state = STALE

    partial_issues: list[HealthIssue] = []
    if http_observation is not None and http_observation.content_type:
        if not _is_expected_content_type(
            http_observation.content_type, accepted_content_types
        ):
            partial_issues.append(
                HealthIssue(
                    "unexpected_content_type",
                    f"response content type is {http_observation.content_type}",
                )
            )
    if categories.failed > 0:
        partial_issues.append(
            HealthIssue(
                "category_failures",
                f"{categories.failed} enabled categories failed",
            )
        )
    unresolved = _unresolved_enabled_categories(categories)
    if unresolved:
        partial_issues.append(
            HealthIssue(
                "category_unresolved",
                "enabled categories have no success/failure result: "
                + ", ".join(unresolved),
            )
        )
    if freshness is not None and freshness.parse_error:
        partial_issues.append(
            HealthIssue("invalid_timestamp", freshness.parse_error)
        )
    if (
        minimum_match_ratio is not None
        and item_count is not None
        and item_count > 0
        and match_count is not None
        and match_count / item_count < minimum_match_ratio
    ):
        partial_issues.append(
            HealthIssue(
                "low_match_ratio",
                f"match ratio {match_count / item_count:.6f} is below "
                f"{minimum_match_ratio:.6f}",
            )
        )
    if degrade_on_schema_drift and drift is not None and drift.has_drift:
        partial_issues.append(
            HealthIssue("schema_drift", "response structure differs from baseline")
        )

    issues.extend(partial_issues)
    if state == HEALTHY and partial_issues:
        state = PARTIAL

    return SourceHealth(
        source=str(source),
        state=state,
        root_kind=current_schema.root_kind,
        expected_root_kinds=expected_roots,
        item_count=item_count,
        match_count=match_count,
        categories=categories,
        references=references,
        http=http_observation,
        freshness=freshness,
        schema=current_schema,
        drift=drift,
        issues=tuple(issues),
    )


def failed_source_health(
    source: str,
    error: BaseException | str,
    *,
    http: HttpObservation | Mapping[str, Any] | Any | None = None,
) -> SourceHealth:
    """Create a failure report when no compatible payload is available."""

    return evaluate_source_health(
        source,
        None,
        expected_root=("object", "array"),
        required_references=(),
        http=http,
        error=error,
    )


def skipped_source_health(source: str, reason: str = "") -> SourceHealth:
    """Create a stable report for a source disabled by configuration."""

    issue = (HealthIssue("skipped", reason),) if reason else ()
    return SourceHealth(
        source=str(source),
        state=SKIPPED,
        root_kind="unknown",
        expected_root_kinds=(),
        item_count=None,
        match_count=None,
        categories=CategoryMetrics(0, 0, 0, 0),
        references=ReferenceMetrics(False, (), (), ()),
        issues=issue,
    )


def json_kind(value: Any) -> str:
    """Return a JSON-oriented type name, keeping bool distinct from integer."""

    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "unsupported"


def _coerce_schema_fingerprint(
    value: SchemaFingerprint | Mapping[str, Any],
) -> SchemaFingerprint:
    if isinstance(value, SchemaFingerprint):
        return value
    if isinstance(value, Mapping):
        return SchemaFingerprint.from_dict(value)
    raise TypeError("schema baseline must be SchemaFingerprint or mapping")


def _expected_root_kinds(value: str | Iterable[str]) -> tuple[str, ...]:
    values = (value,) if isinstance(value, str) else tuple(value)
    cleaned = tuple(sorted({str(item).strip().casefold() for item in values if str(item).strip()}))
    if not cleaned:
        raise ValueError("expected_root must contain at least one JSON root kind")
    return cleaned


def _category_metrics(
    discovered: Iterable[str] | int,
    enabled: Iterable[str] | int,
    succeeded: Iterable[str] | int,
    failed: Iterable[str] | int,
) -> CategoryMetrics:
    discovered_count, discovered_names = _count_and_names(discovered)
    enabled_count, enabled_names = _count_and_names(enabled)
    succeeded_count, succeeded_names = _count_and_names(succeeded)
    failed_count, failed_names = _count_and_names(failed)
    return CategoryMetrics(
        discovered_count,
        enabled_count,
        succeeded_count,
        failed_count,
        discovered_names,
        enabled_names,
        succeeded_names,
        failed_names,
    )


def _count_and_names(value: Iterable[str] | int) -> tuple[int, tuple[str, ...]]:
    if isinstance(value, bool):
        raise TypeError("category count cannot be boolean")
    if isinstance(value, int):
        if value < 0:
            raise ValueError("category count must be non-negative")
        return value, ()
    names = _normalized_labels(value)
    return len(names), names


def _normalized_labels(values: Iterable[Any]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        values = (values,)
    return tuple(sorted({str(value).strip() for value in values if str(value).strip()}))


def _reference_metrics(
    item_names: Iterable[str] | None,
    required_references: Iterable[str],
) -> ReferenceMetrics:
    required = _normalized_labels(required_references)
    if item_names is None:
        return ReferenceMetrics(False, required, (), ())
    normalized_items = {_normalize_item_name(value) for value in item_names}
    present = tuple(
        reference
        for reference in required
        if _normalize_item_name(reference) in normalized_items
    )
    missing = tuple(reference for reference in required if reference not in present)
    return ReferenceMetrics(True, required, present, missing)


def _normalize_item_name(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _freshness_observation(
    timestamp: datetime | int | float | str | None,
    *,
    max_age_seconds: float | None,
    now: datetime | int | float | str | None,
    default_timezone: tzinfo,
) -> FreshnessObservation | None:
    if timestamp is None:
        return None
    checked_at = _coerce_datetime(now, default_timezone) if now is not None else datetime.now(timezone.utc)
    try:
        source_time = _coerce_datetime(timestamp, default_timezone)
    except (TypeError, ValueError, OverflowError) as exc:
        return FreshnessObservation(
            source_timestamp=str(timestamp),
            checked_at=_utc_text(checked_at),
            age_seconds=None,
            max_age_seconds=max_age_seconds,
            stale=False,
            parse_error=str(exc),
        )

    age = max(0.0, (checked_at - source_time).total_seconds())
    stale = max_age_seconds is not None and age > max_age_seconds
    return FreshnessObservation(
        source_timestamp=_utc_text(source_time),
        checked_at=_utc_text(checked_at),
        age_seconds=age,
        max_age_seconds=max_age_seconds,
        stale=stale,
    )


def _coerce_datetime(value: datetime | int | float | str, default_timezone: tzinfo) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, bool):
        raise TypeError("boolean is not a timestamp")
    elif isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ValueError("timestamp must be finite")
        seconds = float(value)
        if abs(seconds) >= 100_000_000_000:
            seconds /= 1000.0
        parsed = datetime.fromtimestamp(seconds, tz=timezone.utc)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("timestamp is empty")
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    else:
        raise TypeError(f"unsupported timestamp type: {type(value).__name__}")

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=default_timezone)
    return parsed.astimezone(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _coerce_http_observation(value: Any) -> HttpObservation | None:
    if value is None or isinstance(value, HttpObservation):
        return value

    if isinstance(value, Mapping):
        status_code = value.get("status_code", value.get("status"))
        content_type = value.get("content_type", "")
        headers = value.get("headers")
        if not content_type and isinstance(headers, Mapping):
            content_type = headers.get("content-type", headers.get("Content-Type", ""))
        return HttpObservation(
            status_code=int(status_code) if status_code is not None else None,
            content_type=str(content_type or ""),
            url=str(value.get("url", "") or ""),
            elapsed_ms=_optional_int(value.get("elapsed_ms")),
            content_bytes=_optional_int(
                value.get("content_bytes", value.get("bytes"))
            ),
        )

    status_code = getattr(value, "status_code", getattr(value, "status", None))
    content_type = getattr(value, "content_type", "")
    headers = getattr(value, "headers", None)
    if not content_type and isinstance(headers, Mapping):
        content_type = headers.get("content-type", headers.get("Content-Type", ""))
    return HttpObservation(
        status_code=int(status_code) if status_code is not None else None,
        content_type=str(content_type or ""),
        url=str(getattr(value, "url", "") or ""),
        elapsed_ms=_optional_int(getattr(value, "elapsed_ms", None)),
        content_bytes=_optional_int(
            getattr(value, "content_bytes", getattr(value, "bytes", None))
        ),
    )


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _is_json_content_type(value: str) -> bool:
    media_type = value.split(";", 1)[0].strip().casefold()
    return media_type == "application/json" or media_type.endswith("+json")


def _is_expected_content_type(value: str, accepted: Iterable[str]) -> bool:
    media_type = value.split(";", 1)[0].strip().casefold()
    accepted_media_types = {
        str(item).split(";", 1)[0].strip().casefold()
        for item in accepted
        if str(item).strip()
    }
    return _is_json_content_type(value) or media_type in accepted_media_types


def _unresolved_enabled_categories(categories: CategoryMetrics) -> tuple[str, ...]:
    if not categories.enabled_names:
        return ()
    resolved = set(categories.succeeded_names).union(categories.failed_names)
    return tuple(sorted(set(categories.enabled_names).difference(resolved)))


def _escape_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _validate_count(name: str, value: int | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer or None")
    if value < 0:
        raise ValueError(f"{name} must be non-negative")
