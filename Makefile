.PHONY: build

build: cog/cog.template.yaml cog/generate.sh
	./cog/generate.sh
	cog build
