# The game-free checks (tests/run_all.py) on Linux, with every tool they look for: gcc, g++, clang, glslang, spirv-val,
# the Vulkan and SPIR-V headers at mise.toml's [tasks.deps] commits, and requirements.txt's Python packages.
#
#   docker build -t longshot-tests -f scripts/docker/tests.Dockerfile .
#   bash scripts/docker/run_all.sh [run_all.py options]
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive PIP_BREAK_SYSTEM_PACKAGES=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ clang lld make git ca-certificates curl xz-utils pkg-config \
        python3 python3-pip glslang-tools spirv-tools libzstd-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/req/requirements.txt
COPY nx2/prompt_requirements.txt /tmp/req/nx2/prompt_requirements.txt
RUN python3 -m pip install --no-cache-dir -r /tmp/req/requirements.txt pillow==13.0.0
RUN mkdir -p /deps && cd /deps \
    && curl -fsSL --retry 5 https://github.com/KhronosGroup/Vulkan-Headers/archive/74d8a6cb930c68ef617b202c3ff3c59d919e086b.tar.gz | tar -xz \
    && mv Vulkan-Headers-* vulkan-headers \
    && curl -fsSL --retry 5 https://github.com/KhronosGroup/SPIRV-Headers/archive/04f10f650d514df88b76d25e83db360142c7b174.tar.gz | tar -xz \
    && mv SPIRV-Headers-* spirv-headers
ENV LONGSHOT_VULKAN_HEADERS=/deps/vulkan-headers/include LONGSHOT_SPIRV_HEADERS=/deps/spirv-headers/include
RUN git config --global --add safe.directory '*'
WORKDIR /src
