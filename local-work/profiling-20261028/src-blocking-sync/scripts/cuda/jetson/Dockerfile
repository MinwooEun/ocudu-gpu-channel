# Jetson AGX Orin image for the J track (JETSON_MILESTONES.md).
#
# Layered on user-a's shared base image (~user-a/jetson-dev-image/Dockerfile on
# the Jetson host: l4t-jetpack r36.4.0, gcc-12 default, pip cmake>=3.28, `dev`
# user, password sshd). The base is not edited; this only adds what the OCUDU
# CUDA / Open5GS / srsRAN_4G stack needs, so a container rebuild keeps them.
#
# Package list = the workstation's debian overlay
# (scripts/native/locks/ubuntu-noble-amd64.debs.lock.tsv) renamed to jammy arm64
# (no t64 suffixes), plus iproute2/iptables for netns and the UPF.
# Every name was checked with apt-cache policy in the Jetson container, 2026-09-24.
ARG BASE_IMAGE=ocudu-jetson-dev:latest
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    ninja-build iproute2 iputils-ping iptables python3-click \
    autoconf automake libtool bison flex m4 meson gettext \
    libfftw3-dev libmbedtls-dev libyaml-cpp-dev libsctp-dev \
    libboost-dev libboost-program-options-dev libgtest-dev googletest \
    libconfig++-dev libzmq3-dev \
    libgnutls28-dev libgcrypt20-dev libssl-dev libidn-dev libtalloc-dev libyaml-dev \
    libmicrohttpd-dev libcurl4-gnutls-dev libnghttp2-dev libtins-dev \
    libmongoc-dev libbson-dev libmongocrypt-dev libsasl2-dev \
    libpcap-dev libnl-3-dev libnl-route-3-dev libdbus-1-dev \
    libsnappy-dev libzstd-dev zlib1g-dev libsimde-dev libutf8proc-dev \
    libp11-kit-dev libtasn1-6-dev nettle-dev libgmp-dev libunbound-dev \
    libibverbs-dev libintelrdfpmath-dev \
    python3-pymongo python3-yaml \
    && rm -rf /var/lib/apt/lists/*

# `ip netns add` bind-mounts under /run/netns. The runners expect the directory;
# recreate it on every start because /run does not survive a container restart.
CMD ["/bin/sh", "-c", "mkdir -p /run/netns && exec /usr/sbin/sshd -D -e"]
