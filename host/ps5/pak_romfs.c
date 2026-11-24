/* PS5: the game's romfs from the title folder's packs (host/ps5/pak_romfs.h). The format is ps5/builder/data_packs.py's (its
   docstring; docs/ps5-data-packs.md): Data.idx, the manifest, names the groups (a top folder each) and their packs; each
   group's index (its folders, its files, a ready hash table) is at the end of the group's last pack.

   At the start the manifest is read and checked, every pack opened and checked against it (size, number, part, group, build
   id, where its group's index is), and every group's index read and checked: every section inside the index, every name,
   child, parent and part in range, every file inside its part's data. After that every lookup follows only checked values,
   nothing is allocated, locked or changed, and any number of threads read at once.

   A path finds its group by its first part (a file at the root: the group "", when there is one), then its node in that
   group's hash table. Paths are matched exactly (case-sensitive, as the console's own romfs), with runs of '/' collapsed
   first: the game asks its voice streams as Voice/Resource//Stream (Longshot issues #1298, #982). */
#define _GNU_SOURCE
#include "pak_romfs.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#define ROOT_LEN (sizeof(PAK_ROMFS_ROOT) - 1)
#define VERSION 2u
#define PACK_HEAD 0x40u
#define GROUP_HEAD 0x80u
#define MANIFEST_HEAD 0x80u
#define NO_PARENT 0xffffffffu
#define MAX_PACKS 1024u
#define MAX_GROUPS 1024u
#define ROOT_NODE 0   /* (the romfs root: the groups; a node of group g is (g + 1) << 32 | its node) */

typedef struct { uint32_t name, len, first, parts, files, pad; } MGroup;
typedef struct { uint32_t name, len, group, part; uint64_t size, index_at, index_size; uint8_t sha[32]; } MPack;
typedef struct { uint32_t name, len, parent, first, count; } Dir;
typedef struct { uint32_t name, len, folder; uint16_t part, flags; uint64_t offset, size; } File;
typedef struct { uint64_t hash; uint32_t node, pad; } Slot;
_Static_assert(sizeof(MGroup) == 24 && sizeof(MPack) == 72 && sizeof(Dir) == 20 && sizeof(File) == 32 && sizeof(Slot) == 16,
               "the format's records");

typedef struct {
    const char *name;
    uint32_t name_len, first_pack, parts;
    uint8_t *raw;
    const Dir *dirs;
    const uint32_t *kids;
    const File *files;
    const Slot *table;
    const char *names;
    uint32_t nd, nf, cap, nkids;
    uint64_t nnames;
} Group;

static uint8_t *manifest;
static Group groups[MAX_GROUPS];
static uint32_t ngroups, npacks;
static int root_group = -1;   /* (the group "": files at the root) */
static int fds[MAX_PACKS];
static uint64_t data_size[MAX_PACKS];
static int ready;
static char why[2048];   /* (a pack's whole path and a sentence) */

const char *pak_romfs_error(void) { return why; }

static uint64_t fnv(const char *s, size_t n) {
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < n; i++) h = (h ^ (uint8_t)s[i]) * 1099511628211ull;
    return h ? h : 1;
}

static int read_all(int fd, void *buf, size_t n, uint64_t at) {
    size_t done = 0;
    while (done < n) {
        const ssize_t r = pread(fd, (char *)buf + done, n - done, (off_t)(at + done));
        if (r < 0 && errno == EINTR) continue;
        if (r <= 0) return 0;
        done += (size_t)r;
    }
    return 1;
}

static void cleanup(void) {
    for (uint32_t i = 0; i < MAX_PACKS; i++)
        if (fds[i] >= 0) close(fds[i]), fds[i] = -1;
    for (uint32_t g = 0; g < MAX_GROUPS; g++) free(groups[g].raw), groups[g].raw = NULL;
    free(manifest), manifest = NULL;
    ngroups = npacks = 0, root_group = -1;
}

/* the sections of an index or the manifest: each inside size, at a multiple of 8 */
static int spans(const uint8_t *raw, uint64_t size, uint32_t at, int count, uint64_t *off, uint64_t *len) {
    for (int i = 0; i < count; i++) {
        memcpy(&off[i], raw + at + 16 * i, 8), memcpy(&len[i], raw + at + 8 + 16 * i, 8);
        if (off[i] % 8 || off[i] > size || len[i] > size - off[i]) return 0;
    }
    return 1;
}

/* (a group's index: every value a lookup will follow) */
static int check_group(Group *G, uint32_t g, uint64_t size, const uint8_t *bid, const char *where) {
    const uint8_t *raw = G->raw;
    uint32_t version, number, parts;
    memcpy(&version, raw + 4, 4), memcpy(&number, raw + 8, 4);
    memcpy(&G->nf, raw + 0x20, 4), memcpy(&G->nd, raw + 0x24, 4), memcpy(&parts, raw + 0x28, 4), memcpy(&G->cap, raw + 0x2c, 4);
    uint64_t off[5], len[5];
    if (size < GROUP_HEAD || memcmp(raw, "LSGI", 4) || version != VERSION || number != g || memcmp(raw + 0x10, bid, 16) ||
        parts != G->parts || !spans(raw, size, 0x30, 5, off, len))
        return snprintf(why, sizeof why, "%s: the index of group %u is not this manifest's", where, g), 0;
    if (!G->nd || !G->cap || (G->cap & (G->cap - 1)) || (uint64_t)G->cap < (uint64_t)G->nd + G->nf ||
        len[0] != 20ull * G->nd || len[1] % 4 || len[2] != 32ull * G->nf || len[3] != 16ull * G->cap)
        return snprintf(why, sizeof why, "%s: the index of group %u has tables of the wrong size", where, g), 0;
    G->dirs = (const Dir *)(raw + off[0]), G->kids = (const uint32_t *)(raw + off[1]), G->files = (const File *)(raw + off[2]);
    G->table = (const Slot *)(raw + off[3]), G->names = (const char *)(raw + off[4]);
    G->nkids = (uint32_t)(len[1] / 4), G->nnames = len[4];
    const uint64_t nodes = (uint64_t)G->nd + G->nf;
    for (uint32_t i = 0; i < G->nd; i++) {
        const Dir *d = &G->dirs[i];
        if ((uint64_t)d->name + d->len > G->nnames || (uint64_t)d->first + d->count > G->nkids ||
            (i ? d->parent >= G->nd || !d->len : d->parent != NO_PARENT))
            return snprintf(why, sizeof why, "%s: group %u, folder %u is out of range", where, g, i), 0;
    }
    if (G->dirs[0].len != G->name_len || memcmp(G->names + G->dirs[0].name, G->name, G->name_len))
        return snprintf(why, sizeof why, "%s: group %u's index is another group's", where, g), 0;
    for (uint32_t i = 0; i < G->nkids; i++)
        if (G->kids[i] >= nodes || G->kids[i] == 0)
            return snprintf(why, sizeof why, "%s: group %u, child %u is out of range", where, g, i), 0;
    for (uint32_t i = 0; i < G->nf; i++) {
        const File *f = &G->files[i];
        const uint64_t room = f->part < G->parts ? data_size[G->first_pack + f->part] : 0;
        if ((uint64_t)f->name + f->len > G->nnames || !f->len || f->folder >= G->nd || f->part >= G->parts ||
            f->offset > room || f->size > room - f->offset)
            return snprintf(why, sizeof why, "%s: group %u, file %u is out of range", where, g, i), 0;
    }
    for (uint32_t i = 0; i < G->cap; i++)
        if (G->table[i].hash && G->table[i].node >= nodes)
            return snprintf(why, sizeof why, "%s: group %u, hash slot %u is out of range", where, g, i), 0;
    return 1;
}

int pak_romfs_open(const char *index_path, const char *packs_dir) {
    if (ready) return 1;
    for (uint32_t i = 0; i < MAX_PACKS; i++) fds[i] = -1;
    const int fd = open(index_path, O_RDONLY);
    struct stat st;
    if (fd < 0 || fstat(fd, &st) || st.st_size < (off_t)MANIFEST_HEAD) {
        snprintf(why, sizeof why, "%s cannot be read (%s)", index_path, fd < 0 ? strerror(errno) : "too short");
        if (fd >= 0) close(fd);
        return 0;
    }
    const uint64_t size = (uint64_t)st.st_size;
    manifest = malloc(size);
    const int got = manifest && read_all(fd, manifest, size, 0);
    close(fd);
    if (!got) {
        snprintf(why, sizeof why, "%s could not be read whole", index_path);
        cleanup();
        return 0;
    }
    /* ---- the manifest ---- */
    uint32_t version;
    uint64_t off[3], len[3];
    memcpy(&version, manifest + 4, 4), memcpy(&ngroups, manifest + 0x20, 4), memcpy(&npacks, manifest + 0x24, 4);
    if (memcmp(manifest, "LSMF", 4)) {
        snprintf(why, sizeof why, "%s is not a data manifest%s", index_path,
                 memcmp(manifest, "LSIX", 4) ? "" : " (it is an older builder's index: build the title folder again)");
        goto bad;
    }
    if (version != VERSION) {
        snprintf(why, sizeof why, "%s is version %u, this title reads version %u: build the title folder again", index_path,
                 version, VERSION);
        goto bad;
    }
    if (!spans(manifest, size, 0x30, 3, off, len) || !ngroups || ngroups > MAX_GROUPS || !npacks || npacks > MAX_PACKS ||
        len[0] != 24ull * ngroups || len[1] != 72ull * npacks) {
        snprintf(why, sizeof why, "%s: its sections are outside the file or of the wrong size: an incomplete copy", index_path);
        goto bad;
    }
    const MGroup *mg = (const MGroup *)(manifest + off[0]);
    const MPack *mp = (const MPack *)(manifest + off[1]);
    const char *mnames = (const char *)(manifest + off[2]);
    uint32_t next = 0;
    for (uint32_t g = 0; g < ngroups; g++) {   /* (groups in pack order, each with its parts one after another) */
        if ((uint64_t)mg[g].name + mg[g].len > len[2] || mg[g].first != next || !mg[g].parts ||
            (uint64_t)mg[g].first + mg[g].parts > npacks) {
            snprintf(why, sizeof why, "%s: group %u's entry is out of range", index_path, g);
            goto bad;
        }
        groups[g].name = mnames + mg[g].name, groups[g].name_len = mg[g].len;
        groups[g].first_pack = mg[g].first, groups[g].parts = mg[g].parts;
        if (!mg[g].len) root_group = (int)g;
        next += mg[g].parts;
    }
    if (next != npacks) {
        snprintf(why, sizeof why, "%s: its groups do not take every pack", index_path);
        goto bad;
    }
    /* ---- the packs ---- */
    const uint8_t *bid = manifest + 0x10;
    for (uint32_t i = 0; i < npacks; i++) {
        const MPack *p = &mp[i];
        const MGroup *owner = p->group < ngroups ? &mg[p->group] : NULL;
        const int last = owner && p->part + 1 == owner->parts;
        if ((uint64_t)p->name + p->len > len[2] || !owner || owner->first + p->part != i || p->size < PACK_HEAD ||
            (last ? !p->index_size || p->index_at < PACK_HEAD || p->index_at > p->size || p->index_size != p->size - p->index_at
                  : p->index_at || p->index_size)) {
            snprintf(why, sizeof why, "%s: pack %u's entry is out of range", index_path, i);
            goto bad;
        }
        char path[1024];
        snprintf(path, sizeof path, "%s/%.*s", packs_dir, (int)p->len, mnames + p->name);
        fds[i] = open(path, O_RDONLY);
        uint8_t head[PACK_HEAD];
        struct stat ps;
        if (fds[i] < 0) {
            snprintf(why, sizeof why, "%s is missing (%s): copy the title folder again", path, strerror(errno));
            goto bad;
        }
        if (fstat(fds[i], &ps) || (uint64_t)ps.st_size != p->size) {
            snprintf(why, sizeof why, "%s is %.1f MiB, the manifest says %.1f MiB: an incomplete copy; copy it again", path,
                     (double)ps.st_size / 1048576.0, (double)p->size / 1048576.0);
            goto bad;
        }
        if (!read_all(fds[i], head, sizeof head, 0) || memcmp(head, "LSPK", 4)) {
            snprintf(why, sizeof why, "%s is not a data pack", path);
            goto bad;
        }
        uint32_t pv, number, part, group;
        uint64_t data, index_at, index_size;
        memcpy(&pv, head + 4, 4), memcpy(&number, head + 8, 4), memcpy(&part, head + 12, 4);
        memcpy(&data, head + 0x20, 8), memcpy(&index_at, head + 0x28, 8), memcpy(&index_size, head + 0x30, 8);
        memcpy(&group, head + 0x38, 4);
        if (pv != VERSION || number != i || part != p->part || group != p->group || memcmp(head + 0x10, bid, 16) ||
            index_at != p->index_at || index_size != p->index_size ||
            (last ? data > index_at - PACK_HEAD : data != p->size - PACK_HEAD)) {
            snprintf(why, sizeof why, "%s is from another build than Data.idx: copy the whole title folder again", path);
            goto bad;
        }
        data_size[i] = data;
    }
    /* ---- each group's index, from its last part ---- */
    for (uint32_t g = 0; g < ngroups; g++) {
        Group *G = &groups[g];
        const uint32_t last = G->first_pack + G->parts - 1;
        const MPack *p = &mp[last];
        G->raw = malloc(p->index_size);
        if (!G->raw || !read_all(fds[last], G->raw, p->index_size, p->index_at)) {
            snprintf(why, sizeof why, "the index of group %u could not be read", g);
            goto bad;
        }
        char where[1100];
        snprintf(where, sizeof where, "%s/%.*s", packs_dir, (int)p->len, mnames + p->name);
        if (!check_group(G, g, p->index_size, bid, where)) goto bad;
    }
    ready = 1;
    uint64_t files = 0;
    for (uint32_t g = 0; g < ngroups; g++) files += groups[g].nf;
    fprintf(stderr, "[ps5] game data: %s, %llu files in %u packs (%u groups, each indexed in its last pack)\n", index_path,
            (unsigned long long)files, npacks, ngroups);
    return 1;
bad:
    cleanup();
    return 0;
}

int pak_romfs_path(const char *path) {
    return ready && !strncmp(path, PAK_ROMFS_ROOT, ROOT_LEN) && (path[ROOT_LEN] == 0 || path[ROOT_LEN] == '/');
}

static void node_name(const Group *G, uint32_t node, const char **s, uint32_t *n, uint32_t *parent) {
    if (node < G->nd) *s = G->names + G->dirs[node].name, *n = G->dirs[node].len, *parent = G->dirs[node].parent;
    else *s = G->names + G->files[node - G->nd].name, *n = G->files[node - G->nd].len, *parent = G->files[node - G->nd].folder;
}

/* whether node's whole path is rel[0, n): its name ends it, its folder's comes before a '/', up to the group's folder */
static int path_is(const Group *G, uint32_t node, const char *rel, size_t n) {
    for (int depth = 0; depth < 256; depth++) {
        const char *s;
        uint32_t len, parent;
        node_name(G, node, &s, &len, &parent);
        if (parent == NO_PARENT) return n == len && !memcmp(rel, s, len);   /* (the group's folder: all of what is left) */
        if (len > n || memcmp(rel + n - len, s, len)) return 0;
        if (parent == 0 && !G->name_len) return n == len;   /* (in the root group's folder, the romfs root) */
        if (n == len || rel[n - len - 1] != '/') return 0;
        n -= len + 1, node = parent;
    }
    return 0;
}

static int64_t lookup(int g, const char *rel, size_t n) {
    const Group *G = &groups[g];
    const uint64_t h = fnv(rel, n);
    for (uint32_t i = (uint32_t)h & (G->cap - 1), tries = 0; tries < G->cap; i = (i + 1) & (G->cap - 1), tries++) {
        if (!G->table[i].hash) return -1;
        if (G->table[i].hash == h && path_is(G, G->table[i].node, rel, n)) return ((int64_t)(g + 1) << 32) | G->table[i].node;
    }
    return -1;
}

int64_t pak_romfs_find(const char *path, int *is_dir, uint64_t *size) {
    if (!pak_romfs_path(path)) return -1;
    char rel[1024];
    size_t n = 0;
    for (const char *p = path + ROOT_LEN; *p; p++) {
        if (*p == '/' && (!n || rel[n - 1] == '/')) continue;
        if (n + 1 >= sizeof rel) return -1;
        rel[n++] = *p;
    }
    while (n && rel[n - 1] == '/') n--;
    if (!n) {
        if (is_dir) *is_dir = 1;
        if (size) *size = 0;
        return ROOT_NODE;
    }
    const char *slash = memchr(rel, '/', n);
    const size_t top = slash ? (size_t)(slash - rel) : n;
    int64_t node = -1;
    if (!slash && root_group >= 0) node = lookup(root_group, rel, n);
    for (uint32_t g = 0; node < 0 && g < ngroups; g++)
        if (groups[g].name_len == top && top && !memcmp(groups[g].name, rel, top)) node = lookup((int)g, rel, n);
    if (node < 0) return -1;
    const Group *G = &groups[(node >> 32) - 1];
    const uint32_t k = (uint32_t)node;
    if (is_dir) *is_dir = k < G->nd;
    if (size) *size = k < G->nd ? 0 : G->files[k - G->nd].size;
    return node;
}

int pak_romfs_file(int64_t node, int *fd, uint64_t *base, uint64_t *size) {
    if (!ready || node <= 0 || (node >> 32) > ngroups) return 0;
    const Group *G = &groups[(node >> 32) - 1];
    const uint32_t k = (uint32_t)node;
    if (k < G->nd || k >= G->nd + G->nf) return 0;
    const File *f = &G->files[k - G->nd];
    *fd = fds[G->first_pack + f->part], *base = PACK_HEAD + f->offset, *size = f->size;
    return 1;
}

int pak_romfs_dir_next(int64_t dir_node, uint32_t *cursor, const char **name, size_t *name_len, int *is_dir,
                       uint64_t *size) {
    if (!ready || dir_node < 0) return 0;
    if (dir_node == ROOT_NODE) {   /* (the root: each group's folder, then the root group's own entries) */
        while (*cursor < ngroups) {
            const Group *G = &groups[(*cursor)++];
            if (!G->name_len) continue;
            *name = G->name, *name_len = G->name_len, *is_dir = 1, *size = 0;
            return 1;
        }
        if (root_group < 0) return 0;
        uint32_t inner = *cursor - ngroups;
        const int64_t root_dir = (int64_t)(root_group + 1) << 32;
        const int more = pak_romfs_dir_next(root_dir, &inner, name, name_len, is_dir, size);
        *cursor = ngroups + inner;
        return more;
    }
    if ((dir_node >> 32) > ngroups) return 0;
    const Group *G = &groups[(dir_node >> 32) - 1];
    const uint32_t k = (uint32_t)dir_node;
    if (k >= G->nd) return 0;
    const Dir *d = &G->dirs[k];
    if (*cursor >= d->count) return 0;
    const uint32_t c = G->kids[d->first + (*cursor)++];
    uint32_t len, parent;
    node_name(G, c, name, &len, &parent);
    *name_len = len, *is_dir = c < G->nd, *size = c < G->nd ? 0 : G->files[c - G->nd].size;
    return 1;
}

int64_t pak_romfs_read(const char *path, void *buf, uint64_t cap_bytes) {
    int dir = 0;
    int fd;
    uint64_t base, size;
    const int64_t node = pak_romfs_find(path, &dir, NULL);
    if (node < 0 || dir || !pak_romfs_file(node, &fd, &base, &size)) return -1;
    if (buf && size <= cap_bytes && !read_all(fd, buf, (size_t)size, base)) return -1;
    return (int64_t)size;
}
