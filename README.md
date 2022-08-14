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

```sh
TRACE_FILE=/shared/dump.trace LD_PRELOAD="/home/batman/libfaketime/src/libfaketimeMT.so.1 /home/batman/apitrace/build/" ./selfdrive/ui/ui
```

```sh
apitrace dump-images -o - /shared/dump.trace | ffmpeg -r 20 -f image2pipe -vcodec ppm -i pipe: -vcodec mpeg4 -y /shared/dump.mp4
```

```sh
LD_PRELOAD="/home/batman/libfaketime/src/libfaketimeMT.so.1" FAKETIME="+0 x0.5" ./selfdrive/ui/ui
```

```sh
LD_PRELOAD="/home/batman/libfaketime/src/libfaketimeMT.so.1" FAKETIME="+0 x0.5" ./tools/replay/replay --demo
```