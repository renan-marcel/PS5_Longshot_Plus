"""PS5 Longshot Plus Builder, packaged for players: nothing to install, its own Python, compiler and kit inside.

    python3 -I ps5/builder/package.py --system linux-x64     dist/builder/PS5LongshotPlusBuilder-<version>-x86_64.AppImage
    python3 -I ps5/builder/package.py --system windows-x64   dist/builder/PS5LongshotPlusBuilder-<version>-windows-x64.zip

Both are made on Linux (the Windows one is cross-built: no Windows PC is needed), from the kit (--kit, ps5/builder/
make_kit.py or build_kit.sh) and the PS5_Vulkan submodule's sources. What goes in:

    PS5LongshotPlusBuilder/
      PS5LongshotPlusBuilder.exe | ps5-longshot-plus-builder    the start (Windows: launcher.c; Linux: a shell script, the AppImage's AppRun)
      app/                      the window and the build (app.py, pipeline.py)
      python/                   CPython (python-build-standalone) with PyQt6 and what the lifter imports
      tools/                    clang, ld.lld and llvm-nm (llvm-mingw's LLVM, whose clang has the PS5's target), ps5-native-tool
      kit/                      the title's ready-built part, with the lifter's helper library for this system

Windows is a portable folder in a zip: unpack it anywhere and start the .exe; there is no installer. Linux is one
AppImage. Every download is checked against the SHA-256 named here.
"""
import argparse
import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
LLVM = "https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/"
PYTHON = "https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
DOWNLOADS = {   # name: (url, sha256)
    "llvm-linux": (LLVM + "llvm-mingw-20261104-ucrt-ubuntu-22.04-x86_64.tar.xz", "919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926"),
    "llvm-windows": (LLVM + "llvm-mingw-20261104-ucrt-x86_64.zip", "552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f"),
    "python-linux": (PYTHON + "cpython-3.13.18+20261110-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz", "f2d2199eb25880e07863b391cf7124e7ffa1338b0d65600dfcec117c4223a7fb"),
    "python-windows": (PYTHON + "cpython-3.13.18+20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz", "2e0fed09d48989f64c9305da9ff2d37a41c0d13ab2aa6283405b2b620dfbf805"),
    "llvm-macos": (LLVM + "llvm-mingw-20261104-ucrt-macos-universal.tar.xz", ""),
    "python-macos-arm64": (PYTHON + "cpython-3.13.18+20261110-aarch64-apple-darwin-install_only_stripped.tar.gz", ""),
    "python-macos-x64": (PYTHON + "cpython-3.13.18+20261110-x86_64-apple-darwin-install_only_stripped.tar.gz", ""),
    "zlib": ("https://github.com/madler/zlib/releases/download/v1.4/zlib-1.4.tar.gz", "02dd159783677a749c04adbdd02b55b8a2bcc7e054f51b76b549199a916ad584"),
    "appimagetool": ("https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage", "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0"),
}
# (what the lifter imports, requirements.txt's pins, and the window)
PACKAGES = ["lz4==4.4.5", "numpy==2.5.4", "capstone==5.0.9", "unicorn==2.1.4", "zstandard==0.25.0", "PyQt6==6.12.1"]
LLVM_KEEP = {
    "linux-x64": ["bin/clang-23", "bin/clang", "bin/lld", "bin/ld.lld", "bin/llvm-nm", "lib/libclang-cpp.so.23.1",
                  "lib/libLLVM.so.23.1", "lib/clang/23/include", "LICENSE.TXT"],
    # (bin/clang.exe there is llvm-mingw's wrapper, which picks a MinGW target from its own name: clang-23.exe is the compiler)
    "windows-x64": ["bin/clang-23.exe", "bin/ld.lld.exe", "bin/llvm-nm.exe", "bin/libLLVM-23.dll", "bin/libclang-cpp.dll",
                    "bin/libc++.dll", "bin/libunwind.dll", "bin/libwinpthread-1.dll", "lib/clang/23/include", "LICENSE.TXT"],
    "macos-arm64": ["bin/clang-23", "bin/clang", "bin/lld", "bin/ld.lld", "bin/llvm-nm", "lib/clang/23/include", "LICENSE.TXT"],
    "macos-x64": ["bin/clang-23", "bin/clang", "bin/lld", "bin/ld.lld", "bin/llvm-nm", "lib/clang/23/include", "LICENSE.TXT"],
}
NATIVE_SOURCES = ("native_app_builder.cpp", "self_container.cpp", "elf_object.cpp", "sce_module_writer.cpp")
ZLIB_SOURCES = ("adler32.c", "crc32.c", "inffast.c", "inflate.c", "inftrees.c", "zutil.c", "trees.c", "deflate.c", "compress.c", "uncompr.c")
README = """PS5 Longshot Plus Builder %(version)s

Builds the PlayStation 5 title folder of PS5 Longshot Plus from your own copy of the game.

1. Start %(start)s.
2. Choose your game file (.nup), the folder to build into and your console (PS5 / PS5 Slim, or PS5 Pro), then Build.
   The build takes 40 to 70 minutes and 6 GB of disk. On a computer with little memory free, set Memory to use
   (2 GB at the least): the build keeps within it, more slowly.
3. Copy the folder it makes (PPSA99198) to /data/homebrew on the console, or send it from the window over FTP.
   Your game file goes to /data/longshotplus/roms on the console.

The folder it makes comes from your game: never share it. This builder holds no game files.
What the builder is made of, and the licences: kit/NOTICE.md and LICENSE.
Without a window: %(start)s --cli --game <file> --out <folder> --model base|pro
"""


def say(text):
    print("package: " + text, flush=True)


def fetch(name, cache):
    url, want = DOWNLOADS[name]
    os.makedirs(cache, exist_ok=True)
    path = os.path.join(cache, url.rsplit("/", 1)[1])
    if not os.path.exists(path):
        say("downloading " + url)
        urllib.request.urlretrieve(url, path + ".part")
        os.replace(path + ".part", path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if want and h.hexdigest() != want:
        sys.exit("package: %s has SHA-256 %s, not the %s named in package.py: not used" % (path, h.hexdigest(), want))
    return path


def unpack(archive, to):
    """the archive's one top folder's contents into `to`, once"""
    if os.path.exists(os.path.join(to, ".unpacked")):
        return to
    shutil.rmtree(to, ignore_errors=True)
    tmp = to + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
    else:
        with tarfile.open(archive) as t:
            t.extractall(tmp, filter="fully_trusted")
    inner = os.listdir(tmp)
    os.replace(os.path.join(tmp, inner[0]) if len(inner) == 1 else tmp, to)
    shutil.rmtree(tmp, ignore_errors=True)
    open(os.path.join(to, ".unpacked"), "w").close()
    return to


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def version():
    """BUILDER_VERSION (the release's tag, from the workflow), else git's description of this checkout"""
    if os.environ.get("BUILDER_VERSION"):
        return os.environ["BUILDER_VERSION"]
    return subprocess.run(["git", "-C", ROOT, "describe", "--tags", "--always"], capture_output=True, text=True).stdout.strip() or "dev"


def native_parts(system, vulkan, cache, top, kit):
    """ps5-native-tool (PS5_Vulkan tooling/native: the ELF made the console's executable, and signed) and the lifter's two
    helper libraries, for the system, their runtime linked in: a64emit (third_party/a64-kit/lift/a64emit.cpp), and zbic
    (third_party/zbic), which unpacks the game's main program where the dump has it ZBIC-compressed (nx2/zbic.py). Both
    are built on first use where there is a compiler; a player has none, so they come ready (v0.1.0 came without zbic:
    reading a real .nup stopped there)"""
    native = os.path.join(vulkan, "tooling", "native")
    if not os.path.exists(os.path.join(native, NATIVE_SOURCES[0])):
        sys.exit("package: no PS5_Vulkan sources at %s (git submodule update --init ps5/deps/PS5_Vulkan, or PS5_VULKAN)" % vulkan)
    zlib = unpack(fetch("zlib", cache), os.path.join(cache, "zlib"))
    build = os.path.join(cache, "build-" + system)
    shutil.rmtree(build, ignore_errors=True)
    os.makedirs(build)
    lift = os.path.join(ROOT, "third_party", "a64-kit", "lift")
    kit_lift = os.path.join(kit, "src", "third_party", "a64-kit", "lift")
    emit_src = [os.path.join(lift, "a64emit.cpp"), os.path.join(lift, "suyu", "arm64_to_c.h")]
    # (build_emit.py's stamp: with it the lifter takes the library as built and asks for no compiler)
    key = hashlib.sha1(b"".join(open(f, "rb").read() for f in emit_src)).hexdigest()
    if system == "windows-x64":
        mingw = unpack(fetch("llvm-linux", cache), os.path.join(cache, "llvm-linux"))
        cc, cxx = (os.path.join(mingw, "bin", "x86_64-w64-mingw32-" + n) for n in ("clang", "clang++"))
        tool, lib, extra = os.path.join(top, "tools", "bin", "ps5-native-tool.exe"), os.path.join(kit_lift, "a64emit.dll"), ["-static"]
        emit_flags = ["-shared", "-static", "-fms-extensions", "-D_CRT_SECURE_NO_WARNINGS"]
        zbic_lib, zbic_flags = "zbic.dll", ["-shared", "-static"]
    elif system.startswith("macos-"):
        arch = "arm64" if system == "macos-arm64" else "x86_64"
        cc, cxx = "clang", "clang++"
        tool, lib = os.path.join(top, "tools", "bin", "ps5-native-tool"), os.path.join(kit_lift, "liba64emit.so")
        extra = ["-arch", arch, "-mmacosx-version-min=12.0"]
        emit_flags = ["-arch", arch, "-mmacosx-version-min=12.0", "-dynamiclib", "-fPIC"]
        zbic_lib, zbic_flags = "zbic.so", ["-arch", arch, "-mmacosx-version-min=12.0", "-dynamiclib", "-fPIC"]
    else:
        cc, cxx = "gcc", "g++"
        tool, lib, extra = os.path.join(top, "tools", "bin", "ps5-native-tool"), os.path.join(kit_lift, "liba64emit.so"), ["-static"]
        emit_flags = ["-shared", "-fPIC", "-static-libstdc++", "-static-libgcc"]
        zbic_lib, zbic_flags = "zbic.so", ["-shared", "-fPIC"]
    objs = []
    for f in ZLIB_SOURCES:
        o = os.path.join(build, f[:-2] + ".o")
        run([cc, "-O2", "-w"] + (extra if system.startswith("macos-") else []) + ["-c", os.path.join(zlib, f), "-o", o])
        objs.append(o)
    os.makedirs(os.path.dirname(tool), exist_ok=True)
    run([cxx, "-std=c++20", "-O2", "-w", "-I", zlib] + [os.path.join(native, f) for f in NATIVE_SOURCES] + objs + extra + ["-o", tool])
    run([cxx, "-std=c++20", "-O2", "-w", emit_src[0]] + emit_flags + ["-o", lib])
    open(lib + ".sha1", "w").write(key)
    # (nx2/zbic.py takes the library beside the sources as it is: SRC there is <kit>/src/third_party/zbic)
    zbic_src = os.path.join(ROOT, "third_party", "zbic")
    zbic_dir = os.path.join(kit, "src", "third_party", "zbic")
    os.makedirs(zbic_dir, exist_ok=True)
    # (compiled by the pinned LLVM on both systems, as Longshot's own builds compile it: the Linux runner's GCC 11 made a
    # library that read no ZBIC frame (zbic_check.c). On Linux llvm-mingw's clang is told the PC's own target; its C library
    # is the build PC's)
    zbic_cc = [cc] if (system == "windows-x64" or system.startswith("macos-")) else \
        [os.path.join(unpack(fetch("llvm-linux", cache), os.path.join(cache, "llvm-linux")), "bin", "clang"), "--target=x86_64-linux-gnu"]
    run(zbic_cc + ["-O2", "-w", "-DZSTD_ZBIC_SUPPORT=1", "-I", zbic_src, os.path.join(zbic_src, "zstd.c"),
                   os.path.join(zbic_src, "zbic_api.c"), os.path.join(HERE, "zbic_check.c")] +
        zbic_flags + ["-o", os.path.join(zbic_dir, zbic_lib)])
    for f in ("LICENSE", "PROVENANCE.md"):
        shutil.copy2(os.path.join(zbic_src, f), os.path.join(zbic_dir, f))
    if system == "windows-x64":
        run([cc, "-O2", "-municode", "-mwindows", "-static", os.path.join(HERE, "launcher.c"), "-o", os.path.join(top, "PS5LongshotPlusBuilder-Windows-x64.exe")])
        with open(os.path.join(top, "PS5LongshotPlusBuilder-cli.cmd"), "w", newline="\r\n") as f:
            f.write("@echo off\nrem PS5 Longshot Plus Builder without the window: \"PS5LongshotPlusBuilder-cli.cmd --game <file> --out <folder> "
                    "--model base|pro\", or --check. Its output goes to this console, or where it is redirected\n"
                    "\"%~dp0python\\python.exe\" -I -u \"%~dp0app\\pipeline.py\" %*\n")


def stage(system, a):
    """the folder: top"""
    linux = system == "linux-x64"
    macos = system.startswith("macos-")
    base_out = os.path.join(a.out, system)
    shutil.rmtree(base_out, ignore_errors=True)
    app_name = "PS5LongshotPlusBuilder-AppleSilicon.app" if system == "macos-arm64" else "PS5LongshotPlusBuilder-Intel.app"
    dir_name = "PS5LongshotPlusBuilder-Windows-x64" if system == "windows-x64" else "PS5LongshotPlusBuilder-Linux-x64"
    top = os.path.join(base_out, app_name, "Contents", "MacOS") if macos else os.path.join(base_out, dir_name)
    os.makedirs(top)
    vulkan = os.environ.get("PS5_VULKAN") or os.path.join(ROOT, "ps5", "deps", "PS5_Vulkan")

    # ---- Python and its packages ----
    py_key = "python-linux" if linux else (system.replace("macos-", "python-macos-") if macos else "python-windows")
    with tarfile.open(fetch(py_key, a.cache)) as t:
        t.extractall(top, filter="fully_trusted")
    if linux:
        run([os.path.join(top, "python", "bin", "python3"), "-I", "-m", "pip", "install", "--no-warn-script-location",
             "--disable-pip-version-check", "--no-compile", "-q"] + PACKAGES)
        shutil.rmtree(os.path.join(top, "python", "share"), ignore_errors=True)
        qt_lib = os.path.join(top, "python", "lib", "python3.13", "site-packages", "PyQt6", "Qt6", "lib")
        # (Qt's xcb platform plugin asks for libxcb-cursor, which a desktop does not always have: the build PC's goes along)
        cursor = next((p for p in ("/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0", "/usr/lib64/libxcb-cursor.so.0") if os.path.exists(p)), None)
        if cursor:
            shutil.copy2(os.path.realpath(cursor), os.path.join(qt_lib, "libxcb-cursor.so.0"))
        else:
            say("no libxcb-cursor.so.0 on this PC to take along (apt install libxcb-cursor0): the window will ask the player's")
    elif macos:
        plat = "macosx_11_0_arm64" if system == "macos-arm64" else "macosx_12_0_x86_64"
        wheels = os.path.join(a.cache, "wheels-" + system)
        shutil.rmtree(wheels, ignore_errors=True)
        mac_pkgs = ["PyQt6==6.10.2" if x.startswith("PyQt6==") else x for x in PACKAGES]
        run([sys.executable, "-I", "-m", "pip", "download", "-q", "--disable-pip-version-check", "--only-binary=:all:", "--platform", plat, "--python-version", "3.13", "--implementation", "cp", "-d", wheels] + mac_pkgs)
        site = os.path.join(top, "python", "lib", "python3.13", "site-packages")
        for w in sorted(os.listdir(wheels)):
            with zipfile.ZipFile(os.path.join(wheels, w)) as z: z.extractall(site)
        shutil.rmtree(os.path.join(top, "python", "share"), ignore_errors=True)
        shutil.rmtree(os.path.join(top, "python", "include"), ignore_errors=True)
    else:
        host_py = os.path.join(unpack(fetch("python-linux", a.cache), os.path.join(a.cache, "python-linux")), "bin", "python3")
        # (Windows' wheels, fetched and unpacked by this PC's Python: a wheel is a zip of what goes in site-packages)
        wheels = os.path.join(a.cache, "wheels-windows")
        shutil.rmtree(wheels, ignore_errors=True)
        run([host_py, "-I", "-m", "pip", "download", "-q", "--disable-pip-version-check", "--only-binary=:all:", "--platform", "win_amd64",
             "--python-version", "3.13", "--implementation", "cp", "-d", wheels] + PACKAGES)
        site = os.path.join(top, "python", "Lib", "site-packages")
        for w in sorted(os.listdir(wheels)):
            with zipfile.ZipFile(os.path.join(wheels, w)) as z:
                z.extractall(site)

    # ---- the compiler ----
    llvm_key = "llvm-linux" if linux else ("llvm-macos" if macos else "llvm-windows")
    llvm = unpack(fetch(llvm_key, a.cache), os.path.join(a.cache, llvm_key))
    for rel in LLVM_KEEP[system]:
        src, dst = os.path.join(llvm, rel), os.path.join(top, "tools", rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.isdir(src):
            shutil.copytree(src, dst, symlinks=True)
        else:
            shutil.copy2(src, dst, follow_symlinks=False)
    if system == "windows-x64":
        shutil.copy2(os.path.join(top, "tools", "bin", "clang-23.exe"), os.path.join(top, "tools", "bin", "clang.exe"))
    elif macos:
        for f in os.listdir(os.path.join(llvm, "lib")):
            if f.endswith(".dylib"):
                shutil.copy2(os.path.join(llvm, "lib", f), os.path.join(top, "tools", "lib", f), follow_symlinks=False)

    # ---- the window, the build, the kit, the system's own programs ----
    os.makedirs(os.path.join(top, "app"))
    for f in ("app.py", "pipeline.py", "shader_lists.py", "game_data.py", "data_packs.py", "asset_deps.py", "known_gpu_hangs.txt"):
        shutil.copy2(os.path.join(HERE, f), os.path.join(top, "app", f))
    shutil.copy2(os.path.join(ROOT, "ps5", "sce_sys", "icon0.png"), os.path.join(top, "app", "longshot.png"))
    shutil.copytree(a.kit, os.path.join(top, "kit"))
    native_parts(system, vulkan, a.cache, top, os.path.join(top, "kit"))
    shutil.copy2(os.path.join(ROOT, "LICENSE"), os.path.join(top, "LICENSE"))
    ver = version()
    open(os.path.join(top, "VERSION"), "w").write(ver + "\n")
    if linux or macos:
        launcher = os.path.join(top, "PS5LongshotPlusBuilder" if macos else "ps5-longshot-plus-builder")
        with open(launcher, "w") as f:
            f.write('#!/bin/sh\n# PS5 Longshot Plus Builder: the window. "--cli ..." runs the build without it (app/pipeline.py\'s options).\n'
                    'here=$(cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)\n'
                    'export PYTHONDONTWRITEBYTECODE=1\n'
                    'if [ "${1:-}" = "--cli" ]; then shift; exec "$here/python/bin/python3" -I -u "$here/app/pipeline.py" "$@"; fi\n'
                    'exec "$here/python/bin/python3" -I "$here/app/app.py" "$@"\n')
        os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if macos:
        contents = os.path.dirname(top)
        res_dir = os.path.join(contents, "Resources")
        os.makedirs(res_dir, exist_ok=True)
        src_png = os.path.join(ROOT, "ps5", "sce_sys", "icon0.png")
        shutil.copy2(src_png, os.path.join(res_dir, "longshot.png"))
        iconset = os.path.join(a.cache, "longshot.iconset")
        shutil.rmtree(iconset, ignore_errors=True)
        os.makedirs(iconset, exist_ok=True)
        for sz in (16, 32, 64, 128, 256, 512):
            subprocess.run(["sips", "-s", "format", "png", "-z", str(sz), str(sz), src_png, "--out", os.path.join(iconset, "icon_%dx%d.png" % (sz, sz))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            subprocess.run(["sips", "-s", "format", "png", "-z", str(sz * 2), str(sz * 2), src_png, "--out", os.path.join(iconset, "icon_%dx%d@2x.png" % (sz, sz))], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        subprocess.run(["iconutil", "-c", "icns", iconset, "-o", os.path.join(res_dir, "longshot.icns")], check=False)
        open(os.path.join(contents, "Info.plist"), "w").write('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://apple.com"><plist version="1.0"><dict><key>CFBundleExecutable</key><string>PS5LongshotPlusBuilder</string><key>CFBundleIconFile</key><string>longshot</string><key>CFBundleIdentifier</key><string>dev.longshot.ps5builder</string><key>CFBundleName</key><string>%s</string><key>CFBundlePackageType</key><string>APPL</string><key>CFBundleShortVersionString</key><string>%s</string><key>LSMinimumSystemVersion</key><string>12.0</string><key>NSHighResolutionCapable</key><true/></dict></plist>\n' % ("PS5 Longshot Plus Builder (Apple Silicon)" if system == "macos-arm64" else "PS5 Longshot Plus Builder (Intel)", ver))
        top = os.path.dirname(contents)
        subprocess.run(["codesign", "--force", "--deep", "-s", "-", top], check=False)
    with open(os.path.join(os.path.dirname(top) if macos else top, "README.txt"), "w", newline="\r\n" if system == "windows-x64" else "\n") as f:
        f.write(README % {"version": ver, "start": ("PS5LongshotPlusBuilder-AppleSilicon.app" if system == "macos-arm64" else "PS5LongshotPlusBuilder-Intel.app") if macos else ("PS5LongshotPlusBuilder-%s-linux-x64.AppImage" % ver if linux else "PS5LongshotPlusBuilder-Windows-x64.exe")})
    return top, ver


def appimage(top, ver, a):
    appdir = os.path.join(a.out, "linux-x64", "PS5LongshotPlusBuilder.AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(os.path.join(appdir, "usr"))
    os.replace(top, os.path.join(appdir, "usr", "PS5LongshotPlusBuilder"))
    with open(os.path.join(appdir, "AppRun"), "w") as f:
        f.write('#!/bin/sh\nexec "$(dirname -- "$(readlink -f -- "$0")")/usr/PS5LongshotPlusBuilder/ps5-longshot-plus-builder" "$@"\n')
    os.chmod(os.path.join(appdir, "AppRun"), 0o755)
    with open(os.path.join(appdir, "ps5-longshot-plus-builder.desktop"), "w") as f:
        f.write("[Desktop Entry]\nType=Application\nName=PS5 Longshot Plus Builder (Linux x64)\nComment=Builds the PS5 title folder of PS5 Longshot Plus from "
                "your own copy of the game\nExec=ps5-longshot-plus-builder\nIcon=ps5-longshot-plus-builder\nCategories=Game;Utility;\nTerminal=false\n")
    shutil.copy2(os.path.join(ROOT, "ps5", "sce_sys", "icon0.png"), os.path.join(appdir, "ps5-longshot-plus-builder.png"))
    shutil.copy2(os.path.join(appdir, "ps5-longshot-plus-builder.png"), os.path.join(appdir, ".DirIcon"))
    tool = fetch("appimagetool", a.cache)
    os.chmod(tool, 0o755)
    out = os.path.join(a.out, "PS5LongshotPlusBuilder-%s-linux-x64.AppImage" % ver)
    # (--appimage-extract-and-run: no FUSE in a build container)
    run([tool, "--appimage-extract-and-run", "--no-appstream", appdir, out], env=dict(os.environ, ARCH="x86_64", VERSION=ver))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=sorted(LLVM_KEEP))
    ap.add_argument("--kit", default=os.path.join(ROOT, "dist", "kit"))
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "builder"))
    ap.add_argument("--cache", default=os.path.join(ROOT, ".local", "builder-downloads"))
    ap.add_argument("--folder-only", action="store_true", help="stop at the folder (dist/builder/<system>/PS5LongshotPlusBuilder)")
    a = ap.parse_args()
    a.out, a.cache, a.kit = (os.path.abspath(p) for p in (a.out, a.cache, a.kit))
    if not os.path.exists(os.path.join(a.kit, "kit.json")):
        sys.exit("package: no kit at %s (ps5/builder/build_kit.sh)" % a.kit)
    top, ver = stage(a.system, a)
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(top) for f in fs if not os.path.islink(os.path.join(d, f)))
    say("%s (%d MB)" % (top, total >> 20))
    if a.folder_only:
        return 0
    if a.system == "linux-x64":
        out = appimage(top, ver, a)
    else:
        out = os.path.join(a.out, "PS5LongshotPlusBuilder-%s-%s.zip" % (ver, a.system))
        if os.path.exists(out):
            os.remove(out)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for d, _, fs in sorted(os.walk(top)):
                for f in sorted(fs):
                    p = os.path.join(d, f)
                    z.write(p, os.path.relpath(p, os.path.dirname(top)))
    say("%s (%d MB)" % (out, os.path.getsize(out) >> 20))
    with open(out + ".sha256", "w") as f:
        h = hashlib.sha256()
        with open(out, "rb") as g:
            for block in iter(lambda: g.read(1 << 20), b""):
                h.update(block)
        f.write("%s  %s\n" % (h.hexdigest(), os.path.basename(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
