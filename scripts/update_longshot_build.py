"""Incrementally update an existing PS5 Longshot build directory (objects, optional C patch, relink, sign)."""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def detect_title_dir(build_root, title_id):
    if title_id:
        return os.path.join(build_root, title_id)
    for cand in sorted(glob.glob(os.path.join(build_root, "PPSA*"))):
        if os.path.isdir(cand):
            return cand
    sys.exit(f"ERROR: No PPSA* title folder found in {build_root}. Pass --title-id.")


def main():
    parser = argparse.ArgumentParser(description="Incrementally update an existing PS5 build directory.")
    parser.add_argument(
        "--build-dir",
        default=os.environ.get("LONGSHOT_PS5_BUILD"),
        required=os.environ.get("LONGSHOT_PS5_BUILD") is None,
        help="Existing PS5 build directory (or set LONGSHOT_PS5_BUILD)",
    )
    parser.add_argument("--title-id", default=None, help="PS5 Title ID folder (auto-detected if omitted)")
    parser.add_argument("--work-dir", default=os.path.join(ROOT, "work"), help="Repo work/ with compiled .o files")
    parser.add_argument("--objects", nargs="*", help="Runtime .o files to copy (default: all host_*.o / vk_*.o in work-dir)")
    parser.add_argument("--patch-heap-free", action="store_true", help="Patch f_803b44e0 in code_003_1.c and recompile it")
    args = parser.parse_args()

    build_root = args.build_dir
    work = os.path.join(build_root, "longshot-ps5-work")
    app = detect_title_dir(build_root, args.title_id)
    kit = os.path.join(build_root, "kitout", "builder", "PS5LongshotPlusBuilder-Windows-x64", "kit")
    tools = os.path.join(build_root, "kitout", "builder", "PS5LongshotPlusBuilder-Windows-x64", "tools", "bin")

    clang = os.path.join(tools, "clang.exe")
    lld = os.path.join(tools, "ld.lld.exe")
    native = os.path.join(tools, "ps5-native-tool.exe")

    print("=== 1. Copying updated runtime objects to kit obj ===")
    obj_dir = os.path.join(kit, "obj")
    os.makedirs(obj_dir, exist_ok=True)
    objs = args.objects or sorted(
        f for f in os.listdir(args.work_dir)
        if f.endswith(".o") and (f.startswith("host_") or f.startswith("vk_"))
    )

    kj_path = os.path.join(kit, "kit.json")
    with open(kj_path, "r", encoding="utf-8") as f:
        kj_data = json.load(f)

    new_kit_objs = []
    for o in objs:
        src = os.path.join(args.work_dir, o)
        if not os.path.isfile(src):
            print(f"  Skipping missing {src}")
            continue
        dst = os.path.join(obj_dir, o)
        shutil.copy2(src, dst)
        print(f"  {o} -> {dst}")
        if o not in kj_data["objects"]:
            kj_data["objects"].append(o)
            new_kit_objs.append(o)

    if new_kit_objs:
        kj_data["objects"].sort()
        with open(kj_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(kj_data, f, indent=1)
        print("  kit.json updated with:", ", ".join(new_kit_objs))

    if args.patch_heap_free:
        sys.path.insert(0, os.path.join(ROOT, "nx2"))
        import oot_patches
        print("=== 2. Patching f_803b44e0 in code_003_1.c ===")
        c_file = os.path.join(work, "lift", "sa", "gen", "code_003_1.c")
        with open(c_file, "r", encoding="utf-8") as f:
            source = f.read()
        patched = oot_patches.patch_heap_free(source)
        if patched is None:
            sys.exit("ERROR: patch_heap_free returned None! Function f_803b44e0 not found in code_003_1.c")
        if patched != source:
            with open(c_file, "w", encoding="utf-8", newline="\n") as f:
                f.write(patched)
            print("  code_003_1.c successfully patched with hos_oot_heap_free(c)!")
        else:
            print("  code_003_1.c was already patched.")

        print("=== 3. Recompiling code_003_1.c -> game_code_003_1.o ===")
        rt64 = os.path.join(work, "rt64")
        gen = os.path.join(work, "lift", "sa", "gen")
        place = lambda a: a.replace("{kit}", kit).replace("{rt64}", rt64).replace("{gen}", gen)
        flags = [place(a) for a in kj_data["target_flags"] + kj_data["game_flags"]]
        obj_out = os.path.join(work, "obj", "game_code_003_1.o")
        t0 = time.time()
        r = subprocess.run([clang] + flags + ["-c", c_file, "-o", obj_out], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"ERROR: clang failed on code_003_1.c:\n{r.stderr}")
        print(f"  Compiled {obj_out} ({os.path.getsize(obj_out)} bytes) in {time.time() - t0:.1f}s")

    print("=== 4. Updating link.rsp and re-linking llvm-pie.elf ===")
    rsp_path = os.path.join(work, "link", "link.rsp")
    with open(rsp_path, "r", encoding="utf-8") as f:
        rsp_lines = [l.strip().strip('"') for l in f.readlines()]

    rsp_changed = False
    for o in objs:
        obj_entry = f"{kit}/obj/{o}".replace("\\", "/")
        if obj_entry not in rsp_lines and os.path.isfile(os.path.join(obj_dir, o)):
            rsp_lines.append(obj_entry)
            rsp_changed = True
    if rsp_changed:
        with open(rsp_path, "w", encoding="utf-8", newline="\n") as f:
            for line in rsp_lines:
                f.write(f'"{line}"\n')
    print(f"  link.rsp ready ({len(rsp_lines)} entries)")

    elf_out = os.path.join(work, "link", "llvm-pie.elf")
    t0 = time.time()
    r = subprocess.run([lld, "@" + rsp_path], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: ld.lld failed:\n{r.stderr}")
    print(f"  Linked {elf_out} ({os.path.getsize(elf_out) >> 20} MB) in {time.time() - t0:.1f}s")

    print("=== 5. Processing eboot.elf.new and signing eboot.bin ===")
    new_elf = os.path.join(work, "eboot.elf.new")
    stub_dir = os.path.join(kit, "sdk", "target", "lib")
    link_cmd = [
        native, "link", "--in", elf_out, "--out", new_elf, "--stub-dir", stub_dir,
        "--stub", os.path.join(kit, "lib", "stubs", "libSceAgc.so"),
        "--stub", os.path.join(kit, "lib", "stubs", "libSceAgcDriver.so"),
        "--module-sdk", "0x02000009", "--companion-sdk", "0x08050001", "--file-name", "eboot.elf",
    ]
    r = subprocess.run(link_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: ps5-native-tool link failed:\n{r.stderr}")
    print(f"  ps5-native-tool link created {new_elf} ({os.path.getsize(new_elf) >> 20} MB)")

    eboot_out = os.path.join(app, "eboot.bin")
    sign_cmd = [native, "self", "--sign", "--in", new_elf, "--out", eboot_out, "--magic", "0x1D3D154F"]
    r = subprocess.run(sign_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"ERROR: ps5-native-tool sign failed:\n{r.stderr}")

    r = subprocess.run([native, "self", "--inspect", "--file", eboot_out], capture_output=True, text=True)
    print("=== Inspection of updated eboot.bin ===")
    print(r.stdout.strip())
    print(f"\nSUCCESS: {app} updated!")


if __name__ == "__main__":
    main()
