# 📽 openpilot Replay Clipper

Capture and develop short clips of [openpilot][op] with the openpilot UI (path, lane lines, modes, etc.) included, with the segment ID and seconds marker branded into the clip. Useful for posting clips in the [comma.ai Discord's #driving-feedback and/or #openpilot-experience channel](https://discord.comma.ai), [reddit](https://www.reddit.com/r/comma_ai), [Facebook](https://www.facebook.com/groups/706398630066928), or anywhere else that takes video.

Show the bad and the good of openpilot! Very useful for [making outstanding bug reports](https://github.com/commaai/openpilot/wiki/FAQ#how-do-i-report-a-bug) or [posting UI video in interesting situations on X](https://twitter.com/yassineyousfi_/status/1590473942439198720)!

## Platforms

The replay clipper is packaged to run on two platforms for ease of use:

- [Replicate][replicate] (Not free, cheap! But very fast and the UI is easy to use.)
- [GitHub Codespaces][ghcs] (Free! But slow.)

[Alternatively, you can also run this setup on your own machine. It is quite a bit more complicated but can grant you more power and speed via more CPU or use of a GPU if you desire.](#self-running)

Give this project a test with [Replicate](https://replicate.com/nelsonjchen/op-replay-clipper) or [GitHub Codespaces](https://github.com/codespaces) if you haven't already!

### Common to Replicate and GitHub Codespaces

* Setup is fast. You can go from nothing to rendering and developing a clip within two minutes.
* You don't need a comma prime or lite subscription.
* You don't need to install anything on your computer!
* You don't need an existing openpilot development environment setup!
* You need a GitHub account to use GitHub Codespaces *and* Replicate as Replicate uses GitHub for authentication.

### Replicate

* The GUI is really easy to use compared to GitHub Codespaces.
* Replicate is a paid service. You might need to input payment information at some point.
* It costs about $0.01 per render and you may have multiple renders to do. You really won't notice and it's a small price to pay for the convenience.
* Replicate is fast. It can render a 30 second clip in about 1 minute or even faster since a GPU is available to accelerate the rendering and encoding.
* You can run and queue up multiple jobs at a time. Replicate might even spin up multiple renderers if you're lucky and complete them faster.
* You don't need to worry about cleanup. Replicate just cleans up after itself.
* You'll need to temporarily make your route public for Replicate to access it. You can toggle it back to non-Public after you're done with clip making.

### Codespaces

* Some experience with VSCode and text editors is recommended.
* The free GitHub account will give you 30 free hours of a 4 CPU machine every month.
* It's preset with a spending limit of $0/mo. There is no risk of charging you anything.
* Cleanup is easy, but you should delete it from https://github.com/codespaces afterwards if you aren't going to use it anymore so it isn't taking up your free hours. It will automatically be deleted after 30 days of inactivity though.
* Downloading rendered clips is a bit tricky at the moment.
* You can run this against a non-public route by providing a JWT token.
* This is slower than Replicate. It can render a 30 second clip in about 5 minutes and the slowdown is due to the lack of a GPU to accelerate the rendering and encoding. So it's all software rendering and encoding.

## Samples

Demonstration of speed or longitudinal behavior of openpilot with model-based longitudinal is nearly impossible or hard without this clipper. This video is of a good model based long behavior at highway speeds.

https://user-images.githubusercontent.com/5363/202886008-82cfbf02-d19a-4482-ab7a-59f96c802dd1.mp4

Cars can have bugs themselves. Here's my 2020 Corolla Hatchback phantomly braking on metal strips in stop and go traffic probably from the radar. Perhaps a future openpilot that doesn't depend on radar might be the one sanity checking the radar instead of the other way around currently. And another example of that in Portland.

https://user-images.githubusercontent.com/5363/219708673-4673f4ff-9b47-4c57-9be3-65f3ea703f3f.mp4

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/1e59844b-46f8-4289-bea9-511db2718549

This is a video of a bug report where openpilot's lateral handling lost the lane.

https://user-images.githubusercontent.com/5363/205901777-53fd18f9-2ab5-400b-92f5-45daf3a34fbd.mp4

Lane cutting?

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/d0ab3365-b5ef-4e05-84ee-370b88e8af02

Nav-assisted follow the road instead of taking the side road.

https://github.com/nelsonjchen/op-replay-clipper/assets/5363/8f970c76-21d1-4209-b0e1-3eb6989feea8

## Limitations

- This has only been tested on data from a Comma 3 and/or Comma 3X. It is unknown if it can work for any other devices.
- The UI replayed is comma.ai's latest stock UI on their master branch; routes from forks that differ alot from stock may not render correctly. Your experience may and will vary. Please make sure to note these replays are from fork data and may not be representative of the stock behavior. [The comma team really does not like it if you ask them to debug fork code as "it just takes too much time to be sidetracked by hidden and unclear changes"](https://discord.com/channels/469524606043160576/616456819027607567/1042263657851142194).
- Older routes may not replay correctly or at all on the latest UI in the master branch.
- I strongly recommend you work on this from a desktop, laptop, or at least a tablet for Codespaces. Replicate should works OK on a phone too though.
- **You are advised to upload all files of the route to Comma Connect servers before attempting to render a route. If you do not upload all files, the replay will not render past the starting UI.**

## Usage

### Pre-Setup

Ensure your openpilot route's files are fully uploaded on https://connect.comma.ai/. Click `Files` when viewing a route and select the option to upload all files (`Upload ## files`). Make sure it says "`uploaded`".

- This route is not yet fully uploaded:
  - <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
- This route is fully uploaded:
  - <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
- The driver or interior camera is not required to be enabled for recording or uploading for this. It's easier to just hit that "Upload all" button though. Unfortunately there's no only upload all wide camera, forward camera, and logs button.
  - If this is news to you about recording or uploading driver video, you should be aware of a toggle in the openpilot UI to not record driver video and thus effectively not allowing upload of the driver video. Unfortunately, there's no record but block upload driver videos option.
- Note: If you do not upload all the forward camera files, the replay will not progress past the starting UI.
- It is possible to upload only a portion of the route and still render a clip, but it's not recommended if you are new to this clipper. You can find those instructions [in Advanced Tips > Partial Uploads](#partial-upload).

### Setup

#### Time Estimates

- Replicate
  - Setup: If the clipper is cold, it'll take about 4 minutes to spin up. You aren't charged for this by Replicate. If you're lucky, someone else has already spun up the clipper and an existing public instance will already be warm and ready to go.
  - Per Clip
     - 1 minute for an uncached 30 second clip.
     - 0.5 minutes to re-render said 30 second clip that was run recently and data cached by Replicate.
- Codespaces
  - Setup: 1 minute
  - Per Clip: About 5 minutes to capture a 30 second frame with the UI and compress the 30 second clip to ~50MB.

#### Setup Replicate

1. Visit https://replicate.com/nelsonjchen/op-replay-clipper. That's it. You're done. You can skip to [Steps](#steps).

#### Setup GitHub Codespaces

1. Right click on this button below, select `Open in New Tab`, and launch a codespace in US West region. It'll be fully loaded when icons appear in the left sidebar for files.

   <a href="https://github.com/codespaces/new?hide_repo_select=true&ref=master&repo=532830402&machine=standardLinux32gb&devcontainer_path=.devcontainer%2Fdevcontainer.json&location=WestUs2" target="_blank">![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)</a>

   ![image](https://user-images.githubusercontent.com/5363/202962338-d4301937-19c3-410a-af5b-e7ba3a7060fb.png)

2. In the left sidebar, open [scratch_run.sh](./scratch_run.sh). You will be editing this file and running it to run the script to generate a clip.

   ![image](https://user-images.githubusercontent.com/5363/202962401-d8d2a398-e737-4750-a1bb-f7867f316ce5.png)

### Steps

#### Gather Information

You'll need:

- A comma connect `route or segment ID`.
   - <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
- The `starting second` on the route you want to clip.
   - On comma connect, the route's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute and start from 0. So scrub it, and do a little mental arithmetic to get the starting second. I usually do "60 \* segment number + offset" as my mental calculation.
     - Sample
       - <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
     - In this example, the starting second would be at least 60 \* 3 = 180 seconds.
     - Don't stress on this, if this is your first time, just wing it. You'll get it.
- How long you want the clip to be. Recommended to be 30 seconds or less.

#### Replicate

1. Make sure the route is Public. If it isn't, toggle the `Make Public` active under More Info. You can toggle it back  after you're done with clip making to make it private again.
   - ![image](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/24d70619-f735-4b17-a852-77a4f96cda25)
2. Put `route or segment ID` into the `route` field.
3. Put the `starting second` into the `start` field.
4. Put the `clip length` into the `length` field.
5. Click `Submit` and wait for the clip to render.

![image](https://github.com/nelsonjchen/op-replay-clipper/assets/5363/787d0ef0-3d9d-48d7-9671-74f6f07c640c)

#### GitHub Codespaces

There are options but these are the basic steps. Note, the screenshots below may vary in themes and UI, but the layout is generally the same.

1. Edit the placeholder `route or segment ID` in `scratch_run.sh` to the `route or segment ID`.
2. Edit the starting second in the `scratch_run.sh` file to this value.
3. Make sure the route is accessible.
   - Get a JWT Token from https://jwt.comma.ai with the same account type you log into Comma Connect with. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Edit the JWT token in the `scratch_run.sh` file to this value. **Keep this token private, do not share it with anyone as it will grant access to your comma connect account for a year.**
4. Change the clip length value in `scratch_run.sh` to the number of seconds you want to capture. Longer lengths take proportionally longer to capture.
5. Run the script with `./scratch_run.sh` in the Terminal.
   - Sample: <img width="1072" alt="image" src="https://user-images.githubusercontent.com/5363/202886850-cf4e392f-f40f-423c-bbae-2b5917f74971.png">
6. Wait 3 minutes, and the script should complete.
   - Sample: <img width="1511" alt="Screenshot 2022-11-27 at 2 32 19 PM" src="https://user-images.githubusercontent.com/5363/204163251-638257ee-df14-440a-a8f0-3e26e4aae80e.png">
7. ~~After it completes, click "Go Live" in the bottom right corner to start a web server and open the web server in a new tab. Browse to the `shared` folder.~~ [This and the next step is currently broken with web browser codespace; It may be fine on Desktop VSCode connected to a codespace though.](https://github.com/nelsonjchen/op-replay-clipper/issues/30) As an alternative, you can right click on the file in VSCode under shared and press "Download...". If on macOS it complains about "system folders", make a new folder under your home folder and save to there.
   - Clicking Go Live:
      - <img width="1186" alt="Screenshot 2022-11-27 at 4 25 19 PM" src="https://user-images.githubusercontent.com/5363/204168299-79346fa7-45c7-4b03-b6b5-ff793af2a05e.png">
   - Web Server View Sample
      - <img width="1510" alt="Screenshot 2022-11-27 at 4 26 43 PM" src="https://user-images.githubusercontent.com/5363/204168325-4682c223-39d8-45f6-8065-ce3f2cd02bff.png">
8. ~~Right click and download `clip.mp4` (or any files you've generated) to your computer. You can share or upload this file wherever you want.~~
9. If you want to make more clips, continue to edit and run `./scratch_run.sh`, and refresh the web server's tab.
10. Cleanup is easy. Delete the GitHub Codespace here: https://github.com/codespaces. If you forget, the GitHub Codespace will automatically stop after 30 minutes of inactivity and will automatically be completely deleted after 30 days of idle by default.
  - It is also possible to restart a pre-existing codespace and continue where you left off if it wasn't deleted.

## Self running

Maybe you want to run this on your own computer, like if you want to generate many clips, really long clips, have run out of the free Codespace hours, or some other reason.

### Compute Requirements

The requirements may be a bit high.

- 4 vCPUs/hyperthreads
  - 2vCPUs/hyperthreads with a lower `--speedhack-ratio` value that renders slower to maintain stability
- A working Docker-Compose setup. Docker for Windows or Docker for Mac will work.
- Intel or AMD processor.
  - Emulation of Intel on Apple Silicon with Docker for Mac is [too slow](#bad-or-too-slow-computer) to handle the requirements. Please use a suitable Intel or AMD machine.
- 10 GB of disk space. More needed if you're rendering longer clips as intermediates are quite raw.
- 100MB/s disk speed.
  - Docker for Windows users should clone the repository to the Linux filesystem to meet the requirement.
- A GPU is **not** needed. However, one could be used to accelerate the rendering process.

The CPU requirement is due to a number of factors:

- Reliable H.265 hardware decoding is not always available. The high quality forward video is only captured in H.265 and could only be decoded at 0.7 speed on a Ryzen 2800 and at half speed reliabily for the purposes of capture. And there are also two video streams: telescope and wide!
- Reliable OpenGL rendering is not always available. Software OpenGL rendering is used instead to guarantee compatibility.
- Capturing the UI can be quite intensive due to all the software and non-hardware-accelerated rendering and decoding.
- Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like [the planner's line lagging and not matching the forward video such as in the case of the forward video not decoding fast enough](#bad-or-too-slow-computer). A generous margin of extra performance is used to ensure that the UI is captured at the same speed as the forward video in case of unexpected system jitters.

Even with these CPU requirements, it was not enough to run the tooling at full speed on the CPU. Some measures have been done to make clip recording possible.

- Relevant processes are speedhack'd with `faketime` to run at 0.3x by default.
- Capture is done in real time but undercranked to simulate full speed.

### Self running setup

#### 🪟 Docker for Windows

1. Install Ubuntu for WSL2: https://ubuntu.com/tutorials/install-ubuntu-on-wsl2-on-windows-10
2. Install Docker for Windows: https://docs.docker.com/desktop/install/windows-install/
3. Open up the Ubuntu terminal and clone this repository: `git clone https://github.com/nelsonjchen/op-replay-clipper/`
   - For performance reasons, make sure you clone to the Linux filesystem. The default working directory of your home directory in Ubuntu when you open up Ubuntu is adequate.
4. Change folders to `cd op-replay-clipper`
5. Continue to [Steps](#steps).

#### 🔨 DIY (Misc, I already have Docker, I already run Docker on Linux, I have my own setup, Advanced)

If you are knowledgeable about Docker, Linux, Docker-Compose and whatnot, I'm sure you can figure it out. Just clone this repo down and go through the [Steps](#steps).

You may need to `chmod` the `shared` folder to be writable by the internal Docker user of the image. Just do `777`, it's all temporary anyway.

### Self Running Usage.

It's recommended you open the repository as a Dev Container in VS Code:

https://code.visualstudio.com/docs/devcontainers/containers#_quick-start-open-an-existing-folder-in-a-container

From there on, follow the [Steps as normally used with GitHub Codespaces](#steps).

You may want to "Rebuild Container without Cache" to update to a newer Openpilot UI periodically.

#### GPU Acceleration

Currently only tested with NVIDIA GPUs and on WSL2 in Windows 11. Setup in other environments may be possible, but untested.

See `.devcontainer/docker-compose.yml` for some lines to uncomment when running this tool inside VSCode's Dev Container. You
will need to "Rebuild Container" from the command palette after uncommenting to enable the GPU. Run `nvidia-smi` inside the Dev Container. If you see your GPU, you should be able to run this tool with GPU acceleration.

You should be able to run the tool with a higher `--speedhack-ratio` value (0.5 to 1.5).

Things that are accelerated by passing in a GPU:

* (Nvidia-only/Auto) `replay`'s decoding of the forward video if a NVIDIA GPU is provided and CUDA is available.
* (Nvidia-only/Manual) Optionally, on NVIDIA GPUs, you can also pass into `clip.sh` the option `--nv-direct-encoding` to encode the captured video directly to a H.264 MP4 via the GPU. Video quality is lower, but it is *quick*.

If a real Nvidia Linux non-WSL2 GPU is passed in, there is also an option to make an X.org server inside the container use it for accelerated OpenGL rendering.

### Self Running Teardown

### Teardown

#### 🪟 Docker for Windows

Docker for Windows has a terrible memory or handle leak issue. Quit it from the black whale icon in system tray. Additionally, you may want to also shutdown Ubuntu by running `wsl --shutdown` from a PowerShell or Command Prompt to regain maximum performance.

While Docker for Windows is running, you may also want to click Clean Up while inside it if you want to regain some disk space.

#### 🔨 DIY

You may want to prune images. Up to you, DIYer!

### Self Running Development

Best to use the Dev Container.

### Bad or Too Slow Computer

Here's the result you get when you run the clipper on a computer that's too slow or doesn't meet the requirements after all the performance "modifiers". Nothing lines up and it's slow.

From https://discord.com/channels/469524606043160576/1030241716818681897/1030341590201413664

https://user-images.githubusercontent.com/5363/196210351-acc0b235-f87b-4dbc-8b2a-67ca842e52ac.mp4

## Advanced Tips

### Partial Upload

It is possible to upload only a small portion of a long route for the clipper with Comma Connect's GUI.

**You are strongly recommended to select a minute before, and a minute after the incident you want to clip.** This will give a buffer before and after the incident to provide a margin for the clipper to render with. Think of the clipper as a fragile film projector; please give it some slack and upload the files for these adjacent segments. If you do not, rendering may not start at all or errors may occur.

The video below shows how to do this with Comma Connect's GUI.

https://user-images.githubusercontent.com/5363/204060281-ed1c2376-498a-45f8-a8ac-481fda7ee800.mov

## Architecture

* Designed to be run in a Docker container. Running these scripts on your host system may be possible, but is not supported and may even brick your system.
* Container builds `master` openpilot UI and `replay` tool from source with some patches.
   * Redirected `/dev/shm` to `/var/tmp` to avoid running out of space. Exceptions being the IPC for video data and certain high-speed queues which are symlinked to `/dev/shm`.
   * Patch `replay` to download 3 forward segments instead of 5 to settle networking faster and begin rendering for short clips.
* `faketime` is used to slow down or speed up the replay tool and UI for a choice of flexibility and stability depending on hardware availability/capability or desired clip quality.
* Most logic is in a single shell script, `clip.sh`.
* A Replicate Cog `predict.py` is made to wrap `clip.sh` to make it easy to use in Replicate.
   * A custom version of Cog is currently used to expose more Nvidia driver capabilities on Replicate.
* `clip.sh` has an option to spins up and sets up an appropriate X11 server for the UI to render to.
   * Replicate uses a bona-fide Nvidia XOrg server that is configured to provide OpenGL acceleration to the openpilot UI.
   * XVnc is used on all other platforms for debugging purposes but has no OpenGL acceleration.
* `tmux` is used in `clip.sh` to control and send commands to the replay tool and UI.
* `ffmpeg` is used to capture the UI, edit and encode the video, hardware accelerated if available.

## Credits

The real MVP is [@deanlee](https://github.com/deanlee) for the replay tool in the openpilot project. The level of effort to develop the replay tool is far beyond this script. The script is just a wrapper around the replay tool to make it easy to use for clipping videos.

https://github.com/commaai/openpilot/blame/master/tools/replay/main.cc

[do]: https://www.digitalocean.com/
[op]: https://github.com/commaai/openpilot
[ghcs]: https://github.com/features/codespaces
[replicate]: https://replicate.com/nelsonjchen/op-replay-clipper
