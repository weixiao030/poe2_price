"""Optional native termination must not discard a completed core price build."""

from contextlib import contextmanager
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
import threading
from urllib.parse import parse_qs, urlparse
import zipfile

import pytest

from tests.test_tablet_affixes import synthetic_baseitems, csd, game_tables, refs, names
from tests.test_tablet_cn import cn_page, LEAGUE
from tests.test_cn_historical_prices import snapshot
from tests.test_whole_tablets import words_fixture
import build_poe2scout_price_patch as builder
import poe2_tablet_worker as worker
from price_sources.http_client import RetryingRequests


ROOT = Path(__file__).resolve().parents[1]
BUNDLED_PYTHON = ROOT / "desktop/.runtime/tools/python/poe_python.exe"
TARGET = "data/balance/simplified chinese/baseitemtypes.datc64"


@contextmanager
def tablet_server():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlparse(self.path).query)
            requests.append(query)
            body = json.dumps(cn_page(query["rarity"][0]), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("runtime", ["system", "bundled"])
def test_isolated_worker_builds_valid_resources_with_real_http(tmp_path, monkeypatch, runtime):
    if runtime == "bundled":
        if not BUNDLED_PYTHON.exists():
            pytest.skip("prepare the release Python runtime first")
        monkeypatch.setattr(worker.sys, "executable", str(BUNDLED_PYTHON))
    source = tmp_path / "中文底板.dat"
    source.write_bytes(synthetic_baseitems())
    english = tmp_path / "english.dat"
    english.write_bytes(synthetic_baseitems(english=True))
    patched = tmp_path / "patched.dat"
    patched.write_bytes(source.read_bytes())
    template = tmp_path / "template.it"
    template.write_text('Mods\n{\nstat_description_list = "Data/StatDescriptions/tablet_stat_descriptions.csd"\n}\n', encoding="utf-8")
    descriptions = tmp_path / "tablet.csd"
    descriptions.write_bytes(csd().encode("utf-8"))
    archive = tmp_path / "补丁.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(TARGET, source.read_bytes())
        z.writestr("data/balance/simplified chinese/words.datc64", b"preserved unique layer")
    report_path = tmp_path / "report.json"
    with tablet_server() as (api, requests):
        report = worker.build_tablet_affix_resources_isolated(
            client=RetryingRequests(max_retries=0, timeout=5, total_timeout=5),
            api_base=api, league=LEAGUE, template_it=template, template_csd=descriptions,
            source_baseitems=source, patched_baseitems=patched, output_zip=archive,
            game_path=TARGET, resource_report=report_path, english_baseitems=english,
            display_rates={"exalted": Decimal(1), "chaos": Decimal(100), "divine": Decimal(500)},
            server="cn", include_base_prices=False, league_resolved=True, **game_tables(tmp_path),
        )
    assert len(requests) == 2
    assert {q["rarity"][0] for q in requests} == {"magic", "rare"}
    assert all(q["league"] == [LEAGUE] and q["server"] == ["cn"] for q in requests)
    assert report == json.loads(report_path.read_text(encoding="utf-8"))
    assert report["resources"] and report["league"] == LEAGUE
    assert report["display_rates_exalted"]["divine"] == "500"
    with zipfile.ZipFile(archive) as z:
        entries = {key: z.read(key) for key in z.namelist()}
    refs.validate_resources(entries)
    assert entries[TARGET] == patched.read_bytes()
    assert entries["data/balance/simplified chinese/words.datc64"] == b"preserved unique layer"
    assert not list(tmp_path.glob(".tablet-worker-*"))


@pytest.mark.parametrize("failure", ["native-exit", "ordinary-exception", "missing-report"])
def test_worker_failure_rolls_back_partial_writes_and_main_build_finishes(tmp_path, monkeypatch, failure):
    source = tmp_path / "source.dat"
    english = tmp_path / "english.dat"
    for path, is_english in ((source, False), (english, True)):
        raw = synthetic_baseitems(english=is_english)
        item = names.scan_base_item_names(raw)[-1]
        edits, warnings = names.build_replacements(names.scan_base_item_names(raw), [dict(
            metadata_path=item.metadata_path, new_name="E Item" if is_english else "E 物品",
        )], "=", False, "append", False)
        assert not warnings
        path.write_bytes(names.apply_replacements_append(raw, edits))
    words = tmp_path / "words.dat"
    words_fixture(words, "传奇物品")
    words_data = bytearray(words.read_bytes())
    pointer = len(words_data) - (4 + builder.WORDS_ROW_SIZE)
    words_data.extend("Test Unique\0\0".encode("utf-16-le"))
    struct.pack_into("<I", words_data, 4 + builder.WORDS_EN_NAME_OFFSET, pointer)
    words.write_bytes(words_data)
    gold = tmp_path / "gold.dat"
    gold.write_bytes(struct.pack("<I", 1) + bytes(builder.UNIQUE_GOLD_PRICES_ROW_SIZE))
    patched = tmp_path / "patched.dat"
    out = tmp_path / "out"
    archive = out / "patch.zip"
    original_run = subprocess.run
    launched = []
    before_worker = {}

    def terminate_worker(command, **kwargs):
        if str(Path(worker.__file__).resolve()) not in command:
            return original_run(command, **kwargs)
        launched.append(command)
        before_worker["dat"] = patched.read_bytes()
        # Execute a real child, corrupt both staging files, then terminate with
        # the player's Windows status (no crash dialog or real game involved).
        code = """
import ctypes, json, os, pathlib, sys
request = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))['options']
pathlib.Path(request['output_zip']).write_bytes(b'partial corrupt ZIP')
pathlib.Path(request['patched_baseitems']).write_bytes(b'partial corrupt DAT')
pathlib.Path(request['resource_report']).write_text('{}', encoding='utf-8')
if sys.argv[3] == 'native-exit':
    if os.name == 'nt': ctypes.windll.kernel32.ExitProcess(ctypes.c_uint32(0xC0000409))
    os._exit(71)
if sys.argv[3] == 'ordinary-exception':
    pathlib.Path(sys.argv[2]).write_text(json.dumps({'error':'ValueError: bad tablet snapshot'}), encoding='utf-8')
    sys.exit(1)
"""
        return original_run([sys.executable, "-c", code, command[-2], command[-1], failure], **kwargs)

    class Client(RetryingRequests):
        def get_json(self, url):
            if "poecurrency.top" in url:
                payload = snapshot(stale=False)
                payload[0]["items"].append(dict(item_name="传奇物品", engname="Test Unique",
                    currency_unit="e", latest_buy1=600,
                    latest_datetime=payload[0]["items"][0]["latest_datetime"]))
                return payload
            if urlparse(url).path.endswith("/leagues"):
                return {"server": "cn", "default": LEAGUE, "stale": False,
                        "data": [{"name": LEAGUE, "hardcore": False, "current": True}]}
            assert urlparse(url).path.endswith("/currencies")
            return {"server": "cn", "league": LEAGUE, "primary": "exalted", "stale": False,
                    "values": {"exalted": 1, "chaos": 100, "divine": 500}}

    monkeypatch.setattr(builder, "RetryingRequests", Client)
    monkeypatch.setattr(worker.subprocess, "run", terminate_worker)
    assert builder.main([
        "--patch-scope", "all", "--no-tablet-prices", "--resolved-leagues",
        "--cn-reference-source", "none", "--fallback-price-sources", "none",
        "--price-source", "poecurrency-cn", "--en-baseitems", str(english),
        "--tc-baseitems", str(source), "--out-dir", str(out), "--output-zip", str(archive),
        "--patched-dat", str(patched), "--game-path", TARGET,
        "--en-words", str(words), "--tc-words", str(words), "--unique-gold-prices", str(gold),
    ]) == 0
    assert len(launched) == 1
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["tablet_affixes"]["status"] == "skipped"
    reason = summary["tablet_affixes"]["reason"]
    if failure == "native-exit" and os.name == "nt":
        assert "-1073740791 (0xC0000409)" in reason
    elif failure == "ordinary-exception":
        assert "bad tablet snapshot" in reason
    elif failure == "missing-report":
        assert "no valid build report" in reason
    assert patched.read_bytes() == before_worker["dat"]
    assert names.scan_base_item_names(patched.read_bytes())[-1].name == "E 物品=2.5C"
    assert summary["unique_words_patched"] == 1
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == {TARGET, "data/balance/simplified chinese/words.datc64"}
        assert z.read(TARGET) == before_worker["dat"]
        word_data = z.read("data/balance/simplified chinese/words.datc64")
        assert builder.read_words_row(word_data, builder.detect_words_layout(word_data), 0).display_name == "[2D|传奇物品]"
    assert not (out / "tablet_affix.report.json").exists()
    assert not list(out.glob(".tablet-worker-*"))
