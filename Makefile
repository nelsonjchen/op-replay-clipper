.PHONY: build predict predict-360 push local-clip local-venv test-local

build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build

downloader:
	uv run python downloader.py shared/data_dir "a2a0ccea32023010|2023-07-27--13-01-19" 5 300 60

downloader_zstd:
	uv run python downloader.py shared/data_dir "fe18f736cb0d7813|00000257--fb26599141" 5 573 12

ffmpeg_clip:
	uv run python ffmpeg_clip.py --render-type driver "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

ffmpeg_clip_fuw:
	uv run python ffmpeg_clip.py --render-type forward_upon_wide "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

ffmpeg_clip_360:
	uv run python ffmpeg_clip.py --render-type 360 "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

ffmpeg_clip_360_fuw:
	uv run python ffmpeg_clip.py --render-type 360_forward_upon_wide "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

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
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/1712798688347/1712798721553" -i renderType=ui

# This is a private URL
predict-url-ui-route-url-format:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/000001a9--b4153e8c21/436/450" -i jwtToken="xxx" -i renderType=ui

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

predict-bug-all-number:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000497--5809888120/1611/1635" -i renderType=ui

predict-bug-all-number-360:
	./cog/generate.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000497--5809888120/1611/1635" -i renderType=360

push:
	./cog/generate.sh
	cog push r8.im/nelsonjchen/op-replay-clipper

local-venv:
	uv sync

local-clip:
	uv run python local_clip.py "$(RENDER)" "$(ROUTE)"

test-local:
	uv run pytest
