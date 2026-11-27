#!/usr/bin/env bash
# PS5 Longshot Plus Builder: the kit, from a fresh clone on Linux, with no game.
#
#   bash ps5/builder/build_kit.sh [--jobs N] [--out dist/kit]
#   bash ps5/builder/build_kit.sh --packages            the apt packages it needs
#   sudo bash ps5/builder/build_kit.sh --install-packages
#
# The kit is everything of the PS5 title that is not made from the game, compiled already (ps5/builder/make_kit.py says what
# is in it). This fetches and builds what it is made of, each at a pinned revision, and is what the release workflow runs
# (.github/workflows/builder-release.yml):
#   PS5_Vulkan       the submodule ps5/deps/PS5_Vulkan: the link recipe, the tool that makes the console's executable, libc.prx
#   PS5_Mesa         RADV, Mesa's Vulkan driver, built for the console by PS5_Vulkan (the long step)
#   PS5_PayloadSDK   the platform layer the title is compiled with
#   PS5_MihawkGen    frame generation
#   FFmpeg, dav1d, zstd for the console; the Vulkan, SPIR-V and VMA headers
# then compiles the runtime and the Vulkan back end (ps5/build.py --kit) and lays the kit out. A second run does only
# what changed. From PS5_Hookshot's build-title.sh (mihawk-99), which went on to build the game's part as well; that part
# is the builder's now (ps5/builder/pipeline.py), on the player's PC.
set -euo pipefail

MESA_REV=0f86253f674c425052948eb3cb116c81e646a734
SDK_REV=88d6e41ec7ee7e76d871ff14cd78b5cc4c8e5989
SDK_REPO=https://github.com/renan-marcel/PS5_PayloadSDK.git
MIHAWKGEN_REV=c57232a9f16bcb6df5fe07c9bb631518f2b1cc0e
# (the headers gpu/vk is compiled with: scripts/linux/deps.sh's pins, which ps5/build.py names)
VK_HEADERS=v1.4.345 SPIRV_HEADERS=vulkan-sdk-1.4.341.0 VMA=v3.3.0
PYTHON_PACKAGES=(lz4 numpy capstone "unicorn>=2.1,<2.2" zstandard pillow meson ninja mako pyyaml packaging)
APT_PACKAGES="git curl wget unzip xz-utils rsync make nasm pkg-config bison flex file ca-certificates python3 python3-venv \
clang lld llvm llvm-dev libclang-rt-18-dev libclang-dev libclang-cpp-dev libclc-18-dev libllvmspirvlib-18-dev spirv-tools glslang-tools \
zlib1g-dev libzstd-dev g++"

die() { printf '\nbuild_kit: %s\n' "$*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }

jobs= out=
while (( $# )); do
    case $1 in
        --packages) echo "$APT_PACKAGES"; exit 0 ;;
        --install-packages)
            command -v apt-get > /dev/null || die "--install-packages is for apt (Ubuntu, Debian): --packages lists them"
            apt-get update
            # shellcheck disable=SC2086
            DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends $APT_PACKAGES
            exit 0 ;;
        --jobs) jobs=${2:?--jobs takes a number}; shift ;;
        --out) out=${2:?--out takes a folder}; shift ;;
        -h | --help) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "unknown option $1 (--help says what there is)" ;;
    esac
    shift
done

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
projects="$root/.local/projects"
logs="$root/work/build-kit"
deps="$root/.local/ps5-deps"
mkdir -p "$logs" "$deps/downloads" "$projects"
cd "$root"

run() {   # log-name command...: quiet while it works, the end of its log when it fails
    local log="$logs/$1.log" start=$SECONDS
    shift
    "$@" > "$log" 2>&1 || { tail -n 40 "$log" >&2; die "that step failed; the whole log: $log"; }
    note "done in $(( SECONDS - start )) s"
}

step "this PC"
missing=()
for command in git curl wget unzip tar xz rsync make nasm pkg-config bison flex python3 clang clang++ llvm-ar \
        glslangValidator flock sha256sum; do
    command -v "$command" > /dev/null || missing+=("$command")
done
if (( ${#missing[@]} )); then
    note "not found: ${missing[*]}"
    note "on Ubuntu or Debian: sudo bash ${BASH_SOURCE[0]} --install-packages"
    exit 1
fi
clang_major=$(clang --version | sed -n 's/.*clang version \([0-9]*\).*/\1/p' | head -1)
[[ -n $clang_major && $clang_major -ge 18 ]] || die "clang 18 or later is needed (this one: ${clang_major:-unknown})"
note "ok: clang $clang_major, $(nproc) cores, $(awk '/MemTotal/ { printf "%.0f GB of memory", $2 / 1048576 }' /proc/meminfo)"

step "Python's packages, in .local/venv"
python="$root/.local/venv/bin/python"
stamp="${PYTHON_PACKAGES[*]}"
if [[ ! -x $python || $(cat "$root/.local/venv/.packages" 2> /dev/null) != "$stamp" ]]; then
    [[ -x $python ]] || python3 -m venv "$root/.local/venv" ||
        die "python3 cannot make a virtual environment (sudo apt install python3-venv)"
    run pip "$python" -m pip install --disable-pip-version-check "${PYTHON_PACKAGES[@]}"
    printf '%s\n' "$stamp" > "$root/.local/venv/.packages"
else
    note "there already"
fi
export PATH="$root/.local/venv/bin:$PATH"

step "the projects it is made of"
vulkan="$root/ps5/deps/PS5_Vulkan"
[[ -f $vulkan/tools/radv-link.sh ]] || git submodule update --init ps5/deps/PS5_Vulkan
[[ -f $vulkan/tools/radv-link.sh ]] || die "the PS5_Vulkan submodule is not there (git submodule update --init ps5/deps/PS5_Vulkan)"
note "PS5_Vulkan: $(git -C "$vulkan" rev-parse --short HEAD) (the submodule)"
project() {   # name revision [clone options]
    local name=$1 revision=$2 path="$projects/$1" repo="https://github.com/mihawk-99/$1.git"
    shift 2
    if [[ $name == PS5_PayloadSDK ]]; then
        repo=$SDK_REPO
    fi
    if [[ ! -d $path/.git ]]; then
        note "$name: cloning"
        git clone -q "$@" "$repo" "$path"
    elif [[ $name == PS5_PayloadSDK ]]; then
        git -C "$path" remote set-url origin "$repo"
    fi
    git -C "$path" cat-file -e "$revision^{commit}" 2> /dev/null || git -C "$path" fetch -q origin
    git -C "$path" cat-file -e "$revision^{commit}" 2> /dev/null || die "$path does not have $revision"
    [[ " $* " == *" --no-checkout "* ]] || git -C "$path" checkout -q --detach "$revision"
    note "$name: ${revision:0:11}"
}
project PS5_Mesa "$MESA_REV" --no-checkout   # (its revision is exported by PS5_Vulkan's build: no files of its own)
project PS5_PayloadSDK "$SDK_REV" --no-checkout
project PS5_MihawkGen "$MIHAWKGEN_REV"
# (PS5_Vulkan looks for its forks beside itself: these name where they are here)
export PS5_PAYLOAD_SDK_FORK="$projects/PS5_PayloadSDK" PS5_MESA_FORK="$projects/PS5_Mesa"

step "PS5_Vulkan: its payload SDK"
sdk_pin=$(sed -n 's/^sdk_revision=//p' "$vulkan/tools/setup-native-dependencies.sh")
if [[ $(cat "$vulkan/.deps/native/ps5-payload-sdk/.ps5-sdk-revision" 2> /dev/null) == "$sdk_pin" ]]; then
    note "there already"
else
    (cd "$vulkan" && run vulkan-sdk bash tools/setup-native-dependencies.sh)
fi

step "PS5_Vulkan: the tool that makes the console's executable, and libc.prx"
if [[ -x $vulkan/build/host/ps5-native-tool && -f $vulkan/runtime/libc.prx ]]; then
    note "there already"
else
    # (make goes on to PS5_Vulkan's own sample title, which the kit does not need: the two files are what counts)
    (cd "$vulkan" && make > "$logs/vulkan-make.log" 2>&1) || true
    [[ -x $vulkan/build/host/ps5-native-tool && -f $vulkan/runtime/libc.prx ]] ||
        { tail -n 30 "$logs/vulkan-make.log" >&2; die "PS5_Vulkan's make did not build them; the whole log: $logs/vulkan-make.log"; }
    note "done"
fi

step "RADV, the Vulkan driver, at PS5 Mesa ${MESA_REV:0:11} (the long step: 10 to 30 minutes the first time)"
archive="$vulkan/.deps/native/radv-release/lib/libvulkan_radeon.ps5.a"
export PKG_CONFIG_PATH="$vulkan/.deps/native/zlib/root/usr/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
mkdir -p "$vulkan/.deps/native/zlib/root/usr/lib/pkgconfig"
printf "prefix=%s\nlibdir=\${prefix}/lib\nincludedir=\${prefix}/include\nName: zlib\nDescription: zlib\nVersion: 1.3.2\nLibs: -L\${libdir} -lz\nCflags: -I\${includedir}\n" "$vulkan/.deps/native/zlib/root/usr" > "$vulkan/.deps/native/zlib/root/usr/lib/pkgconfig/zlib.pc"
(cd "$vulkan" && PS5_MESA_REVISION=$MESA_REV run radv bash tools/build-radv.sh release)
[[ -f $archive ]] || die "no RADV archive at $archive"

step "the payload SDK the title is compiled with, at ${SDK_REV:0:11}"
sdk="$deps/ps5-payload-sdk"
if [[ $(cat "$sdk/.ps5-sdk-revision" 2> /dev/null) == "$SDK_REV" ]]; then
    note "there already"
else
    tree=$(mktemp -d)
    git -C "$projects/PS5_PayloadSDK" archive "$SDK_REV" | tar -x -C "$tree"
    run sdk bash "$tree/platform/tools/setup-sdk.sh" "$sdk" "$SDK_REV" "$deps/downloads"
    rm -rf -- "$tree"
fi
[[ -x $sdk/bin/prospero-lld ]] || die "the payload SDK at $sdk is incomplete"
export PS5_PAYLOAD_SDK="$sdk" PS5_VULKAN="$vulkan" PS5_MIHAWKGEN="$projects/PS5_MihawkGen"

step "the Vulkan, SPIR-V and VMA headers"
headers() {   # repository tag name
    local to="$deps/cpm/$3/$2"
    [[ -d $to/include ]] && return
    curl -fsSL --retry 5 --retry-all-errors --proto '=https' -o "$deps/downloads/$3-$2.tar.gz" "https://github.com/$1/archive/refs/tags/$2.tar.gz"
    mkdir -p "$to"
    tar -xzf "$deps/downloads/$3-$2.tar.gz" -C "$to" --strip-components=1
}
headers KhronosGroup/Vulkan-Headers "$VK_HEADERS" vulkanheaders
headers KhronosGroup/SPIRV-Headers "$SPIRV_HEADERS" spirv-headers
headers GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator "$VMA" vulkanmemoryallocator
note "there"

step "FFmpeg and zstd for the console (the game's movies, and the game file's compressed parts)"
run ffmpeg bash ps5/tools/build-ffmpeg.sh
run zstd bash ps5/tools/build-zstd.sh

step "the lifter's helper library (third_party/a64-kit)"
run a64emit "$python" -I third_party/a64-kit/lift/build_emit.py

step "the runtime and the renderer, compiled for the console (10 to 20 minutes the first time)"
[[ -n $jobs ]] || jobs=$(awk -v cores="$(nproc)" '/MemTotal/ { m = int($2 / 1572864); c = cores; j = c < m ? c : m; print j < 1 ? 1 : j }' /proc/meminfo)
note "$jobs files at once (--jobs)"
"$python" -I ps5/build.py --kit --jobs "$jobs" 2>&1 | tee "$logs/objects.log" | grep -E '^ps5:|FAILED' || true
grep -q '^ps5: .* 0 failed' "$logs/objects.log" || { tail -n 40 "$logs/objects.log" >&2; die "the kit's objects did not all compile; the whole log: $logs/objects.log"; }

step "the kit"
"$python" -I ps5/builder/make_kit.py ${out:+--out "$out"}
