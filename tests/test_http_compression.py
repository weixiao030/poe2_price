"""Compressed providers must yield valid, bounded JSON just like plain responses."""
import gzip
import sys
from email.message import Message
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "物价补丁/tools"))
from price_sources import http_client


def decode(body, encoding=""):
    headers = Message()
    headers["Content-Type"] = "application/json; charset=utf-8"
    headers["Content-Encoding"] = encoding
    return http_client.RetryingRequests()._decode_response(
        "https://example.invalid/prices", 200, "OK", headers, body
    )


@pytest.mark.parametrize("encoding", ["", "identity", "gzip", "GZip"])
def test_json_is_identical_with_or_without_compression(encoding):
    body = '{"name":"神圣石","price":2}'.encode("utf-8")
    assert decode(gzip.compress(body) if encoding.lower() == "gzip" else body, encoding).json() == {
        "name": "神圣石", "price": 2
    }


@pytest.mark.parametrize("damage", ["truncated", "crc", "plain"])
def test_invalid_gzip_never_reaches_the_parser(damage):
    body = gzip.compress(b'{"price":2}')
    if damage == "truncated":
        body = body[:-5]
    elif damage == "crc":
        body = body[:-8] + bytes([body[-8] ^ 1]) + body[-7:]
    else:
        body = b'{"price":2}'
    with pytest.raises((OSError, EOFError)):
        decode(body, "gzip")


def test_expansion_limit_including_concatenated_members(monkeypatch):
    monkeypatch.setattr(http_client, "MAX_HTTP_RESPONSE_BYTES", 64)
    assert len(decode(gzip.compress(b"x" * 64), "gzip").content) == 64
    with pytest.raises(RuntimeError, match="decoded response exceeded"):
        decode(gzip.compress(b"x" * 40) + gzip.compress(b"y" * 40), "gzip")


def test_unrequested_compression_is_rejected():
    with pytest.raises(ValueError, match="unsupported Content-Encoding"):
        decode(b"bad", "br")
