.PHONY: build cog-predict cog-predict-360 cog-push cog-push-beta clip ui-exact-smoke local-venv test-local replicate-run video-renderer video-renderer-fuw video-renderer-360 video-renderer-360-fuw

REPLICATE_URL ?= https://connect.comma.ai/a2a0ccea32023010/1690488131496/1690488136496
REPLICATE_RENDER ?= forward
REPLICATE_OUTPUT ?= ./shared/replicate-run.mp4

# Generate fresh Cog artifacts from uv metadata and build the image.
build: cog/cog.template.yaml cog/render_artifacts.sh
	./cog/render_artifacts.sh
	cog build

# Helper targets for manual downloader checks.
downloader:
	uv run python core/route_downloader.py shared/data_dir "a2a0ccea32023010|2023-07-27--13-01-19" 5 300 60

downloader_zstd:
	uv run python core/route_downloader.py shared/data_dir "fe18f736cb0d7813|00000257--fb26599141" 5 573 12

# Helper targets for exercising ffmpeg-only renderers directly.
video-renderer:
	uv run python renderers/video_renderer.py --render-type driver "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

video-renderer-fuw:
	uv run python renderers/video_renderer.py --render-type forward_upon_wide "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

video-renderer-360:
	uv run python renderers/video_renderer.py --render-type 360 "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

video-renderer-360-fuw:
	uv run python renderers/video_renderer.py --render-type 360_forward_upon_wide "a2a0ccea32023010|2023-07-27--13-01-19" 242 30 --accel nvidia

cog-predict:
	./cog/render_artifacts.sh
	cog predict

cog-predict-url-wide:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/a2a0ccea32023010/1690488163535/1690488170140" -i renderType=wide

# This is a private URL
cog-predict-url-wide-new-format:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/1710110122129/1710110166074" -i renderType=wide

# This is a private URL
cog-predict-url-ui-new-format:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/1712798688347/1712798721553" -i renderType=ui

# This is a private URL
cog-predict-url-ui-route-url-format:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/000001a9--b4153e8c21/436/450" -i jwtToken="xxx" -i renderType=ui

cog-predict-wide:
	./cog/render_artifacts.sh
	cog predict -i renderType=wide

cog-predict-360:
	./cog/render_artifacts.sh
	cog predict -i renderType=360

cog-predict-fuw:
	./cog/render_artifacts.sh
	cog predict -i renderType=forward_upon_wide

cog-predict-360-fuw:
	./cog/render_artifacts.sh
	cog predict -i renderType=360_forward_upon_wide

# These require an exported token and route variable to work.
cog-predict-non-public:
	./cog/render_artifacts.sh
	cog predict -i route=$(NONPUBLIC_ROUTE) -i jwtToken=$(JWT_TOKEN)

cog-predict-non-public-forward:
	./cog/render_artifacts.sh
	cog predict -i route=$(NONPUBLIC_ROUTE) -i jwtToken=$(JWT_TOKEN) -i renderType=forward

cog-predict-zstd:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000257--fb26599141/573/585" -i renderType=ui

cog-predict-bug-report-2024-09-01:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/a4653a9be878a408/00000029--e1c8705a52/132/144" -i renderType=ui

cog-predict-bug-all-number:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000497--5809888120/1611/1635" -i renderType=ui

cog-predict-bug-all-number-360:
	./cog/render_artifacts.sh
	cog predict -i route="https://connect.comma.ai/fe18f736cb0d7813/00000497--5809888120/1611/1635" -i renderType=360

cog-push:
	./cog/render_artifacts.sh
	cog push r8.im/nelsonjchen/op-replay-clipper

cog-push-beta:
	./cog/render_artifacts.sh
	cog push r8.im/nelsonjchen/op-replay-clipper-beta

# Create or refresh the local uv environment.
local-venv:
	uv sync

# Example:
# make clip RENDER=ui ROUTE="https://connect.comma.ai/<dongle>/<route>/<start>/<end>"
clip:
	uv run python clip.py "$(RENDER)" "$(ROUTE)"

# Render a short exact-sync BIG UI clip locally for quick sanity checks.
ui-exact-smoke:
	uv run python clip.py ui "a2a0ccea32023010|2023-07-27--13-01-19" -s 50 -l 10 --smear-seconds 0 --output ./shared/local-ui-exact-smoke.mp4

# Run the local pytest suite through uv.
test-local:
	uv run pytest

# Example:
# make replicate-run REPLICATE_RENDER=ui REPLICATE_OUTPUT=./shared/replicate-run-ui.mp4
replicate-run:
	uv run python replicate_run.py --url "$(REPLICATE_URL)" --render-type "$(REPLICATE_RENDER)" --output "$(REPLICATE_OUTPUT)"
