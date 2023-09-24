import argparse
import parfive
from pathlib import Path
from typing import List, Optional, Union, TypedDict
from parfive import Results
import requests
import subprocess
import re

# Filelist type

class FileListDict(TypedDict):
    # Each str is like:
    # https://commadata2.blob.core.windows.net/commadata2/a2a0ccea32023010/2023-07-27--13-01-19/0/fcamera.hevc?se=2023-09-24T04%3A17%3A36Z&sp=r&sv=2018-03-28&sr=b&rscd=attachment%3B%20filename%3Da2a0ccea32023010_2023-07-27--13-01-19--0--fcamera.hevc&sig=a2oLhLvbKY7zlqTbyTmCVOjcN4Is1wQlaSUlZz1wK5U%3D

    # Filename are `fcamera.hevc`
    cameras: List[str]
    # Filename are `dcamera.hevc`
    dcameras: List[str]
    # Filename are `ecamera.hevc`
    ecameras: List[str]
    # Filename are `rlog.bz2`
    logs: List[str]


def downloadSegments(
    data_dir: Union[str, Path],
    route_or_segment: str,
    smear_seconds: int,
    start_seconds: int,
    length: int,
):
    """
    Handle downloading segments and throwing up errors if something goes wrong.

    Also pre-decompresses the logs for performance reasons.
    """
    # Get the route/segment name from the route/segment ID.
    # Just strip off the segment ID if it exists with regex
    # Examples:
    # a2a0ccea32023010|2023-07-27--13-01-19 -> a2a0ccea32023010|2023-07-27--13-01-19
    # a2a0ccea32023010|2023-07-27--13-01-19--5 -> a2a0ccea32023010|2023-07-27--13-01-19
    route = re.sub(r"--\d+$", "", route_or_segment)

    # Figure out which segments we're going to be downloading. Think of it like a sliding window that needs to cover minutes.
    # Segments start from index 0 and are 60 seconds long
    # Examples:
    # Start time: 0, length: 60 -> segment 0
    # Start time: 10, length: 60 -> segments 0 and 1
    # Start time: 400, length: 60 -> segments 6 and 7
    actual_start_seconds = max(0, start_seconds - smear_seconds)
    start_segment = actual_start_seconds // 60
    end_segment = (start_seconds + length) // 60
    segment_ids = list(range(start_segment, end_segment + 1))

    # Get file list JSON from https://api.commadotai.com/v1/route/<route>/files
    # E.g https://api.commadotai.com/v1/route/a2a0ccea32023010|2023-07-27--13-01-19/files
    # Make route URL encoded
    route_url = route.replace("|", "%7C")
    filelist_url = f"https://api.commadotai.com/v1/route/{route_url}/files"
    print(f"Downloading file list from {filelist_url}")
    filelist: FileListDict = requests.get(filelist_url).json()
    # For every segment_id check if the file exists in the filelist
    # If it doesn't, throw an error
    for segment_id in segment_ids:
        camera_exists = False
        ecamera_exists = False
        log_exists = False
        for camera_url in filelist["cameras"]:
            if f"/{segment_id}/fcamera.hevc" in camera_url:
                camera_exists = True
                break
        for ecamera_url in filelist["ecameras"]:
            if f"/{segment_id}/ecamera.hevc" in ecamera_url:
                ecamera_exists = True
                break
        for log_url in filelist["logs"]:
            if f"/{segment_id}/rlog.bz2" in log_url:
                log_exists = True
                break
        if not camera_exists:
            raise ValueError(f"Segment {segment_id} does not have a forward camera upload")
        if not ecamera_exists:
            raise ValueError(f"Segment {segment_id} does not have a wide camera upload")
        if not log_exists:
            raise ValueError(f"Segment {segment_id} does not have a log upload")

    # Download the files
    # We use parfive to download the files
    # https://parfive.readthedocs.io/en/latest/
    #
    # We download the files to the data_dir
    # We find the corresponding URL in the filelist, and download it to the data_dir
    # E.g. https://commadata2.blob.core.windows.net/commadata2/a2a0ccea32023010/2023-07-27--13-01-19/0/fcamera.hevc?se=2023-09-24T04%3A17%3A36Z&sp=r&sv=2018-03-28&sr=b&rscd=attachment%3B%20filename%3Da2a0ccea32023010_2023-07-27--13-01-19--0--fcamera.hevc&sig=a2oLhLvbKY7zlqTbyTmCVOjcN4Is1wQlaSUlZz1wK5U%3D -> data_dir/a2a0ccea32023010_2023-07-27--13-01-19/0/fcamera.hevc

    # Make the date directory. It's just the route but with the ID stripped off the front.
    # E.g. a2a0ccea32023010|2023-07-27--13-01-19 -> 2023-07-27--13-01-19
    route_date = re.sub(r"^[^|]+\|", "", route)

    # Generate the list of URLs and paths to download to
    downloader = parfive.Downloader(
        max_conn=20,
    )

    # Download the data
    for segment_id in segment_ids:
        segment_dir = Path(data_dir) / f"{route_date}--{segment_id}"
        # Download the forward camera
        for camera_url in filelist["cameras"]:
            if f"/{segment_id}/fcamera.hevc" in camera_url:
                # Check if the file already exists
                if (segment_dir / "fcamera.hevc").exists():
                    print(f"Skipping {camera_url} because it already exists")
                    break
                downloader.enqueue_file(
                    camera_url,
                    path=segment_dir,
                    filename= "fcamera.hevc"
                )
                break
        # Download the wide camera
        for ecamera_url in filelist["ecameras"]:
            if f"/{segment_id}/ecamera.hevc" in ecamera_url:
                # Check if the file already exists
                if (segment_dir / "ecamera.hevc").exists():
                    print(f"Skipping {ecamera_url} because it already exists")
                    break
                downloader.enqueue_file(
                    ecamera_url,
                    path=segment_dir,
                    filename= "ecamera.hevc"
                )
                break
        # Download the log
        for log_url in filelist["logs"]:
            if f"/{segment_id}/rlog.bz2" in log_url:
                # Check if the file already exists
                if (segment_dir / "rlog.bz2").exists() or (segment_dir / "rlog").exists():
                    print(f"Skipping {log_url} because it already exists")
                    break
                downloader.enqueue_file(
                    log_url,
                    path=segment_dir,
                    filename= "rlog.bz2"
                )
                break

    # Start the download
    results: Results = downloader.download()
    # Assume that the download is done when the results are done
    # Check if the download was successful
    if results.errors:
        raise ValueError(f"Download failed: {results.errors}")

    # Decompress the logs
    for segment_id in segment_ids:
        segment_dir = Path(data_dir) / f"{route_date}--{segment_id}"
        # Decompress the log if rlog doesn't exist
        if (segment_dir / "rlog").exists():
            print(f"Skipping decompression of {segment_id} because it already exists")
            continue
        log_path = segment_dir / "rlog.bz2"
        if log_path.exists():
            subprocess.run(["bzip2", "-d", log_path])
        else:
            raise ValueError(f"Segment {segment_id} does not have a log upload")



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Download openpilot routes/segments.')
    parser.add_argument('data_dir', type=str, help='Directory to download files to')
    parser.add_argument('route_or_segment', type=str, help='Name of the route or segment to download')
    parser.add_argument('smear_seconds', type=int, help='Number of seconds to smear the start time')
    parser.add_argument('start_seconds', type=int, help='Start time in seconds')
    parser.add_argument('length', type=int, help='Length of the segment to download')
    args = parser.parse_args()
    # All arguments are required

    downloadSegments(args.data_dir, args.route_or_segment, args.smear_seconds, args.start_seconds, args.length)