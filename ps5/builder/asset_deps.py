"""The prefetch map (Data.deps): for each of the game's scenes, the romfs files it will read, in the order they are wanted,
and the scenes it leads to. host/ps5/asset_prefetch.c reads them ahead of the game (docs/ps5-asset-prefetch.md).

Made from the title folder's packs (Data.idx and Data/, ps5/builder/data_packs.py) after the builder's step 7
(game_data.py calls ensure), or by hand for a title folder made before:

    python -I ps5/builder/asset_deps.py <title folder> [--report report.json]

What a scene needs, followed from the files themselves (the rules were read off the game's files: docs/ps5-asset-prefetch.md):
  - its parameters, Banc/GameBancParam/<scene>.game__banc__GameBancParam.bgyml, and the ones it names by "$parent"
  - its maps: the parameters' Banc.Main "Work/Banc/Scene/<folder>/<name>.bcett.json" is Banc/<folder>/<name>_*.bcett.byml.zs;
    the other scenes' maps its parameters name are scenes it leads to, not its own
  - the actors the maps place (each map's Actors list, its Gyaml: Pack/Actor/<Gyaml>.pack.zs), most placed first. Links and
    rails (Src/Dst, Rails) are not actors and are left out
  - what each placed actor's pack names outside itself: "?Path" and "Work/Path.gyml" files that are loose in the romfs,
    and its models, Model/<ModelProjectName>.<FmdbName>.bfres.zs
  - last, the packs (only) of the actors those packs name by Work/Actor/<name>...ActorParam.gyml: spawn lists and the
    like, what may come; their models are not followed (a forest's actors name every boss of the Enemy Museum)
  - the scenes it leads to: those, and NextBancParamName in the maps' actors
Files of the resident packs (Pack/*.pack.zs outside Pack/Actor) are left out: the game holds those from its start.

Data.deps (little-endian; written last, beside Data.idx, with Data.idx's build id: the game takes it only with those packs):
  0x00 "LSDP", u32 version (1), u32 scene count, u32 path count
  0x10 build id (16 bytes, Data.idx's)
  0x20 u64 scenes offset, u64 lists offset, u64 list entries (u32 each), u64 paths offset
  0x40 u64 names offset, u64 names size, u64 neighbours offset, u64 neighbour entries (u32 each)
  0x60 SHA-256 of everything after the 0x80-byte header
  scenes:     32 bytes each: u32 name offset, u32 name length, u32 first list entry, u32 list count,
              u32 first neighbour, u32 neighbour count, u64 bytes (the sizes of its files, summed)
  lists:      u32 path index per entry (a scene's files, in the order to read them)
  paths:      8 bytes each: u32 name offset, u32 name length (a romfs path, '/'-separated, no leading slash)
  neighbours: u32 scene index per entry
  names:      the scene names and paths, UTF-8, not terminated
"""
import argparse
import collections
import hashlib
import json
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_packs  # noqa: E402

DEPS_NAME = "Data.deps"
MAGIC = b"LSDP"
VERSION = 1
HEAD = 0x80
MODELS_BY_PROJECT = 8    # (a ModelProjectName with no FmdbName: at most this many of its models)
ZSTD = b"\x28\xb5\x2f\xfd"


def say(text):
    print(text, flush=True)


# ------------------------------------------------------------------------------------------------ the game's formats
def sarc_members(data):
    """{name: bytes} of a SARC (little-endian, as every Switch title's)"""
    if data[:4] != b"SARC":
        raise ValueError("not a SARC")
    header = struct.unpack_from("<H", data, 4)[0]
    data_offset = struct.unpack_from("<I", data, 0x0C)[0]
    sfat_header, count = struct.unpack_from("<HH", data, header + 4)
    nodes = header + sfat_header
    sfnt = nodes + count * 16
    names = sfnt + struct.unpack_from("<H", data, sfnt + 4)[0]
    out = {}
    for i in range(count):
        _, attr, begin, end = struct.unpack_from("<IIII", data, nodes + 16 * i)
        if attr >> 24:
            at = names + (attr & 0xFFFF) * 4
            out[data[at:data.index(b"\0", at)].decode("utf-8")] = data[data_offset + begin:data_offset + end]
    return out


def byml(data):
    """A BYML document (v2-v7, little-endian) as Python values: dict, list, str, int, float, bool, None. Hash maps keep
    their hashes as keys; binary nodes are None"""
    if data[:2] != b"YB":
        raise ValueError("not a little-endian BYML")

    def u24(o):
        return data[o] | data[o + 1] << 8 | data[o + 2] << 16

    def u32(o):
        return struct.unpack_from("<I", data, o)[0]

    def table(o):
        if not o:
            return []
        n = u24(o + 1)
        offs = struct.unpack_from("<%dI" % (n + 1), data, o + 4)
        return [data[o + offs[i]:data.index(b"\0", o + offs[i])].decode("utf-8", "replace") for i in range(n)]

    keys, strings = table(u32(4)), table(u32(8))

    def value(t, v, depth):
        if t == 0xA0:
            return strings[v] if v < len(strings) else None
        if t in (0xC0, 0xC1, 0x20, 0x21):
            return node(v, depth + 1)
        if t == 0xD0:
            return bool(v)
        if t == 0xD1:
            return v - (1 << 32) if v >= 1 << 31 else v
        if t == 0xD2:
            return struct.unpack("<f", struct.pack("<I", v))[0]
        if t == 0xD3:
            return v
        if t in (0xD4, 0xD5):
            return struct.unpack_from("<Q", data, v)[0]
        if t == 0xD6:
            return struct.unpack_from("<d", data, v)[0]
        return None

    def node(o, depth):
        if depth > 64 or o + 4 > len(data):
            return None
        t, n = data[o], u24(o + 1)
        if t == 0xC0:
            vals = o + 4 + (n + 3) // 4 * 4
            return [value(data[o + 4 + i], u32(vals + 4 * i), depth) for i in range(n)]
        if t == 0xC1:
            return {keys[u24(o + 4 + 8 * i)]: value(data[o + 7 + 8 * i], u32(o + 8 + 8 * i), depth) for i in range(n)}
        if t in (0x20, 0x21):
            size = 8 if t == 0x20 else 12
            types = o + 4 + size * n
            out = {}
            for i in range(n):
                e = o + 4 + size * i
                h = u32(e) if t == 0x20 else struct.unpack_from("<Q", data, e)[0]
                out[h] = value(data[types + i], u32(e + size - 4), depth)
            return out
        return None

    root = u32(12)
    return node(root, 0) if root else {}


def strings_in(x):
    """Every string in a BYML value"""
    stack = [x]
    while stack:
        v = stack.pop()
        if isinstance(v, str):
            yield v
        elif isinstance(v, dict):
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


def dicts_in(x):
    stack = [x]
    while stack:
        v = stack.pop()
        if isinstance(v, dict):
            yield v
            stack.extend(v.values())
        elif isinstance(v, list):
            stack.extend(v)


# ------------------------------------------------------------------------------------------------ the romfs
class Romfs:
    """The title folder's romfs, read through Data.idx (data_packs.Index), with the zstd dictionaries of Pack/ZsDic.pack.zs"""

    def __init__(self, title):
        import zstandard
        self.zstd = zstandard
        self.idx = data_packs.Index(title)
        self.size = {}
        for p, _ in self.idx.walk():
            self.size[p] = 0
        self.lower = {p.lower(): p for p in self.size}
        self.models = collections.defaultdict(list)   # ModelProjectName (lower) -> its model files
        for p in self.size:
            if p.startswith("Model/") and p.endswith(".bfres.zs"):
                self.models[p[6:].split(".", 1)[0].lower()].append(p)
        self.dicts = {}
        if "Pack/ZsDic.pack.zs" in self.size:
            for raw in sarc_members(self.unzstd(self.idx.read("Pack/ZsDic.pack.zs"))).values():
                d = zstandard.ZstdCompressionDict(raw)
                self.dicts[d.dict_id()] = d

    def close(self):
        self.idx.close()

    def file_size(self, path):
        if not self.size.get(path):
            grp, node = self.idx._locate(path)
            self.size[path] = grp.files[node - grp.nd][6]
        return self.size[path]

    def canonical(self, path):
        return self.lower.get(path.lower())

    def unzstd(self, data):
        if data[:4] != ZSTD:
            return data
        did = self.zstd.get_frame_parameters(data).dict_id
        if did and did not in self.dicts:
            raise ValueError("zstd dictionary %d is not in Pack/ZsDic.pack.zs" % did)
        return (self.zstd.ZstdDecompressor(dict_data=self.dicts[did]) if did else self.zstd.ZstdDecompressor()).decompress(data)

    def byml(self, path):
        return byml(self.unzstd(self.idx.read(path)))


# ------------------------------------------------------------------------------------------------ the walk
def scene_param_path(scene):
    return "Banc/GameBancParam/%s.game__banc__GameBancParam.bgyml" % scene


def work_to_romfs(romfs, s):
    """A "Work/..." or "?..." name in a game file as the loose romfs file it is, or None"""
    if s.startswith("?"):
        s = s[1:]
    elif s.startswith("Work/"):
        s = s[5:]
        if s.endswith(".gyml"):
            s = s[:-5] + ".bgyml"
    else:
        return None
    return romfs.canonical(s) or romfs.canonical(s + ".zs")


def actor_of_work(s):
    """"Work/Actor/X.engine__actor__ActorParam.gyml" -> "X" """
    if s.startswith("Work/Actor/") and ".engine__actor__ActorParam." in s:
        return s[len("Work/Actor/"):].split(".", 1)[0]
    return None


class Deps:
    def __init__(self, romfs):
        self.romfs = romfs
        self.actor_cache = {}
        self.resident = set()
        self.problems = collections.Counter()

    def actor_files(self, actor):
        """An actor's (pack, small loose files, models, actors it names), from its pack. Memoized"""
        if actor in self.actor_cache:
            return self.actor_cache[actor]
        pack = self.romfs.canonical("Pack/Actor/%s.pack.zs" % actor)
        if not pack:
            self.problems["actor with no pack"] += 1
            self.actor_cache[actor] = (None, [], [], [])
            return self.actor_cache[actor]
        loose, models, named = [], [], []
        try:
            members = sarc_members(self.romfs.unzstd(self.romfs.idx.read(pack)))
        except Exception:
            self.problems["actor pack not read"] += 1
            members = {}
        inner = {m.lower() for m in members}
        for data in members.values():
            if data[:2] != b"YB":
                continue
            try:
                doc = byml(data)
            except Exception:
                self.problems["pack member not read"] += 1
                continue
            for d in dicts_in(doc):   # (its models)
                project, fmdb = d.get("ModelProjectName"), d.get("FmdbName")
                if isinstance(project, str) and isinstance(fmdb, str):
                    m = self.romfs.canonical("Model/%s.%s.bfres.zs" % (project, fmdb))
                    if m:
                        models.append(m)
                        continue
                if isinstance(project, str):
                    models.extend(sorted(self.romfs.models.get(project.lower(), []))[:MODELS_BY_PROJECT])
            for t in strings_in(doc):
                a = actor_of_work(t)
                if a:
                    if a != actor:
                        named.append(a)
                    continue
                if t.startswith("?") and t[1:].lower() in inner:   # (in its own pack: read with it)
                    continue
                f = work_to_romfs(self.romfs, t)
                if f and f not in self.resident and not f.startswith("Model/"):
                    loose.append(f)
        out = (pack, list(dict.fromkeys(loose)), list(dict.fromkeys(models)), list(dict.fromkeys(named)))
        self.actor_cache[actor] = out
        return out

    def scene(self, scene, scenes):
        """(files in order, neighbour scenes) of one scene. The order is what is surest to be read first: its parameters
        and maps; the packs of the actors its maps place; their small files; their models, most placed first; then the
        packs of the actors those name (spawn lists, dictionaries: what may come, never their models)"""
        files, params, maps, neighbours = [], [], [], []
        todo = [scene_param_path(scene)]
        while todo:   # (the parameters and their $parent chain)
            p = self.romfs.canonical(todo.pop())
            if not p or p in params:
                continue
            params.append(p)
            doc = self.romfs.byml(p)
            parent = doc.get("$parent") if isinstance(doc, dict) else None
            if isinstance(parent, str):
                f = work_to_romfs(self.romfs, parent)
                if f:
                    todo.append(f)
            banc = doc.get("Banc") if isinstance(doc, dict) else None
            main = banc.get("Main") if isinstance(banc, dict) else None
            for s in strings_in(doc):
                if s.startswith("Work/Banc/Scene/") and s.endswith(".bcett.json"):
                    folder, name = s[len("Work/Banc/Scene/"):-len(".bcett.json")].rsplit("/", 1)
                    if s != main:   # (another scene's map, named by this one's parameters: a scene it leads to)
                        if name in scenes and name != scene and name not in neighbours:
                            neighbours.append(name)
                        continue
                    prefix = "banc/%s/%s_" % (folder.lower(), name.lower())
                    maps.extend(sorted(p2 for low, p2 in self.romfs.lower.items()
                                       if low.startswith(prefix) and low.endswith(".bcett.byml.zs")
                                       and "/" not in low[len(prefix):]))
                elif s.startswith("Work/") and not s.startswith("Work/Actor/"):
                    f = work_to_romfs(self.romfs, s)
                    if f and f not in self.resident:
                        files.append(f)
        placed = collections.Counter()
        for m in dict.fromkeys(maps):
            doc = self.romfs.byml(m)
            for a in (doc.get("Actors") or []) if isinstance(doc, dict) else []:
                if not isinstance(a, dict) or not isinstance(a.get("Gyaml"), str):
                    continue
                placed[a["Gyaml"]] += 1
                for d in dicts_in(a):
                    nxt = d.get("NextBancParamName")
                    if isinstance(nxt, str) and nxt in scenes and nxt != scene and nxt not in neighbours:
                        neighbours.append(nxt)
        actors = [a for a, _ in placed.most_common()]
        info = [self.actor_files(a) for a in actors]
        packs = [i[0] for i in info if i[0]]
        loose = [f for i in info for f in i[1]]
        models = [f for i in info for f in i[2]]
        named = []
        for i in info:
            for a in i[3]:
                if a not in placed:
                    pack = self.actor_files(a)[0]
                    if pack:
                        named.append(pack)
        ordered = params + list(dict.fromkeys(maps)) + files + packs + loose + models + named
        return list(dict.fromkeys(ordered)), neighbours


def build(title):
    """(scene rows, report) for a title folder"""
    romfs = Romfs(title)
    try:
        deps = Deps(romfs)
        # (the resident packs' members are held by the game from its start: never prefetched)
        for p in romfs.size:
            if p.startswith("Pack/") and p.count("/") == 1 and p.endswith(".pack.zs"):
                deps.resident.add(p)
        prefix, suffix = "Banc/GameBancParam/", ".game__banc__GameBancParam.bgyml"
        scenes = sorted(p[len(prefix):-len(suffix)] for p in romfs.size if p.startswith(prefix) and p.endswith(suffix))
        rows = []
        for i, s in enumerate(scenes):
            files, neighbours = deps.scene(s, set(scenes))
            total = sum(romfs.file_size(f) for f in files)
            rows.append((s, files, neighbours, total))
            say("prefetch map: %d of %d %s: %d files, %.1f MB, leads to %s"
                % (i + 1, len(scenes), s, len(files), total / 1e6, ", ".join(neighbours) or "-"))
        return rows, {"problems": dict(deps.problems), "bid": romfs.idx.bid}
    finally:
        romfs.close()


def encode(rows, bid):
    paths, path_index = [], {}
    names = bytearray()

    def name(text):
        b = text.encode("utf-8")
        off = len(names)
        names.extend(b)
        return off, len(b)

    scene_index = {s: i for i, (s, _, _, _) in enumerate(rows)}
    lists, neighbours, scene_recs = [], [], []
    for s, files, nbrs, total in rows:
        no, nl = name(s)
        first = len(lists)
        for f in files:
            if f not in path_index:
                path_index[f] = len(paths)
                paths.append(name(f))
            lists.append(path_index[f])
        nfirst = len(neighbours)
        neighbours.extend(scene_index[n] for n in nbrs)
        scene_recs.append(struct.pack("<6IQ", no, nl, first, len(files), nfirst, len(nbrs), total))
    body = bytearray()

    def section(blob):
        while len(body) % 8:
            body.append(0)
        off = HEAD + len(body)
        body.extend(blob)
        return off

    scenes_off = section(b"".join(scene_recs))
    lists_off = section(struct.pack("<%dI" % len(lists), *lists))
    paths_off = section(b"".join(struct.pack("<II", o, n) for o, n in paths))
    nbr_off = section(struct.pack("<%dI" % len(neighbours), *neighbours))
    names_off = section(bytes(names))
    head = bytearray(HEAD)
    struct.pack_into("<4sIII", head, 0, MAGIC, VERSION, len(rows), len(paths))
    head[0x10:0x20] = bid
    struct.pack_into("<QQQQ", head, 0x20, scenes_off, lists_off, len(lists), paths_off)
    struct.pack_into("<QQQQ", head, 0x40, names_off, len(names), nbr_off, len(neighbours))
    head[0x60:0x80] = hashlib.sha256(bytes(body)).digest()
    return bytes(head) + bytes(body)


def decode(blob):
    """The reference reader (the checks; host/ps5/asset_prefetch.c reads it in C): {scene: (files, neighbours, bytes)}"""
    if blob[:4] != MAGIC or struct.unpack_from("<I", blob, 4)[0] != VERSION:
        raise ValueError("not a version %d prefetch map" % VERSION)
    if hashlib.sha256(blob[HEAD:]).digest() != blob[0x60:0x80]:
        raise ValueError("prefetch map SHA-256 mismatch")
    nscenes, npaths = struct.unpack_from("<II", blob, 8)
    scenes_off, lists_off, nlists, paths_off = struct.unpack_from("<QQQQ", blob, 0x20)
    names_off, _, nbr_off, nnbr = struct.unpack_from("<QQQQ", blob, 0x40)
    text = lambda o, n: blob[names_off + o:names_off + o + n].decode("utf-8")   # noqa: E731
    paths = [text(*struct.unpack_from("<II", blob, paths_off + 8 * i)) for i in range(npaths)]
    lists = struct.unpack_from("<%dI" % nlists, blob, lists_off)
    nbrs = struct.unpack_from("<%dI" % nnbr, blob, nbr_off)
    recs = [struct.unpack_from("<6IQ", blob, scenes_off + 32 * i) for i in range(nscenes)]
    names = [text(r[0], r[1]) for r in recs]
    return {names[i]: ([paths[k] for k in lists[r[2]:r[2] + r[3]]], [names[k] for k in nbrs[r[4]:r[4] + r[5]]], r[6])
            for i, r in enumerate(recs)}


def current(app):
    """Whether the title folder's Data.deps is of this format and of its Data.idx's packs"""
    try:
        with open(os.path.join(app, DEPS_NAME), "rb") as f:
            head = f.read(HEAD)
        with open(os.path.join(app, data_packs.INDEX_NAME), "rb") as f:
            bid = f.read(0x20)[0x10:0x20]
    except OSError:
        return False
    return head[:4] == MAGIC and struct.unpack_from("<I", head, 4)[0] == VERSION and head[0x10:0x20] == bid


def ensure(app, report=None):
    """Data.deps for a title folder's packs: kept when current, else made (written under another name, then renamed)"""
    if current(app):
        say("prefetch map: kept, made for these packs")
        return
    rows, info = build(app)
    blob = encode(rows, info["bid"])
    tmp = os.path.join(app, DEPS_NAME + ".part")
    with open(tmp, "wb") as f:
        f.write(blob)
    os.replace(tmp, os.path.join(app, DEPS_NAME))
    say("prefetch map: %s, %d scenes, %.1f KB%s" % (DEPS_NAME, len(rows), len(blob) / 1e3,
        (" (%s)" % ", ".join("%s: %d" % kv for kv in sorted(info["problems"].items()))) if info["problems"] else ""))
    if report:
        with open(report, "w", encoding="utf-8") as f:
            json.dump({"scenes": [{"scene": s, "files": len(fl), "bytes": t, "leads_to": n, "first_files": fl[:40]}
                                  for s, fl, n, t in rows], "problems": info["problems"]}, f, indent=1, ensure_ascii=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("app", help="the title folder (Data.idx, Data/)")
    ap.add_argument("--report", help="also write what each scene got, as JSON (game-derived: it stays on this PC)")
    ap.add_argument("--force", action="store_true", help="make it again even when it is current")
    a = ap.parse_args()
    if a.force:
        try:
            os.remove(os.path.join(a.app, DEPS_NAME))
        except FileNotFoundError:
            pass
    ensure(a.app, a.report)
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
