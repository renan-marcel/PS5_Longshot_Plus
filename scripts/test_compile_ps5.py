"""Compile modified Longshot host/vk runtime sources for the x86_64-sie-ps5 target."""
import argparse
import glob
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULT_TARGETS = [
    "host/oot_heap_give_back.c",
    "host/rx_backend.c",
    "host/nn_vi.c",
    "host/ps5/win32_ps5.c",
    "gpu/vk/vk_memory.cpp",
    "gpu/vk/vk_replay.cpp",
    "gpu/vk/vk_main.cpp",
]


def find_builder_dir():
    env = os.environ.get("LONGSHOT_PS5_BUILDER")
    if env and os.path.isdir(env):
        return env
    for cand in sorted(glob.glob(os.path.join(ROOT, "dist", "builder", "*", "PS5LongshotPlusBuilder-*"))):
        if os.path.isdir(os.path.join(cand, "tools", "bin")):
            return cand
    for cand in sorted(glob.glob(os.path.join(ROOT, "dist", "builder", "*"))):
        if os.path.isdir(os.path.join(cand, "tools", "bin")):
            return cand
    return None


def obj_name_for(src_rel):
    norm = src_rel.replace("\\", "/").lstrip("./")
    if norm.startswith("gpu/vk/"):
        stem = norm[len("gpu/"):].replace("/", "_")
    else:
        stem = norm.replace("/", "_")
    return os.path.splitext(stem)[0] + ".o"


def build_flags(kit, sdk, vk_headers, rt64_dir, kit_gen_dir):
    common = [
        "-target", "x86_64-sie-ps5",
        "-fvisibility-nodllstorageclass=default",
        "-isysroot", sdk,
        "-isystem", os.path.join(sdk, "target", "include", "c++", "v1"),
        "-isystem", os.path.join(sdk, "target", "include"),
        "-fno-stack-protector", "-fno-plt", "-femulated-tls",
        "-fdenormal-fp-math=ieee",
        "-march=znver2", "-ffp-contract=off", "-DA64_HOST_BASE=0x1000000000ULL",
        "-fno-omit-frame-pointer", "-ffunction-sections", "-fdata-sections", "-g0",
        "-Wno-everything",
    ]
    host_fl = common + [
        "-Dmkdir=hos_ps5_mkdir",
        "-I" + os.path.join(ROOT, "host", "posix"),
        "-D_GNU_SOURCE",
        "-I" + os.path.join(ROOT, "host"),
        "-I" + rt64_dir,
        "-I" + kit_gen_dir,
        "-I" + os.path.join(ROOT, "gpu", "vk"),
        "-I" + vk_headers,
        "-O2", "-mcx16", "-DA64_POLLING", "-DA64_WRITE_TRACK",
    ]
    vfl = common + [
        "-Dmkdir=hos_ps5_mkdir",
        "-I" + os.path.join(ROOT, "host", "posix"),
        "-D_GNU_SOURCE",
        "-include", os.path.join(ROOT, "host", "ps5", "win32_ps5.h"),
        "-include", "algorithm", "-include", "cstdio", "-include", "cstdlib", "-include", "cstring",
        "-include", "functional", "-include", "string", "-include", "vector",
        "-std=c++20", "-O2", "-DNDEBUG", "-fexceptions", "-fcxx-exceptions", "-DVK_NO_PROTOTYPES",
        "-DMKWVK_BUILDING", "-DLONGSHOT_RELEASE", "-DMKWVK_INCLUDES=2",
        "-I" + os.path.join(ROOT, "gpu", "vk", "compat"),
        "-I" + os.path.join(ROOT, "gpu", "compat"),
        "-I" + os.path.join(ROOT, "gpu", "vk", "eden"),
        "-I" + os.path.join(ROOT, "gpu", "third_party", "suyu"),
        "-I" + os.path.join(ROOT, "gpu", "vk", "sirit", "include"),
        "-I" + os.path.join(ROOT, "gpu", "vk", "sirit", "src"),
        "-I" + vk_headers,
        "-I" + os.path.join(ROOT, "gpu", "vk"),
        "-I" + kit_gen_dir,
        "-I" + os.path.join(ROOT, "host"),
    ]
    return host_fl, vfl


def main():
    parser = argparse.ArgumentParser(description="Compile Longshot PS5 runtime object files.")
    parser.add_argument("targets", nargs="*", help="Relative source paths (e.g. host/nn_vi.c gpu/vk/vk_main.cpp)")
    parser.add_argument("--builder-dir", default=None, help="Path to PS5LongshotPlusBuilder folder")
    parser.add_argument("--kit", default=os.path.join(ROOT, "dist", "kit"), help="Path to PS5 kit")
    parser.add_argument("--sdk", default=None, help="Path to PS5 SDK (default: <kit>/sdk)")
    parser.add_argument(
        "--vk-headers",
        default=os.environ.get("LONGSHOT_VULKAN_HEADERS", os.path.join(ROOT, "_deps", "vulkan-headers", "include")),
        help="Path to Vulkan headers include directory",
    )
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "work"), help="Output directory for .o files")
    args = parser.parse_args()

    builder_dir = args.builder_dir or find_builder_dir()
    if not builder_dir:
        sys.exit("ERROR: PS5 builder directory not found. Pass --builder-dir or set LONGSHOT_PS5_BUILDER.")
    clang = os.path.join(builder_dir, "tools", "bin", "clang.exe")
    if not os.path.isfile(clang):
        clang = os.path.join(builder_dir, "tools", "bin", "clang")
    if not os.path.isfile(clang):
        sys.exit(f"ERROR: clang not found under {builder_dir}/tools/bin")

    sdk = args.sdk or os.path.join(args.kit, "sdk")
    rt64_dir = os.path.join(args.out_dir, "rt64")
    kit_gen_dir = os.path.join(args.out_dir, "kit-gen")
    host_fl, vfl = build_flags(args.kit, sdk, args.vk_headers, rt64_dir, kit_gen_dir)

    os.makedirs(args.out_dir, exist_ok=True)
    targets = args.targets or DEFAULT_TARGETS
    for src_rel in targets:
        src = os.path.join(ROOT, *src_rel.replace("\\", "/").split("/"))
        out_name = obj_name_for(src_rel)
        out = os.path.join(args.out_dir, out_name)
        fl = vfl if src_rel.endswith((".cpp", ".cc", ".cxx")) else host_fl
        print(f"Compiling {src_rel} -> {out_name} ...")
        r = subprocess.run([clang] + fl + ["-c", src, "-o", out], capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAILED on {src_rel}:\n{r.stderr[-2000:]}")
            sys.exit(1)
        print(f"OK: {out_name} size: {os.path.getsize(out)}")

    print("ALL TARGETS COMPILED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
