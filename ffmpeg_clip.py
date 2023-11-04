"""
FFMPEG related clipping from a data directory.

Reference for 360: https://discord.com/channels/469524606043160576/819046761287909446/1068406169317675078

ffmpeg -i clip.ecam.clipped.mp4 -i clip.dcam.clipped.mp4 -filter_complex hstack -c:v libx265 clip.stacked.mp4
ffmpeg -y -i clip.stacked.mp4 -vf v360=dfisheye:equirect:ih_fov=185:iv_fov=185 -c:v libx265 clip.equirect.mp4

"looks like we have v360=dfisheye:equirect:ih_fov=195:iv_fov=122"

ffmpeg -y -i clip.stacked.mp4 -vf v360=dfisheye:equirect:ih_fov=195:iv_fov=122 -c:v libx265 clip.equirect.mp4

ChatGPT combined:

ffmpeg -i clip.ecam.clipped.mp4 -i clip.dcam.clipped.mp4 -filter_complex "[0:v][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=185:iv_fov=185[vout]" -map "[vout]" -c:v libx265 clip.equirect.mp4

Note that the above is not a complete command, it's missing some pre-processing of the driver camera file that comma does and has not been disclosed. More reverse engineering was done to figure out a command that's much closer but not quite identical.

Discovered:

* Driver camera might be shifted down and padded with a dark red color
* Forward camera is initial view

Unresolved Differences:

* The curving is a bit different in the padded and final result. The padded result is a bit more curved somehow.
* Is it possible there's lens correction going on in the driver camera? This would explain the difference in curving.

"""

import argparse
import os
import re
import subprocess
from typing import List
import spatialmedia


def make_ffmpeg_clip(
    render_type: str,
    data_dir: str,
    route_or_segment: str,
    start_seconds: int,
    length_seconds: int,
    target_mb: int,
    nvidia_hardware_rendering: bool,
    forward_upon_wide_h: float,
    output: str,
):
    if render_type not in [
        "forward",
        "wide",
        "driver",
        "360",
        "forward_upon_wide",
        "360_forward_upon_wide",
    ]:
        raise ValueError(f"Invalid choice: {render_type}")
    if not os.path.exists(data_dir):
        raise ValueError(f"Invalid data_dir: {data_dir}")
    route = re.sub(r"--\d+$", "", route_or_segment)
    route_date = re.sub(r"^[^|]+\|", "", route)

    # Target bitrate in bits per second (bps). Try to get close to the target file size.
    target_bps = (target_mb) * 8 * 1024 * 1024 // length_seconds
    # Start seconds relative to the start of the concatenated video
    start_seconds_relative = start_seconds % 60

    # Figure out the segments we'll be operating over
    # The first segment is start_seconds // 60
    # The last segment is (start_seconds + length_seconds) // 60
    segments = list(
        range(start_seconds // 60, (start_seconds + length_seconds) // 60 + 1)
    )

    # Generate concat strings for clip to use
    forward_concat_string_input = "|".join(
        [f"{data_dir}/{route_date}--{segment}/fcamera.hevc" for segment in segments]
    )
    forward_concat_string = f"concat:{forward_concat_string_input}"
    wide_concat_string_input = "|".join(
            [f"{data_dir}/{route_date}--{segment}/ecamera.hevc" for segment in segments]
        )
    wide_concat_string = f"concat:{wide_concat_string_input}"
    driver_concat_string_input = "|".join(
        [f"{data_dir}/{route_date}--{segment}/dcamera.hevc" for segment in segments]
    )
    driver_concat_string = f"concat:{driver_concat_string_input}"

    # Figure out what segments we'll need to concat
    # .hevc files can be concatenated with the concat protocol demuxer

    # Split processing into two types:
    # Simple processing: forward, wide, driver
    # Complex processing: 360, forward_upon_wide, 360_forward_upon_wide
    if render_type in ["forward", "wide", "driver"]:
        #  Map render_type to appropriate filename
        if render_type == "forward":
            ffmpeg_concat_string = forward_concat_string
        elif render_type == "wide":
            ffmpeg_concat_string = wide_concat_string
        elif render_type == "driver":
            ffmpeg_concat_string = driver_concat_string

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
            # Use H264 for maximum Discord compatibility
            command += ["-c:v", "h264_nvenc"]

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

    elif render_type in ["forward_upon_wide"]:
        # Run the ffmpeg command
        command = [
            "ffmpeg",
            "-y",
            "-hwaccel",
            "auto",
            "-probesize",
            "100M",
            "-r",
            "20",
            "-i",
            wide_concat_string,
            "-probesize",
            "100M",
            "-r",
            "20",
            "-i",
            forward_concat_string,
            "-t",
            str(length_seconds),
            "-ss",
            str(start_seconds_relative),
            "-filter_complex",
            f"[1:v]scale=iw/4.5:ih/4.5,format=yuva420p,colorchannelmixer=aa=1[front];[0:v][front]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/{forward_upon_wide_h}",
            "-f",
            "mp4",
            "-movflags",
            "+faststart",
        ]
        if nvidia_hardware_rendering:
            # Use H264 for maximum Discord compatibility
            command += ["-c:v", "h264_nvenc"]

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

    elif render_type == "360" or render_type == "360_forward_upon_wide":

        if render_type == "360":
            # Run the ffmpeg command that has two inputs and fisheye
            command = [
                "ffmpeg",
                "-y",
                "-hwaccel",
                "auto",
                "-probesize",
                "100M",
                "-r",
                "20",
                "-i",
                driver_concat_string,
                "-probesize",
                "100M",
                "-r",
                "20",
                "-i",
                wide_concat_string,
                "-t",
                str(length_seconds),
                "-ss",
                str(start_seconds_relative),
                "-filter_complex",
                f"[0:v]pad=iw:ih+290:0:290:color=#160000,crop=iw:1208[driver];[driver][1:v]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]",
                "-map",
                "[vout]",
            ]
        elif render_type == "360_forward_upon_wide":
            command = [
                "ffmpeg",
                "-y",
                "-hwaccel",
                "auto",
                "-probesize",
                "100M",
                "-r",
                "20",
                "-i",
                driver_concat_string,
                "-probesize",
                "100M",
                "-r",
                "20",
                "-i",
                wide_concat_string,
                "-probesize",
                "100M",
                "-r",
                "20",
                "-i",
                forward_concat_string,
                "-t",
                str(length_seconds),
                "-ss",
                str(start_seconds_relative),
                "-filter_complex",
                f"[2:v]scale=iw/4.5:ih/4.5,format=yuva420p,colorchannelmixer=aa=1[front];[1:v][front]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/{forward_upon_wide_h}[fuw];[0:v]pad=iw:ih+290:0:290:color=#160000,crop=iw:1208[driver];[driver][fuw]hstack=inputs=2[v];[v]v360=dfisheye:equirect:ih_fov=195:iv_fov=122[vout]",
                "-map",
                "[vout]",
            ]
        if nvidia_hardware_rendering:
            # Use HEVC encoding for 360 since people aren't looking at these
            # directly in Discord anyway.
            command += ["-c:v", "hevc_nvenc"]

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

        # Debug return to not do the spherical projection
        # return

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
            "none", None
        )
        spatialmedia.metadata_utils.inject_metadata(
            temp_output, output, metadata, print
        )
        # Delete the temp file
        os.remove(temp_output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="render segments with ffmpeg")
    parser.add_argument(
        "--render_type", "-t", type=str, help="Render type to do", default="forward"
    )
    parser.add_argument(
        "--data_dir", type=str, help="Directory to read from", default="shared/data_dir"
    )
    parser.add_argument(
        "route_or_segment", type=str, help="Name of the route or segment to process"
    )
    parser.add_argument("start_seconds", type=int, help="Start time in seconds")
    parser.add_argument(
        "length_seconds", type=int, help="Length of the segment to render"
    )
    parser.add_argument(
        "--target_mb", type=int, help="Target file size in megabytes", default=25
    )
    parser.add_argument(
        "--forward-upon-wide-h",
        type=float,
        help="Height of the forward camera in forward upon wide overlay videos",
        default=2.2,
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
        forward_upon_wide_h=args.forward_upon_wide_h,
        output=args.output,
    )
