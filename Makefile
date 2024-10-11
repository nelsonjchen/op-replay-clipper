.PHONY: build predict predict-360 push

# Unmodified cog
build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build

# Test downloader by itself
downloader:
	python downloader.py shared/data_dir "a2a0ccea32023010|2023-07-27--13-01-19" 5 300 60

# Test downloader by itself for zstd
downloader_zstd:
	python downloader.py shared/data_dir "fe18f736cb0d7813|00000257--fb26599141" 5 573 12

# Test the ffmpeg_clip by itself
ffmpeg_clip:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t driver

ffmpeg_clip_fuw:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t forward_upon_wide

ffmpeg_clip_360:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t 360

ffmpeg_clip_360_fuw:
	python ffmpeg_clip.py "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 -nv -t 360_forward_upon_wide

# These uses a modified cog up one directory.
predict:
	./cog/generate.sh
	cog predict

predict-url-wide:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/a2a0ccea32023010/1690488163535/1690488170140" -i renderType=wide

# This is a private URL
predict-url-wide-new-format:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/1710110122129/1710110166074" -i renderType=wide

# This is a private URL
predict-url-ui-new-format:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000344--8a0cc00ba1/74/126" -i renderType=ui

# This is a private URL
predict-url-ui-chevron-test:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000344--8a0cc00ba1/74/80" -i renderType=ui

# This is a private URL
predict-url-ui-route-url-format:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/000001a9--b4153e8c21/436/450" -i jwtToken="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3MzI0MzAzNzgsIm5iZiI6MTcwMDg5NDM3OCwiaWF0IjoxNzAwODk0Mzc4LCJpZGVudGl0eSI6IjUyNzM1YjJjZWQwOGE4ZDIifQ.GpVidWtjgrlLR-nSBTfFXj3p0htpusc7NrIgM812ZYc" -i renderType=ui

predict-wide:
	./cog/generate.sh
	cog predict -i renderType=wide

predict-360:
	./cog/generate.sh
	cog predict -i renderType=360

predict-fuw:
	./cog/generate.sh
	cog predict -i renderType=forward_upon_wide

predict-360-fuw:
	./cog/generate.sh
	cog predict -i renderType=360_forward_upon_wide

# These require an exported token and route variable to work.
predict-non-public:
	./cog/generate.sh
	cog predict -i route=$(NONPUBLIC_ROUTE) -i jwtToken=$(JWT_TOKEN)

predict-non-public-forward:
	./cog/generate.sh
	cog predict -i route=$(NONPUBLIC_ROUTE) -i jwtToken=$(JWT_TOKEN) -i renderType=forward

predict-zstd:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000257--fb26599141/573/585" -i renderType=ui

predict-bug-report-2024-09-01:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/a4653a9be878a408/00000029--e1c8705a52/132/144" -i renderType=ui

# Push using modified cog
push:
	./cog/generate.sh
	cog push r8.im/nelsonjchen/op-replay-clipper
