"""Small standard-library HTTP client with retry, deadline, and metrics support."""

from __future__ import annotations

import json
import queue
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_REQUEST_TIME_BUDGET = 45.0
HTTP_READ_CHUNK_SIZE = 64 * 1024
MAX_HTTP_RESPONSE_BYTES = 64 * 1024 * 1024


def compact_text(value: Any, limit: int = 140) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


@dataclass(frozen=True)
class HttpResponse:
    url: str
    status_code: int
    reason: str
    content: bytes
    encoding: str = "utf-8"
    content_type: str = ""

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding or "utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    @property
    def content_bytes(self) -> int:
        return len(self.content)


class RequestDeadlineExceeded(TimeoutError):
    """A wall-clock deadline expired while an HTTP worker was still active."""


class RetryingRequests:
    def __init__(
        self,
        max_retries: int = 4,
        backoff: float = 0.8,
        timeout: float = 25.0,
        total_timeout: float = DEFAULT_REQUEST_TIME_BUDGET,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 poe2-price-patch/1.0"
        ),
    ) -> None:
        self.max_retries = max(0, int(max_retries))
        self.backoff = max(0.0, float(backoff))
        self.timeout = max(0.1, float(timeout))
        self.total_timeout = max(0.1, float(total_timeout))
        self.user_agent = user_agent
        self.retry_statuses = {429, 500, 502, 503, 504}
        self._metrics_lock = threading.Lock()
        self._request_metrics: list[dict[str, Any]] = []

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
        }

    def _decode_response(
        self,
        url: str,
        status_code: int,
        reason: str,
        headers: Any,
        content: bytes,
    ) -> HttpResponse:
        encoding = "utf-8"
        get_content_charset = getattr(headers, "get_content_charset", None)
        if callable(get_content_charset):
            encoding = get_content_charset() or encoding
        content_type = ""
        get_header = getattr(headers, "get", None)
        if callable(get_header):
            content_type = str(get_header("Content-Type", "") or "")
        return HttpResponse(
            url=url,
            status_code=status_code,
            reason=reason,
            content=content,
            encoding=encoding,
            content_type=content_type,
        )

    def _record_request_metric(
        self,
        request_url: str,
        started: float,
        attempts: int,
        response: HttpResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        metric = {
            "request_url": request_url,
            "final_url": response.url if response is not None else "",
            "status_code": response.status_code if response is not None else None,
            "content_type": response.content_type if response is not None else "",
            "content_bytes": response.content_bytes if response is not None else None,
            "attempts": attempts,
            "elapsed_ms": max(0, round((time.monotonic() - started) * 1000)),
            "error": f"{type(error).__name__}: {error}" if error is not None else "",
        }
        with self._metrics_lock:
            self._request_metrics.append(metric)

    def request_metrics(self) -> list[dict[str, Any]]:
        with self._metrics_lock:
            return [dict(metric) for metric in self._request_metrics]

    @staticmethod
    def _set_response_socket_timeout(response: Any, timeout: float) -> None:
        """Best-effort update of urllib's socket timeout for the next body read."""

        fp = getattr(response, "fp", None)
        raw = getattr(fp, "raw", None)
        sock = getattr(raw, "_sock", None)
        settimeout = getattr(sock, "settimeout", None)
        if callable(settimeout):
            settimeout(max(0.1, timeout))

    def _read_response_content(
        self,
        response: Any,
        url: str,
        deadline: float,
        cancel_event: threading.Event,
    ) -> bytes:
        chunks: list[bytes] = []
        total = 0
        read_chunk = getattr(response, "read1", None)
        if not callable(read_chunk):
            read_chunk = response.read

        while True:
            if cancel_event.is_set():
                raise RequestDeadlineExceeded(f"request cancelled after deadline: {url}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RequestDeadlineExceeded(f"response body exceeded deadline: {url}")
            self._set_response_socket_timeout(response, min(self.timeout, remaining))
            chunk = read_chunk(HTTP_READ_CHUNK_SIZE)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_HTTP_RESPONSE_BYTES:
                raise RuntimeError(
                    f"response exceeded {MAX_HTTP_RESPONSE_BYTES} byte safety limit: {url}"
                )

    def _get_once(
        self,
        url: str,
        timeout: float,
        cancel_event: threading.Event | None = None,
    ) -> HttpResponse:
        cancel_event = cancel_event or threading.Event()
        deadline = time.monotonic() + timeout
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = self._read_response_content(
                    response,
                    url,
                    deadline,
                    cancel_event,
                )
                return self._decode_response(
                    url=response.geturl(),
                    status_code=response.status,
                    reason=response.reason,
                    headers=response.headers,
                    content=content,
                )
        except urllib.error.HTTPError as exc:
            try:
                content = self._read_response_content(
                    exc,
                    url,
                    deadline,
                    cancel_event,
                )
                return self._decode_response(
                    url=exc.url,
                    status_code=exc.code,
                    reason=exc.reason,
                    headers=exc.headers,
                    content=content,
                )
            finally:
                exc.close()

    def _get_once_with_deadline(self, url: str, timeout: float) -> HttpResponse:
        """Run one urllib request behind a real wall-clock deadline.

        ``urlopen(timeout=...)`` only limits individual blocking socket operations.
        A large response that keeps delivering a few bytes can therefore make
        an unbounded body read run forever. A daemon worker lets the caller move
        on to fallback/error handling even when DNS, TLS, or a trickling response
        ignores that socket-level timeout.
        """

        result: queue.Queue[tuple[bool, Any]] = queue.Queue(maxsize=1)
        cancel_event = threading.Event()

        def request_worker() -> None:
            try:
                result.put((True, self._get_once(url, timeout, cancel_event)))
            except BaseException as exc:
                result.put((False, exc))

        worker = threading.Thread(
            target=request_worker,
            name="poe2-price-http",
            daemon=True,
        )
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            cancel_event.set()
            raise RequestDeadlineExceeded(
                f"request attempt exceeded {timeout:.1f}s wall-clock deadline: {url}"
            )

        succeeded, value = result.get_nowait()
        if succeeded:
            return value
        raise value

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        last_error: Exception | None = None
        request_started = time.monotonic()
        request_deadline = request_started + self.total_timeout
        attempts = 0
        for attempt in range(self.max_retries + 1):
            attempts = attempt + 1
            remaining = request_deadline - time.monotonic()
            if remaining <= 0:
                last_error = TimeoutError(
                    f"request exceeded {self.total_timeout:.1f}s total time budget: {url}"
                )
                break
            try:
                response = self._get_once_with_deadline(
                    url,
                    min(self.timeout, remaining),
                )
                if response.status_code < 400:
                    self._record_request_metric(
                        url, request_started, attempts, response=response
                    )
                    return response
                if response.status_code not in self.retry_statuses:
                    self._record_request_metric(
                        url, request_started, attempts, response=response
                    )
                    return response
                last_error = RuntimeError(f"{response.status_code} {response.reason}: {url}")
            except RequestDeadlineExceeded as exc:
                # The daemon may still be unwinding a blocked DNS/TLS/socket call.
                # Do not create another worker for this URL; fallback sources can
                # proceed immediately and this leaves at most one orphan thread.
                last_error = exc
                break
            except Exception as exc:
                last_error = exc
            if attempt < self.max_retries:
                delay = self.backoff * (2**attempt)
                remaining = request_deadline - time.monotonic()
                if remaining <= 0:
                    last_error = TimeoutError(
                        f"request exceeded {self.total_timeout:.1f}s total time budget: {url}"
                    )
                    break
                delay = min(delay, remaining)
                print(
                    "[进度] 请求失败，"
                    f"{delay:.1f}s 后重试 {attempt + 1}/{self.max_retries}: "
                    f"{compact_text(url)} ({compact_text(last_error)})",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(delay)
        assert last_error is not None
        self._record_request_metric(url, request_started, attempts, error=last_error)
        raise last_error

    def get_json(self, url: str) -> Any:
        response = self.get(url)
        return response.json()
