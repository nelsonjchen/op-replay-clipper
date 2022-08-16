# Openpilot Web Replay Tool

Replay openpilot routes and share it as a video service.

## Random Notes

```sh
Xtigervnc :0 -geometry 2180x1080 -SecurityTypes None
```

```sh
DISPLAY=:0 ./selfdrive/ui/ui
```

720p resolution

```sh
ffmpeg -framerate 10 -video_size 1920x1080 -f x11grab  -i :0.0 -vcodec libx264 -preset medium -pix_fmt yuv420p  -r 20 -filter:v "setpts=0.5*PTS,scale=1280:720" -y /shared/video.mkv
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
