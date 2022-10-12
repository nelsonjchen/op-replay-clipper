# Openpilot Replay Clipper

Capture short 30 second route clips with the Openpilot UI included, and the route, seconds marker branded into it. No openpilot development environment setup required. Just Docker-Compose and some computing resources.

https://user-images.githubusercontent.com/5363/188810452-47a479c4-fa9a-4037-9592-c6a47f2e1bb1.mp4

🚧 This is all very WIP at the moment and definitely rough!

## Requirements

Unfortunately, the requirements are quite high.

* 8 vCPUs/hyperthreads
* A working Docker-Compose setup. Docker for Windows/Mac will work.
* x86_64. Unfortunately, the `openpilot-prebuilt` image this setup is based on only comes in x86_64 architecture. The x86 emulation with Apple Silicon Macs is simply too slow by 10x and thus Apple Silicon Macs currently will not work. Intel Macs also may be too slow from simply too much overhead.
  * Users in this case are advised to use rental computing resources like a temporary VPS.
* 6 GB of disk space.
* 300MB/s disk speed.
* Your comma device must be able to upload to Comma.ai servers. Roadmap for usage of a retropilot or alternative cloud backend is unclear or unknown.
* A GPU is **not** needed and also unused here.
* The UI replayed is comma.ai's latest stock UI; forks that differ alot are very much YMMV.

The CPU requirement is due to a number of factors:

* Reliable/speedy H.265 hardware decoding is hard to find. The forward video is only captured in H.265 and could only be decoded at 0.7 speed on a Ryzen 2800 and half speed reliabily for the purposes of capture.
* Reliable OpenGL is not always possible. Software OpenGL rendering is used instead.
* Capturing the UI isn't free and can be quite intensive due to all the Software/non-accelerated rendering and decoding.
* Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like the planner's line lagging and not matching the video such as in the case of the video not decoding fast enough as in the case of H.265.
* This was originally targeting a web service usecase. It may still. CPUs are plentiful.

Some things have been done to make this do-able.

* Relevant processes are speedhack'd with `faketime` to run at half speed.
* Capture is done in real time but undercranked to simulate full speed.

## Usage

### Time Estimates

* Initial Download/Building: About 3 or more minutes. Also dependent on downloading a 1GB+ docker image base and the stuff to build atop of it.
* Per Clip: About 3 minutes to capture a 30 second frame with the UI and compress the 30 second clip to 7.8MB (right underneath Discord Free's upload limits). Much of the time is spent waiting or for "safety"/fidelity reasons.

### Steps

1. Find the drive you wish to take a clip from on https://my.comma.ai.
2. Ensure your drive's files are fully uploaded on https://my.comma.ai. Click `Files` and select the option to upload all files (`Upload ## files`).
   * Not yet uploaded:
     * <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
   * Uploaded:
     * <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
   * Note: Driver camera is not required to be enabled for recording or uploading for this. It still might be easier to just hit that button though.
   * Note: If you do not upload the files, the replay will be slow, jerky, and the video quality will be greatly degraded.
3. Find the starting seconds. The drive's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute. So scrub it, and do a little mental arithmetic to get the starting second. Starting seconds must be greater than 30 seconds at the moment.
   * <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
4. Get the route ID from more info. The example below would be `071ba9916a1da2fa|2022-09-04--11-15-52`. Note the omission of the `--1`. That's the segment identifier that is not needed.
   * <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
5. Get a JWT Token from https://jwt.comma.ai. This token will last for a year. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Copy and save the whole thing.   
6. Construct and run the `docker-compose` command to run with the working directory set to this repository on your machine.
   * Docker-Compose
      1. Fill this template in and run it.

         ```
         docker-compose run --rm clipper /workspace/clip.sh -s <STARTING SECONDS> "<ROUTE_ID>" -j <JWT_TOKEN>
         ```

         Make sure to put the route ID in quotes. The route id has a `|` character, which can cause havoc in shells.

      2. Run the command. Here's a non-working but illustrative sample command to capture seconds 180 to 210 of `071ba9916a1da2fa|2022-09-04--11-15-52` with a auth/ident token of `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o` with the non-prebuilt configuration.
         * `docker-compose run --rm clipper /workspace/clip.sh -s 180 "071ba9916a1da2fa|2022-09-04--11-15-52" -j eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o`

8. Wait 3 minutes (more if it's the first time), and a few files will appear in the `shared` folder.
   * `clip.mkv` - 1GB+ Uncompressed video clip
   * `clip.mp4` - 7.8MB file of the clip for uploading with Discord Free.
   * The rest are intermediaries such as logs/databases from doing a two-pass encoding to target a 7.8MB file size.
9. Enjoy!

## Architecture

Just a single shell script that runs an X11 server, and tmux commands to control the replay executable.  There's some faketime to make it run reliably without extensive or any modifications to the pre-built openpilot that is used. Docker is used to just make it portable, but also easy to cleanup. Docker Compose is used to make sure  the `/dev/shm` size is correct.

## Future

Since this is all CPU based, requires no acceleration, and is clearly shoved into Docker, maybe it's possible to make a web service.
