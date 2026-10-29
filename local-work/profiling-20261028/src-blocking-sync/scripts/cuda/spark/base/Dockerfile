# Shared base image for the three DGX Spark dev containers (minwoo, user-a, user-b).
# Goal: every container builds and runs Zhouyou Gu's ocudu-gpu-channel skeleton
# (github.com/zhouyou-gu/ocudu-gpu-channel) on GB10 (sm_121).
#
# CUDA is NOT installed in the image. The host's /usr/local/cuda-13.0 (nvcc
# 13.0.88, the same toolkit the WG1 reference used) is bind-mounted read-only by
# create-containers.sh, so all three containers and the host share one exact
# toolkit. The driver comes in through the NVIDIA CDI spec (/var/run/cdi/nvidia.yaml).
#
# Ubuntu 24.04 matches the host (DGX OS 7.5.0) and gives cmake 3.28 / gcc 13,
# which already satisfy the skeleton's CUDA20 + C++20 requirements -- the
# cmake-from-pip and gcc-12 workarounds of the Jetson (22.04) image are not needed.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake ninja-build pkg-config libzmq3-dev \
    git git-lfs ca-certificates curl wget \
    python3 python3-pip python3-venv \
    openssh-server sudo iproute2 iputils-ping \
    tmux vim nano htop less gdb \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash dev && \
    echo "dev ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/dev && \
    chmod 0440 /etc/sudoers.d/dev

# Password and key login. A drop-in, because sshd takes the first occurrence of a
# keyword and Ubuntu includes sshd_config.d/*.conf at the top (user-a's Jetson finding).
# The openssh-server package generates host keys at build time, which would give
# every container the same identity; delete them so CMD's `ssh-keygen -A` makes a
# fresh set per container on first start (kept in the container layer afterwards).
RUN mkdir -p /run/sshd /etc/ssh/sshd_config.d && \
    printf 'PasswordAuthentication yes\nPubkeyAuthentication yes\nPermitRootLogin no\nUsePAM yes\n' \
        > /etc/ssh/sshd_config.d/99-dev.conf && \
    rm -f /etc/ssh/ssh_host_*

# sshd login shells do not inherit image ENV; put the mounted toolkit on PATH here.
RUN ln -s /usr/local/cuda-13.0 /usr/local/cuda && \
    printf 'export PATH=/usr/local/cuda/bin:$PATH\nexport LD_LIBRARY_PATH=/usr/local/cuda/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}\n' \
        > /etc/profile.d/cuda.sh && chmod 644 /etc/profile.d/cuda.sh && \
    printf 'PATH="/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"\nLD_LIBRARY_PATH="/usr/local/cuda/lib64"\n' \
        > /etc/environment
# profile.d covers login shells only; `ssh host cmd` is not one. pam_env reads
# /etc/environment for every sshd session, so nvcc is on PATH either way.
ENV PATH=/usr/local/cuda/bin:${PATH}

# An empty named volume inherits the mount point's ownership on first use.
RUN mkdir -p /workspace && chown dev:dev /workspace
WORKDIR /workspace

EXPOSE 22
# Host keys are generated per container on first start, so the three containers
# do not share an identity. /run/netns is recreated because /run does not persist.
CMD ["/bin/sh", "-c", "ssh-keygen -A >/dev/null && mkdir -p /run/netns && exec /usr/sbin/sshd -D -e"]
