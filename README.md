# 📽 Openpilot Replay Clipper

Capture short 30 seconds clips of Openpilot routes with the Openpilot UI included, with the route and seconds marker branded into the clip. No openpilot development environment setup required. Just Docker-Compose and some computing resources.

https://user-images.githubusercontent.com/5363/188810452-47a479c4-fa9a-4037-9592-c6a47f2e1bb1.mp4

## Requirements

Unfortunately, the requirements are quite high.

You will need a decent computer, either your own or one that is rented for a few minutes such as one on DigitalOcean, to run this tool.

* 8 vCPUs/hyperthreads
* A working Docker-Compose setup. Docker for Windows will work.
* Intel or AMD processor.
  * Emulation of Intel on Apple Silicon with Docker for Mac is too slow to handle the requirements.
* 10 GB of disk space.
* 300MB/s disk speed.
  * Docker for Mac Intel users currently cannot use the clipper due to Docker's serious shared filesystem CPU overhead.
  * Docker for Windows users need to clone the repository to the Linux filesystem to meet the requirement.
* A GPU is **not** needed and is also unused in the tool.

There are other notes too regarding the data you want to render:

* The UI replayed is comma.ai's latest stock UI; routes from forks that differ alot from stock may not render correctly. Your experience may vary.
* The desired route to be rendered must have been able to upload to Comma.ai servers and must be accessible.
* You are advised to upload all files of the route to Comma.ai servers before attempting to render a route.

The heavy CPU requirement is due to a number of factors:

* Reliable H.265 hardware decoding is not always available. The high quality forward video is only captured in H.265 and could only be decoded at 0.7 speed on a Ryzen 2800 and at half speed reliabily for the purposes of capture.
* Reliable OpenGL rendering is not always available. Software OpenGL rendering is used instead to guarantee compatibility.
* Capturing the UI can be quite intensive due to all the software and non-hardware-accelerated rendering and decoding.
* Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like the planner's line lagging and not matching the forward video such as in the case of the forward video not decoding fast enough. A generous margin is used to ensure that the UI is captured at the same speed as the forward video.
* This tool was originally targeting a web service usecase. It may still. CPUs are plentiful, unrestricted, and cheap.

Even with the higher CPU requirements, it is not enough to run the tooling at full speed on the CPU. Some measures have been done to make clip recording possible.

* Relevant processes are speedhack'd with `faketime` to run at half speed.
* Capture is done in real time but undercranked to simulate full speed.

## Usage

### Time Estimates

* Setup
  * Machine Setup: 20 minutes
  * DigitalOcean VPS/Droplet Rental: 5-15 minutes
  * As with any setup option, if you've alreadys setup some of the stuff before such as having a DigitalOcean account or already have WSL2 running and so on, you do not need to repeat those steps.
* Initial Download/Building: About 1-5 minutes. This part may be download intensive and depend on your internet connection.
* Per Clip: About 3 minutes to capture a 30 second frame with the UI and compress the 30 second clip to 7.8MB (right underneath Discord Free's upload limits).
* Teardown and cleanup: 1 minute

### Setup

You can set up your own machine or rent a temporary server. There are many server vendors out there but DigitalOcean was chosen for the guide due to its relative ease of use, accessibility, and affordable pricing.

#### 🪟 Docker for Windows

1. Install Ubuntu for WSL2: https://ubuntu.com/tutorials/install-ubuntu-on-wsl2-on-windows-10
2. Install Docker for Windows: https://docs.docker.com/desktop/install/windows-install/
3. Open up the Ubuntu terminal and clone this repository: `git clone https://github.com/nelsonjchen/op-replay-clipper/`
4. Change folders to `cd op-replay-clipper`
5. Continue to [Steps](#steps).

#### 🌊 DigitalOcean Droplet/VPS

DigitalOcean calls their servers Droplets. The guide will use the term Droplet for simplicity.

Note: Pay attention to [Teardown](#teardown). You need to delete this droplet after you are done or otherwise you may be billed a lot. If at anytime you want to abort, go to [Teardown](#teardown) and destroy the droplet.

1. Sign up for a DigitalOcean account and put in payment information and whatnot.
2. Visit https://marketplace.digitalocean.com/apps/docker and click the `Create Docker Droplet` button on the right.
3. At the droplet creation screen, choose any option with 8 CPUs. Note the prices. **Remember to delete the droplet!**
   * <img width="1273" alt="Screen Shot 2022-10-11 at 9 23 42 PM" src="https://user-images.githubusercontent.com/5363/195249619-53828bb6-6c9d-4169-9757-ac11d41a2495.png">
4. Go through all the options below. Nothing needs to be selected other than the minimum. Any region is fine. Password doesn't matter so anything is fine. No options need to be checked.
5. Once you press create, click on the droplet you created. Wait for it to be created. You may need to refresh the page once in a while. It'll take about a minute or two.
6. Once it is up and running, click on the Console link on the right.
   * <img width="1234" alt="Screen Shot 2022-10-11 at 9 11 42 PM" src="https://user-images.githubusercontent.com/5363/195248204-e20be940-05be-4dcb-b808-172e7f491102.png">
7. You'll get a window popup and a shell like this:
   * <img width="1146" alt="Screen Shot 2022-10-11 at 9 13 28 PM" src="https://user-images.githubusercontent.com/5363/195248431-54841a6f-271b-4835-9d44-a5ce4cfefb1f.png">
8. Run `git clone https://github.com/nelsonjchen/op-replay-clipper/`
9. Run `cd op-replay-clipper`
10. Run `chmod -R 777 shared`
11. Continue to [Steps](#steps).

#### 🔨 DIY (Misc, I already have Docker, I already run Docker on Linux, I have my own setup, Advanced)

If you are knowledgeable about Docker, Linux, Docker-Compose and whatnot, I'm sure you can figure it out. Just clone this repo down and go through the [Steps](#steps).

You may need to `chmod` the `shared` folder to be writable by the internal Docker user of the image. Just do `777`, it's all temporary anyway.

### Steps

1. Find the drive you wish to take a clip from on https://my.comma.ai.
2. Ensure your drive's files are fully uploaded on https://my.comma.ai. Click `Files` and select the option to upload all files (`Upload ## files`).
   * Not yet uploaded:
     * <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
   * Uploaded:
     * <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
   * Note: Driver camera is not required to be enabled for recording or uploading for this. It still might be easier to just hit that button though.
   * Note: If you do not upload the files, the replay will be slow, jerky, and the video quality will be greatly degraded.
3. Find the starting seconds. The drive's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute. So scrub it, and do a little mental arithmetic to get the starting second. I usually do "60 * segment number + offset" as my calculation. Starting seconds must be greater than 60 seconds at the moment.
   * <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
4. Get the route ID from more info. The example below would be `071ba9916a1da2fa|2022-09-04--11-15-52`. Note the omission of the `--1`. That's the segment identifier that is not needed.
   * <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
5. Get a JWT Token from https://jwt.comma.ai. This token will last for a year. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Copy and save the whole thing. This token allows access to routes your Comma connect account has access to. **Keep this token private, do not share it with anyone.**
6. Construct and run the `docker-compose` command to run with the working directory set to this repository on your machine.
   1. Fill this template in a text editor, copy it back out once it's filled, and run it.

      ```
      docker-compose run --rm clipper /workspace/clip.sh -j <JWT_TOKEN> "<ROUTE_ID>" -s <STARTING SECONDS>
      ```

      Make sure to put the route ID in quotes. The route id has a `|` character, which can cause havoc in shells.

   2. Run the command. Here's a non-working but illustrative sample command to capture seconds 180 to 210 of `071ba9916a1da2fa|2022-09-04--11-15-52` with a auth/ident token of `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o`.
      * ```
        docker-compose run --rm clipper /workspace/clip.sh -j eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o "071ba9916a1da2fa|2022-09-04--11-15-52" -s 180
        ```

7. Wait 3 minutes (more if it's the first time), and a few files will appear in the `shared` folder.
   * `clip.mkv` - 1GB+ Uncompressed video clip in RGB
   * `clip.mp4` - ~7.8MB file of the clip for uploading with Discord Free. It is encoded for maximum compatibility.
   * The rest are intermediaries such as logs/databases from doing a two-pass encoding to target a 7.8MB file size. They are irrelevant.
   * Here is a picture of what completed run's shell looks like:
     * <img width="1146" alt="Screen Shot 2022-10-11 at 9 51 15 PM" src="https://user-images.githubusercontent.com/5363/195253293-d4fa6065-f387-4c32-8587-6d65dbabafa0.png">

#### Clip File Retrieval

The clip files are stored in the `shared` folder. You can retrieve them by:

##### 🪟 Docker for Windows

1. Run `explorer.exe shared` and copy or do whatever you want with `clip.mp4`

##### 🌊 DigitalOcean

1. Run `curl icanhazip.com` and note the IP address
2. Run `docker run -it --rm -p 8080:8080 -v $(pwd)/shared:/public danjellz/http-server`
3. Go to `http://<ip address>:8080/` and download `clip.mp4`.
   * <img width="994" alt="Screen Shot 2022-10-11 at 9 52 53 PM" src="https://user-images.githubusercontent.com/5363/195253322-da9d380e-6bb7-4e38-b2f9-a573974831ab.png">

##### 🔨 DIY

1. It's in the `shared` folder and named `clip.mp4`.

### Multiple Clips

You can absolutely do multiple clips! Just make sure to save the existing `clip.mp4` before kicking off the next run with the `docker-compose` command from Steps as the existing `clip.mp4` in `shared` will be overwritten on each run.

### Teardown

#### 🪟 Docker for Windows

Docker for Windows has a terrible memory leak. Quit it from the system tray. Additionally, you may want to also shutdown Ubuntu by running `wsl --shutdown` from a PowerShell or Command Prompt to regain maximum performance.

While Docker for Windows is running, you may also want to click Clean Up while inside it if you want to regain some disk space.

#### 🌊 DigitalOcean

This is extremely important if you don't want to be overcharged.

1. Go back to the droplet view screen in DigitalOcean
   * <img width="1243" alt="Screen Shot 2022-10-11 at 9 18 59 PM" src="https://user-images.githubusercontent.com/5363/195249068-7e748e7a-539e-43c3-97bd-fc9508bd91b7.png">
2. Click on Destroy Droplet and follow the dialog to destroy the droplet.
   * <img width="1235" alt="Screen Shot 2022-10-11 at 9 19 38 PM" src="https://user-images.githubusercontent.com/5363/195249143-59d40d50-b094-49b9-9d77-cd8febdd3027.png">
3. Hopefuly you don't have any OP clipper related droplets running. If so, great!
   * <img width="1265" alt="Screen Shot 2022-10-11 at 9 20 45 PM" src="https://user-images.githubusercontent.com/5363/195249252-a28f2265-e99c-4e2a-b67f-f3cdd0cb1f87.png">

#### 🔨 DIY

You may want to prune images. Up to you, DIYer!

### Advanced

Run the script with `-h` to get a usage text to help with more options.

Common options that may be of interest:

* You can change the length from 30 seconds to anything with the `-l` argument. e.g. `-l 60` for a minute
  * Be aware that increasing the clip length proportionally doubles the time it takes to record. 60 seconds takes 2 minutes to record. 5 minutes will take 10 minutes! 10, 20!
* You can change the target file size for the clip with `-m` for the size in MB. e.g. `-m 50` to target 50MB
  * For reference, here are some common target file sizes
    * Discord Free w/ Video Preview: 8MB
    * Discord Nitro w/ Video Preview: 50MB
    * Modern Discord Nitro + Desktop Max: 500MB

## Architecture

Just a single shell script that runs an X11 server, and tmux commands to control the replay executable.  There is `faketime` to make it run reliably without modifications to the pre-built openpilot that is in the image. Docker is used to just make it portable, but also easy to cleanup. Docker-Compose is used to make sure  the `/dev/shm` size is correct.

## Future

Since this is all CPU based, requires no acceleration, and is clearly shoved into Docker, maybe it's possible to make a web service.
