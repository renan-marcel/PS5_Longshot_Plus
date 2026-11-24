"""PS5: the game's data as a few large packs, each group's index inside its own pack, and a small manifest
(docs/ps5-data-packs.md), so a drive with large clusters (exFAT: 128-256 KB) holds 26 GB of game files in 26 GB, not 62,
and a copy to the console moves 53 files, not 186,583.

Nothing is compressed: each game file is in its pack byte for byte as nx2/nup.py extracts it. The console's reader is
host/ps5/pak_romfs.c; this file is the writer (the builder's step 7, ps5/builder/game_data.py) and a reference reader for
the checks (tests/test_ps5_data_packs.py, tests/test_pak_romfs.py).

A group is a top folder of the romfs (Tex, Model, ...; the files at the root, if any, are the group ""). Its packs, its parts:
Data/<Top>.pak, or Data/<Top>.<n>.pak when it takes more than LIMIT bytes. The group's index (its folders, its files and a
ready hash table) is at the end of its LAST part: every file entry says which part holds it. Data.idx, the manifest, is
written last: the groups, the packs, and where each group's index is, with its SHA-256.

Layout (little-endian):
    pack  0x00 "LSPK", u32 version, u32 pack number, u32 part in its group, 16 bytes build id,
          0x20 u64 data size, u64 index offset (0: none in this part), u64 index size, u32 group, u32 0
          0x40 the files one after another, each at a multiple of ALIGN; then, in a group's last part, its index (at a
               multiple of 8)
    group index
          0x00 "LSGI", u32 version, u32 group, u32 0, 16 bytes build id
          0x20 u32 files, u32 folders, u32 parts, u32 hash capacity (a power of 2)
          0x30 five sections, u64 offset and u64 size each (from the index's start): folders, children, files, hash, names
          folders   {u32 name, u32 name length, u32 parent, u32 first child, u32 children}            20 B
          children  u32 node each (below the folder count a folder, else a file: node - folders), by name
          files     {u32 name, u32 name length, u32 folder, u16 part, u16 flags, u64 offset, u64 size} 32 B
          hash      {u64 hash, u32 node, u32 0}, open addressing; hash 0: empty                        16 B
          names     the last part of each name, UTF-8, not terminated
          Node 0 is the group's own folder: named as the group, parent NO_PARENT; in the group "" it has no name. Every
          other folder and every file is in the hash table under its whole path (and the group's folder under its name).
    manifest (Data.idx)
          0x00 "LSMF", u32 version, u32 flags, u32 0, 16 bytes build id
          0x20 u32 groups, u32 packs, u64 files in all
          0x30 three sections, u64 offset and u64 size each: groups, packs, names
          0x60 SHA-256 of everything after the header (MANIFEST_HEAD bytes)
          groups  {u32 name, u32 name length, u32 first pack, u32 parts, u32 files, u32 0}, by name     24 B
          packs   {u32 name, u32 name length, u32 group, u32 part, u64 pack file size, u64 index offset,
                   u64 index size, 32 bytes index SHA-256 (0 where the part holds no index)}           72 B
          names   UTF-8, not terminated
    A path: relative, "/" between parts, case-sensitive. Its hash: 64-bit FNV-1a of the whole path (0 made 1). Each section
    starts at a multiple of 8. File flag ALIAS: a damaged texture given the bytes of a whole one of its kind (its part,
    offset and size are that one's).
"""
import hashlib
import os
import re
import struct

PACK_MAGIC, GROUP_MAGIC, MANIFEST_MAGIC, VERSION = b"LSPK", b"LSGI", b"LSMF", 2
PACK_HEAD = 0x40
GROUP_HEAD = 0x80
MANIFEST_HEAD = 0x80
ALIGN = 16
LIMIT = 4 << 30
NO_PARENT = 0xffffffff
ALIAS = 1
INDEX_NAME = "Data.idx"
PACKS_FOLDER = "Data"
ZSTD = b"\x28\xb5\x2f\xfd"


def fnv(path):
    h = 1469598103934665603
    for b in path.encode("utf-8"):
        h = ((h ^ b) * 1099511628211) & 0xffffffffffffffff
    return h or 1


def zstd_start(head):
    """(nx2/nup.py's) whether a file starts as zstd data: a frame, or a skippable frame"""
    return head == ZSTD or (len(head) == 4 and head[1:] == b"\x2a\x4d\x18" and head[0] & 0xf0 == 0x50)


def build_id(stamp):
    """The same for the same game file and layout: a pack kept from a stopped build matches the manifest made later"""
    return hashlib.sha256(("longshot data packs %d %d %s" % (VERSION, ALIGN, stamp)).encode()).digest()[:16]


def group_of(path):
    return path.split("/")[0] if "/" in path else ""


class Pack:
    """One pack of the plan: its file name, its group (a top folder, "" the root), its part in the group, the files in it
    (indices into the listing) and its data size"""
    def __init__(self, name, group, part, members, size):
        self.name, self.group, self.part, self.members, self.size = name, group, part, members, size


def plan(files, limit=LIMIT):
    """files: [(path, size)] sorted by path (bytes). The packs, in order: a group per top folder, a new part when the next
    file would take one past limit"""
    groups = {}
    for i, (path, size) in enumerate(files):
        parts = groups.setdefault(group_of(path), [[[], 0]])
        at = -(-parts[-1][1] // ALIGN) * ALIGN
        if parts[-1][0] and at + size > limit:
            parts.append([[], 0])
            at = 0
        parts[-1][0].append(i)
        parts[-1][1] = at + size
    out = []
    for group in sorted(groups, key=lambda g: g.encode()):
        parts = groups[group]
        stem = group or "Root"
        for n, (members, size) in enumerate(parts):
            out.append(Pack("%s.pak" % stem if len(parts) == 1 else "%s.%d.pak" % (stem, n), group, n, members, size))
    return out


def places(packs, files):
    """{file: (part, offset in its pack's data)}"""
    out = {}
    for p in packs:
        at = 0
        for i in p.members:
            at = -(-at // ALIGN) * ALIGN
            out[i] = (p.part, at)
            at += files[i][1]
    return out


def pack_header(number, part, group, bid, size, index_offset=0, index_size=0):
    return (PACK_MAGIC + struct.pack("<III", VERSION, number, part) + bid +
            struct.pack("<QQQII", size, index_offset, index_size, group, 0))


def stand_ins(files, damaged):
    """{damaged index: stand-in index}: nup.stand_in_for's rule on the listing (the same last part of the name, the longest
    common start of the name, the nearest size; never a damaged one). files: [(path, size)]. A stand-in is always in the
    damaged file's own folder, so in its group"""
    damaged = set(damaged)
    by_folder = {}
    for i, (path, _) in enumerate(files):
        by_folder.setdefault(path.rpartition("/")[0], []).append(i)
    out = {}
    for d in sorted(damaged):
        folder, _, name = files[d][0].rpartition("/")
        suffix = re.search(r"(_[A-Za-z]+\d*)?(\.[^_]*)$", name).group(0)
        best = None
        for o in by_folder[folder]:
            other = files[o][0].rpartition("/")[2]
            if o in damaged or other == name or not other.endswith(suffix):
                continue
            score = (_common(name, other), -abs(files[o][1] - files[d][1]))
            if best is None or score > best[0]:
                best = (score, o)
        if best:
            out[d] = best[1]
    return out


def _common(a, b):
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def _put(table, h, node):
    i = h & (len(table) - 1)
    while table[i]:
        i = (i + 1) & (len(table) - 1)
    table[i] = (h, node)


def _sections(head_size, sections):
    """(the spans, the body): each section at a multiple of 8 counted from the start of what head_size bytes begin"""
    body, spans = bytearray(), []
    for s in sections:
        body += bytes(-(head_size + len(body)) % 8)
        spans.append((head_size + len(body), len(s)))
        body += s
    return spans, bytes(body)


def group_index(group, number, members, files, at, bid, nparts, aliases=None):
    """A group's index: members, the files of the group (indices into files [(path, size)]); at {file: (part, offset)};
    aliases {file: other} (its bytes are the other's)"""
    aliases = aliases or {}
    names = bytearray()

    def name(text):
        b = text.encode("utf-8")
        off = len(names)
        names.extend(b)
        return off, len(b)

    folders = {group: 0}
    rows = [[*name(group), NO_PARENT]]   # name offset, length, parent
    file_folder = {}
    for i in members:
        parts = files[i][0].split("/")
        parent = 0
        for k in range(2 if group else 1, len(parts)):
            key = "/".join(parts[:k])
            if key not in folders:
                folders[key] = len(rows)
                rows.append([*name(parts[k - 1]), parent])
            parent = folders[key]
        file_folder[i] = parent
    nd, nf = len(rows), len(members)
    file_names = {i: name(files[i][0].rpartition("/")[2]) for i in members}
    kids = [[] for _ in range(nd)]
    for key, node in folders.items():
        if node:
            kids[rows[node][2]].append((key.rpartition("/")[2].encode(), node))
    for k, i in enumerate(members):
        kids[file_folder[i]].append((files[i][0].rpartition("/")[2].encode(), nd + k))
    children, firsts = [], []
    for k in kids:
        firsts.append(len(children))
        children += [node for _, node in sorted(k)]
    folder_bytes = b"".join(struct.pack("<5I", r[0], r[1], r[2], firsts[n], len(kids[n])) for n, r in enumerate(rows))
    file_bytes = bytearray()
    for i in members:
        src = aliases.get(i, i)
        part, offset = at[src]
        file_bytes += struct.pack("<IIIHHQQ", *file_names[i], file_folder[i], part, ALIAS if i in aliases else 0, offset,
                                  files[src][1])
    cap = 1024
    while cap < 2 * (nd + nf):
        cap *= 2
    table = [None] * cap
    for key, node in folders.items():
        if key:   # (the root group's own folder is the romfs root: not looked up through a group)
            _put(table, fnv(key), node)
    for k, i in enumerate(members):
        _put(table, fnv(files[i][0]), nd + k)
    hash_bytes = b"".join(struct.pack("<QII", *(slot or (0, 0)), 0) for slot in table)
    spans, body = _sections(GROUP_HEAD, [folder_bytes, struct.pack("<%dI" % len(children), *children), bytes(file_bytes),
                                         hash_bytes, bytes(names)])
    head = GROUP_MAGIC + struct.pack("<III", VERSION, number, 0) + bid + struct.pack("<IIII", nf, nd, nparts, cap)
    head += b"".join(struct.pack("<QQ", *s) for s in spans)
    head += bytes(GROUP_HEAD - len(head))
    return head + body


def manifest(groups, packs, bid, nfiles):
    """The manifest: groups [(name, first pack, parts, files)], packs [(file name, group, part, file size, index offset,
    index size, index SHA-256)]"""
    names = bytearray()

    def name(text):
        b = text.encode("utf-8")
        off = len(names)
        names.extend(b)
        return off, len(b)
    group_bytes = b"".join(struct.pack("<6I", *name(g[0]), g[1], g[2], g[3], 0) for g in groups)
    pack_bytes = b"".join(struct.pack("<IIIIQQQ", *name(p[0]), p[1], p[2], p[3], p[4], p[5]) + (p[6] or bytes(32))
                          for p in packs)
    spans, body = _sections(MANIFEST_HEAD, [group_bytes, pack_bytes, bytes(names)])
    head = MANIFEST_MAGIC + struct.pack("<III", VERSION, 0, 0) + bid + struct.pack("<IIQ", len(groups), len(packs), nfiles)
    head += b"".join(struct.pack("<QQ", *s) for s in spans)
    head += hashlib.sha256(body).digest()
    assert len(head) == MANIFEST_HEAD
    return head + body


class _Group:
    def __init__(self, name, raw, fds):
        self.name, self.fds = name, fds
        nf, nd, self.nparts, self.cap = struct.unpack_from("<IIII", raw, 0x20)
        spans = [struct.unpack_from("<QQ", raw, 0x30 + 16 * i) for i in range(5)]
        for off, size in spans:
            if off + size > len(raw):
                raise ValueError("group %r: index section outside the index" % name)
        sec = [raw[o:o + n] for o, n in spans]
        self.nd, self.nf, self.names = nd, nf, sec[4]
        self.folders = [struct.unpack_from("<5I", sec[0], 20 * i) for i in range(nd)]
        self.children = struct.unpack_from("<%dI" % (len(sec[1]) // 4), sec[1])
        self.files = [struct.unpack_from("<IIIHHQQ", sec[2], 32 * i) for i in range(nf)]
        self.table = [struct.unpack_from("<QI", sec[3], 16 * i) for i in range(self.cap)]

    def node_name(self, node):
        r = self.folders[node] if node < self.nd else self.files[node - self.nd]
        return self.names[r[0]:r[0] + r[1]].decode("utf-8")

    def path_of(self, node):
        parts = []
        while node != NO_PARENT:
            parts.append(self.node_name(node))
            node = self.folders[node][2] if node < self.nd else self.files[node - self.nd][2]
        return "/".join(p for p in reversed(parts) if p)

    def find(self, path):
        h = fnv(path)
        i = h & (self.cap - 1)
        while self.table[i][0]:
            if self.table[i][0] == h and self.path_of(self.table[i][1]) == path:
                return self.table[i][1]
            i = (i + 1) & (self.cap - 1)
        return None

    def listdir(self, node):
        _, _, _, first, count = self.folders[node]
        return [(self.node_name(c), c < self.nd) for c in self.children[first:first + count]]


class Index:
    """The reference reader: what host/ps5/pak_romfs.c does, in Python. title: the title folder (Data.idx, Data/)"""
    def __init__(self, title):
        with open(os.path.join(title, INDEX_NAME), "rb") as f:
            raw = f.read()
        if len(raw) < MANIFEST_HEAD or raw[:4] != MANIFEST_MAGIC:
            raise ValueError("not a data manifest")
        version = struct.unpack_from("<I", raw, 4)[0]
        if version != VERSION:
            raise ValueError("data manifest version %d, this reader reads %d" % (version, VERSION))
        if hashlib.sha256(raw[MANIFEST_HEAD:]).digest() != raw[0x60:0x80]:
            raise ValueError("data manifest SHA-256 mismatch")
        self.bid = raw[0x10:0x20]
        ng, npk, self.nfiles = struct.unpack_from("<IIQ", raw, 0x20)
        spans = [struct.unpack_from("<QQ", raw, 0x30 + 16 * i) for i in range(3)]
        for off, size in spans:
            if off + size > len(raw):
                raise ValueError("data manifest section outside the file")
        sec = [raw[o:o + n] for o, n in spans]
        names = sec[2]
        text = lambda o, n: names[o:o + n].decode("utf-8")   # noqa: E731
        group_rows = [struct.unpack_from("<6I", sec[0], 24 * i) for i in range(ng)]
        pack_rows = [struct.unpack_from("<IIIIQQQ", sec[1], 72 * i) + (sec[1][72 * i + 40:72 * i + 72],) for i in range(npk)]
        self.fds, self.groups = [], {}
        try:
            for i, (no, nl, group, part, size, ioff, isize, digest) in enumerate(pack_rows):
                path = os.path.join(title, PACKS_FOLDER, text(no, nl))
                if os.path.getsize(path) != size:
                    raise ValueError("%s is %d bytes, the manifest says %d" % (path, os.path.getsize(path), size))
                self.fds.append(open(path, "rb"))
                head = self.fds[-1].read(PACK_HEAD)
                version, number, in_group = struct.unpack_from("<III", head, 4)
                _, at_index, index_size, of_group = struct.unpack_from("<QQQI", head, 0x20)
                if head[:4] != PACK_MAGIC or head[0x10:0x20] != self.bid or version != VERSION or number != i or \
                        in_group != part or (at_index, index_size, of_group) != (ioff, isize, group):
                    raise ValueError("%s is not this manifest's pack %d" % (path, i))
            for g, (no, nl, first, parts, nfiles, _) in enumerate(group_rows):
                last = pack_rows[first + parts - 1]
                f = self.fds[first + parts - 1]
                f.seek(last[5])
                raw_index = f.read(last[6])
                if hashlib.sha256(raw_index).digest() != last[7] or raw_index[:4] != GROUP_MAGIC:
                    raise ValueError("group %r: its index does not match the manifest" % text(no, nl))
                grp = _Group(text(no, nl), raw_index, self.fds[first:first + parts])
                if grp.nf != nfiles or grp.nparts != parts:
                    raise ValueError("group %r: its index does not match the manifest" % text(no, nl))
                self.groups[grp.name] = grp
        except BaseException:
            self.close()
            raise

    def close(self):
        for f in self.fds:
            f.close()

    def _locate(self, path):
        """(group, node) of a path; (None, None) for the root; None when there is none"""
        path = re.sub("/+", "/", path).strip("/")
        if not path:
            return None, None
        if "/" not in path and "" in self.groups:
            node = self.groups[""].find(path)
            if node is not None:
                return self.groups[""], node
        grp = self.groups.get(path.split("/")[0]) if path.split("/")[0] else None
        if grp is None:
            return None
        node = grp.find(path)
        return None if node is None else (grp, node)

    def find(self, path):
        """("dir" | "file") of a path, None when there is none"""
        at = self._locate(path)
        if at is None:
            return None
        grp, node = at
        return "dir" if grp is None or node < grp.nd else "file"

    def listdir(self, path):
        at = self._locate(path)
        if at is None or (at[0] is not None and at[1] >= at[0].nd):
            raise NotADirectoryError(path)
        grp, node = at
        if grp is None:   # (the root: each group's folder in the manifest's order, then the root group's own entries)
            out = [(g, True) for g in self.groups if g]
            if "" in self.groups:
                out += self.groups[""].listdir(0)
            return out
        return grp.listdir(node)

    def read(self, path):
        at = self._locate(path)
        if at is None or at[0] is None or at[1] < at[0].nd:
            raise FileNotFoundError(path)
        grp, node = at
        _, _, _, part, _, offset, size = grp.files[node - grp.nd]
        f = grp.fds[part]
        f.seek(PACK_HEAD + offset)
        data = f.read(size)
        if len(data) != size:
            raise ValueError("%s: the pack ends early" % path)
        return data

    def walk(self):
        """(path, flags) of every file"""
        for grp in self.groups.values():
            for i, r in enumerate(grp.files):
                yield grp.path_of(grp.nd + i), r[4]
