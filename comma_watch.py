#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from dotenv import load_dotenv
from zoneinfo import ZoneInfo


API_URL = "https://api.comma.ai"
ATHENA_URL = "https://athena.comma.ai"
DEFAULT_FILE_TYPES = ("cameras", "dcameras", "ecameras", "logs")
ONLINE_DEVICE_WINDOW_SECONDS = 120
FILE_TYPE_NAMES = {
    "cameras": ("fcamera.hevc",),
    "dcameras": ("dcamera.hevc",),
    "ecameras": ("ecamera.hevc",),
    "logs": ("rlog.bz2", "rlog.zst"),
}
BOOKMARK_EVENT_TYPES = {"user_flag", "user_bookmark", "bookmark"}


@dataclass(frozen=True)
class Device:
    alias: str | None
    dongle_id: str


@dataclass(frozen=True)
class Route:
    fullname: str
    route_id: str
    start_time: str | None
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
    bookmarks_found: bool
    uploads_queued: bool
    all_bookmarked_files_satisfied: bool
    queue_cleared: bool


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
        description="Watch Comma routes for bookmark flags and queue high-quality uploads around them."
    )
    parser.add_argument(
        "--device-alias",
        default=os.environ.get("COMMA_DEVICE_ALIAS", ""),
        help="Optional device alias filter. If omitted, scans every owned online device.",
    )
    parser.add_argument("--jwt-token", default=os.environ.get("COMMA_JWT", ""), help="Comma JWT token. Defaults to COMMA_JWT.")
    parser.add_argument("--timezone", default=os.environ.get("TZ", "America/Los_Angeles"))
    parser.add_argument(
        "--date",
        default="today",
        help="Target local date in YYYY-MM-DD format, or 'today'. Defaults to today's date in --timezone.",
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
        help="Keep the upload queue clear until bookmarks exist, then keep only bookmark-related uploads queued.",
    )
    return parser.parse_args()


def local_date_from_arg(raw: str, tz: ZoneInfo) -> date:
    if raw == "today":
        return datetime.now(tz).date()
    return date.fromisoformat(raw)


def parse_route_start_local(start_time: str | None, tz: ZoneInfo) -> datetime | None:
    if not start_time:
        return None
    return datetime.fromisoformat(start_time).replace(tzinfo=timezone.utc).astimezone(tz)


def route_id_from_fullname(fullname: str) -> str:
    return fullname.split("|", 1)[1]


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


def list_routes_for_local_date(api: CommaApi, dongle_id: str, target_date: date, tz: ZoneInfo) -> list[Route]:
    routes: list[Route] = []
    created_before: int | None = None

    for _ in range(10):
        batch = api.get_routes(dongle_id, created_before=created_before)
        if not batch:
            break
        for item in batch:
            start_local = parse_route_start_local(item.get("start_time"), tz)
            if start_local is None:
                route_date = datetime.now(tz).date()
            else:
                route_date = start_local.date()
            if route_date == target_date:
                routes.append(
                    Route(
                        fullname=item["fullname"],
                        route_id=route_id_from_fullname(item["fullname"]),
                        start_time=item.get("start_time"),
                        maxqlog=item.get("maxqlog", 0),
                        procqlog=item.get("procqlog"),
                        url=item["url"],
                    )
                )
        created_before = batch[-1]["create_time"]
        oldest_local = parse_route_start_local(batch[-1].get("start_time"), tz)
        if oldest_local is not None and oldest_local.date() < target_date:
            break

    routes.sort(key=lambda route: parse_route_start_local(route.start_time, tz) or datetime.max.replace(tzinfo=tz))
    return routes


def parsed_segment_upper_bound(route: Route) -> int:
    if route.procqlog is None:
        return route.maxqlog
    return max(0, min(route.procqlog, route.maxqlog))


def bookmarked_segments(api: CommaApi, route: Route) -> list[int]:
    segments: set[int] = set()
    for seg in range(parsed_segment_upper_bound(route) + 1):
        events = api.get_events(route.url, seg)
        for event in events:
            if event.get("type") not in BOOKMARK_EVENT_TYPES:
                continue
            route_offset_millis = int(event["route_offset_millis"])
            segments.add(route_offset_millis // 60000)
    return sorted(segments)


def expand_segments(bookmarked: Iterable[int], *, previous_segments: int, next_segments: int, max_segment: int) -> list[int]:
    expanded: set[int] = set()
    for segment in bookmarked:
        start = max(0, segment - previous_segments)
        end = min(max_segment, segment + next_segments)
        expanded.update(range(start, end + 1))
    return sorted(expanded)


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


def generate_candidate_paths(route: Route, segments: Iterable[int], file_types: Iterable[str]) -> list[str]:
    candidates: list[str] = []
    for segment in segments:
        for file_type in file_types:
            for filename in FILE_TYPE_NAMES[file_type]:
                candidates.append(f"{route.route_id}--{segment}/{filename}")
    return candidates


def request_uploads(api: CommaApi, dongle_id: str, paths: list[str]) -> dict[str, Any]:
    upload_metadata = api.request_upload_urls(dongle_id, paths)
    files = [
        UploadFile(file_path=path, url=metadata["url"], headers=metadata["headers"])
        for path, metadata in zip(paths, upload_metadata, strict=True)
    ]
    payload = {
        "files_data": [
            {
                "allow_cellular": False,
                "fn": file.file_path,
                "headers": file.headers,
                "priority": 1,
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
    target_date: date,
    tz: ZoneInfo,
    previous_segments: int,
    next_segments: int,
    file_types: list[str],
    exclusive_bookmark_priority: bool,
) -> ScanOutcome:
    bookmarks_found = False
    uploads_queued = False
    all_bookmarked_files_satisfied = True
    queue_cleared = False
    devices = select_devices(api.get_devices(), device_alias or None)
    print(f"[{datetime.now(tz).isoformat()}] Watching {len(devices)} device(s) on {target_date.isoformat()}")
    if not devices:
        return ScanOutcome(bookmarks_found=False, uploads_queued=False, all_bookmarked_files_satisfied=False, queue_cleared=False)

    any_routes_found = False
    for device in devices:
        print(f"Device {device.alias or device.dongle_id} ({device.dongle_id})")
        routes = list_routes_for_local_date(api, device.dongle_id, target_date, tz)
        print(f"Found {len(routes)} route(s) for target date")
        if not routes:
            continue
        any_routes_found = True

        online_queue = api.athena_call(device.dongle_id, "listUploadQueue", {}).get("result", [])
        offline_queue = api.get_athena_offline_queue(device.dongle_id)
        queued_paths = normalize_queue_paths(online_queue, offline_queue)
        target_paths: set[str] = set()

        device_bookmarks_found = False
        for route in routes:
            route_detail = api.get_route(route.fullname)
            hydrated_route = Route(
                fullname=route.fullname,
                route_id=route.route_id,
                start_time=route_detail.get("start_time"),
                maxqlog=route_detail.get("maxqlog", route.maxqlog),
                procqlog=route_detail.get("procqlog", route.procqlog),
                url=route_detail.get("url", route.url),
            )
            start_local = parse_route_start_local(hydrated_route.start_time, tz)
            route_files = api.get_route_files(hydrated_route.fullname)
            qlog_count = len(route_files.get("qlogs", []))
            parsed_upper_bound = parsed_segment_upper_bound(hydrated_route)
            print(
                f"Inspecting {hydrated_route.fullname} start={start_local.isoformat() if start_local else 'unknown'} "
                f"maxqlog={hydrated_route.maxqlog} procqlog={hydrated_route.procqlog} qlogs={qlog_count}"
            )
            if parsed_upper_bound < hydrated_route.maxqlog:
                print(f"Waiting for parsed qlogs: scanning segments 0..{parsed_upper_bound} so far")
            bookmark_segments = bookmarked_segments(api, hydrated_route)
            print(f"Bookmarked segments: {bookmark_segments}")
            if not bookmark_segments:
                continue

            bookmarks_found = True
            device_bookmarks_found = True
            target_segments = expand_segments(
                bookmark_segments,
                previous_segments=previous_segments,
                next_segments=next_segments,
                max_segment=hydrated_route.maxqlog,
            )
            print(f"Expanded segment window: {target_segments}")

            uploaded_paths = normalize_uploaded_paths(route_files)
            desired_paths = generate_candidate_paths(hydrated_route, target_segments, file_types)
            target_paths.update(desired_paths)
            missing_paths = [path for path in desired_paths if path not in uploaded_paths and path not in queued_paths]
            print(
                f"Desired files={len(desired_paths)} uploaded={len(uploaded_paths)} queued={len(queued_paths)} missing={len(missing_paths)}"
            )
            if not missing_paths:
                print("Bookmarked route is already uploaded or queued.")
                continue

            response = request_uploads(api, device.dongle_id, missing_paths)
            print("Queued upload request:")
            print(json.dumps(response, indent=2))
            queued_paths.update(missing_paths)
            uploads_queued = True
            all_bookmarked_files_satisfied = False

        if exclusive_bookmark_priority:
            if device_bookmarks_found:
                cancel_ids = [
                    item["id"]
                    for item in online_queue
                    if item.get("id") and normalize_online_queue_item_path(item) not in target_paths
                ]
                if cancel_ids:
                    response = api.cancel_uploads(device.dongle_id, cancel_ids)
                    print(f"Canceled {len(cancel_ids)} non-bookmark queue item(s):")
                    print(json.dumps(response, indent=2))
                    queue_cleared = True
            else:
                cancel_ids = [item["id"] for item in online_queue if item.get("id")]
                if cancel_ids:
                    response = api.cancel_uploads(device.dongle_id, cancel_ids)
                    print(f"Canceled {len(cancel_ids)} queue item(s) while waiting for bookmarks:")
                    print(json.dumps(response, indent=2))
                    queue_cleared = True

    if not any_routes_found or not bookmarks_found:
        all_bookmarked_files_satisfied = False
    return ScanOutcome(
        bookmarks_found=bookmarks_found,
        uploads_queued=uploads_queued,
        all_bookmarked_files_satisfied=all_bookmarked_files_satisfied,
        queue_cleared=queue_cleared,
    )


def main() -> int:
    load_dotenv()
    args = parse_args()
    if not args.jwt_token:
        raise SystemExit("Missing JWT token. Set COMMA_JWT or pass --jwt-token.")

    tz = ZoneInfo(args.timezone)
    target_date = local_date_from_arg(args.date, tz)
    api = CommaApi(args.jwt_token)

    start_time = time.monotonic()
    outcome = ScanOutcome(bookmarks_found=False, uploads_queued=False, all_bookmarked_files_satisfied=False, queue_cleared=False)
    while True:
        try:
            outcome = scan_once(
                api,
                device_alias=args.device_alias,
                target_date=target_date,
                tz=tz,
                previous_segments=args.previous_segments,
                next_segments=args.next_segments,
                file_types=args.file_types,
                exclusive_bookmark_priority=args.exclusive_bookmark_priority,
            )
            if args.exit_when_satisfied and outcome.bookmarks_found and (
                outcome.uploads_queued or outcome.all_bookmarked_files_satisfied
            ):
                print("Bookmarks found and upload work is queued or already complete. Exiting watcher.")
                return 0
        except Exception as exc:
            print(f"Watcher error: {exc}")

        if args.once:
            return 0 if outcome.bookmarks_found and (outcome.uploads_queued or outcome.all_bookmarked_files_satisfied) else 1
        if args.timeout_seconds > 0 and time.monotonic() - start_time >= args.timeout_seconds:
            print("Timed out waiting for bookmarked segments.")
            return 1
        print(f"Sleeping for {args.poll_seconds} seconds")
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
