# Openpilot Web Replay Tool

Replay openpilot routes and share it as a video service.

https://user-images.githubusercontent.com/5363/188427652-adbe2ca5-c3ea-429e-bbd7-556aed2a6254.mp4


# Usage

Go to https://op-web-replay.mindflakes.com/

Fill out the form with:

- The route you want to replay
- Seconds to start the route at
- JWT key for if the route is non-public

POST and get to a page that polls for an output. Should be done in about two minutes.

# Architecture

1. Google Cloud Run Web Server starts up
1. Check if route is accessible with JWT key if provided
3. Check if route has rlogs and has fcamera videos.
4. If it does, insert Google Cloud Run job and redirect to page to poll for results.
5. Run program to start X Server, Start Replay at seconds to start at (but immediately stop), and start the UI
6. Restart the replay at seconds at.
6. Wait a few seconds for the UI to catch up on downloads.
7. Start Recording with ffmpeg
9. Kill all processes when done
10. Upload to Cloud Storage a manifest json and the video file
11. Polling Page sees new file at Cloud Storage and presents it for downloading.
12. Cloud Storage configured auto-cleans up files after 3 days.

## Random Notes

```sh
Xtigervnc :0 -geometry 2180x1080 -SecurityTypes None
```

```sh
DISPLAY=:0 ./selfdrive/ui/ui
```

720p resolution

```sh
ffmpeg -framerate 10 -video_size 1920x1080 -f x11grab  -i :0.0 -vcodec libx264 -preset medium -pix_fmt yuv420p  -r 20 -filter:v "setpts=0.5*PTS,scale=1280:720" -y /shared/video.mp4
```

1080p resolution

```sh
ffmpeg -framerate 10 -video_size 1920x1080 -f x11grab  -i :0.0 -vcodec libx264 -preset medium -pix_fmt yuv420p  -r 20 -filter:v "setpts=0.5*PTS,scale=1920:1080" -y /shared/video.mp4
```

```sh
faketime -m -f "+0 x0.5" ./selfdrive/ui/ui
```

```sh
faketime -m -f "+0 x0.5" ./tools/replay/replay --demo
```
