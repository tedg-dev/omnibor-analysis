FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC

# ============================================================
# Base build tools and libraries
# ============================================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    clang \
    make \
    cmake \
    ninja-build \
    autoconf \
    automake \
    libtool \
    pkg-config \
    git \
    wget \
    curl \
    ca-certificates \
    python3 \
    python3-pip \
    strace \
    # Utilities needed by bomsh scripts
    xxd \
    binutils \
    elfutils \
    file \
    # Common C/C++ library dev packages for target repos
    libssl-dev \
    zlib1g-dev \
    libpcre2-dev \
    libnghttp2-dev \
    libssh2-1-dev \
    libbrotli-dev \
    libzstd-dev \
    libc-ares-dev \
    libidn2-dev \
    # FFmpeg dependencies
    nasm \
    yasm \
    libx264-dev \
    libx265-dev \
    libvpx-dev \
    libopus-dev \
    libmp3lame-dev \
    libfdk-aac-dev \
    libfreetype-dev \
    libfontconfig1-dev \
    libfribidi-dev \
    libass-dev \
    && rm -rf /var/lib/apt/lists/*

# ============================================================
# Install Syft (manifest-based SBOM generation)
# ============================================================
RUN curl -sSfL https://raw.githubusercontent.com/anchore/syft/main/install.sh | sh -s -- -b /usr/local/bin

# ============================================================
# Build bomtrace3 from omnibor/bomsh
# ============================================================
WORKDIR /opt
RUN git clone https://github.com/omnibor/bomsh.git

# Build bomtrace2
WORKDIR /opt/bomsh-build
RUN git clone https://github.com/strace/strace.git strace2 && \
    cd strace2 && \
    patch -p1 < /opt/bomsh/.devcontainer/patches/bomtrace2.patch && \
    ./bootstrap && \
    ./configure --disable-mpers && \
    make -j$(nproc) && \
    cp src/strace /opt/bomsh/bin/bomtrace2

# Build bomtrace3
RUN git clone https://github.com/strace/strace.git strace3 && \
    cd strace3 && \
    patch -p1 < /opt/bomsh/.devcontainer/patches/bomtrace3.patch && \
    cp /opt/bomsh/.devcontainer/src/*.[hc] src/ && \
    ./bootstrap && \
    ./configure --disable-mpers && \
    make -j$(nproc) && \
    cp src/strace /opt/bomsh/bin/bomtrace3

# Clean up build artifacts
RUN rm -rf /opt/bomsh-build

# Add bomsh bin and scripts to PATH
ENV PATH="/opt/bomsh/bin:/opt/bomsh/scripts:${PATH}"

# Copy bomsh_hook2.py to /tmp (required by bomtrace2)
RUN cp /opt/bomsh/scripts/bomsh_hook2.py /tmp/

# ============================================================
# Working directory — repos are mounted here
# ============================================================
WORKDIR /workspace

CMD ["/bin/bash"]
