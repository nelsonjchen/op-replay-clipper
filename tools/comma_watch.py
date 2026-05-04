#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo


API_URL = "https://api.comma.ai"
ATHENA_URL = "https://athena.comma.ai"
DEFAULT_FILE_TYPES = ("cameras", "logs", "ecameras", "dcameras")
ONLINE_DEVICE_WINDOW_SECONDS = 120
RECENT_BOOKMARK_COUNT = 5
ALERT_LOOKBACK_SEGMENTS = 2
DEFAULT_STATE_PATH = "/tmp/comma-watch-state.json"
FILE_TYPE_NAMES = {
    "cameras": ("fcamera.hevc",),
    "dcameras": ("dcamera.hevc",),
    "ecameras": ("ecamera.hevc",),
    "logs": ("rlog.bz2", "rlog.zst"),
}
DISPLAY_FILE_ORDER = ("fcamera", "rlog", "ecamera", "dcamera")
DM_DISPLAY_FILE_ORDER = ("fcamera", "rlog", "dcamera", "ecamera")
BOOKMARK_EVENT_TYPES = {"user_flag", "user_bookmark", "bookmark"}
USER_PROMPT_ALERT_STATUSES = {1, "1", "userPrompt", "user_prompt"}
DM_ALERT_HINTS = (
    "driver",
    "distract",
    "toodistracted",
    "toounresponsive",
    "predriverdistracted",
    "predriverunresponsive",
    "promptdriver",
)
PHASE_REASON_LABELS = {
    "recent_bookmarks": "recent bookmark",
    "older_bookmarks": "older bookmark",
    "dm_alerts": "DM alert",
    "alerts": "alert",
    "bookmark_fill_recent": "bookmark fill",
    "bookmark_fill_older": "bookmark fill",
}
LOW_QUALITY_FILE_KINDS = {"qlog", "qcamera"}
PHASE_PRIORITY_BASES = {
    "recent_bookmarks": 0,
    "older_bookmarks": 12,
    "dm_alerts": 24,
    "alerts": 36,
    "bookmark_fill_recent": 60,
    "bookmark_fill_older": 72,
}
MAX_WATCHER_PRIORITY = 98
FILE_KIND_BY_TYPE = {
    "cameras": ("fcamera",),
    "logs": ("rlog",),
    "ecameras": ("ecamera",),
    "dcameras": ("dcamera",),
}


@dataclass(frozen=True)
class Device:
    alias: str | None
    dongle_id: str


@dataclass(frozen=True)
class Route:
    fullname: str
    route_id: str
    start_time: str | None
    end_time: str | None
    maxqlog: int
    procqlog: int | None
    url: str


@dataclass(frozen=True)
class UploadFile:
    file_path: str
    url: str
    headers: dict[str, str]


@dataclass(frozen=True)
class ScanOutcome:
    targets_found: bool
    uploads_queued: bool
    all_target_files_satisfied: bool
    queue_cleared: bool


@dataclass(frozen=True)
class SegmentEvent:
    route_id: str
    segment: int
    event_time: datetime
    max_segment: int
    category: str = "generic"


@dataclass(frozen=True)
class SegmentTarget:
    route_id: str
    segment: int


@dataclass(frozen=True)
class PriorityEvents:
    bookmark_events: list[SegmentEvent]
    dm_alert_events: list[SegmentEvent]
    alert_events: list[SegmentEvent]


@dataclass(frozen=True)
class RouteBookmarkFill:
    recent_fill_targets: list[SegmentTarget]
    older_fill_targets: list[SegmentTarget]


@dataclass(frozen=True)
class QueueEntry:
    path: str
    route_id: str
    segment: int
    filename: str
    file_kind: str | None
    current: bool
    progress: float
    retry_count: int
    priority: int | None
    upload_id: str | None


class CommaApi:
    def __init__(self, jwt_token: str, *, session: requests.Session | None = None) -> None:
        self.session = session or requests.Session()
        self.session.headers.update({"Authorization": f"JWT {jwt_token}"})

    def get_devices(self) -> list[dict[str, Any]]:
        return self._get_json("/v1/me/devices")

    def get_routes(self, dongle_id: str, *, limit: int = 100, created_before: int | None = None) -> list[dict[str, Any]]:
        endpoint = f"/v1/devices/{dongle_id}/routes?limit={limit}"
        if created_before is not None:
            endpoint += f"&created_before={created_before}"
        return self._get_json(endpoint)

    def get_route(self, route_name: str) -> dict[str, Any]:
        return self._get_json(f"/v1/route/{route_name}/")

    def get_route_files(self, route_name: str) -> dict[str, list[str]]:
        return self._get_json(f"/v1/route/{route_name}/files")

    def request_upload_urls(self, dongle_id: str, paths: list[str], *, expiry_days: int = 7) -> list[dict[str, Any]]:
        return self._post_json(
            f"/v1/{dongle_id}/upload_urls/",
            {"expiry_days": expiry_days, "paths": paths},
            api_url=API_URL,
        )

    def get_athena_offline_queue(self, dongle_id: str) -> list[dict[str, Any]]:
        return self._get_json(f"/v1/devices/{dongle_id}/athena_offline_queue")

    def athena_call(self, dongle_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        return self._post_jsonrpc(dongle_id, method, params)

    def cancel_uploads(self, dongle_id: str, upload_ids: list[str]) -> dict[str, Any] | None:
        if not upload_ids:
            return None
        return self.athena_call(dongle_id, "cancelUpload", {"upload_id": upload_ids})

    def get_events(self, route_url: str, segment: int) -> list[dict[str, Any]]:
        response = requests.get(f"{route_url}/{segment}/events.json", timeout=30)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        return response.json()

    def _get_json(self, endpoint: str) -> Any:
        response = self.session.get(urljoin(API_URL, endpoint), timeout=30)
        response.raise_for_status()
        return response.json()

    def _post_json(self, endpoint: str, payload: dict[str, Any], *, api_url: str) -> Any:
        response = self.session.post(
            urljoin(api_url, endpoint),
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    def _post_jsonrpc(self, dongle_id: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{ATHENA_URL}/{dongle_id}",
            json={"id": 0, "jsonrpc": "2.0", "method": method, "params": params},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return response.json()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Watch Comma routes for bookmarks and alerts and queue high-quality uploads."
    )
    parser.add_argument(
        "--device-alias",
        default=os.environ.get("COMMA_DEVICE_ALIAS", ""),
        help="Optional device alias filter. If omitted, scans every owned online device.",
    )
    parser.add_argument("--jwt-token", default=os.environ.get("COMMA_JWT", ""), help="Comma JWT token. Defaults to COMMA_JWT.")
    parser.add_argument("--timezone", default=os.environ.get("TZ", "America/Los_Angeles"))
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=48,
        help="Only inspect routes whose local start time is within this many hours. Defaults to 48.",
    )
    parser.add_argument("--poll-seconds", type=int, default=30, help="Polling interval while waiting for bookmarks or uploads.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="How long to watch before exiting. Use 0 to run forever.",
    )
    parser.add_argument(
        "--previous-segments",
        type=int,
        default=3,
        help="How many segments before each bookmarked segment to upload.",
    )
    parser.add_argument(
        "--next-segments",
        type=int,
        default=1,
        help="How many segments after each bookmarked segment to upload.",
    )
    parser.add_argument(
        "--file-types",
        nargs="+",
        choices=sorted(FILE_TYPE_NAMES),
        default=list(DEFAULT_FILE_TYPES),
        help="High-quality file types to queue.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one scan and exit instead of polling.",
    )
    parser.add_argument(
        "--exit-when-satisfied",
        action="store_true",
        help="Exit once bookmarked segments are already uploaded or successfully queued.",
    )
    parser.add_argument(
        "--exclusive-bookmark-priority",
        action="store_true",
        help="Keep the upload queue clear until bookmarks/alerts exist, then keep only those uploads queued.",
    )
    parser.add_argument(
        "--state-path",
        default=os.environ.get("COMMA_WATCH_STATE_PATH", DEFAULT_STATE_PATH),
        help="Where to write the live watcher JSON state snapshot.",
    )
    return parser.parse_args()


def parse_route_start_local(start_time: str | None, tz: ZoneInfo) -> datetime | None:
    if not start_time:
        return None
    start = datetime.fromisoformat(start_time)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.astimezone(tz)


def parse_route_start_utc(start_time: str | None) -> datetime | None:
    if not start_time:
        return None
    start = datetime.fromisoformat(start_time)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return start.astimezone(timezone.utc)


def route_id_from_fullname(fullname: str) -> str:
    return fullname.split("|", 1)[1]


def parse_segment_path(raw_path: str) -> tuple[str, int, str] | None:
    path = Path(raw_path)
    segment_dir = path.parent.name
    if not segment_dir or "--" not in segment_dir:
        return None
    route_id, segment_text = segment_dir.rsplit("--", 1)
    try:
        segment = int(segment_text)
    except ValueError:
        return None
    return route_id, segment, path.name


def file_kind_for_filename(filename: str) -> str | None:
    if filename == "fcamera.hevc":
        return "fcamera"
    if filename == "dcamera.hevc":
        return "dcamera"
    if filename == "ecamera.hevc":
        return "ecamera"
    if filename in {"rlog.zst", "rlog.bz2"}:
        return "rlog"
    if filename.startswith("qlog"):
        return "qlog"
    if filename.startswith("qcamera"):
        return "qcamera"
    return None


def write_state_snapshot(state_path: Path, payload: dict[str, Any]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(f"{state_path.suffix}.tmp")
    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(state_path)


def find_device(devices: Iterable[dict[str, Any]], alias: str) -> Device:
    for device in devices:
        if device.get("alias") == alias:
            return Device(alias=device.get("alias"), dongle_id=device["dongle_id"])
    raise ValueError(f"Could not find a device with alias {alias!r}.")


def is_owned_online_device(device: dict[str, Any], *, now: int | None = None) -> bool:
    if not device.get("is_owner"):
        return False
    last_ping = device.get("last_athena_ping") or 0
    if now is None:
        now = int(time.time())
    return last_ping >= now - ONLINE_DEVICE_WINDOW_SECONDS


def select_devices(devices: Iterable[dict[str, Any]], device_alias: str | None, *, now: int | None = None) -> list[Device]:
    if device_alias:
        return [find_device(devices, device_alias)]

    if now is None:
        now = int(time.time())
    selected = [
        Device(alias=device.get("alias"), dongle_id=device["dongle_id"])
        for device in devices
        if is_owned_online_device(device, now=now)
    ]
    selected.sort(key=lambda device: ((device.alias or "").lower(), device.dongle_id))
    return selected


def list_routes_in_lookback_window(api: CommaApi, dongle_id: str, *, window_start: datetime, tz: ZoneInfo) -> list[Route]:
    routes: list[Route] = []
    created_before: int | None = None

    for _ in range(10):
        batch = api.get_routes(dongle_id, created_before=created_before)
        if not batch:
            break
        for item in batch:
            start_local = parse_route_start_local(item.get("start_time"), tz)
            if start_local is not None and start_local >= window_start:
                routes.append(
                    Route(
                        fullname=item["fullname"],
                        route_id=route_id_from_fullname(item["fullname"]),
                        start_time=item.get("start_time"),
                        end_time=item.get("end_time"),
                        maxqlog=item.get("maxqlog", 0),
                        procqlog=item.get("procqlog"),
                        url=item["url"],
                    )
                )
        created_before = batch[-1]["create_time"]
        oldest_local = parse_route_start_local(batch[-1].get("start_time"), tz)
        if oldest_local is not None and oldest_local < window_start:
            break

    routes.sort(key=lambda route: parse_route_start_local(route.start_time, tz) or datetime.max.replace(tzinfo=tz))
    return routes


def parsed_segment_upper_bound(route: Route) -> int:
    if route.procqlog is None:
        return route.maxqlog
    return max(0, min(route.procqlog, route.maxqlog))


def segment_from_event(event: dict[str, Any], *, default_segment: int, max_segment: int) -> int:
    route_offset_millis = event.get("route_offset_millis")
    if route_offset_millis is None:
        return default_segment
    try:
        segment = int(route_offset_millis) // 60000
    except (TypeError, ValueError):
        return default_segment
    return max(0, min(max_segment, segment))


def event_time_for_route(route: Route, event: dict[str, Any], *, default_segment: int) -> datetime:
    route_start = parse_route_start_utc(route.start_time)
    if route_start is None:
        return datetime.min.replace(tzinfo=timezone.utc)

    route_offset_millis = event.get("route_offset_millis")
    if route_offset_millis is None:
        return route_start + timedelta(minutes=default_segment)

    try:
        offset = int(route_offset_millis)
    except (TypeError, ValueError):
        return route_start + timedelta(minutes=default_segment)
    return route_start + timedelta(milliseconds=offset)


def is_dm_alert_event(event: dict[str, Any]) -> bool:
    data = event.get("data") or {}
    haystacks = (
        str(event.get("type", "")),
        str(data.get("alertType", "")),
        str(data.get("alertText1", "")),
        str(data.get("alertText2", "")),
        str(data.get("event", "")),
        str(data.get("name", "")),
    )
    lowered = " ".join(haystacks).lower()
    return any(hint in lowered for hint in DM_ALERT_HINTS)


def categorize_segment_events(
    route: Route, events: Iterable[dict[str, Any]], *, segment: int
) -> tuple[dict[int, datetime], dict[int, datetime], dict[int, datetime]]:
    bookmarks: dict[int, datetime] = {}
    dm_alerts: dict[int, datetime] = {}
    alerts: dict[int, datetime] = {}

    for event in events:
        target_segment = segment_from_event(event, default_segment=segment, max_segment=route.maxqlog)
        event_type = event.get("type")
        data = event.get("data") or {}
        event_time = event_time_for_route(route, event, default_segment=segment)

        if event_type in BOOKMARK_EVENT_TYPES:
            existing = bookmarks.get(target_segment)
            if existing is None or event_time > existing:
                bookmarks[target_segment] = event_time
        if data.get("alertStatus") in USER_PROMPT_ALERT_STATUSES:
            target_alerts = dm_alerts if is_dm_alert_event(event) else alerts
            existing = target_alerts.get(target_segment)
            if existing is None or event_time < existing:
                target_alerts[target_segment] = event_time

    return bookmarks, dm_alerts, alerts


def collect_priority_events(api: CommaApi, route: Route) -> PriorityEvents:
    bookmark_segments: dict[int, datetime] = {}
    dm_alert_segments: dict[int, datetime] = {}
    alert_segments: dict[int, datetime] = {}

    for seg in range(parsed_segment_upper_bound(route) + 1):
        try:
            events = api.get_events(route.url, seg)
        except requests.RequestException as exc:
            print(f"Skipping events for {route.route_id} seg={seg}: {exc}")
            continue
        bookmarks, dm_alerts, alerts = categorize_segment_events(route, events, segment=seg)
        for target_segment, event_time in bookmarks.items():
            existing = bookmark_segments.get(target_segment)
            if existing is None or event_time > existing:
                bookmark_segments[target_segment] = event_time
        for target_segment, event_time in dm_alerts.items():
            existing = dm_alert_segments.get(target_segment)
            if existing is None or event_time < existing:
                dm_alert_segments[target_segment] = event_time
        for target_segment, event_time in alerts.items():
            existing = alert_segments.get(target_segment)
            if existing is None or event_time < existing:
                alert_segments[target_segment] = event_time

    return PriorityEvents(
        bookmark_events=[
            SegmentEvent(
                route_id=route.route_id,
                segment=segment,
                event_time=event_time,
                max_segment=route.maxqlog,
                category="bookmark",
            )
            for segment, event_time in bookmark_segments.items()
        ],
        dm_alert_events=[
            SegmentEvent(
                route_id=route.route_id,
                segment=segment,
                event_time=event_time,
                max_segment=route.maxqlog,
                category="dm_alert",
            )
            for segment, event_time in dm_alert_segments.items()
        ],
        alert_events=[
            SegmentEvent(
                route_id=route.route_id,
                segment=segment,
                event_time=event_time,
                max_segment=route.maxqlog,
                category="alert",
            )
            for segment, event_time in alert_segments.items()
        ],
    )


def expand_segments(bookmarked: Iterable[int], *, previous_segments: int, next_segments: int, max_segment: int) -> list[int]:
    expanded: set[int] = set()
    for segment in bookmarked:
        start = max(0, segment - previous_segments)
        end = min(max_segment, segment + next_segments)
        expanded.update(range(start, end + 1))
    return sorted(expanded)


def prioritize_segments(bookmarked: Iterable[int], *, previous_segments: int, next_segments: int, max_segment: int) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()

    for segment in bookmarked:
        candidates = [segment]
        if previous_segments >= 1:
            candidates.append(segment - 1)
        if next_segments >= 1:
            candidates.append(segment + 1)
        for offset in range(2, previous_segments + 1):
            candidates.append(segment - offset)

        for candidate in candidates:
            if candidate < 0 or candidate > max_segment or candidate in seen:
                continue
            seen.add(candidate)
            ordered.append(candidate)

    return ordered


def alert_segments_with_lookback(segment: int, *, previous_segments: int, max_segment: int) -> list[int]:
    ordered: list[int] = []
    for candidate in [segment, *range(segment - 1, segment - previous_segments - 1, -1)]:
        if 0 <= candidate <= max_segment:
            ordered.append(candidate)
    return ordered


def dedupe_segment_targets(segment_targets: Iterable[SegmentTarget]) -> list[SegmentTarget]:
    ordered: list[SegmentTarget] = []
    seen: set[tuple[str, int]] = set()
    for target in segment_targets:
        key = (target.route_id, target.segment)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(target)
    return ordered


def combine_priority_segments(
    *,
    bookmark_events: Iterable[SegmentEvent],
    dm_alert_events: Iterable[SegmentEvent],
    alert_events: Iterable[SegmentEvent],
    previous_segments: int,
    next_segments: int,
    alert_lookback_segments: int = ALERT_LOOKBACK_SEGMENTS,
    recent_bookmark_count: int = RECENT_BOOKMARK_COUNT,
) -> list[list[SegmentTarget]]:
    bookmark_events_sorted = sorted(bookmark_events, key=lambda event: event.event_time)
    recent_bookmark_events = list(reversed(bookmark_events_sorted[-recent_bookmark_count:]))
    older_bookmark_events = bookmark_events_sorted[:-recent_bookmark_count]
    dm_alert_events_sorted = sorted(dm_alert_events, key=lambda event: event.event_time)
    alert_events_sorted = sorted(alert_events, key=lambda event: event.event_time)

    grouped_targets: list[list[SegmentTarget]] = []

    for bookmark_group in (recent_bookmark_events, older_bookmark_events):
        targets: list[SegmentTarget] = []
        for event in bookmark_group:
            for segment in prioritize_segments(
                [event.segment],
                previous_segments=previous_segments,
                next_segments=next_segments,
                max_segment=event.max_segment,
            ):
                targets.append(SegmentTarget(route_id=event.route_id, segment=segment))
        grouped_targets.append(dedupe_segment_targets(targets))

    dm_alert_targets: list[SegmentTarget] = []
    for event in dm_alert_events_sorted:
        for segment in alert_segments_with_lookback(
            event.segment,
            previous_segments=alert_lookback_segments,
            max_segment=event.max_segment,
        ):
            dm_alert_targets.append(SegmentTarget(route_id=event.route_id, segment=segment))
    grouped_targets.append(dedupe_segment_targets(dm_alert_targets))

    alert_targets: list[SegmentTarget] = []
    for event in alert_events_sorted:
        for segment in alert_segments_with_lookback(
            event.segment,
            previous_segments=alert_lookback_segments,
            max_segment=event.max_segment,
        ):
            alert_targets.append(SegmentTarget(route_id=event.route_id, segment=segment))
    grouped_targets.append(dedupe_segment_targets(alert_targets))

    return grouped_targets


def unique_route_order(events: Iterable[SegmentEvent]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for event in events:
        if event.route_id in seen:
            continue
        seen.add(event.route_id)
        ordered.append(event.route_id)
    return ordered


def radiate_remaining_route_segments(max_segment: int, seeded_segments: Iterable[int]) -> list[int]:
    seed_set = set(seeded_segments)
    if not seed_set:
        return list(range(max_segment + 1))

    remaining = [segment for segment in range(max_segment + 1) if segment not in seed_set]
    return sorted(
        remaining,
        key=lambda segment: (
            min(abs(segment - seed) for seed in seed_set),
            segment,
        ),
    )


def combine_bookmark_route_fill_segments(
    *,
    bookmark_events: Iterable[SegmentEvent],
    recent_bookmark_targets: Iterable[SegmentTarget],
    older_bookmark_targets: Iterable[SegmentTarget],
    recent_bookmark_count: int = RECENT_BOOKMARK_COUNT,
) -> RouteBookmarkFill:
    bookmark_events_sorted = sorted(bookmark_events, key=lambda event: event.event_time)
    recent_bookmark_events = list(reversed(bookmark_events_sorted[-recent_bookmark_count:]))
    older_bookmark_events = bookmark_events_sorted[:-recent_bookmark_count]

    route_max_segments: dict[str, int] = {}
    for event in bookmark_events_sorted:
        route_max_segments[event.route_id] = event.max_segment

    seeded_targets_by_route: dict[str, set[int]] = {}
    for target in list(recent_bookmark_targets) + list(older_bookmark_targets):
        seeded_targets_by_route.setdefault(target.route_id, set()).add(target.segment)

    recent_route_ids = unique_route_order(recent_bookmark_events)
    older_route_ids = [route_id for route_id in unique_route_order(older_bookmark_events) if route_id not in set(recent_route_ids)]

    def build_fill_targets(route_ids: list[str]) -> list[SegmentTarget]:
        fill_targets: list[SegmentTarget] = []
        for route_id in route_ids:
            seeded_segments = seeded_targets_by_route.get(route_id, set())
            max_segment = route_max_segments[route_id]
            for segment in radiate_remaining_route_segments(max_segment, seeded_segments):
                fill_targets.append(SegmentTarget(route_id=route_id, segment=segment))
        return fill_targets

    return RouteBookmarkFill(
        recent_fill_targets=build_fill_targets(recent_route_ids),
        older_fill_targets=build_fill_targets(older_route_ids),
    )


def normalize_uploaded_paths(filelist: dict[str, list[str]]) -> set[str]:
    uploaded: set[str] = set()
    for urls in filelist.values():
        for url in urls:
            parts = url.split("?")[0].split("/")
            if len(parts) < 3:
                continue
            route_id = parts[-3]
            segment = parts[-2]
            filename = parts[-1]
            uploaded.add(f"{route_id}--{segment}/{filename}")
    return uploaded


def build_route_file_inventory(filelist: dict[str, list[str]]) -> dict[tuple[str, int], dict[str, bool]]:
    inventory: dict[tuple[str, int], dict[str, bool]] = {}
    for urls in filelist.values():
        for url in urls:
            parts = url.split("?")[0].split("/")
            if len(parts) < 3:
                continue
            route_id = parts[-3]
            segment_text = parts[-2]
            filename = parts[-1]
            try:
                segment = int(segment_text)
            except ValueError:
                continue
            kind = file_kind_for_filename(filename)
            if kind is None:
                continue
            key = (route_id, segment)
            inventory.setdefault(key, empty_segment_files())[kind] = True
    return inventory


def normalize_queue_paths(online_queue: list[dict[str, Any]], offline_queue: list[dict[str, Any]]) -> set[str]:
    queued: set[str] = set()

    for item in online_queue:
        raw_path = item.get("path", "")
        if not raw_path:
            continue
        path = Path(raw_path)
        segment_dir = path.parent.name
        if not segment_dir:
            continue
        queued.add(f"{segment_dir}/{path.name}")

    for item in offline_queue:
        if item.get("method") != "uploadFilesToUrls":
            continue
        params = item.get("params") or {}
        for file_data in params.get("files_data", []):
            fn = file_data.get("fn")
            if fn:
                queued.add(fn)

    return queued


def normalize_online_queue_item_path(item: dict[str, Any]) -> str | None:
    raw_path = item.get("path", "")
    if not raw_path:
        return None
    path = Path(raw_path)
    segment_dir = path.parent.name
    if not segment_dir:
        return None
    return f"{segment_dir}/{path.name}"


def ordered_online_queue_paths(online_queue: list[dict[str, Any]]) -> list[str]:
    ordered_paths: list[str] = []
    for item in online_queue:
        normalized = normalize_online_queue_item_path(item)
        if normalized is not None:
            ordered_paths.append(normalized)
    return ordered_paths


def summarize_online_queue(online_queue: list[dict[str, Any]]) -> list[QueueEntry]:
    entries: list[QueueEntry] = []
    for item in online_queue:
        normalized = normalize_online_queue_item_path(item)
        if normalized is None:
            continue
        parsed = parse_segment_path(normalized)
        if parsed is None:
            continue
        route_id, segment, filename = parsed
        entries.append(
            QueueEntry(
                path=normalized,
                route_id=route_id,
                segment=segment,
                filename=filename,
                file_kind=file_kind_for_filename(filename),
                current=bool(item.get("current")),
                progress=float(item.get("progress") or 0.0),
                retry_count=int(item.get("retry_count") or 0),
                priority=item.get("priority"),
                upload_id=item.get("id"),
            )
        )
    return entries


def desired_pending_paths(desired_paths: Iterable[str], uploaded_paths: set[str]) -> list[str]:
    return [path for path in desired_paths if path not in uploaded_paths]


def target_queue_refresh_needed(
    queue_entries: list[QueueEntry],
    *,
    desired_priorities: dict[str, int],
) -> bool:
    if not desired_priorities:
        return False
    for entry in queue_entries:
        desired_priority = desired_priorities.get(entry.path)
        if desired_priority is None:
            continue
        if entry.priority != desired_priority:
            return True
    return False


def should_clear_queue_while_waiting(*, prioritized_segments: list[SegmentTarget], has_pending_priority: bool) -> bool:
    return False


def watcher_priority_for_index(phase_name: str | None, index: int) -> int:
    base = PHASE_PRIORITY_BASES.get(phase_name or "", 80)
    return min(base + index, MAX_WATCHER_PRIORITY)


def desired_path_priorities(phase_name: str | None, paths: Iterable[str]) -> dict[str, int]:
    return {
        path: watcher_priority_for_index(phase_name, index)
        for index, path in enumerate(paths)
    }


def is_preserved_queue_entry(entry: QueueEntry) -> bool:
    return entry.file_kind in LOW_QUALITY_FILE_KINDS


def generate_candidate_paths(route: Route, segments: Iterable[int], file_types: Iterable[str]) -> list[str]:
    candidates: list[str] = []
    for segment in segments:
        for file_type in file_types:
            if file_type == "logs":
                candidates.append(f"{route.route_id}--{segment}/rlog.zst")
                continue
            for filename in FILE_TYPE_NAMES[file_type]:
                candidates.append(f"{route.route_id}--{segment}/{filename}")
    return candidates


def generate_candidate_paths_by_priority(
    segment_groups: Iterable[Iterable[SegmentTarget]], file_types: Iterable[Iterable[str] | str]
) -> list[str]:
    candidates: list[str] = []
    segment_group_list = [list(group) for group in segment_groups]
    file_type_groups = list(file_types)
    if file_type_groups and isinstance(file_type_groups[0], str):
        file_type_groups = [list(file_type_groups) for _ in segment_group_list]

    for segments, group_file_types in zip(segment_group_list, file_type_groups, strict=True):
        segment_list = list(segments)
        for segment in segment_list:
            for file_type in group_file_types:
                if file_type == "logs":
                    candidates.append(f"{segment.route_id}--{segment.segment}/rlog.zst")
                    continue
                for filename in FILE_TYPE_NAMES[file_type]:
                    candidates.append(f"{segment.route_id}--{segment.segment}/{filename}")
    return candidates


def first_pending_phase(
    phase_specs: Iterable[tuple[str, list[SegmentTarget], list[str]]],
    uploaded_paths: set[str],
) -> tuple[str, list[SegmentTarget], list[str], list[str], list[str]] | None:
    for phase_name, phase_targets, phase_file_types in phase_specs:
        if not phase_targets:
            continue
        desired_paths = generate_candidate_paths_by_priority([phase_targets], [phase_file_types])
        pending_paths = desired_pending_paths(desired_paths, uploaded_paths)
        if pending_paths:
            return phase_name, phase_targets, phase_file_types, desired_paths, pending_paths
    return None


def athena_enqueue_order(paths: Iterable[str]) -> list[str]:
    return list(reversed(list(paths)))


def file_kinds_for_file_types(file_types: Iterable[str], *, dm_boost: bool = False) -> list[str]:
    order = DM_DISPLAY_FILE_ORDER if dm_boost else DISPLAY_FILE_ORDER
    selected = {
        kind
        for file_type in file_types
        for kind in FILE_KIND_BY_TYPE.get(file_type, ())
    }
    return [kind for kind in order if kind in selected]


def phase_reason_label(phase_name: str | None) -> str | None:
    if phase_name is None:
        return None
    return PHASE_REASON_LABELS.get(phase_name, phase_name.replace("_", " "))


def empty_segment_files() -> dict[str, bool]:
    return {name: False for name in (*DISPLAY_FILE_ORDER, "qcamera", "qlog")}


def phase_segment_lookup(phase_specs: Iterable[tuple[str, list[SegmentTarget]]]) -> dict[tuple[str, int], dict[str, Any]]:
    lookup: dict[tuple[str, int], dict[str, Any]] = {}
    for phase_name, targets in phase_specs:
        for index, target in enumerate(targets, start=1):
            key = (target.route_id, target.segment)
            lookup.setdefault(
                key,
                {
                    "phase": phase_name,
                    "rank": index,
                },
            )
    return lookup


def route_segment_rows(
    *,
    route: Route,
    route_inventory: dict[tuple[str, int], dict[str, bool]],
    queue_items_by_segment: dict[tuple[str, int], list[QueueEntry]],
    segment_phase_lookup: dict[tuple[str, int], dict[str, Any]],
    active_phase_targets: list[SegmentTarget],
    bookmark_segments: set[int],
    dm_alert_segments: set[int],
    alert_segments: set[int],
) -> list[dict[str, Any]]:
    active_phase_keys = {(target.route_id, target.segment): index for index, target in enumerate(active_phase_targets, start=1)}
    rows: list[dict[str, Any]] = []
    for segment in range(route.maxqlog + 1):
        key = (route.route_id, segment)
        files = dict(route_inventory.get(key, empty_segment_files()))
        queue_items = queue_items_by_segment.get(key, [])
        queued_file_kinds = [item.file_kind for item in queue_items if item.file_kind]
        active_file_kinds = [item.file_kind for item in queue_items if item.current and item.file_kind]
        phase_info = segment_phase_lookup.get(key)
        rows.append(
            {
                "segment": segment,
                "files": files,
                "bookmark": segment in bookmark_segments,
                "dm_alert": segment in dm_alert_segments,
                "alert": segment in alert_segments,
                "phase": phase_info["phase"] if phase_info else None,
                "phase_rank": phase_info["rank"] if phase_info else None,
                "active_phase_rank": active_phase_keys.get(key),
                "queued_file_kinds": queued_file_kinds,
                "active_file_kinds": active_file_kinds,
                "queued_count": len(queue_items),
                "active_count": sum(1 for item in queue_items if item.current),
            }
        )
    return rows


def build_watch_state(
    *,
    now_local: datetime,
    window_start: datetime,
    devices_state: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "generated_at": now_local.isoformat(),
        "window_start": window_start.isoformat(),
        "devices": devices_state,
    }


def segment_status_for_window(
    *,
    route_id: str,
    segment: int,
    required_file_order: list[str],
    route_inventory: dict[tuple[str, int], dict[str, bool]],
    queue_items_by_segment: dict[tuple[str, int], list[QueueEntry]],
) -> dict[str, Any]:
    files = route_inventory.get((route_id, segment), empty_segment_files())
    queue_items = queue_items_by_segment.get((route_id, segment), [])

    uploaded = [kind for kind in required_file_order if files.get(kind)]
    active = []
    queued = []
    for kind in required_file_order:
        if kind in uploaded:
            continue
        matching = [item for item in queue_items if item.file_kind == kind]
        if any(item.current for item in matching):
            active.append(kind)
        elif matching:
            queued.append(kind)
    missing = [kind for kind in required_file_order if kind not in uploaded and kind not in active and kind not in queued]
    return {
        "segment": segment,
        "uploaded_file_kinds": uploaded,
        "queued_file_kinds": queued,
        "active_file_kinds": active,
        "missing_file_kinds": missing,
        "is_complete": not active and not queued and not missing,
    }


def summarize_incident_completion(segment_statuses: list[dict[str, Any]]) -> dict[str, int]:
    uploaded = sum(len(status["uploaded_file_kinds"]) for status in segment_statuses)
    queued = sum(len(status["queued_file_kinds"]) for status in segment_statuses)
    active = sum(len(status["active_file_kinds"]) for status in segment_statuses)
    missing = sum(len(status["missing_file_kinds"]) for status in segment_statuses)
    return {
        "uploaded": uploaded,
        "queued": queued,
        "active": active,
        "missing": missing,
        "total": uploaded + queued + active + missing,
    }


def incident_ready_state(segment_statuses: list[dict[str, Any]]) -> str:
    if segment_statuses and all(status["is_complete"] for status in segment_statuses):
        return "complete"
    if any(status["active_file_kinds"] for status in segment_statuses):
        return "in_progress"
    if any(status["queued_file_kinds"] for status in segment_statuses):
        return "queued"
    return "waiting"


def first_incomplete_segment(segment_statuses: list[dict[str, Any]]) -> dict[str, Any] | None:
    for status in segment_statuses:
        if status["is_complete"]:
            continue
        return {
            "segment": status["segment"],
            "missing_file_kinds": list(status["missing_file_kinds"]),
            "queued_file_kinds": list(status["queued_file_kinds"]),
            "active_file_kinds": list(status["active_file_kinds"]),
        }
    return None


def currently_uploading_files(segment_statuses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    for status in segment_statuses:
        for kind in status["active_file_kinds"]:
            files.append({"segment": status["segment"], "file_kind": kind})
    return files


def build_incident_windows(
    *,
    routes_by_id: dict[str, Route],
    bookmark_events: list[SegmentEvent],
    dm_alert_events: list[SegmentEvent],
    alert_events: list[SegmentEvent],
    recent_bookmark_targets: list[SegmentTarget],
    older_bookmark_targets: list[SegmentTarget],
    active_phase_name: str | None,
    active_phase_targets: list[SegmentTarget],
    recent_fill_targets: list[SegmentTarget],
    older_fill_targets: list[SegmentTarget],
    previous_segments: int,
    next_segments: int,
    alert_lookback_segments: int,
    file_types: list[str],
    route_inventories: dict[str, dict[tuple[str, int], dict[str, bool]]],
    queue_items_by_segment: dict[tuple[str, int], list[QueueEntry]],
) -> list[dict[str, Any]]:
    active_phase_keys = {(target.route_id, target.segment) for target in active_phase_targets}
    recent_fill_routes = {target.route_id for target in recent_fill_targets}
    older_fill_routes = {target.route_id for target in older_fill_targets}
    windows: list[dict[str, Any]] = []

    bookmark_events_sorted = sorted(bookmark_events, key=lambda event: event.event_time)
    recent_bookmark_events = list(reversed(bookmark_events_sorted[-RECENT_BOOKMARK_COUNT:]))
    older_bookmark_events = bookmark_events_sorted[:-RECENT_BOOKMARK_COUNT]
    dm_alert_events_sorted = sorted(dm_alert_events, key=lambda event: event.event_time)
    alert_events_sorted = sorted(alert_events, key=lambda event: event.event_time)

    def append_window(event: SegmentEvent, *, category: str, base_phase: str) -> None:
        route = routes_by_id[event.route_id]
        if category == "bookmark":
            segment_order = prioritize_segments(
                [event.segment],
                previous_segments=previous_segments,
                next_segments=next_segments,
                max_segment=event.max_segment,
            )
            required_order = file_kinds_for_file_types(file_types)
        elif category == "dm_alert":
            segment_order = alert_segments_with_lookback(
                event.segment,
                previous_segments=alert_lookback_segments,
                max_segment=event.max_segment,
            )
            required_order = file_kinds_for_file_types(file_types, dm_boost=True)
        else:
            segment_order = alert_segments_with_lookback(
                event.segment,
                previous_segments=alert_lookback_segments,
                max_segment=event.max_segment,
            )
            required_order = file_kinds_for_file_types(file_types)

        segment_statuses = [
            segment_status_for_window(
                route_id=event.route_id,
                segment=segment,
                required_file_order=required_order,
                route_inventory=route_inventories.get(event.route_id, {}),
                queue_items_by_segment=queue_items_by_segment,
            )
            for segment in segment_order
        ]
        completion = summarize_incident_completion(segment_statuses)
        ready_state = incident_ready_state(segment_statuses)

        phase_membership = base_phase
        is_active_phase_window = any((event.route_id, segment) in active_phase_keys for segment in segment_order)
        if category == "bookmark" and active_phase_name == "bookmark_fill_recent" and event.route_id in recent_fill_routes:
            phase_membership = "bookmark_fill_recent"
            is_active_phase_window = True
        elif category == "bookmark" and active_phase_name == "bookmark_fill_older" and event.route_id in older_fill_routes:
            phase_membership = "bookmark_fill_older"
            is_active_phase_window = True
        elif active_phase_name == base_phase and is_active_phase_window:
            phase_membership = base_phase

        windows.append(
            {
                "id": f"{category}:{event.route_id}:{event.segment}",
                "category": category,
                "route_id": event.route_id,
                "event_time": event.event_time.isoformat(),
                "anchor_segment": event.segment,
                "segment_order": segment_order,
                "phase_membership": phase_membership,
                "is_active_phase_window": is_active_phase_window,
                "route_start_time": route.start_time,
                "segment_statuses": segment_statuses,
                "required_file_order": required_order,
                "completion": completion,
                "first_incomplete_segment": first_incomplete_segment(segment_statuses),
                "currently_uploading_files": currently_uploading_files(segment_statuses),
                "ready_state": ready_state,
            }
        )

    for event in recent_bookmark_events:
        append_window(event, category="bookmark", base_phase="recent_bookmarks")
    for event in older_bookmark_events:
        append_window(event, category="bookmark", base_phase="older_bookmarks")
    for event in dm_alert_events_sorted:
        append_window(event, category="dm_alert", base_phase="dm_alerts")
    for event in alert_events_sorted:
        append_window(event, category="alert", base_phase="alerts")

    windows.sort(
        key=lambda window: (
            0 if window["is_active_phase_window"] else 1,
            {
                "recent_bookmarks": 0,
                "older_bookmarks": 1,
                "dm_alerts": 2,
                "alerts": 3,
                "bookmark_fill_recent": 4,
                "bookmark_fill_older": 5,
            }.get(window["phase_membership"], 6),
            window["event_time"],
        )
    )
    return windows


def annotate_queue_entries(
    queue_entries: list[QueueEntry],
    *,
    incident_windows: list[dict[str, Any]],
    active_phase_name: str | None,
    active_phase_targets: list[SegmentTarget],
) -> list[dict[str, Any]]:
    active_phase_keys = {(target.route_id, target.segment) for target in active_phase_targets}
    annotated: list[dict[str, Any]] = []
    for entry in queue_entries:
        incident_context: dict[str, Any] | None = None
        for window in incident_windows:
            if window["route_id"] != entry.route_id or entry.segment not in window["segment_order"]:
                continue
            segment_rank = window["segment_order"].index(entry.segment) + 1
            file_rank = window["required_file_order"].index(entry.file_kind) + 1 if entry.file_kind in window["required_file_order"] else None
            incident_context = {
                "incident_window_id": window["id"],
                "reason_label": phase_reason_label(window["phase_membership"]),
                "segment_rank_within_window": segment_rank,
                "file_rank_within_segment": file_rank,
            }
            break
        if incident_context is None and (entry.route_id, entry.segment) in active_phase_keys and active_phase_name in {
            "bookmark_fill_recent",
            "bookmark_fill_older",
        }:
            incident_context = {
                "incident_window_id": None,
                "reason_label": phase_reason_label(active_phase_name),
                "segment_rank_within_window": None,
                "file_rank_within_segment": None,
            }
        annotated.append(
            {
                "path": entry.path,
                "route_id": entry.route_id,
                "segment": entry.segment,
                "filename": entry.filename,
                "file_kind": entry.file_kind,
                "current": entry.current,
                "progress": entry.progress,
                "retry_count": entry.retry_count,
                "priority": entry.priority,
                "upload_id": entry.upload_id,
                "incident_window_id": incident_context["incident_window_id"] if incident_context else None,
                "reason_label": incident_context["reason_label"] if incident_context else None,
                "segment_rank_within_window": incident_context["segment_rank_within_window"] if incident_context else None,
                "file_rank_within_segment": incident_context["file_rank_within_segment"] if incident_context else None,
            }
        )
    return annotated


def request_uploads(api: CommaApi, dongle_id: str, paths: list[str], *, priorities: dict[str, int]) -> dict[str, Any]:
    ordered_paths = list(paths)
    upload_metadata = api.request_upload_urls(dongle_id, ordered_paths)
    files = [
        UploadFile(file_path=path, url=metadata["url"], headers=metadata["headers"])
        for path, metadata in zip(ordered_paths, upload_metadata, strict=True)
    ]
    payload = {
        "files_data": [
            {
                "allow_cellular": False,
                "fn": file.file_path,
                "headers": file.headers,
                "priority": priorities[file.file_path],
                "url": file.url,
            }
            for file in files
        ]
    }
    return api.athena_call(dongle_id, "uploadFilesToUrls", payload)


def scan_once(
    api: CommaApi,
    *,
    device_alias: str,
    lookback_hours: int,
    tz: ZoneInfo,
    previous_segments: int,
    next_segments: int,
    file_types: list[str],
    exclusive_bookmark_priority: bool,
    state_path: Path,
) -> ScanOutcome:
    targets_found = False
    uploads_queued = False
    all_target_files_satisfied = True
    queue_cleared = False
    devices = select_devices(api.get_devices(), device_alias or None)
    now_local = datetime.now(tz)
    window_start = now_local - timedelta(hours=lookback_hours)
    watcher_state = build_watch_state(now_local=now_local, window_start=window_start, devices_state=[])
    print(
        f"[{now_local.isoformat()}] Watching {len(devices)} device(s) in the last {lookback_hours} hour(s) "
        f"since {window_start.isoformat()}"
    )
    if not devices:
        write_state_snapshot(state_path, watcher_state)
        return ScanOutcome(targets_found=False, uploads_queued=False, all_target_files_satisfied=False, queue_cleared=False)

    any_routes_found = False
    for device in devices:
        print(f"Device {device.alias or device.dongle_id} ({device.dongle_id})")
        routes = list_routes_in_lookback_window(api, device.dongle_id, window_start=window_start, tz=tz)
        print(f"Found {len(routes)} route(s) in lookback window")
        device_state: dict[str, Any] = {
            "alias": device.alias,
            "dongle_id": device.dongle_id,
            "routes": [],
            "incident_windows": [],
            "queue": {
                "length": 0,
                "active_length": 0,
                "items": [],
            },
            "active_phase": None,
        }
        watcher_state["devices"].append(device_state)
        if not routes:
            continue
        any_routes_found = True

        online_queue = api.athena_call(device.dongle_id, "listUploadQueue", {}).get("result", [])
        offline_queue = api.get_athena_offline_queue(device.dongle_id)
        queue_entries = summarize_online_queue(online_queue)
        queue_items_by_segment: dict[tuple[str, int], list[QueueEntry]] = {}
        for entry in queue_entries:
            queue_items_by_segment.setdefault((entry.route_id, entry.segment), []).append(entry)
        device_state["queue"] = {
            "length": len(queue_entries),
            "active_length": sum(1 for entry in queue_entries if entry.current),
            "items": [
                {
                    "path": entry.path,
                    "route_id": entry.route_id,
                    "segment": entry.segment,
                    "filename": entry.filename,
                    "file_kind": entry.file_kind,
                    "current": entry.current,
                    "progress": entry.progress,
                    "retry_count": entry.retry_count,
                    "priority": entry.priority,
                    "upload_id": entry.upload_id,
                }
                for entry in queue_entries
            ],
        }
        queued_paths = normalize_queue_paths(online_queue, offline_queue)
        target_paths: set[str] = set()
        uploaded_paths: set[str] = set()
        bookmark_events: list[SegmentEvent] = []
        dm_alert_events: list[SegmentEvent] = []
        alert_events: list[SegmentEvent] = []
        routes_by_id: dict[str, Route] = {}
        route_states_by_id: dict[str, dict[str, Any]] = {}
        route_inventories: dict[str, dict[tuple[str, int], dict[str, bool]]] = {}
        route_bookmark_segments: dict[str, set[int]] = {}
        route_dm_alert_segments: dict[str, set[int]] = {}
        route_alert_segments: dict[str, set[int]] = {}
        active_phase_name: str | None = None
        recent_fill_targets: list[SegmentTarget] = []
        older_fill_targets: list[SegmentTarget] = []

        for route in routes:
            route_detail = api.get_route(route.fullname)
            hydrated_route = Route(
                fullname=route.fullname,
                route_id=route.route_id,
                start_time=route_detail.get("start_time"),
                end_time=route_detail.get("end_time", route.end_time),
                maxqlog=route_detail.get("maxqlog", route.maxqlog),
                procqlog=route_detail.get("procqlog", route.procqlog),
                url=route_detail.get("url", route.url),
            )
            start_local = parse_route_start_local(hydrated_route.start_time, tz)
            routes_by_id[hydrated_route.route_id] = hydrated_route
            route_files = api.get_route_files(hydrated_route.fullname)
            qlog_count = len(route_files.get("qlogs", []))
            parsed_upper_bound = parsed_segment_upper_bound(hydrated_route)
            print(
                f"Inspecting {hydrated_route.fullname} start={start_local.isoformat() if start_local else 'unknown'} "
                f"maxqlog={hydrated_route.maxqlog} procqlog={hydrated_route.procqlog} qlogs={qlog_count}"
            )
            if parsed_upper_bound < hydrated_route.maxqlog:
                print(f"Waiting for parsed qlogs: scanning segments 0..{parsed_upper_bound} so far")
            uploaded_paths.update(normalize_uploaded_paths(route_files))
            route_inventories[hydrated_route.route_id] = build_route_file_inventory(route_files)
            priority_events = collect_priority_events(api, hydrated_route)
            bookmark_segments = sorted({event.segment for event in priority_events.bookmark_events})
            dm_alert_segments = sorted({event.segment for event in priority_events.dm_alert_events})
            alert_segments = sorted({event.segment for event in priority_events.alert_events})
            route_bookmark_segments[hydrated_route.route_id] = set(bookmark_segments)
            route_dm_alert_segments[hydrated_route.route_id] = set(dm_alert_segments)
            route_alert_segments[hydrated_route.route_id] = set(alert_segments)
            print(f"Bookmarked segments: {bookmark_segments}")
            print(f"DM alert segments: {dm_alert_segments}")
            print(f"Alert segments: {alert_segments}")
            if priority_events.bookmark_events or priority_events.dm_alert_events or priority_events.alert_events:
                targets_found = True
            bookmark_events.extend(priority_events.bookmark_events)
            dm_alert_events.extend(priority_events.dm_alert_events)
            alert_events.extend(priority_events.alert_events)
            route_state = {
                "fullname": hydrated_route.fullname,
                "route_id": hydrated_route.route_id,
                "start_time": hydrated_route.start_time,
                "end_time": hydrated_route.end_time,
                "maxqlog": hydrated_route.maxqlog,
                "procqlog": hydrated_route.procqlog,
                "qlogs": qlog_count,
                "bookmark_segments": bookmark_segments,
                "dm_alert_segments": dm_alert_segments,
                "alert_segments": alert_segments,
                "segments": [],
            }
            route_states_by_id[hydrated_route.route_id] = route_state
            device_state["routes"].append(route_state)

        prioritized_segment_groups = combine_priority_segments(
            bookmark_events=bookmark_events,
            dm_alert_events=dm_alert_events,
            alert_events=alert_events,
            previous_segments=previous_segments,
            next_segments=next_segments,
        )
        recent_bookmark_targets, older_bookmark_targets, dm_alert_targets, alert_targets = prioritized_segment_groups
        prioritized_segments = [target for group in prioritized_segment_groups for target in group]
        print(
            "Recent bookmark targets:",
            [f"{target.route_id}:{target.segment}" for target in recent_bookmark_targets],
        )
        print(
            "Older bookmark targets:",
            [f"{target.route_id}:{target.segment}" for target in older_bookmark_targets],
        )
        print(
            "DM alert targets:",
            [f"{target.route_id}:{target.segment}" for target in dm_alert_targets],
        )
        print(
            "Alert targets:",
            [f"{target.route_id}:{target.segment}" for target in alert_targets],
        )
        segment_lookup: dict[tuple[str, int], dict[str, Any]] = {}
        active_phase_targets: list[SegmentTarget] = []
        if prioritized_segments:
            dm_boost_file_types = [file_type for file_type in ("cameras", "logs", "dcameras", "ecameras") if file_type in file_types]
            named_phase_targets = [
                ("recent_bookmarks", recent_bookmark_targets),
                ("older_bookmarks", older_bookmark_targets),
                ("dm_alerts", dm_alert_targets),
                ("alerts", alert_targets),
            ]
            priority_phase = first_pending_phase(
                [
                    ("recent_bookmarks", recent_bookmark_targets, file_types),
                    ("older_bookmarks", older_bookmark_targets, file_types),
                    ("dm_alerts", dm_alert_targets, dm_boost_file_types),
                    ("alerts", alert_targets, file_types),
                ],
                uploaded_paths,
            )

            active_phase_targets: list[SegmentTarget] = []
            desired_paths: list[str] = []
            pending_paths: list[str] = []

            if priority_phase is not None:
                active_phase_name, active_phase_targets, _active_phase_file_types, desired_paths, pending_paths = priority_phase
            else:
                fill_targets = combine_bookmark_route_fill_segments(
                    bookmark_events=bookmark_events,
                    recent_bookmark_targets=recent_bookmark_targets,
                    older_bookmark_targets=older_bookmark_targets,
                )
                print(
                    "Bookmark route fill targets:",
                    [
                        f"{target.route_id}:{target.segment}"
                        for target in (fill_targets.recent_fill_targets + fill_targets.older_fill_targets)
                    ],
                )
                recent_fill_targets = fill_targets.recent_fill_targets
                older_fill_targets = fill_targets.older_fill_targets
                fill_phase = first_pending_phase(
                    [
                        ("bookmark_fill_recent", fill_targets.recent_fill_targets, file_types),
                        ("bookmark_fill_older", fill_targets.older_fill_targets, file_types),
                    ],
                    uploaded_paths,
                )
                if fill_phase is not None:
                    active_phase_name, active_phase_targets, _active_phase_file_types, desired_paths, pending_paths = fill_phase

            target_paths = set(desired_paths)
            has_pending_priority = priority_phase is not None
            has_pending_targets = bool(pending_paths)
            missing_paths = [path for path in pending_paths if path not in queued_paths]
            print(
                "Global segment priority order:",
                [f"{target.route_id}:{target.segment}" for target in prioritized_segments],
            )
            if active_phase_name is not None:
                print(
                    f"Active phase: {active_phase_name}",
                    [f"{target.route_id}:{target.segment}" for target in active_phase_targets],
                )
                device_state["active_phase"] = {
                    "name": active_phase_name,
                    "targets": [f"{target.route_id}:{target.segment}" for target in active_phase_targets],
                }
            pending_priorities = desired_path_priorities(active_phase_name, pending_paths)
            print(
                f"Desired files={len(desired_paths)} uploaded={len(uploaded_paths)} queued={len(queued_paths)} missing={len(missing_paths)}"
            )
            refreshed_queue = False
            if exclusive_bookmark_priority and target_queue_refresh_needed(
                queue_entries,
                desired_priorities=pending_priorities,
            ):
                cancel_ids = [
                    entry.upload_id
                    for entry in queue_entries
                    if entry.upload_id
                    and entry.path in pending_priorities
                    and entry.priority != pending_priorities[entry.path]
                ]
                if cancel_ids:
                    response = api.cancel_uploads(device.dongle_id, cancel_ids)
                    print(f"Canceled {len(cancel_ids)} queued target item(s) to refresh priorities:")
                    print(json.dumps(response, indent=2))
                    queue_cleared = True
                online_queue = api.athena_call(device.dongle_id, "listUploadQueue", {}).get("result", [])
                queue_entries = summarize_online_queue(online_queue)
                queue_items_by_segment = {}
                for entry in queue_entries:
                    queue_items_by_segment.setdefault((entry.route_id, entry.segment), []).append(entry)
                offline_queue = api.get_athena_offline_queue(device.dongle_id)
                queued_paths = normalize_queue_paths(online_queue, offline_queue)
                missing_paths = [path for path in desired_paths if path not in uploaded_paths and path not in queued_paths]
                pending_priorities = desired_path_priorities(active_phase_name, missing_paths)
                refreshed_queue = True

            if not missing_paths:
                if refreshed_queue:
                    print("Priority segment files were already uploaded after queue refresh.")
                else:
                    print("Priority segment files are already uploaded or queued.")
            else:
                response = request_uploads(api, device.dongle_id, missing_paths, priorities=pending_priorities)
                print("Queued upload request:")
                print(json.dumps(response, indent=2))
                queued_paths.update(missing_paths)
                uploads_queued = True
                all_target_files_satisfied = False

            segment_lookup = phase_segment_lookup(named_phase_targets)
            for route in routes:
                route_state = route_states_by_id[route.route_id]
                route_state["segments"] = route_segment_rows(
                    route=routes_by_id[route.route_id],
                    route_inventory=route_inventories.get(route.route_id, {}),
                    queue_items_by_segment=queue_items_by_segment,
                    segment_phase_lookup=segment_lookup,
                    active_phase_targets=active_phase_targets,
                    bookmark_segments=route_bookmark_segments.get(route.route_id, set()),
                    dm_alert_segments=route_dm_alert_segments.get(route.route_id, set()),
                    alert_segments=route_alert_segments.get(route.route_id, set()),
                )
        else:
            print("No bookmark or alert targets found in lookback window.")
            all_target_files_satisfied = False
            has_pending_priority = False
            has_pending_targets = False
            for route in routes:
                route_state = route_states_by_id[route.route_id]
                route_state["segments"] = route_segment_rows(
                    route=routes_by_id[route.route_id],
                    route_inventory=route_inventories.get(route.route_id, {}),
                    queue_items_by_segment=queue_items_by_segment,
                    segment_phase_lookup={},
                    active_phase_targets=[],
                    bookmark_segments=route_bookmark_segments.get(route.route_id, set()),
                    dm_alert_segments=route_dm_alert_segments.get(route.route_id, set()),
                    alert_segments=route_alert_segments.get(route.route_id, set()),
                )

        if exclusive_bookmark_priority:
            if prioritized_segments and has_pending_targets:
                pass
            elif should_clear_queue_while_waiting(
                prioritized_segments=prioritized_segments,
                has_pending_priority=has_pending_targets,
            ):
                cancel_ids = [
                    entry.upload_id
                    for entry in queue_entries
                    if entry.upload_id and not is_preserved_queue_entry(entry)
                ]
                if cancel_ids:
                    response = api.cancel_uploads(device.dongle_id, cancel_ids)
                    print(f"Canceled {len(cancel_ids)} queue item(s) while waiting for priority segments:")
                    print(json.dumps(response, indent=2))
                    queue_cleared = True

        refreshed_online_queue = api.athena_call(device.dongle_id, "listUploadQueue", {}).get("result", [])
        refreshed_queue_entries = summarize_online_queue(refreshed_online_queue)
        refreshed_queue_by_segment: dict[tuple[str, int], list[QueueEntry]] = {}
        for entry in refreshed_queue_entries:
            refreshed_queue_by_segment.setdefault((entry.route_id, entry.segment), []).append(entry)
        incident_windows = build_incident_windows(
            routes_by_id=routes_by_id,
            bookmark_events=bookmark_events,
            dm_alert_events=dm_alert_events,
            alert_events=alert_events,
            recent_bookmark_targets=recent_bookmark_targets,
            older_bookmark_targets=older_bookmark_targets,
            active_phase_name=active_phase_name if prioritized_segments else None,
            active_phase_targets=active_phase_targets,
            recent_fill_targets=recent_fill_targets,
            older_fill_targets=older_fill_targets,
            previous_segments=previous_segments,
            next_segments=next_segments,
            alert_lookback_segments=ALERT_LOOKBACK_SEGMENTS,
            file_types=file_types,
            route_inventories=route_inventories,
            queue_items_by_segment=refreshed_queue_by_segment,
        )
        device_state["queue"] = {
            "length": len(refreshed_queue_entries),
            "active_length": sum(1 for entry in refreshed_queue_entries if entry.current),
            "items": annotate_queue_entries(
                refreshed_queue_entries,
                incident_windows=incident_windows,
                active_phase_name=active_phase_name if prioritized_segments else None,
                active_phase_targets=active_phase_targets,
            ),
        }
        device_state["incident_windows"] = incident_windows
        for route in routes:
            route_state = route_states_by_id[route.route_id]
            route_state["segments"] = route_segment_rows(
                route=routes_by_id[route.route_id],
                route_inventory=route_inventories.get(route.route_id, {}),
                queue_items_by_segment=refreshed_queue_by_segment,
                segment_phase_lookup=segment_lookup,
                active_phase_targets=active_phase_targets,
                bookmark_segments=route_bookmark_segments.get(route.route_id, set()),
                dm_alert_segments=route_dm_alert_segments.get(route.route_id, set()),
                alert_segments=route_alert_segments.get(route.route_id, set()),
            )

    if not any_routes_found or not targets_found:
        all_target_files_satisfied = False
    write_state_snapshot(state_path, watcher_state)
    return ScanOutcome(
        targets_found=targets_found,
        uploads_queued=uploads_queued,
        all_target_files_satisfied=all_target_files_satisfied,
        queue_cleared=queue_cleared,
    )


def main() -> int:
    load_dotenv()
    args = parse_args()
    if not args.jwt_token:
        raise SystemExit("Missing JWT token. Set COMMA_JWT or pass --jwt-token.")

    tz = ZoneInfo(args.timezone)
    api = CommaApi(args.jwt_token)
    state_path = Path(args.state_path)

    start_time = time.monotonic()
    outcome = ScanOutcome(targets_found=False, uploads_queued=False, all_target_files_satisfied=False, queue_cleared=False)
    while True:
        try:
            outcome = scan_once(
                api,
                device_alias=args.device_alias,
                lookback_hours=args.lookback_hours,
                tz=tz,
                previous_segments=args.previous_segments,
                next_segments=args.next_segments,
                file_types=args.file_types,
                exclusive_bookmark_priority=args.exclusive_bookmark_priority,
                state_path=state_path,
            )
            if args.exit_when_satisfied and outcome.targets_found and (
                outcome.uploads_queued or outcome.all_target_files_satisfied
            ):
                print("Priority segments found and upload work is queued or already complete. Exiting watcher.")
                return 0
        except Exception as exc:
            print(f"Watcher error: {exc}")

        if args.once:
            return 0 if outcome.targets_found and (outcome.uploads_queued or outcome.all_target_files_satisfied) else 1
        if args.timeout_seconds > 0 and time.monotonic() - start_time >= args.timeout_seconds:
            print("Timed out waiting for priority segments.")
            return 1
        print(f"Sleeping for {args.poll_seconds} seconds")
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
