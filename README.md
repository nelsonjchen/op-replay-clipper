# Openpilot Web Replay Tool

Replay openpilot routes and share it as a video service.

## Random Notes

```sh
Xtigervnc :0 -geometry 2180x1080 -SecurityTypes None
```

```sh
DISPLAY=:0 ./selfdrive/ui/ui
```

```sh
ffmpeg -video_size 2180x1080 -f x11grab -framerate 20 -i :0.0 -vf scale=1090x590 -preset ultrafast out.mp4
```