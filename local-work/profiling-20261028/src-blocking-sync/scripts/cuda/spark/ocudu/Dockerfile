# minwoo's container: the shared base plus everything the OCUDU CUDA gNB,
# Open5GS and srsRAN_4G need. The package list is the workstation's debian
# overlay (scripts/native/locks/ubuntu-noble-amd64.debs.lock.tsv) verbatim --
# the host and this image are Ubuntu 24.04 (noble), so no renaming is needed.
# One exception: libfftw3-quad3 (quad precision) is built for x86 only and has
# no arm64 package; OCUDU uses single-precision FFTW, so it is left out.
ARG BASE_IMAGE=ocudu-spark-base:1
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf \
    automake \
    autotools-dev \
    bison \
    flex \
    gettext \
    googletest \
    libboost1.83-dev \
    libboost-program-options1.83.0 \
    libboost-program-options1.83-dev \
    libboost-program-options-dev \
    libbson-1.0-0t64 \
    libbson-dev \
    libconfig9 \
    libconfig++9v5 \
    libconfig++-dev \
    libconfig-dev \
    libcurl3t64-gnutls \
    libcurl4-gnutls-dev \
    libdbus-1-dev \
    libevent-2.1-7t64 \
    libfftw3-bin \
    libfftw3-dev \
    libfftw3-double3 \
    libfftw3-long3 \
    libfftw3-single3 \
    libgcrypt20-dev \
    libgmp10 \
    libgmp-dev \
    libgmpxx4ldbl \
    libgnutls28-dev \
    libgnutls30t64 \
    libgnutls-dane0t64 \
    libgnutls-openssl27t64 \
    libgpg-error-dev \
    libgtest-dev \
    libhogweed6t64 \
    libibverbs-dev \
    libidn12 \
    libidn2-dev \
    libidn-dev \
    libintelrdfpmath-dev \
    libmbedcrypto7t64 \
    libmbedtls14t64 \
    libmbedtls-dev \
    libmbedx509-1t64 \
    libmicrohttpd12t64 \
    libmicrohttpd-dev \
    libmongoc-1.0-0t64 \
    libmongoc-dev \
    libmongocrypt0 \
    libmongocrypt-dev \
    libnettle8t64 \
    libnghttp2-14 \
    libnghttp2-dev \
    libnl-3-dev \
    libnl-route-3-dev \
    libp11-kit-dev \
    libpcap0.8-dev \
    libpcap-dev \
    libsasl2-dev \
    libsctp1 \
    libsctp-dev \
    libsimde-dev \
    libsnappy1v5 \
    libsnappy-dev \
    libssl3t64 \
    libssl-dev \
    libtalloc2 \
    libtalloc-dev \
    libtasn1-6-dev \
    libtins4.5 \
    libtins-dev \
    libtool \
    libunbound8 \
    libutf8proc3 \
    libutf8proc-dev \
    libyaml-0-2 \
    libyaml-cpp0.8 \
    libyaml-cpp-dev \
    libyaml-dev \
    libzmq3-dev \
    libzmq5 \
    libzstd-dev \
    m4 \
    meson \
    nettle-dev \
    ninja-build \
    python3-bson \
    python3-gridfs \
    python3-pymongo \
    zlib1g \
    zlib1g-dev \
    iptables python3-click \
    && rm -rf /var/lib/apt/lists/*
