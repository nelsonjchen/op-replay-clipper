from __future__ import annotations

import bz2
from pathlib import Path

from core import route_downloader


def test_decompress_log_preserving_source_keeps_bz2(tmp_path: Path) -> None:
    compressed = tmp_path / "rlog.bz2"
    output = tmp_path / "rlog"
    payload = b"hello route log"
    compressed.write_bytes(bz2.compress(payload))

    route_downloader._decompress_log_preserving_source(compressed, output)

    assert compressed.exists()
    assert output.read_bytes() == payload
