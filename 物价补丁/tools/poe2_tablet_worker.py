"""Run the optional tablet affix layer outside the main price build process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

# The release's embedded Python omits the script directory from sys.path.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from price_sources.http_client import RetryingRequests


PATH_OPTIONS = (
    "template_it", "template_csd", "source_baseitems", "patched_baseitems",
    "output_zip", "resource_report", "english_baseitems", "template_map_csd",
    "template_global_csd", "tablet_mods", "tablet_stats", "tablet_tags", "cache_dir",
)
HTTP_OPTIONS = ("max_retries", "backoff", "timeout", "total_timeout", "user_agent")


def build_tablet_affix_resources_isolated(*, client, **options):
    # The caller retains backups of the ZIP and DAT. Even a native crash after
    # the worker has written either file is handled by the caller's rollback.
    request = dict(options)
    for key in PATH_OPTIONS:
        if request.get(key) is not None:
            request[key] = str(Path(request[key]).resolve())
    request["display_rates"] = {
        key: str(value) for key, value in (request.get("display_rates") or {}).items()
    }
    http_options = {key: getattr(client, key) for key in HTTP_OPTIONS}
    with tempfile.TemporaryDirectory(prefix=".tablet-worker-", dir=options["output_zip"].parent) as work:
        request_path = Path(work) / "request.json"
        result_path = Path(work) / "result.json"
        request_path.write_text(json.dumps({"options": request, "http": http_options},
                                          ensure_ascii=False), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-u", str(Path(__file__).resolve()),
             str(request_path), str(result_path)],
            # Inherit the build log streams so progress and native tracebacks
            # are visible immediately rather than only at worker completion.
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            check=False,
        )
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        if completed.returncode:
            code = completed.returncode & 0xFFFFFFFF
            signed = code if code < 0x80000000 else code - 0x100000000
            raise RuntimeError(
                f"tablet worker failed: exit code {signed} (0x{code:08X})"
                + (f": {result['error']}" if result.get("error") else "")
            )
        report = result.get("report")
        if not isinstance(report, dict) or report.get("status") not in {"ok", "partial"}:
            raise RuntimeError("tablet worker returned no valid build report")
        return report


def main(argv):
    from decimal import Decimal
    from poe2_tablet_prices import build_tablet_affix_resources

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    request_path, result_path = map(Path, argv)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    options = request["options"]
    for key in PATH_OPTIONS:
        if options.get(key) is not None:
            options[key] = Path(options[key])
    options["display_rates"] = {key: Decimal(value) for key, value in options["display_rates"].items()}
    try:
        report = build_tablet_affix_resources(
            client=RetryingRequests(**request["http"]),
            on_retry=lambda message: print(f"[进度] {message}", flush=True), **options,
        )
    except Exception as exc:
        result_path.write_text(json.dumps({"error": f"{type(exc).__name__}: {exc}"},
                                          ensure_ascii=False), encoding="utf-8")
        raise
    result_path.write_text(json.dumps({"report": report}, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
