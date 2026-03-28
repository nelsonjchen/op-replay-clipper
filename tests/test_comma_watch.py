from datetime import date, datetime
from zoneinfo import ZoneInfo

from comma_watch import (
    Device,
    is_owned_online_device,
    Route,
    expand_segments,
    local_date_from_arg,
    normalize_online_queue_item_path,
    normalize_queue_paths,
    normalize_uploaded_paths,
    parsed_segment_upper_bound,
    select_devices,
)


def test_expand_segments_clamps_route_bounds() -> None:
    assert expand_segments([0, 5], previous_segments=3, next_segments=1, max_segment=6) == [0, 1, 2, 3, 4, 5, 6]


def test_normalize_uploaded_paths_extracts_route_segment_and_filename() -> None:
    filelist = {
        "cameras": [
            "https://commadata2.blob.core.windows.net/commadata2/fde53c3c109fb4c0/0000026f--c5469f881d/2/fcamera.hevc?sig=x"
        ],
        "logs": [
            "https://commadata2.blob.core.windows.net/commadata2/fde53c3c109fb4c0/0000026f--c5469f881d/2/rlog.zst?sig=x"
        ],
    }
    assert normalize_uploaded_paths(filelist) == {
        "0000026f--c5469f881d--2/fcamera.hevc",
        "0000026f--c5469f881d--2/rlog.zst",
    }


def test_normalize_queue_paths_handles_online_and_offline_shapes() -> None:
    online_queue = [
        {"path": "/data/media/0/realdata/0000026f--c5469f881d--2/fcamera.hevc"},
    ]
    offline_queue = [
        {
            "method": "uploadFilesToUrls",
            "params": {"files_data": [{"fn": "0000026f--c5469f881d--3/rlog.zst"}]},
        }
    ]
    assert normalize_queue_paths(online_queue, offline_queue) == {
        "0000026f--c5469f881d--2/fcamera.hevc",
        "0000026f--c5469f881d--3/rlog.zst",
    }


def test_local_date_from_arg_today_uses_timezone_today() -> None:
    tz = ZoneInfo("America/Los_Angeles")
    today = datetime.now(tz).date()
    assert local_date_from_arg("today", tz) == today
    assert local_date_from_arg(today.isoformat(), tz) == date.fromisoformat(today.isoformat())


def test_normalize_online_queue_item_path_extracts_segment_dir_and_filename() -> None:
    item = {"path": "/data/media/0/realdata/0000026f--c5469f881d--2/fcamera.hevc"}
    assert normalize_online_queue_item_path(item) == "0000026f--c5469f881d--2/fcamera.hevc"


def test_parsed_segment_upper_bound_clamps_to_available_segments() -> None:
    route = Route(
        fullname="fde53c3c109fb4c0|0000026f--c5469f881d",
        route_id="0000026f--c5469f881d",
        start_time="2026-03-28T04:59:16",
        maxqlog=20,
        procqlog=17,
        url="https://example.test/route",
    )
    assert parsed_segment_upper_bound(route) == 17


def test_select_devices_defaults_to_owned_online_devices() -> None:
    now = 1_000
    devices = [
        {"alias": "Mine Online", "dongle_id": "a", "is_owner": True, "last_athena_ping": now},
        {"alias": "Mine Offline", "dongle_id": "b", "is_owner": True, "last_athena_ping": now - 500},
        {"alias": "Not Mine", "dongle_id": "c", "is_owner": False, "last_athena_ping": now},
    ]
    assert is_owned_online_device(devices[0], now=now) is True
    assert is_owned_online_device(devices[1], now=now) is False
    assert is_owned_online_device(devices[2], now=now) is False
    assert select_devices(devices, "", now=now) == [Device(alias="Mine Online", dongle_id="a")]
