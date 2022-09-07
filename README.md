# Openpilot Web Replay Tool

Capture short 30 second route clips with the Openpilot UI included, and the route, seconds marker branded into it. 

https://user-images.githubusercontent.com/5363/188810452-47a479c4-fa9a-4037-9592-c6a47f2e1bb1.mp4

🚧 This is all very WIP at the moment and definitely rough!

## Requirements

Unfortunately, the requirements are quite high.

* 8 cores
* A working Docker-Compose setup. Docker for Windows/Mac will work. 
* x86_64. Unfortunately, the `openpilot-prebuilt` image this setup is based on only comes in x86_64 architecture. No M-series Macs will work.
* 6 GB of disk space.
* 300MB/s disk speed.
* Your device must be able to upload to Comma.ai servers. Roadmap for usage of a retropilot or alternative cloud backend is unclear or unknown.
* A GPU is **not** needed.

The CPU requirement is due to a number of factors:

* Reliable H.265 hardware decoding is hard to find. The captured H.265 forward video could only be decoded at 0.7 speed on a Ryzen 2800 and half speed reliabily for the purposes of capture.
* Reliable OpenGL is not always possible. Software OpenGL rendering is used instead.
* Capturing the UI isn't free and can be quite intensive.
* Capturing the UI must be done with everything not mismatching by speed. Otherwise, you get weird rendering issues like the planner's line lagging and not matching the video such as in the case of the video not decoding fast enough as in the case of H.265.

Some things have been done to make this do-able.

* Relevant processes are speedhack'd with `faketime` to run at half speed.
* Capture is done in real time but undercranked to simulate full speed.

## Usage

### Time Estimates

* Initial Download/Building: ? , will feel quick depending on internet connection.
* Per Clip: About 3 minutes to capture a 30 second frame with the UI and compress the 30 second clip to 7.8MB (right underneath Discord Free's upload limits). Much of the time is spent waiting or for "safety"/fidelity reasons.

### Steps

1. Get a JWT Token from https://jwt.comma.ai. This token will last for a year. It'll be a long string that starts a bit like `eyJ0eXAiOiJKV1QiLCJhb...`. Copy and save the whole thing.
2. Find the drive you wish to take a clip from on https://my.comma.ai.
3. Ensure your drive's files are fully uploaded on https://my.comma.ai. Click `Files` and select the option to upload all files (`Upload ## files`). 
  * Not yet uploaded: 
    <img width="347" alt="Screen Shot 2022-09-06 at 11 55 39 PM" src="https://user-images.githubusercontent.com/5363/188815682-6694c2f8-1d77-468e-9152-75a709477c9a.png">
  * Uploaded: 
    <img width="316" alt="Screen Shot 2022-09-07 at 12 27 26 AM" src="https://user-images.githubusercontent.com/5363/188816174-51045496-4614-4050-b911-c4abb987c5fe.png">
4. Find the starting seconds. The drive's timeline will have a widget below your cursor that's "segment number, local time". Segments are made every minute. So scrub it, and do a little mental arithmetic to get the starting second. Starting seconds must be greater than 30 seconds at the moment.
  * <img width="282" alt="Screen Shot 2022-09-06 at 11 56 10 PM" src="https://user-images.githubusercontent.com/5363/188816664-6e1cd8e3-a363-4653-85da-a03332e39c13.png">
5. Get the route ID from more info. The example below would be `071ba9916a1da2fa|2022-09-04--11-15-52`. Note the omission of the `--1`. That's the segment identifier that is not needed.
  * <img width="336" alt="image" src="https://user-images.githubusercontent.com/5363/188817040-5341e1af-2176-47ad-87f3-ba0a3d88a32a.png">
6. Construct the `docker-compose` command to run with the working directory set to this repository on your machine.
  * Fill this template in and run it.
    
    ```
    docker-compose run --rm dev /workspace/clip.sh <STARTING SECONDS> "<ROUTE_ID>" <JWT_TOKEN>
    ```
    
    Make sure to put the route ID in quotes. The route id has a `|` character, which can cause havoc in shells. 
    
7. Run the command. Here's a non-working but illustrative sample command.
  * `docker-compose run --rm dev /workspace/clip.sh 180 "071ba9916a1da2fa|2022-09-04--11-15-52" eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6MTIzNDU2Nzg5LCJuYW1lIjoiSm9zZXBoIn0.OpOSSw7e485LOP5PrzScxHb7SR6sAOMRckfFwi4rp7o`
8. Wait a few minutes, and a few files will appear in the `shared` folder.
  * `clip.mkv` - 1GB+ Uncompressed video clip
  * `clip.mp4` - 7.8MB file of the clip for uploading with Discord Free.
  * The rest are intermediaries such as logs/databases from doing a two-pass encoding to target a 7.8MB file size.
9. Enjoy!
    
