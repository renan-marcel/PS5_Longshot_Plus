"""The PS5 Longshot Plus Builder's kit: everything of the title that is not made from the game, ready built.

    PS5_VULKAN=<built PS5_Vulkan> PS5_MIHAWKGEN=<PS5_MihawkGen> python3 -I ps5/builder/make_kit.py [--out dist/kit]

Run after `ps5/build.py --kit` (or a whole build) of this checkout: work/ps5 holds the objects. No game is needed: the
kit's objects are the ones no game file goes into (ps5/builder/build_kit.sh does all of it from a fresh clone). The kit holds the
objects of the runtime, the Vulkan back end, Dear ImGui, libopus and PS5_MihawkGen compiled for the console; RADV, FFmpeg,
dav1d and zstd as libraries; the payload SDK's headers and libraries; the link's scripts and flags; the lifter's sources
(nx2, host, third_party/a64-kit) and the title folder's own files. Nothing in it comes from a game: ps5/builder/pipeline.py
adds the game's part on the player's PC. What each part is and its licence: the kit's NOTICE.md.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_build():
    spec = importlib.util.spec_from_file_location("ps5build", os.path.join(ROOT, "ps5", "build.py"))
    b = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(b)
    return b


def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def tracked(*paths):
    """the files git has under paths (no build leftovers)"""
    out = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--"] + list(paths), capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "kit"))
    a = ap.parse_args()
    b = load_build()
    kit = os.path.abspath(a.out)
    work = b.OUT
    rt64 = os.path.join(work, "rt64")
    jobs = b.jobs_for(rt64, os.path.join(work, "gen"))
    objects = sorted(j[1] for j in jobs if not os.path.basename(j[1]).startswith("game_"))
    missing = [o for o in objects if not os.path.exists(o) or not os.path.exists(o + ".key")]
    if missing:
        sys.exit("make_kit: compile the kit's objects first (ps5/build.py --kit): %s" % missing[:3])
    if os.path.exists(kit):
        shutil.rmtree(kit)
    os.makedirs(kit)

    # ---- the objects that are not the game's ----
    kept = []
    for o in objects:
        name = os.path.basename(o)
        if name.startswith("game_"):
            continue
        copy(o, os.path.join(kit, "obj", name))
        kept.append(name)

    # ---- libraries ----
    vulkan, sdk = os.path.abspath(b.VULKAN), os.path.abspath(b.SDK)
    # (the CRT and the stubs that name AGC's imports, as ps5/tools/link.sh makes them)
    cc = lambda *args: subprocess.run(["sh", os.path.join(vulkan, "tooling", "prospero-clang18")] + list(args), check=True,
                                      env=dict(os.environ, PS5_PAYLOAD_SDK=sdk, PS5_CLANG=os.environ.get("PS5_CLANG") or shutil.which("clang")))
    cc("-std=c++20", "-O2", "-fno-exceptions", "-fno-rtti", "-c", os.path.join(vulkan, "tooling", "native", "app_crt.cpp"),
       "-o", os.path.join(kit, "obj", "app_crt.o"))
    os.makedirs(os.path.join(kit, "lib", "stubs"))
    for lib, src in (("libSceAgc", "agc_canary_link_stub.c"), ("libSceAgcDriver", "agc_driver_canary_link_stub.c")):
        o = os.path.join(kit, "lib", "stubs", lib + "_stub.o")
        cc("-std=c11", "-O2", "-fPIC", "-c", os.path.join(vulkan, "vendor", "ps5", "sdk", "stubs", src), "-o", o)
        subprocess.run([os.path.join(sdk, "bin", "prospero-lld"), "--shared", "-soname", lib + ".prx", "-o",
                        os.path.join(kit, "lib", "stubs", lib + ".so"), o], check=True)
        os.remove(o)
    archive = os.path.join(ROOT, ".local", "ps5-deps", "radv", "lib", "libvulkan_radeon.ps5.a")
    if not os.path.exists(archive):
        archive = os.path.join(vulkan, ".deps", "native", "radv-release", "lib", "libvulkan_radeon.ps5.a")
    clang = os.environ.get("PS5_CLANG") or shutil.which("clang")
    resource = subprocess.run([clang, "--print-resource-dir"], capture_output=True, text=True, check=True).stdout.strip()
    builtins = os.path.join(resource, "lib", "linux", "libclang_rt.builtins-x86_64.a")
    copy(archive, os.path.join(kit, "lib", "libvulkan_radeon.ps5.a"))
    copy(builtins, os.path.join(kit, "lib", "libclang_rt.builtins-x86_64.a"))
    for n in ("libavcodec.a", "libswscale.a", "libavutil.a", "libdav1d.a"):
        copy(os.path.join(b.FFMPEG, "lib", n), os.path.join(kit, "lib", n))
    copy(os.path.join(b.DEPS, "zstd", "lib", "libzstd.a"), os.path.join(kit, "lib", "libzstd.a"))
    shutil.copytree(os.path.join(sdk, "target"), os.path.join(kit, "sdk", "target"), symlinks=False)

    # ---- the link: PS5_Vulkan's recipe, read from its own script, its paths made the kit's ----
    shutil.copytree(os.path.join(vulkan, "tooling", "native"), os.path.join(kit, "link", "native"),
                    ignore=shutil.ignore_patterns("*.cpp", "*.hpp", "runtime"))
    copy(os.path.join(vulkan, "tooling", "psbc", "ps5-pie-unwind.ld"), os.path.join(kit, "link", "psbc", "ps5-pie-unwind.ld"))
    script = r'''
set -euo pipefail
source "$1/tools/radv-link.sh"
radv_link_recipe "$1" "$2" "$3"
printf '%s\0' "${radv_linker_script[@]}"; printf 'SEP\0'
printf '%s\0' "${radv_link_flags[@]}"; printf 'SEP\0'
printf '%s\0' "${radv_link_inputs[@]}"
'''
    r = subprocess.run(["bash", "-c", script, "recipe", vulkan, sdk, archive], capture_output=True, check=True,
                       env=dict(os.environ, PS5_CLANG=clang))
    parts = [[x for x in p.split("\0") if x] for p in r.stdout.decode().split("SEP\0")]
    copy(os.path.join(vulkan, "build", "radv-platform-local.map"), os.path.join(kit, "link", "radv-platform-local.map"))
    places = [(os.path.join(vulkan, "build", "radv-platform-local.map"), "{kit}/link/radv-platform-local.map"),
              (os.path.join(vulkan, "tooling", "psbc"), "{kit}/link/psbc"),
              (os.path.join(vulkan, "tooling", "native"), "{kit}/link/native"),
              (archive, "{kit}/lib/libvulkan_radeon.ps5.a"), (builtins, "{kit}/lib/libclang_rt.builtins-x86_64.a"),
              (sdk, "{kit}/sdk")]

    def placed(arg):
        for real, name in places:
            arg = arg.replace(real, name)
        if ROOT in arg or vulkan in arg or "/home/" in arg:
            sys.exit("make_kit: a link argument still names this PC: " + arg)
        return arg
    flags = {"script": [placed(x) for x in parts[0]], "flags": [placed(x) for x in parts[1]],
             "inputs": [placed(x) for x in parts[2]]}
    # (what the modules a title loads export: ps5/tools/link.sh's list, made here once)
    exported = set()
    libs = sorted(f for f in os.listdir(os.path.join(sdk, "target", "lib")) if f.endswith(".so"))
    for lib in [os.path.join(sdk, "target", "lib", f) for f in libs if f not in ("libkernel_sys.so", "libScePosixForWebKit.so")] + \
            [os.path.join(kit, "lib", "stubs", n) for n in ("libSceAgc.so", "libSceAgcDriver.so")]:
        out = subprocess.run([os.path.join(sdk, "bin", "llvm-nm"), "-D", "--defined-only", lib], capture_output=True, text=True).stdout
        exported.update(l.split()[-1] for l in out.splitlines() if l.strip())
    with open(os.path.join(kit, "link", "exported.txt"), "w") as f:
        f.write("\n".join(sorted(exported)) + "\n")

    # ---- the game's compile flags, as ps5/build.py has them ----
    game = next(j for j in jobs if os.path.basename(j[1]) == "game_a64_rt.o")
    game_places = [(rt64, "{rt64}"), (b.GEN, "{gen}"), (os.path.join(b.kit.KIT, "rt"), "{kit}/src/third_party/a64-kit/rt"),
                   (os.path.join(ROOT, "nx2", "rt"), "{kit}/src/nx2/rt")]

    def game_placed(arg):
        for real, name in game_places:
            arg = arg.replace(real, name)
        if "/home/" in arg:
            sys.exit("make_kit: a compile flag still names this PC: " + arg)
        return arg

    # ---- the lifter and what it reads ----
    for rel in tracked("nx2", "host", "third_party/a64-kit", "assets/longshot.png", "assets/pipeline_states", "LICENSE"):
        if rel.startswith("nx2/test_") or "/tests/" in rel:
            continue
        copy(os.path.join(ROOT, rel), os.path.join(kit, "src", rel))

    # ---- the title folder's own files ----
    for n in os.listdir(os.path.join(ROOT, "ps5", "sce_sys")):
        copy(os.path.join(ROOT, "ps5", "sce_sys", n), os.path.join(kit, "title", "sce_sys", n))
    copy(os.path.join(vulkan, "runtime", "libc.prx"), os.path.join(kit, "title", "sce_module", "libc.prx"))
    if b.HAS_MIHAWKGEN:
        copy(b.MIHAWKGEN_NETWORK, os.path.join(kit, "title", "framegen", "network.fgw"))

    rev = lambda d: subprocess.run(["git", "-C", d, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    title_id = json.load(open(os.path.join(ROOT, "ps5", "sce_sys", "param.json")))["titleId"]
    info = {
        "format": 1,
        "title_id": title_id,
        "longshot": subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--always", "--dirty"], capture_output=True, text=True).stdout.strip(),
        "revisions": {"PS5_Longshot": rev(ROOT), "PS5_Vulkan": rev(vulkan), "PS5_MihawkGen": rev(b.MIHAWKGEN) if b.HAS_MIHAWKGEN else ""},
        "compiler": subprocess.run([clang, "--version"], capture_output=True, text=True).stdout.splitlines()[0],
        # (the SDK wrapper's part, PS5_Vulkan tooling/prospero-clang18, then build.py's)
        "target_flags": ["-target", "x86_64-sie-ps5", "-fvisibility-nodllstorageclass=default", "-isysroot", "{kit}/sdk",
                         "-isystem", "{kit}/sdk/target/include/c++/v1", "-isystem", "{kit}/sdk/target/include",
                         "-fno-stack-protector", "-fno-plt", "-femulated-tls", "-fdenormal-fp-math=ieee"],
        "game_flags": [game_placed(x) for x in game[2]],
        "game_files": ["a64_table.c", "a64_hooks.c", "a64_suyu.c", "a64_stubs.c", "hos_image.c", "nvn2_exports.c"],
        "objects": kept,
        "link": flags,
    }
    with open(os.path.join(kit, "kit.json"), "w") as f:
        json.dump(info, f, indent=1)
    with open(os.path.join(kit, "NOTICE.md"), "w") as f:
        f.write("""# What this kit is made of

Built from PS5_Longshot %s. No part of it comes from a game.

| Part | From | Licence |
|---|---|---|
| obj/host_*, obj/vk_* | Longshot's runtime and Vulkan back end (MagicBeanDev/Longshot, with PS5_Hookshot's port), Eden's shader recompiler, sirit, suyu's texture decoders, Dear ImGui | GPL-3.0 (Dear ImGui: MIT) |
| obj/opus_* | libopus 1.5.2 | BSD-3-Clause |
| obj/mihawkgen_*, title/framegen | PS5_MihawkGen %s | GPL-3.0-or-later |
| obj/lsfg_* | Lossless Scaling's frame generation on Vulkan (third_party/lsfg and gpu/vk/lsfg: PS5SX2's port of the Eden emulator's lsfg-vk); its shaders are read from the player's own Lossless.dll, not shipped | GPL-3.0-or-later |
| lib/libvulkan_radeon.ps5.a | Mesa's RADV built by PS5_Vulkan %s from PS5_Mesa | MIT |
| lib/libav*.a, libswscale.a | FFmpeg | LGPL-2.1-or-later |
| lib/libdav1d.a | dav1d | BSD-2-Clause |
| lib/libzstd.a | zstd | BSD-3-Clause |
| lib/libclang_rt.builtins-x86_64.a | LLVM compiler-rt | Apache-2.0 with LLVM exceptions |
| sdk/, link/, obj/app_crt.o, title/sce_module/libc.prx | ps5-payload-sdk and PS5_Vulkan's platform layer | GPL-3.0 |
| src/ | Longshot's lifter (nx2), runtime sources (host) and a64-kit | GPL-3.0 |
| (not in the kit) the amiibo catalogue | AmiiboAPI (N3evin), downloaded on the player's PC at build time with Download amiibo, not shipped | MIT |

The sources are in the PS5_Longshot repository at the revision above and in the projects named.
""" % (info["revisions"]["PS5_Longshot"][:12], info["revisions"]["PS5_MihawkGen"][:12], info["revisions"]["PS5_Vulkan"][:12]))
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(kit) for f in fs)
    print("kit: %s, %d objects, %d MB" % (kit, len(kept), total >> 20))


if __name__ == "__main__":
    main()
