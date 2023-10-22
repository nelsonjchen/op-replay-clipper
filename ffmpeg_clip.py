"""
FFMPEG related clipping from a data directory.

Reference for 360: https://discord.com/channels/469524606043160576/819046761287909446/1068406169317675078

ffmpeg -i clip.ecam.clipped.mp4 -i clip.dcam.clipped.mp4 -filter_complex hstack -c:v libx265 clip.stacked.mp4
ffmpeg -y -i clip.stacked.mp4 -vf v360=dfisheye:equirect:ih_fov=185:iv_fov=185 -c:v libx265 clip.equirect.mp4

"looks like we have v360=dfisheye:equirect:ih_fov=195:iv_fov=122"

ffmpeg -y -i clip.stacked.mp4 -vf v360=dfisheye:equirect:ih_fov=195:iv_fov=122 -c:v libx265 clip.equirect.mp4

ChatGPT combined:

ffmpeg -i clip.ecam.clipped.mp4 -i clip.dcam.clipped.mp4 -filter_complex "[0:v][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=185:iv_fov=185[vout]" -map "[vout]" -c:v libx265 clip.equirect.mp4

"""

import argparse
import os
import re
import subprocess
from typing import List
import spatialmedia

# https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/ffmpeg-with-nvidia-gpu/index.html#command-line-for-latency-tolerant-high-quality-transcoding
hq_nvc_flags = [
    "-preset",
    "p6",
]

def make_ffmpeg_clip(
    render_type: str,
    data_dir: str,
    route_or_segment: str,
    start_seconds: int,
    length_seconds: int,
    target_mb: int,
    nvidia_hardware_rendering: bool,
    output: str
  ):
  if render_type not in ["forward", "wide", "driver", "360"]:
    raise ValueError(f"Invalid choice: {render_type}")
  if not os.path.exists(data_dir):
    raise ValueError(f"Invalid data_dir: {data_dir}")
  route = re.sub(r"--\d+$", "", route_or_segment)
  route_date = re.sub(r"^[^|]+\|", "", route)

  # Target bitrate in bits per second (bps). Try to get close to the target file size.
  target_bps = (target_mb - 5) * 8 * 1024 * 1024 // length_seconds
  # Start seconds relative to the start of the concatenated video
  start_seconds_relative = start_seconds % 60

  # Figure out the segments we'll be operating over
  # The first segment is start_seconds // 60
  # The last segment is (start_seconds + length_seconds) // 60
  segments = list(range(start_seconds // 60, (start_seconds + length_seconds) // 60 + 1))

  # Figure out what segments we'll need to concat
  # .hevc files can be concatenated with the concat protocol demuxer

  # Split processing into two types:
  # Simple processing: forward, wide, driver
  # Complex processing: 360
  if render_type in ["forward", "wide", "driver"]:
    #  Map render_type to appropriate filename
    if render_type == "forward":
      filename = "fcamera.hevc"
    elif render_type == "wide":
      filename = "ecamera.hevc"
    elif render_type == "driver":
      filename = "dcamera.hevc"
     # Concat the segments
    ffmpeg_concat_string_input = "|".join(
        [f"{data_dir}/{route_date}--{segment}/{filename}" for segment in segments]
    )
    ffmpeg_concat_string = f"concat:{ffmpeg_concat_string_input}"
    # Run the ffmpeg command
    command = [
        "ffmpeg",
        "-r",
        "20",
        "-vsync",
        "0",
        "-y",
        "-hwaccel",
        "auto",
        "-probesize",
        "100M",
        "-i",
        ffmpeg_concat_string,
        "-t",
        str(length_seconds),
        "-ss",
        str(start_seconds_relative),
        "-f",
        "mp4",
        "-movflags",
        "+faststart",
    ]
    if nvidia_hardware_rendering:
        command += ["-c:v", "h264_nvenc"]
        command += hq_nvc_flags

    # Target bitrate
    command += [
        "-b:v",
        str(target_bps),
    ]
    command += [output]
    print(command)
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    try:
        while True:
            proc_output = process.stdout.readline()
            if proc_output == b"" and process.poll() is not None:
                break
            if proc_output:
                print(proc_output)
    except KeyboardInterrupt:
        process.kill()
        raise

  elif render_type == "360":
    # Need to make two concat strings
    # One for wide, one for driver
    wide_concat_string_input = "|".join(
        [f"{data_dir}/{route_date}--{segment}/ecamera.hevc" for segment in segments]
    )
    wide_concat_string = f"concat:{wide_concat_string_input}"
    driver_concat_string_input = "|".join(
        [f"{data_dir}/{route_date}--{segment}/dcamera.hevc" for segment in segments]
    )
    driver_concat_string = f"concat:{driver_concat_string_input}"

    # Run the ffmpeg command that has two inputs and fisheye
    command = [
        "ffmpeg",
        "-r",
        "20",
        "-vsync",
        "0",
        "-y",
        "-hwaccel",
        "auto",
        "-probesize",
        "100M",
        "-i",
        wide_concat_string,
        "-probesize",
        "100M",
        "-i",
        driver_concat_string,
        "-t",
        str(length_seconds),
        "-ss",
        str(start_seconds_relative),
        "-filter_complex",
        f"[0:v][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]",
        "-map",
        "[vout]",
    ]
    if nvidia_hardware_rendering:
        command += ["-c:v", "h264_nvenc"]
        # https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/ffmpeg-with-nvidia-gpu/index.html#command-line-for-latency-tolerant-high-quality-transcoding
        command += hq_nvc_flags

    # Target bitrate
    command += [
        "-b:v",
        str(target_bps),
    ]
    command += [output]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)

    try:
        while True:
            proc_output = process.stdout.readline()
            if proc_output == b"" and process.poll() is not None:
                break
            if proc_output:
                print(proc_output)
    except KeyboardInterrupt:
        process.kill()
        raise

    # Add spherical projection to the output
    # Move the old output to a temp file
    # Print type(output)
    temp_output = output + ".temp.mp4"
    if os.path.exists(temp_output):
        os.remove(temp_output)
        # Print working directory

    print(os.getcwd())
    os.rename(output, temp_output)

    metadata = spatialmedia.metadata_utils.Metadata()
    metadata.video = spatialmedia.metadata_utils.generate_spherical_xml(
       "none",
        None
    )
    spatialmedia.metadata_utils.inject_metadata(
       temp_output, output, metadata, print
    )
    # Delete the temp file
    os.remove(temp_output)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="render segments with ffmpeg")
    parser.add_argument("--render_type", "-t", type=str, help="Render type to do", default="forward")
    parser.add_argument("--data_dir", type=str, help="Directory to read from", default="shared/data_dir")
    parser.add_argument(
        "route_or_segment", type=str, help="Name of the route or segment to process"
    )
    parser.add_argument("start_seconds", type=int, help="Start time in seconds")
    parser.add_argument("length_seconds", type=int, help="Length of the segment to render")
    parser.add_argument(
        "--target_mb", type=int, help="Target file size in megabytes", default=25
    )
    parser.add_argument(
        "--nvidia-hardware-rendering",
        "-nv",
        action="store_true",
        help="Use NVENC hardware rendering",
    )
    parser.add_argument(
        "--output", type=str, help="Output file name", default="./shared/cog-clip.mp4"
    )
    args = parser.parse_args()

    # All arguments are required
    make_ffmpeg_clip(
        render_type=args.render_type,
        data_dir=args.data_dir,
        route_or_segment=args.route_or_segment,
        start_seconds=args.start_seconds,
        length_seconds=args.length_seconds,
        target_mb=args.target_mb,
        nvidia_hardware_rendering=args.nvidia_hardware_rendering,
        output=args.output,
    )

