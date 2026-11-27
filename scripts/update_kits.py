"""Sync compiled runtime objects and modified sources into local PS5 kits."""
import argparse
import glob
import json
import os
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def discover_kits():
    kits = []
    dist_kit = os.path.join(ROOT, "dist", "kit")
    if os.path.isdir(dist_kit):
        kits.append(dist_kit)
    for k in sorted(glob.glob(os.path.join(ROOT, "dist", "builder", "*", "*", "kit"))):
        if os.path.isdir(k):
            kits.append(k)
    return kits


def main():
    parser = argparse.ArgumentParser(description="Update PS5 kit objects and sources from work/ and repo.")
    parser.add_argument("--work-dir", default=os.path.join(ROOT, "work"), help="Directory containing compiled .o files")
    parser.add_argument("--kit", action="append", dest="kits", help="Target kit directory (repeatable)")
    parser.add_argument("--objects", nargs="*", help="Object filenames to copy (default: all host_*.o / vk_*.o in work-dir)")
    parser.add_argument("--sync-sources", action="store_true", help="Also copy modified nx2/ and host/ sources into kit/src")
    args = parser.parse_args()

    kits = args.kits or discover_kits()
    if not kits:
        raise SystemExit("No PS5 kits found. Pass --kit <path>.")

    if args.objects:
        objects_to_copy = args.objects
    else:
        objects_to_copy = sorted(
            f for f in os.listdir(args.work_dir)
            if f.endswith(".o") and (f.startswith("host_") or f.startswith("vk_"))
        )

    for k in kits:
        obj_dir = os.path.join(k, "obj")
        os.makedirs(obj_dir, exist_ok=True)
        kj_path = os.path.join(k, "kit.json")
        with open(kj_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        updated_json = False
        for obj_name in objects_to_copy:
            src = os.path.join(args.work_dir, obj_name)
            if not os.path.isfile(src):
                print(f"Skipping missing {src}")
                continue
            dst = os.path.join(obj_dir, obj_name)
            shutil.copy2(src, dst)
            print(f"Copied {obj_name} -> {dst}")
            if obj_name not in data.get("objects", []):
                data["objects"].append(obj_name)
                updated_json = True

        if updated_json:
            data["objects"].sort()
            with open(kj_path, "w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, indent=1)
            print(f"Updated {kj_path} objects list")

        if args.sync_sources:
            src_nx2 = os.path.join(k, "src", "nx2")
            os.makedirs(src_nx2, exist_ok=True)
            shutil.copy2(os.path.join(ROOT, "nx2", "oot_patches.py"), os.path.join(src_nx2, "oot_patches.py"))
            src_host = os.path.join(k, "src", "host")
            os.makedirs(src_host, exist_ok=True)
            for fname in ("heap_give_back.h", "oot_heap_give_back.c", "rx_backend.c", "nn_vi.c"):
                shutil.copy2(os.path.join(ROOT, "host", fname), os.path.join(src_host, fname))
            print(f"Synced sources -> {os.path.join(k, 'src')}")

    print("KIT UPDATE COMPLETED!")


if __name__ == "__main__":
    main()
