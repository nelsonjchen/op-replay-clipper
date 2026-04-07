from __future__ import annotations

import bz2
from pathlib import Path
import re

import pytest

from core import route_downloader


def test_decompress_log_preserving_source_keeps_bz2(tmp_path: Path) -> None:
    compressed = tmp_path / "rlog.bz2"
    output = tmp_path / "rlog"
    payload = b"hello route log"
    compressed.write_bytes(bz2.compress(payload))

    route_downloader._decompress_log_preserving_source(compressed, output)

    assert compressed.exists()
    assert output.read_bytes() == payload


class _FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


def _empty_filelist() -> dict[str, list[str]]:
    return {
        "cameras": [],
        "dcameras": [],
        "ecameras": [],
        "logs": [],
        "qlogs": [],
        "qcameras": [],
    }


def test_missing_upload_message_uses_route_relative_connect_url_and_preroll_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = "fde53c3c109fb4c0|00000284--a36981be25"

    def _fake_get(url: str, headers=None):
        assert headers is None
        assert url == f"https://api.commadotai.com/v1/route/{route.replace('|', '%7C')}/files"
        return _FakeResponse(_empty_filelist())

    monkeypatch.setattr(route_downloader.requests, "get", _fake_get)

    with pytest.raises(ValueError) as excinfo:
        route_downloader.downloadSegments(
            data_dir=tmp_path,
            route_or_segment=route,
            smear_seconds=3,
            start_seconds=1,
            length=266,
            file_types=["cameras"],
            decompress_logs=False,
        )

    message = str(excinfo.value)
    assert "Segment 0 does not have a forward camera upload." in message
    assert 'Open https://connect.comma.ai/fde53c3c109fb4c0/00000284--a36981be25/1/267, use "Files" to upload the missing files with "Upload All"' in message
    assert "This clip starts 1 seconds into the route, so it still uses route segment 0 because Connect clip URLs are relative to the route start." in message
    assert "This render also uses 3 seconds of hidden preroll, so it can require uploads from before the visible clip start." in message
    assert "Upload ## Files" not in message
    assert re.search(r"https://connect\.comma\.ai/fde53c3c109fb4c0/\d{10,}/\d{10,}", message) is None


def test_missing_upload_message_omits_preroll_note_without_smear(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    route = "fde53c3c109fb4c0|00000284--a36981be25"

    monkeypatch.setattr(
        route_downloader.requests,
        "get",
        lambda url, headers=None: _FakeResponse(_empty_filelist()),
    )

    with pytest.raises(ValueError) as excinfo:
        route_downloader.downloadSegments(
            data_dir=tmp_path,
            route_or_segment=route,
            smear_seconds=0,
            start_seconds=61,
            length=5,
            file_types=["cameras"],
            decompress_logs=False,
        )

    message = str(excinfo.value)
    assert "Segment 1 does not have a forward camera upload." in message
    assert 'Open https://connect.comma.ai/fde53c3c109fb4c0/00000284--a36981be25/61/66, use "Files" to upload the missing files with "Upload All"' in message
    assert "hidden preroll" not in message
    assert "route segment 0" not in message
