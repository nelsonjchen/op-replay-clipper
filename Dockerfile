FROM ghcr.io/commaai/openpilot-prebuilt:latest

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    gdb \
    htop \
    vim \
    tigervnc-standalone-server \
    apitrace-tracers \
    apitrace \
    ffmpeg \
    mesa-utils

# Build libfaketime

WORKDIR /home/batman

RUN git clone --recurse-submodules https://github.com/wolfcw/libfaketime

WORKDIR /home/batman/libfaketime

RUN make

# Build apitrace

WORKDIR /home/batman

RUN git clone --recurse-submodules https://github.com/apitrace/apitrace

WORKDIR /home/batman/apitrace

RUN cmake -S. -Bbuild -DCMAKE_BUILD_TYPE=RelWithDebInfo -DENABLE_GUI=FALSE && make -j 16 -C build

WORKDIR /home/batman
