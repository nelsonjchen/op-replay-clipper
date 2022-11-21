# 📽 Openpilot Replay Clipper

Capture short clips of [openpilot][op] routes with the openpilot UI included, with the route and seconds marker branded into the clip. Useful for posting replay clips with the UI including path and lane-lines in the [comma.ai Discord's #openpilot-experience channel](https://discord.comma.ai) or anywhere else that takes video.

No pre-existing openpilot development environment setup of any sort is required nor does any software need to be installed on your computer. Just [GitHub Codespaces][ghcs] which is available to anyone with a free GitHub account and a web browser which will give you 30 free hours of a 4 CPU machine every month with only a few clicks and a spending limit already pre-set to $0/mo with no risk of charging you anything. Cleanup is automated too. [Alternatively, you can also run this setup on your own machine, but it's quite a bit more complicated but can grant you more power.](#self-running)

https://user-images.githubusercontent.com/5363/202886008-82cfbf02-d19a-4482-ab7a-59f96c802dd1.mp4

https://user-images.githubusercontent.com/5363/202887339-97c69dc1-8a4a-4248-a1bc-fd8599bbb5b5.mp4

## Limitations

- The UI replayed is comma.ai's latest stock UI on their master branch; routes from forks that differ alot from stock may not render correctly. Your experience may and will vary. Please make sure to note these replays are from fork data and may not be representative of the stock behavior. [The comma team really does not like it if you ask them to debug fork code as "it just takes too much time to be sidetracked by hidden and unclear changes"](https://discord.com/channels/469524606043160576/616456819027607567/1042263657851142194).
- Older routes may not replay correctly or at all on the latest UI in the master branch.
- **You are advised to upload all files of the route to Comma Connect servers before attempting to render a route. If you do not upload all files, the replay will not render past the starting UI.**

## Usage

### Pre-Setup

Ensure your route's files are fully uploaded on https://my.comma.ai. Click `Files` when viewing a route and select the option to upload all files (`Upload ## files`). Make sure it says "`uploaded`".

- This route is not yet fully uploaded:
  - <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
- This route is fully uploaded:
  - <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
- Note: The driver or interior camera is not required to be enabled for recording or uploading for this. It's easier to just hit that "Upload all" button though. Unfortunately there's no only upload all wide camera and forward camera button.
- Note: If you do not upload all the forward camera files, the replay will not progress past the starting UI.

### Setup

We will be using [GitHub Codespaces][ghcs].

#### Time Estimates

- Setup: 1 minute
- [Per Clip](#steps): About 5 minutes to capture a 30 second frame with the UI and compress the 30 second clip to ~50MB.

#### Setup GitHub Codespaces

1. Right click on this button below, select `Open in New Tab`, and launch a codespace in US West region.

   <a href="https://github.com/codespaces/new?hide_repo_select=true&ref=master&repo=532830402&machine=standardLinux32gb&devcontainer_path=.devcontainer%2Fdevcontainer.json&location=WestUs2" target="_blank">![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)</a>
   
   ![image](https://user-images.githubusercontent.com/5363/202962338-d4301937-19c3-410a-af5b-e7ba3a7060fb.png)

2. In the left sidebar, open [scratch_run.sh](./scratch_run.sh). You will be editing this file and running it to run the script to generate a clip.

   ![image](https://user-images.githubusercontent.com/5363/202962401-d8d2a398-e737-4750-a1bb-f7867f316ce5.png)

### Steps

There are options but these are the basic steps.

1. Find the route you wish to take a clip from on https://my.comma.ai.
2. Find the starting seconds value. The route's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute. So scrub it, and do a little mental arithmetic to get the starting second. I usually do "60 \* segment number + offset" as my mental calculation. Edit the starting second in the `scratch_run.sh` file to this value.
   - Sample: <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
   - In this example, the starting second would be at least 6 \* 30 = 180 seconds.
3. Get the route ID from `More Info`. The example below would be `071ba9916a1da2fa|2022-09-04--11-15-52`. Edit the route ID in the `scratch_run.sh` file to this value.
   - <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
4. Get a JWT Token from https://jwt.comma.ai. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Edit the JWT token in the `scratch_run.sh` file to this value. **Keep this token private, do not share it with anyone as it will grant access to your comma connect account for a year.**
5. Change the clip length value in `scratch_run.sh` to the number of seconds you want to capture. Longer lengths take proportionally longer to capture.
6. Run the script with `./scratch_run.sh` in the Terminal.
   - Sample: <img width="1072" alt="image" src="https://user-images.githubusercontent.com/5363/202886850-cf4e392f-f40f-423c-bbae-2b5917f74971.png">
7. Wait 3 minutes, and the script should complete.
   - Sample: ![nelsonjchen-refactored-sniffle-wrr5p5v636j9 github dev_](https://user-images.githubusercontent.com/5363/202887303-72b7b772-7d39-4a15-ab33-43dca030f019.png)
8. If you want to capture more clips, edit `./scratch_run.sh` accordingly and change the output name.
9. After it completes, run `python3 -m http.server` in the Terminal to start a web server. VSCode should prompt you to open the link in your browser. Click the `Open in Browser` link and browse to the `shared` folder
   - Sample: <img width="1288" alt="Screenshot 2022-11-19 at 9 35 34 PM" src="https://user-images.githubusercontent.com/5363/202887379-bbc39fd4-be0d-4688-927c-e0f63bff758c.png">
   - Shared Folder: <img width="526" alt="image" src="https://user-images.githubusercontent.com/5363/202887400-f19c2980-2cd1-4504-8153-751158bec61f.png">
10. Right click and download `clip.mp4` (or any files you've generated) to your computer. You can share or upload this file wherever you want.
11. If you want to make more clips, press `Ctrl-C` to exit the web server, continue to edit and run `./scratch_run.sh`, and re-run the command to start a web server.
11. Cleanup is easy. Just close the browser tabs. The GitHub Codespace will automatically stop after 30 minutes of inactivity and will automatically be completely deleted after 30 days of idle by default. If you wish, you can stop and delete the codespaces earlier than the default times here: https://github.com/codespaces. It is also possible to restart a pre-existing codespace and continue where you left off if it wasn't deleted.

## Self running

Maybe you want to run this on your own computer, like if you want to generate many clips, really long clips, have run out of the free Codespace hours, or some other reason.

### Compute Requirements

The requirements may be a bit high.

- 4 vCPUs/hyperthreads
  - 2vCPUs/hyperthreads with `--slow-cpu` flag that renders slower to maintain stability
- A working Docker-Compose setup. Docker for Windows or Docker for Mac will work.
- Intel or AMD processor.
  - Emulation of Intel on Apple Silicon with Docker for Mac is [too slow](#bad-or-too-slow-computer) to handle the requirements. Please use a suitable Intel or AMD machine.
- 10 GB of disk space.
- 100MB/s disk speed.
  - Docker for Windows users should clone the repository to the Linux filesystem to meet the requirement.
- A GPU is **not** needed and is also unused in the tool.

The CPU requirement is due to a number of factors:

- Reliable H.265 hardware decoding is not always available. The high quality forward video is only captured in H.265 and could only be decoded at 0.7 speed on a Ryzen 2800 and at half speed reliabily for the purposes of capture. And there are also two video streams: telescope and wide!
- Reliable OpenGL rendering is not always available. Software OpenGL rendering is used instead to guarantee compatibility.
- Capturing the UI can be quite intensive due to all the software and non-hardware-accelerated rendering and decoding.
- Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like [the planner's line lagging and not matching the forward video such as in the case of the forward video not decoding fast enough](#bad-or-too-slow-computer). A generous margin of extra performance is used to ensure that the UI is captured at the same speed as the forward video in case of unexpected system jitters.

Even with these CPU requirements, it was not enough to run the tooling at full speed on the CPU. Some measures have been done to make clip recording possible.

- Relevant processes are speedhack'd with `faketime` to run at 0.3x by default or 0.1x with the `--slow-cpu` flag.
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

### Self Running Teardown

### Teardown

#### 🪟 Docker for Windows

Docker for Windows has a terrible memory or handle leak issue. Quit it from the black whale icon in system tray. Additionally, you may want to also shutdown Ubuntu by running `wsl --shutdown` from a PowerShell or Command Prompt to regain maximum performance.

While Docker for Windows is running, you may also want to click Clean Up while inside it if you want to regain some disk space.

#### 🔨 DIY

You may want to prune images. Up to you, DIYer!

### Self Running Development

Use the `dev` service in the `docker-compose.yml` file to run the `clip.sh` script in a development environment. This will allow you to make changes to the `clip.sh` script and see the changes reflected in the container.

Additionally, a Devcontainer is provided for VSCode users. This will allow you to run the `clip.sh` script in a development environment with the same dependencies installed as the Docker container.

## Bad or Too Slow Computer

Here's the result you get when you run the clipper on a computer that's too slow or doesn't meet the requirements after all the performance "modifiers". Nothing lines up and it's slow.

From https://discord.com/channels/469524606043160576/1030241716818681897/1030341590201413664

https://user-images.githubusercontent.com/5363/196210351-acc0b235-f87b-4dbc-8b2a-67ca842e52ac.mp4

## Architecture

Just a single shell script that runs an X11 server, and tmux commands to control the replay executable. There is `faketime` to make it run reliably without modifications to the pre-built openpilot that is in the image. Docker is used to just make it portable, but also easy to cleanup. Docker-Compose is used to make sure the `/dev/shm` size is correct and to specify the use of already pre-built images for general use or backwards compatibility use.

## Credits

The real MVP is @deanlee for the replay tool in the openpilot project. The level of effort to develop the replay tool is far beyond this script. The script is just a wrapper around the replay tool to make it easy to use for clipping videos.

https://github.com/commaai/openpilot/blame/master/tools/replay/main.cc

[do]: https://www.digitalocean.com/
[op]: https://github.com/commaai/openpilot
[ghcs]: https://github.com/features/codespaces
