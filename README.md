# 📽 Openpilot Replay Clipper

Capture short clips of [openpilot][op] routes with the openpilot UI included, with the route and seconds marker branded into the clip. No pre-existing openpilot development environment setup required. Just some computing resources either you provide or [GitHub Codespaces][ghcs], which gives you 30 free hours of a 4 CPU machine free every month.

Useful for posting replay clips with the UI including path and lane-lines in the [comma.ai Discord's #openpilot-experience channel](https://discord.comma.ai) or anywhere else that takes video.

A manual left turn and then activating OP:

https://user-images.githubusercontent.com/5363/188810452-47a479c4-fa9a-4037-9592-c6a47f2e1bb1.mp4


"Experimental Mode" (`experimental`) UI Rendering Mode with the `--experimental` option for 0.9.0 routes:

https://user-images.githubusercontent.com/5363/196816467-39a147ed-885c-4f90-89d4-cc1ff852b8f0.mp4

*Note*: The above clip was a bug report and may not reflect the current state of end-to-end longitudinal support. End-to-end longitudinal is under heavy development.

## Requirements

The requirements may be a bit high. 

You will need an appropiate computer, either your own or one that is temporary for a few minutes such as one on [GitHub Codespaces][ghcs], to run this tool.

* 4 vCPUs/hyperthreads
  * 2vCPUs/hyperthreads with `--slow-cpu` flag that renders slower to maintain stability
* A working Docker-Compose setup. Docker for Windows or Docker for Mac will work.
* Intel or AMD processor.
  * Emulation of Intel on Apple Silicon with Docker for Mac is [too slow](#bad-or-too-slow-computer) to handle the requirements. Please use a suitable Intel or AMD machine.
* 10 GB of disk space.
* 100MB/s disk speed.
  * Docker for Windows users should clone the repository to the Linux filesystem to meet the requirement.
* A GPU is **not** needed and is also unused in the tool.

There are other notes too regarding the data you want to render:

* The UI replayed is comma.ai's latest stock UI; routes from forks that differ alot from stock may not render correctly. Your experience may vary. Please make sure to note these replays are from fork data and may not be representative of the stock behavior. As a side note, [the comma team really does not like it if you ask them to debug fork code as "it just takes too much time to be sidetracked by hidden and unclear changes"](https://discord.com/channels/469524606043160576/616456819027607567/1042263657851142194).
* The desired route to be rendered must have been fully able to upload to Comma.ai servers and must be accessible.
* **You are advised to upload all files of the route to Comma.ai servers before attempting to render a route. If you do not upload all files, the replay will not render past the starting UI.**

The CPU requirement is due to a number of factors:

* Reliable H.265 hardware decoding is not always available. The high quality forward video is only captured in H.265 and could only be decoded at 0.7 speed on a Ryzen 2800 and at half speed reliabily for the purposes of capture. And there are also two video streams: telescope and wide!
* Reliable OpenGL rendering is not always available. Software OpenGL rendering is used instead to guarantee compatibility.
* Capturing the UI can be quite intensive due to all the software and non-hardware-accelerated rendering and decoding.
* Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like [the planner's line lagging and not matching the forward video such as in the case of the forward video not decoding fast enough](#bad-or-too-slow-computer). A generous margin of extra performance is used to ensure that the UI is captured at the same speed as the forward video in case of unexpected system jitters.

Even with these CPU requirements, it was not enough to run the tooling at full speed on the CPU. Some measures have been done to make clip recording possible.

* Relevant processes are speedhack'd with `faketime` to run at 0.3x by default or 0.1x with the `--slow-cpu` flag.
* Capture is done in real time but undercranked to simulate full speed.

## Usage

### Pre-Setup

Ensure your drive's files are fully uploaded on https://my.comma.ai. Click `Files` and select the option to upload all files (`Upload ## files`). Make sure it says "`uploaded`".

* Drive is not yet fully uploaded:
  * <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
* Drive is fully uploaded:
  * <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
* Note: Driver camera is not required to be enabled for recording or uploading for this. It's easier to just hit that "Upload all" button though.
* Note: If you do not upload all the files, the replay will be slow, jerky, and the video quality will be greatly degraded.

### Setup

You can set up your own machine or use [GitHub Codespaces][ghcs]. There are many online server vendors out there but [GitHub Codespaces][ghcs] was chosen for the guide due to its relative ease of use, accessibility, generous free usage, and no-risk of surprise charges.

#### The Way Or The Path

* [🐙 GitHub Codespaces][ghcs] is probably the easiest, cleanest, most hygenic way.
* Machine Setup such as 🪟 Docker for Windows or 🔨 "DIY" is the way to go if you want to use your own computer and it has the power to do it. If you have some pre-existing expertise and resources, this is the way to go.

#### Time Estimates

* Setup
  * 🐙 GitHub Codespaces: 1 minute
  * 🪟/🔨 Machine Setup: 20 minutes
  * For all setup options, if you've already setup some of the resources beforehand such as having a DigitalOcean account, already have Docker or WSL2 running and so on, you will not need to repeat those steps.
* Initial Download/Building
  * 🐙 GitHub Codespaces: If you launch the codespace outside of the US West region, it will take about 6 minutes to setup. Launch the codespace in US West whenever possible as it is pre-built and ready to go immediately.
  * 🪟/🔨 Machine Setup: About 1-5 minutes. This part may be download intensive and depend on your internet connection. This may be cached as well. 
* [Per Clip](#steps): About 6 minutes to capture a 30 second frame with the UI and compress the 30 second clip to 7.8MB.
* [Teardown and Cleanup](#teardown): 1 minute

#### 🐙 GitHub Codespaces

1. Just click this button and launch a codespace in US West region.
 
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://github.com/codespaces/new?hide_repo_select=true&ref=master&repo=532830402&machine=standardLinux32gb&devcontainer_path=.devcontainer%2Fdevcontainer.json&location=WestUs2)

#### 🪟 Docker for Windows

1. Install Ubuntu for WSL2: https://ubuntu.com/tutorials/install-ubuntu-on-wsl2-on-windows-10
2. Install Docker for Windows: https://docs.docker.com/desktop/install/windows-install/
3. Open up the Ubuntu terminal and clone this repository: `git clone https://github.com/nelsonjchen/op-replay-clipper/`
   * For performance reasons, make sure you clone to the Linux filesystem. The default working directory of your home directory in Ubuntu when you open up Ubuntu is adequate.
4. Change folders to `cd op-replay-clipper`
5. Continue to [Steps](#steps).

#### 🔨 DIY (Misc, I already have Docker, I already run Docker on Linux, I have my own setup, Advanced)

If you are knowledgeable about Docker, Linux, Docker-Compose and whatnot, I'm sure you can figure it out. Just clone this repo down and go through the [Steps](#steps).

You may need to `chmod` the `shared` folder to be writable by the internal Docker user of the image. Just do `777`, it's all temporary anyway.



### Steps

1. Find the drive you wish to take a clip from on https://my.comma.ai.
2. Find the starting seconds. The drive's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute. So scrub it, and do a little mental arithmetic to get the starting second. I usually do "60 * segment number + offset" as my calculation.
   * <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
   * In this example, the starting second would be at least 6 * 30 = 180 seconds.
3. Get the route ID from `More Info`. The example below would be `071ba9916a1da2fa|2022-09-04--11-15-52`. Note the omission of the `--1`. That's the segment identifier that is not needed. You can leave it in but it'll have no effect.
   * <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
4. Get a JWT Token from https://jwt.comma.ai. This token will last for a year. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Copy and save the whole thing. This token allows access to routes your Comma connect account has access to. **Keep this token private, do not share it with anyone.**
   * Alternatively, if the route to be rendered is "Public", you can skip this step. Omit the `-j <JWT_TOKEN>` argument from the next step.
5. Construct and run the `docker-compose` command to run with the working directory set to this repository on your machine.
   * Add the `--slow-cpu` flag if you are running on a slow CPU. This will reduce the speed of the rendering to maintain stability.
   * Add the `--experimental` flag if you want to render with the "Experimental mode" UI. At the moment, this will result in a yellow path that changes color according to openpilot's desired longitudinal control. Unfortunately, this current can not be automatically set from replay data.
   1. Fill this template in a text editor, copy it back out once it's filled, and run it.

      ```
      docker-compose run --rm clipper /workspace/clip.sh -j <JWT_TOKEN> "<ROUTE_ID>" -s <STARTING SECONDS>
      ```

      Make sure to put the route ID in quotes. The route id has a `|` character, which can cause havoc in shells.

   2. Run the command. Here's a non-working but illustrative sample command to capture seconds 180 to 210 of `071ba9916a1da2fa|2022-09-04--11-15-52` with a auth/ident token of `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o`.
      * ```
        docker-compose run --rm clipper /workspace/clip.sh -j eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o "071ba9916a1da2fa|2022-09-04--11-15-52" -s 180
        ```

6. Wait 3 minutes (more if it's the first time), and a few files will appear in the `shared` folder.
   * `clip.mkv` - 1GB+ Uncompressed video clip in RGB
   * `clip.mp4` - ~7.8MB file of the clip for uploading with Discord Free. It is encoded for maximum compatibility.
   * The rest are intermediaries such as logs/databases from doing a two-pass encoding to target a 7.8MB file size. They are irrelevant.
   * Here is a picture of what completed run's shell looks like:
     * <img width="1146" alt="Screen Shot 2022-10-11 at 9 51 15 PM" src="https://user-images.githubusercontent.com/5363/195253293-d4fa6065-f387-4c32-8587-6d65dbabafa0.png">

#### Clip File Retrieval

The clip files are stored in the `shared` folder. You can retrieve them by:

##### 🪟 Docker for Windows

1. Run `explorer.exe shared` and copy or do whatever you want with `clip.mp4`

##### 🔨 DIY

1. It's in the `shared` folder and named `clip.mp4`.

##### 🌊 DigitalOcean

1. Run `curl icanhazip.com` and note the IP address
2. Run `docker run -it --rm -p 8080:8080 -v $(pwd)/shared:/public danjellz/http-server`
3. Go to `http://<ip address>:8080/` and download `clip.mp4`.
   * <img width="994" alt="Screen Shot 2022-10-11 at 9 52 53 PM" src="https://user-images.githubusercontent.com/5363/195253322-da9d380e-6bb7-4e38-b2f9-a573974831ab.png">
4. Stop the web server by pressing `Ctrl+C`.

### Multiple Clips

You can absolutely do multiple clips! Just make sure to save the existing `clip.mp4` before kicking off the next run with the `docker-compose` command from [Steps](#steps) as any existing `clip.mp4` in `shared` will be overwritten on each run.

Alternatively, you can also append a `-o` argument to the `docker-compose` command to specify a different output file name. For example:

```
docker-compose run --rm clipper /workspace/clip.sh "071ba9916a1da2fa|2022-09-04--11-15-52" -s 100 -o clip.mp4
```

### Openpilot 0.9.0

* This specific version requires use of the `clipper_pin_090` version as newer UIs read from a variable that is not present. Replace `clipper` in any docker-compose command with `clipper_pin_090`.

### Development

Use the `dev` service in the `docker-compose.yml` file to run the `clip.sh` script in a development environment. This will allow you to make changes to the `clip.sh` script and see the changes reflected in the container.

Additionally, a Devcontainer is provided for VSCode users. This will allow you to run the `clip.sh` script in a development environment with the same dependencies installed as the Docker container.

### Teardown

#### 🪟 Docker for Windows

Docker for Windows has a terrible memory or handle leak issue. Quit it from the black whale icon in system tray. Additionally, you may want to also shutdown Ubuntu by running `wsl --shutdown` from a PowerShell or Command Prompt to regain maximum performance.

While Docker for Windows is running, you may also want to click Clean Up while inside it if you want to regain some disk space.

#### 🐙 GitHub Codespaces

Visit https://github.com/codespaces and delete the codespace. If you forget, it'll be auto-cleaned up in 30 days. 

#### 🔨 DIY

You may want to prune images. Up to you, DIYer!

### Advanced

Run the script with `-h` to get a usage text to help with more options.

Common options that may be of interest:

* You can change the length from 30 seconds to anything with the `-l` argument. e.g. `-l 60` for a minute
  * Be aware that increasing the clip length proportionally doubles the time it takes to record. 60 seconds takes 4 minutes to record. 5 minutes will take 20 minutes! 10, 40!
* You can change the target file size for the clip with `-m` for the size in MB. e.g. `-m 50` to target 50MB
  * For reference, here are some common target file sizes
    * Discord Free w/ Video Preview: 8MB
    * Discord Nitro or Server Boost Level 2 w/ Video Preview: 50MB
      * The comma.ai Discord has been boosted to Level 2, so you can upload 50MB files there.
    * Modern Discord Nitro + Desktop Max: 500MB
* You can change the output clip's name with the `-o` argument. e.g. `-o some_clip.mp4`
  * This is useful if you want to do multiple clips and not overwrite an existing clip in the `shared` folder.
* You can use [ntfy.sh](https://ntfy.sh) to send a notification to yourself to your phone or desktop when rendering a clip is done. Pass in a topic with the `-n` argument and it will be called when the clip has finished rendering. Pick a unique topic as it is like a "password". See the [ntfy.sh](https://ntfy.sh) docs for more info and setup.
* Usage of `--experimental` or "Experimental mode" is not reflected correctly from the route data. Add `--experimental` to turn on that rendering mode with the yellow path in place of the green path. In "Experimental mode", the rendered path will be colored according to longitudinal desires, not latitiude. For example, future braking will be more red.

## Bad or Too Slow Computer

Here's the result you get when you run the clipper on a computer that's too slow or doesn't meet the requirements after all the performance "modifiers". Nothing lines up and it's slow.

From https://discord.com/channels/469524606043160576/1030241716818681897/1030341590201413664

https://user-images.githubusercontent.com/5363/196210351-acc0b235-f87b-4dbc-8b2a-67ca842e52ac.mp4

## Architecture

Just a single shell script that runs an X11 server, and tmux commands to control the replay executable.  There is `faketime` to make it run reliably without modifications to the pre-built openpilot that is in the image. Docker is used to just make it portable, but also easy to cleanup. Docker-Compose is used to make sure  the `/dev/shm` size is correct and to specify the use of already pre-built images for general use or backwards compatibility use.



## Credits

The real MVP is @deanlee for the replay tool in the openpilot project. The level of effort to develop the replay tool is far beyond this script. The script is just a wrapper around the replay tool to make it easy to use for clipping videos.

https://github.com/commaai/openpilot/blame/master/tools/replay/main.cc

[do]: https://www.digitalocean.com/
[op]: https://github.com/commaai/openpilot
[ghcs]: https://github.com/features/codespaces
