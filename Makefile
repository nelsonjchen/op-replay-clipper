.PHONY: build predict

# Unmodified cog
build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build

# Uses a modified cog up one directory.
predict:
	./cog/generate.sh
	../cog/cog predict

# Push using modified cog
push:
	./cog/generate.sh
	../cog/cog push r8.im/nelsonjchen/op-replay-clipper