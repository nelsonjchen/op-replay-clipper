.PHONY: build predict predict-360 push

# Unmodified cog
build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build

# These uses a modified cog up one directory.
predict:
	./cog/generate.sh
	../cog/cog predict

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