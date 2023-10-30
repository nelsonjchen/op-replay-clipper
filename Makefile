.PHONY: build predict predict-360 push

# Unmodified cog
build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build

# Test downloader by itself
downloader:
	python downloader.py shared/data_dir "a2a0ccea32023010|2023-07-27--13-01-19" 5 300 60

# Test the ffmpeg_clip by itself
ffmpeg_clip:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t driver

ffmpeg_clip_360:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t 360

# These uses a modified cog up one directory.
predict:
	./cog/generate.sh
	../cog/cog predict

predict-url-wide:
	./cog/generate.sh
	../cog/cog predict -i route="https://connect.comma.ai/a2a0ccea32023010/1690488163535/1690488170140" -i renderType=wide

predict-wide:
	./cog/generate.sh
	../cog/cog predict -i renderType=wide

predict-360:
	./cog/generate.sh
	../cog/cog predict -i renderType=360

# Push using modified cog
push:
	./cog/generate.sh
	../cog/cog push r8.im/nelsonjchen/op-replay-clipper