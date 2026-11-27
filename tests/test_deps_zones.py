"""Game-free: zones in the prefetch map (ps5/builder/asset_deps.py, Data.deps version 2) and in the game
(host/ps5/asset_prefetch.c), with made-up scenes:

- a scene's zone is its own maps' folder (Banc/<folder>/<scene>_*): A_Adult and A_Child are zone A, B is zone B;
- a folder of more than 4 scenes is no zone (a folder of boss rooms reached from everywhere): each of its scenes is a
  zone of its own; a folder of a few scenes leading to many zones (a field) stays one zone;
- version 2 round-trips in Python (scene -> zone, a zone's files in first-wanted order, its neighbour zones) and the
  C reader gives the same zone; a version 1 map reads in both, each scene its own zone;
- the game's zone-change callback comes once per change of zone, not per scene: A_Adult -> A_Child is none.

    python -I -B tests/test_deps_zones.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "{cc}"]
RUN_ALL_SKIP = {"windows": "POSIX file calls, as the PS5's C library: checked on Linux"}
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import asset_deps  # noqa: E402

BID = bytes(range(1, 17))


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def scene(name, folder, leads):
    files = ["Banc/GameBancParam/%s.game__banc__GameBancParam.bgyml" % name, "Banc/%s/%s_Static.bcett.byml.zs" % (folder, name),
             "Model/%s.%s.bfres.zs" % (name, name), "Model/Shared.Shared.bfres.zs"]
    return (name, files, leads, 1000)


ROWS = [scene("A_Adult", "A", ["A_Child", "B"]), scene("A_Child", "A", ["A_Adult"]), scene("B", "B", ["A_Adult", "Stage1"])] + \
    [scene("C%d" % k, "C%d" % k, []) for k in range(1, 6)] + \
    [scene("Stage%d" % k, "Stages", ["C%d" % k]) for k in range(1, 6)] + [scene("Stage6", "Stages", ["A_Adult"])] +     [scene("F_Adult", "F", ["C1", "C2", "C3"]), scene("F_Child", "F", ["C4", "C5", "B"])]


def check_python():
    names, of = asset_deps.zones(ROWS)
    zone = {s: names[of[s]] for s in of}
    need(zone["A_Adult"] == zone["A_Child"] == "A" and zone["B"] == "B" and zone["C3"] == "C3",
         "a scene's zone is its maps' folder: %r" % zone)
    need(all(zone["Stage%d" % k] == "Stage%d" % k for k in range(1, 7)),
         "a folder of more than 4 scenes is no zone: each scene its own (%r)" % {k: v for k, v in zone.items() if "Stage" in k})
    need(zone["F_Adult"] == zone["F_Child"] == "F", "a field of 2 scenes leading to 6 zones is one zone (%r)" % zone["F_Adult"])
    blob = asset_deps.encode(ROWS, BID)
    need(asset_deps.decode(blob)["B"][1] == ["A_Adult", "Stage1"], "version 2 still decodes the scenes as before")
    of2, zs = asset_deps.decode_zones(blob)
    need(of2 == zone, "the zones round-trip: %r" % of2)
    scenes, files, nbrs = zs["A"]
    need(scenes == ["A_Adult", "A_Child"], "zone A's scenes")
    need(files == ROWS[0][1] + [f for f in ROWS[1][1] if f not in ROWS[0][1]], "zone A's files, first wanted first, once each")
    need(nbrs == ["B"], "zone A leads to B, not to itself (%r)" % nbrs)
    v1 = asset_deps.encode(ROWS, BID, version=1)
    of1, zs1 = asset_deps.decode_zones(v1)
    need(all(of1[s] == s for s, _, _, _ in ROWS) and zs1["A_Adult"][0] == ["A_Adult"], "a version 1 map: each scene its own zone")
    need(asset_deps.decode(v1)["A_Adult"][1] == ["A_Child", "B"], "a version 1 map still decodes")
    return blob, v1


def check_c(cc, blob, v1):
    with tempfile.TemporaryDirectory(prefix="deps-zones-") as tmp:
        tmp = Path(tmp)
        exe = tmp / "prefetch"
        base = [cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", str(ROOT / "tests" / "asset_prefetch_test.c"),
                str(ROOT / "host" / "ps5" / "asset_prefetch.c"), "-I", str(ROOT / "host" / "ps5"), "-lpthread", "-o", str(exe)]
        r = subprocess.run(base[:1] + ["-fsanitize=address,undefined"] + base[1:], capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run(base, capture_output=True, text=True)
        need(r.returncode == 0, "it compiles: " + r.stderr[-3000:])
        (tmp / "pack").write_bytes(b"\0" * 16)
        (tmp / "files.txt").write_text("x\t0\t16\n", encoding="utf-8")
        for name, data, want in (("v2", blob, ["zone-change  -> A", "zone A", "zone-change A -> B", "zone B"]),
                                 ("v1", v1, ["zone-change  -> A_Adult", "zone A_Adult", "zone-change A_Adult -> A_Child",
                                             "zone A_Child", "zone-change A_Child -> B", "zone B"])):
            title = tmp / name
            title.mkdir()
            (title / "Data.deps").write_bytes(data)
            r = subprocess.run([str(exe), str(title), str(tmp / "pack"), str(tmp / "files.txt"), "scene:A_Adult", "zone",
                                "scene:A_Child", "zone", "scene:B", "zone", "stop"], capture_output=True, text=True, timeout=60,
                               env=dict(os.environ, HOS_PREFETCH="0"))
            need(r.returncode == 0, "the driver ran: " + (r.stdout + r.stderr)[-2000:])
            got = [l for l in r.stdout.splitlines() if l.startswith("zone")]
            if name == "v2":
                want = ["zone-change  -> A", "zone A", "zone A", "zone-change A -> B", "zone B"]
            need(got == want, "%s: the game's zones and their changes: %r" % (name, got))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    blob, v1 = check_python()
    check_c(a.cc, blob, v1)
    print("PASS: zones in the prefetch map and in the game")


if __name__ == "__main__":
    main()
