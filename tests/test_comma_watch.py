from datetime import datetime

from tools.comma_watch import (
    athena_enqueue_order,
    categorize_segment_events,
    combine_bookmark_route_fill_segments,
    combine_priority_segments,
    Device,
    RouteBookmarkFill,
    SegmentEvent,
    SegmentTarget,
    alert_segments_with_lookback,
    desired_pending_paths,
    generate_candidate_paths,
    generate_candidate_paths_by_priority,
    is_owned_online_device,
    is_dm_alert_event,
    ordered_online_queue_paths,
    prioritize_segments,
    radiate_remaining_route_segments,
    Route,
    expand_segments,
    normalize_online_queue_item_path,
    normalize_queue_paths,
    normalize_uploaded_paths,
    parsed_segment_upper_bound,
    select_devices,
    should_clear_queue_while_waiting,
    target_queue_refresh_needed,
)


def test_expand_segments_clamps_route_bounds() -> None:
    assert expand_segments([0, 5], previous_segments=3, next_segments=1, max_segment=6) == [0, 1, 2, 3, 4, 5, 6]


def test_prioritize_segments_radiates_out_from_bookmark() -> None:
    assert prioritize_segments([5], previous_segments=3, next_segments=1, max_segment=6) == [5, 4, 6, 3, 2]


def test_alert_segments_with_lookback_prioritizes_center_then_history() -> None:
    assert alert_segments_with_lookback(5, previous_segments=2, max_segment=10) == [5, 4, 3]


def test_categorize_segment_events_splits_bookmark_and_alert() -> None:
    route = Route(
        fullname="fde53c3c109fb4c0|0000026f--c5469f881d",
        route_id="0000026f--c5469f881d",
        start_time="2026-03-28T04:59:16",
        end_time="2026-03-28T05:19:16",
        maxqlog=10,
        procqlog=10,
        url="https://example.test/route",
    )
    events = [
        {"type": "user_bookmark", "route_offset_millis": 301000, "data": {}},
        {"type": "state", "route_offset_millis": 361000, "data": {"alertStatus": 1, "state": "enabled"}},
    ]
    bookmarks, dm_alerts, alerts = categorize_segment_events(route, events, segment=5)
    assert sorted(bookmarks) == [5]
    assert sorted(dm_alerts) == []
    assert sorted(alerts) == [6]


def test_categorize_segment_events_splits_dm_alerts() -> None:
    route = Route(
        fullname="fde53c3c109fb4c0|0000026f--c5469f881d",
        route_id="0000026f--c5469f881d",
        start_time="2026-03-28T04:59:16",
        end_time="2026-03-28T05:19:16",
        maxqlog=10,
        procqlog=10,
        url="https://example.test/route",
    )
    events = [
        {
            "type": "state",
            "route_offset_millis": 361000,
            "data": {"alertStatus": 1, "alertType": "driverDistracted"},
        },
    ]
    bookmarks, dm_alerts, alerts = categorize_segment_events(route, events, segment=5)
    assert sorted(bookmarks) == []
    assert sorted(dm_alerts) == [6]
    assert sorted(alerts) == []


def test_is_dm_alert_event_detects_driver_monitoring_strings() -> None:
    assert is_dm_alert_event({"data": {"alertType": "driverUnresponsive"}}) is True
    assert is_dm_alert_event({"data": {"alertType": "controlsUnresponsive"}}) is False


def test_combine_priority_segments_orders_recent_bookmarks_then_older_then_alerts() -> None:
    bookmark_events = [
        SegmentEvent("route-a", 1, datetime.fromisoformat("2026-03-28T01:00:00+00:00"), 10),
        SegmentEvent("route-b", 2, datetime.fromisoformat("2026-03-28T02:00:00+00:00"), 10),
        SegmentEvent("route-c", 3, datetime.fromisoformat("2026-03-28T03:00:00+00:00"), 10),
        SegmentEvent("route-d", 4, datetime.fromisoformat("2026-03-28T04:00:00+00:00"), 10),
        SegmentEvent("route-e", 5, datetime.fromisoformat("2026-03-28T05:00:00+00:00"), 10),
        SegmentEvent("route-f", 6, datetime.fromisoformat("2026-03-28T06:00:00+00:00"), 10),
        SegmentEvent("route-g", 7, datetime.fromisoformat("2026-03-28T07:00:00+00:00"), 10),
    ]
    alert_events = [
        SegmentEvent("route-h", 8, datetime.fromisoformat("2026-03-28T08:00:00+00:00"), 10),
        SegmentEvent("route-i", 9, datetime.fromisoformat("2026-03-28T09:00:00+00:00"), 10),
    ]
    prioritized_groups = combine_priority_segments(
        bookmark_events=bookmark_events,
        dm_alert_events=[],
        alert_events=alert_events,
        previous_segments=3,
        next_segments=1,
    )
    assert prioritized_groups == [
        [
            SegmentTarget("route-g", 7),
            SegmentTarget("route-g", 6),
            SegmentTarget("route-g", 8),
            SegmentTarget("route-g", 5),
            SegmentTarget("route-g", 4),
            SegmentTarget("route-f", 6),
            SegmentTarget("route-f", 5),
            SegmentTarget("route-f", 7),
            SegmentTarget("route-f", 4),
            SegmentTarget("route-f", 3),
            SegmentTarget("route-e", 5),
            SegmentTarget("route-e", 4),
            SegmentTarget("route-e", 6),
            SegmentTarget("route-e", 3),
            SegmentTarget("route-e", 2),
            SegmentTarget("route-d", 4),
            SegmentTarget("route-d", 3),
            SegmentTarget("route-d", 5),
            SegmentTarget("route-d", 2),
            SegmentTarget("route-d", 1),
            SegmentTarget("route-c", 3),
            SegmentTarget("route-c", 2),
            SegmentTarget("route-c", 4),
            SegmentTarget("route-c", 1),
            SegmentTarget("route-c", 0),
        ],
        [
            SegmentTarget("route-a", 1),
            SegmentTarget("route-a", 0),
            SegmentTarget("route-a", 2),
            SegmentTarget("route-b", 2),
            SegmentTarget("route-b", 1),
            SegmentTarget("route-b", 3),
            SegmentTarget("route-b", 0),
        ],
        [
        ],
        [
            SegmentTarget("route-h", 8),
            SegmentTarget("route-h", 7),
            SegmentTarget("route-h", 6),
            SegmentTarget("route-i", 9),
            SegmentTarget("route-i", 8),
            SegmentTarget("route-i", 7),
        ],
    ]


def test_radiate_remaining_route_segments_expands_out_from_seed_window() -> None:
    assert radiate_remaining_route_segments(10, {2, 3, 4, 5, 6}) == [1, 7, 0, 8, 9, 10]


def test_combine_bookmark_route_fill_segments_fills_bookmarked_routes_after_priority_windows() -> None:
    bookmark_events = [
        SegmentEvent("route-old", 5, datetime.fromisoformat("2026-03-28T05:00:00+00:00"), 10),
        SegmentEvent("route-new", 8, datetime.fromisoformat("2026-03-28T08:00:00+00:00"), 12),
    ]
    result = combine_bookmark_route_fill_segments(
        bookmark_events=bookmark_events,
        recent_bookmark_targets=[
            SegmentTarget("route-new", 8),
            SegmentTarget("route-new", 7),
            SegmentTarget("route-new", 9),
            SegmentTarget("route-new", 6),
            SegmentTarget("route-new", 5),
        ],
        older_bookmark_targets=[
            SegmentTarget("route-old", 5),
            SegmentTarget("route-old", 4),
            SegmentTarget("route-old", 6),
            SegmentTarget("route-old", 3),
            SegmentTarget("route-old", 2),
        ],
        recent_bookmark_count=1,
    )
    assert result == RouteBookmarkFill(
        recent_fill_targets=[
            SegmentTarget("route-new", 4),
            SegmentTarget("route-new", 10),
            SegmentTarget("route-new", 3),
            SegmentTarget("route-new", 11),
            SegmentTarget("route-new", 2),
            SegmentTarget("route-new", 12),
            SegmentTarget("route-new", 1),
            SegmentTarget("route-new", 0),
        ],
        older_fill_targets=[
            SegmentTarget("route-old", 1),
            SegmentTarget("route-old", 7),
            SegmentTarget("route-old", 0),
            SegmentTarget("route-old", 8),
            SegmentTarget("route-old", 9),
            SegmentTarget("route-old", 10),
        ],
    )


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


def test_normalize_online_queue_item_path_extracts_segment_dir_and_filename() -> None:
    item = {"path": "/data/media/0/realdata/0000026f--c5469f881d--2/fcamera.hevc"}
    assert normalize_online_queue_item_path(item) == "0000026f--c5469f881d--2/fcamera.hevc"


def test_ordered_online_queue_paths_preserves_queue_order() -> None:
    online_queue = [
        {"path": "/data/media/0/realdata/0000026f--c5469f881d--2/fcamera.hevc"},
        {"path": "/data/media/0/realdata/0000026f--c5469f881d--1/rlog.zst"},
    ]
    assert ordered_online_queue_paths(online_queue) == [
        "0000026f--c5469f881d--2/fcamera.hevc",
        "0000026f--c5469f881d--1/rlog.zst",
    ]


def test_desired_pending_paths_skips_uploaded_files() -> None:
    assert desired_pending_paths(
        ["a/fcamera.hevc", "a/rlog.zst", "a/ecamera.hevc"],
        {"a/rlog.zst"},
    ) == ["a/fcamera.hevc", "a/ecamera.hevc"]


def test_target_queue_refresh_needed_when_order_is_wrong() -> None:
    online_queue = [
        {"id": "1", "path": "/data/media/0/realdata/route--2/fcamera.hevc"},
        {"id": "2", "path": "/data/media/0/realdata/route--2/rlog.zst"},
    ]
    assert (
        target_queue_refresh_needed(
            online_queue,
            desired_pending_paths=["route--2/fcamera.hevc", "route--2/rlog.zst"],
            missing_paths=["route--2/fcamera.hevc"],
            target_paths={"route--2/fcamera.hevc", "route--2/rlog.zst"},
        )
        is True
    )


def test_target_queue_refresh_not_needed_when_order_matches() -> None:
    online_queue = [
        {"id": "1", "path": "/data/media/0/realdata/lower--1/fcamera.hevc"},
        {"id": "2", "path": "/data/media/0/realdata/route--2/rlog.zst"},
        {"id": "3", "path": "/data/media/0/realdata/route--2/fcamera.hevc"},
    ]
    assert (
        target_queue_refresh_needed(
            online_queue,
            desired_pending_paths=["route--2/fcamera.hevc", "route--2/rlog.zst"],
            missing_paths=["route--2/fcamera.hevc"],
            target_paths={"route--2/fcamera.hevc", "route--2/rlog.zst"},
        )
        is False
    )


def test_target_queue_refresh_not_needed_when_no_pending_targets_remain() -> None:
    online_queue = [
        {"id": "1", "path": "/data/media/0/realdata/other--2/fcamera.hevc"},
        {"id": "2", "path": "/data/media/0/realdata/other--2/rlog.zst"},
    ]
    assert (
        target_queue_refresh_needed(
            online_queue,
            desired_pending_paths=[],
            missing_paths=[],
            target_paths={"route--2/fcamera.hevc", "route--2/rlog.zst"},
        )
        is False
    )


def test_target_queue_refresh_not_needed_when_all_desired_paths_are_already_queued() -> None:
    online_queue = [
        {"id": "1", "path": "/data/media/0/realdata/route--2/rlog.zst"},
        {"id": "2", "path": "/data/media/0/realdata/route--2/fcamera.hevc"},
    ]
    assert (
        target_queue_refresh_needed(
            online_queue,
            desired_pending_paths=["route--2/fcamera.hevc", "route--2/rlog.zst"],
            missing_paths=[],
            target_paths={"route--2/fcamera.hevc", "route--2/rlog.zst"},
        )
        is False
    )


def test_should_not_clear_queue_when_priority_targets_are_already_done() -> None:
    assert (
        should_clear_queue_while_waiting(
            prioritized_segments=[SegmentTarget("route--1", 2)],
            has_pending_priority=False,
        )
        is False
    )


def test_should_not_clear_queue_when_no_priority_targets_exist() -> None:
    assert (
        should_clear_queue_while_waiting(
            prioritized_segments=[],
            has_pending_priority=False,
        )
        is False
    )


def test_parsed_segment_upper_bound_clamps_to_available_segments() -> None:
    route = Route(
        fullname="fde53c3c109fb4c0|0000026f--c5469f881d",
        route_id="0000026f--c5469f881d",
        start_time="2026-03-28T04:59:16",
        end_time="2026-03-28T05:19:16",
        maxqlog=20,
        procqlog=17,
        url="https://example.test/route",
    )
    assert parsed_segment_upper_bound(route) == 17


def test_generate_candidate_paths_requests_rlog_zst_only() -> None:
    route = Route(
        fullname="fde53c3c109fb4c0|0000026f--c5469f881d",
        route_id="0000026f--c5469f881d",
        start_time="2026-03-28T04:59:16",
        end_time="2026-03-28T05:19:16",
        maxqlog=20,
        procqlog=20,
        url="https://example.test/route",
    )
    assert generate_candidate_paths(route, [2], ["cameras", "logs"]) == [
        "0000026f--c5469f881d--2/fcamera.hevc",
        "0000026f--c5469f881d--2/rlog.zst",
    ]


def test_generate_candidate_paths_by_priority_orders_file_types_within_each_tier() -> None:
    assert generate_candidate_paths_by_priority(
        [
            [SegmentTarget("0000026f--c5469f881d", 5), SegmentTarget("0000026f--c5469f881d", 4)],
            [SegmentTarget("00000270--abc", 8)],
        ],
        ["cameras", "logs", "ecameras", "dcameras"],
    ) == [
        "0000026f--c5469f881d--5/fcamera.hevc",
        "0000026f--c5469f881d--5/rlog.zst",
        "0000026f--c5469f881d--5/ecamera.hevc",
        "0000026f--c5469f881d--5/dcamera.hevc",
        "0000026f--c5469f881d--4/fcamera.hevc",
        "0000026f--c5469f881d--4/rlog.zst",
        "0000026f--c5469f881d--4/ecamera.hevc",
        "0000026f--c5469f881d--4/dcamera.hevc",
        "00000270--abc--8/fcamera.hevc",
        "00000270--abc--8/rlog.zst",
        "00000270--abc--8/ecamera.hevc",
        "00000270--abc--8/dcamera.hevc",
    ]


def test_generate_candidate_paths_by_priority_supports_dm_boost_file_order() -> None:
    assert generate_candidate_paths_by_priority(
        [
            [SegmentTarget("route-bookmark", 5)],
            [SegmentTarget("route-old-bookmark", 4)],
            [SegmentTarget("route-dm", 3)],
            [SegmentTarget("route-alert", 2)],
        ],
        [
            ["cameras", "logs", "ecameras", "dcameras"],
            ["cameras", "logs", "ecameras", "dcameras"],
            ["cameras", "logs", "dcameras", "ecameras"],
            ["cameras", "logs", "ecameras", "dcameras"],
        ],
    ) == [
        "route-bookmark--5/fcamera.hevc",
        "route-bookmark--5/rlog.zst",
        "route-bookmark--5/ecamera.hevc",
        "route-bookmark--5/dcamera.hevc",
        "route-old-bookmark--4/fcamera.hevc",
        "route-old-bookmark--4/rlog.zst",
        "route-old-bookmark--4/ecamera.hevc",
        "route-old-bookmark--4/dcamera.hevc",
        "route-dm--3/fcamera.hevc",
        "route-dm--3/rlog.zst",
        "route-dm--3/dcamera.hevc",
        "route-dm--3/ecamera.hevc",
        "route-alert--2/fcamera.hevc",
        "route-alert--2/rlog.zst",
        "route-alert--2/ecamera.hevc",
        "route-alert--2/dcamera.hevc",
    ]


def test_athena_enqueue_order_reverses_priority_paths_for_tail_first_queue() -> None:
    assert athena_enqueue_order(
        [
            "route--2/fcamera.hevc",
            "route--2/rlog.zst",
            "route--1/fcamera.hevc",
        ]
    ) == [
        "route--1/fcamera.hevc",
        "route--2/rlog.zst",
        "route--2/fcamera.hevc",
    ]


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
