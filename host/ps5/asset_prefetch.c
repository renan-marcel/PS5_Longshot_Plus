/* PS5: reading the game's files ahead of it. What and why: asset_prefetch.h, docs/ps5-asset-prefetch.md.

   Threads: the game's (any number, through win32_posix.c's file calls) and one of this module's, which reads ahead. One
   mutex guards the bucket, the queue and the counters; a game read holds it only to look up and pin an entry (the copy is
   made unlocked), and the thread holds it never while it reads the disk. Events from the game (a scene's parameters
   opened, the current scene) are only noted: the thread turns them into a queue, so the game's threads never walk Data.deps
   or touch the disk on this module's behalf. */
#include "asset_prefetch.h"

#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#include "pak_romfs.h"

void hos_log(const char *fmt, ...);
/* (host/ps5/win32_ps5.c: the title's free direct memory; absent in the checks, which have memory to spare) */
__attribute__((weak)) uint64_t hos_ps5_direct_room(void);
extern void rx_vk_evict_unwanted_zone(int target_zone) __attribute__((weak));
extern size_t hos_ps5_trim_free_units(size_t keep_bytes) __attribute__((weak));
/* (host/ps5/pak_romfs.c: the packs' build id, which Data.deps must name) */
const uint8_t *pak_romfs_build_id(void);

#define DEPS_MAGIC "LSDP"
#define DEPS_VERSION 2u        /* (1 is read too: each scene a zone of its own) */
#define DEPS_HEAD 0x80u
#define DEPS_HEAD_V2 0xD0u      /* (version 2: the zone tables, offsets at 0x80) */
#define BUCKETS 4096u
#define PROFILE_MAX 6000u        /* (lines kept per scene) */
#define SCENE_MAX 96
#define BURST_GAP_MS 300.0       /* (reads further apart than this are two bursts) */
#define BURST_LOG_MS 500.0       /* (a burst this long is logged: a scene's load) */
#define CHUNK (1u << 20)         /* (the thread reads a file in pieces of this, giving way to the game between them) */

/* ---------------------------------------------------------------------------------------------- the switches */
static int on_stats = 1, on_bucket = 0, on_learn = 1;
static uint64_t cap_bytes = 192ull << 20, max_file = 16ull << 20, reserve_bytes = 2200ull << 20, margin_bytes = 512ull << 20;

static uint64_t env_mb(const char *name, uint64_t dflt) {
    const char *v = getenv(name);
    return v && *v ? (uint64_t)strtoull(v, NULL, 10) << 20 : dflt;
}
static int env_on(const char *name, int dflt) {
    const char *v = getenv(name);
    return v && *v ? strcmp(v, "0") != 0 : dflt;
}

static double now_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec * 1e3 + t.tv_nsec / 1e6;
}

static uint64_t fnv(const char *s, size_t n) {
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < n; i++) h = (h ^ (uint8_t)s[i]) * 1099511628211ull;
    return h;
}

/* ---------------------------------------------------------------------------------------------- Data.deps */
typedef struct { uint32_t name, len, first, count, nfirst, ncount; uint64_t bytes; } DScene;
static uint8_t *deps;
static size_t deps_size;
static const DScene *dscenes;
static const uint32_t *dlists, *dpaths, *dnbrs;
static const char *dnames;
static uint32_t nscenes, npaths;
static uint64_t nlists, nnbrs, names_size;
/* (version 2) the zones: a scene's zone is its maps' folder (ps5/builder/asset_deps.py zones) */
typedef struct { uint32_t name, len, sfirst, scount, ffirst, fcount, nfirst, ncount; } DZone;
static const DZone *dzones;
static const uint32_t *dzscenes, *dzfiles, *dznbrs, *dscene_zone;
static uint64_t nzones;

static int deps_load(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    if (size < (long)DEPS_HEAD || size > (64l << 20)) { fclose(f); return -1; }
    uint8_t *raw = (uint8_t *)malloc((size_t)size);
    if (!raw || fread(raw, 1, (size_t)size, f) != (size_t)size) { fclose(f); free(raw); return -1; }
    fclose(f);
    uint32_t version;
    uint64_t sc, li, pa, na, nb;
    memcpy(&version, raw + 4, 4), memcpy(&nscenes, raw + 8, 4), memcpy(&npaths, raw + 12, 4);
    memcpy(&sc, raw + 0x20, 8), memcpy(&li, raw + 0x28, 8), memcpy(&nlists, raw + 0x30, 8), memcpy(&pa, raw + 0x38, 8);
    memcpy(&na, raw + 0x40, 8), memcpy(&names_size, raw + 0x48, 8), memcpy(&nb, raw + 0x50, 8), memcpy(&nnbrs, raw + 0x58, 8);
    const uint8_t *bid = pak_romfs_build_id();
    const uint64_t s = (uint64_t)size;
    /* (every section inside the file, at a multiple of 4, and the build id the packs': the format's own checks; its SHA-256
       is the builder's to check, ps5/builder/asset_deps.py decode) */
    if (memcmp(raw, DEPS_MAGIC, 4) || (version != 1 && version != DEPS_VERSION) || !bid || memcmp(raw + 0x10, bid, 16) || nscenes > SCENE_MAX * 4 ||
        sc % 4 || li % 4 || pa % 4 || nb % 4 || sc > s || (uint64_t)nscenes * 32 > s - sc || li > s || nlists * 4 > s - li ||
        pa > s || (uint64_t)npaths * 8 > s - pa || nb > s || nnbrs * 4 > s - nb || na > s || names_size > s - na) {
        free(raw);
        return -1;
    }
    dscenes = (const DScene *)(raw + sc), dlists = (const uint32_t *)(raw + li), dpaths = (const uint32_t *)(raw + pa);
    dnbrs = (const uint32_t *)(raw + nb), dnames = (const char *)(raw + na);
    for (uint32_t i = 0; i < nscenes; i++) {
        const DScene *d = &dscenes[i];
        if ((uint64_t)d->name + d->len > names_size || (uint64_t)d->first + d->count > nlists ||
            (uint64_t)d->nfirst + d->ncount > nnbrs) { free(raw); dscenes = NULL; return -1; }
    }
    for (uint64_t i = 0; i < nlists; i++)
        if (dlists[i] >= npaths) { free(raw); dscenes = NULL; return -1; }
    for (uint64_t i = 0; i < nnbrs; i++)
        if (dnbrs[i] >= nscenes) { free(raw); dscenes = NULL; return -1; }
    for (uint32_t i = 0; i < npaths; i++)
        if ((uint64_t)dpaths[2 * i] + dpaths[2 * i + 1] > names_size) { free(raw); dscenes = NULL; return -1; }
    dzones = NULL, nzones = 0;
    if (version >= 2) {   /* (the zones, each section inside the file and every index in range; else the map is refused) */
        uint64_t zo, nz, zso, nzs, zfo, nzf, zno, nzn, szo;
        if ((uint64_t)size < DEPS_HEAD_V2) { free(raw); dscenes = NULL; return -1; }
        memcpy(&zo, raw + 0x80, 8), memcpy(&nz, raw + 0x88, 8), memcpy(&zso, raw + 0x90, 8), memcpy(&nzs, raw + 0x98, 8);
        memcpy(&zfo, raw + 0xA0, 8), memcpy(&nzf, raw + 0xA8, 8), memcpy(&zno, raw + 0xB0, 8), memcpy(&nzn, raw + 0xB8, 8);
        memcpy(&szo, raw + 0xC0, 8);
        int bad = zo % 4 || zso % 4 || zfo % 4 || zno % 4 || szo % 4 || zo > s || nz > nscenes || nz * 32 > s - zo || zso > s ||
                  nzs * 4 > s - zso || zfo > s || nzf * 4 > s - zfo || zno > s || nzn * 4 > s - zno || szo > s ||
                  (uint64_t)nscenes * 4 > s - szo;
        const DZone *z = (const DZone *)(raw + zo);
        const uint32_t *zs = (const uint32_t *)(raw + zso), *zf = (const uint32_t *)(raw + zfo), *zn = (const uint32_t *)(raw + zno),
                       *sz = (const uint32_t *)(raw + szo);
        for (uint64_t i = 0; !bad && i < nz; i++)
            bad = (uint64_t)z[i].name + z[i].len > names_size || (uint64_t)z[i].sfirst + z[i].scount > nzs ||
                  (uint64_t)z[i].ffirst + z[i].fcount > nzf || (uint64_t)z[i].nfirst + z[i].ncount > nzn;
        for (uint64_t i = 0; !bad && i < nzs; i++) bad = zs[i] >= nscenes;
        for (uint64_t i = 0; !bad && i < nzf; i++) bad = zf[i] >= npaths;
        for (uint64_t i = 0; !bad && i < nzn; i++) bad = zn[i] >= nz;
        for (uint32_t i = 0; !bad && i < nscenes; i++) bad = sz[i] >= nz;
        if (bad) { free(raw); dscenes = NULL; return -1; }
        dzones = z, dzscenes = zs, dzfiles = zf, dznbrs = zn, dscene_zone = sz, nzones = nz;
    }
    deps = raw, deps_size = (size_t)size;
    return 1;
}

static int deps_scene(const char *name) {
    const size_t n = strlen(name);
    for (uint32_t i = 0; i < nscenes && deps; i++)
        if (dscenes[i].len == n && !memcmp(dnames + dscenes[i].name, name, n)) return (int)i;
    return -1;
}

/* The zone of a scene: its zone's name (version 2), else the scene itself; into out (cap), "" for an empty scene */
static void zone_of(const char *scene, char *out, size_t cap) {
    const int s = scene && scene[0] ? deps_scene(scene) : -1;
    if (s >= 0 && dzones) {
        const DZone *z = &dzones[dscene_zone[s]];
        snprintf(out, cap, "%.*s", (int)z->len, dnames + z->name);
    } else {
        snprintf(out, cap, "%s", scene ? scene : "");
    }
}

/* ---------------------------------------------------------------------------------------------- the bucket */
typedef struct {
    int used, fd, ready, next;
    uint64_t base, size, served, last_use;
    uint32_t pins, want_gen, consumed;   /* (consumed: the game read it whole meanwhile, from the disk or from here) */
    uint8_t *data;
} Entry;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t work = PTHREAD_COND_INITIALIZER, idle = PTHREAD_COND_INITIALIZER;
static Entry *entries;
static int nentries, free_entry = -1, heads[BUCKETS];
static uint64_t held, use_clock;
static uint32_t gen = 1;
static AssetPrefetchStats st;

static unsigned slot_of(int fd, uint64_t base) { return (unsigned)((base * 0x9E3779B97F4A7C15ull ^ (uint64_t)fd) >> 52) % BUCKETS; }

static int find_entry(int fd, uint64_t base) {
    for (int i = heads[slot_of(fd, base)]; i >= 0; i = entries[i].next)
        if (entries[i].fd == fd && entries[i].base == base) return i;
    return -1;
}

static int add_entry(int fd, uint64_t base, uint64_t size) {
    int i = free_entry;
    if (i >= 0) {
        free_entry = entries[i].next;
    } else {
        Entry *grown = (Entry *)realloc(entries, sizeof *entries * (size_t)(nentries + 1));
        if (!grown) return -1;
        entries = grown, i = nentries++;
    }
    const unsigned s = slot_of(fd, base);
    memset(&entries[i], 0, sizeof entries[i]);
    entries[i].used = 1, entries[i].fd = fd, entries[i].base = base, entries[i].size = size, entries[i].next = heads[s];
    heads[s] = i;
    st.entries++;
    return i;
}

static void drop_entry(int i) {   /* (mu held; never a pinned one) */
    Entry *e = &entries[i];
    const unsigned s = slot_of(e->fd, e->base);
    for (int *p = &heads[s]; *p >= 0; p = &entries[*p].next)
        if (*p == i) { *p = e->next; break; }
    if (e->data) held -= e->size, free(e->data);
    memset(e, 0, sizeof *e);
    e->next = free_entry, free_entry = i;
    st.entries--;
}

/* ---------------------------------------------------------------------------------------------- the measurements */
typedef struct { uint64_t opens, disk_reads, disk_bytes, hits, hit_bytes; double disk_ms, max_ms; } Window;
static Window win;
static double burst_first = -1, burst_last, burst_disk_ms;
static uint64_t burst_bytes, burst_reads, burst_hits;
static char scene_now[SCENE_MAX], scene_loading[SCENE_MAX];

static void burst_note(double t, double ms, uint64_t bytes, int hit) {   /* (mu held) */
    if (burst_first >= 0 && t - burst_last > BURST_GAP_MS) {
        const double wall = burst_last - burst_first;
        if (on_stats && wall >= BURST_LOG_MS)
            hos_log("io: a burst of reading (%s): %.2f s, the disk %.2f s of it (%.0f%%), %llu reads, %.1f MB, %llu from the "
                    "bucket", scene_loading[0] ? scene_loading : scene_now[0] ? scene_now : "before the first scene",
                    wall / 1e3, burst_disk_ms / 1e3, wall > 0 ? 100.0 * burst_disk_ms / wall : 0.0,
                    (unsigned long long)burst_reads, burst_bytes / 1e6, (unsigned long long)burst_hits);
        burst_first = -1;
    }
    if (burst_first < 0) burst_first = t, burst_disk_ms = 0, burst_bytes = burst_reads = burst_hits = 0;
    burst_last = t + ms, burst_disk_ms += ms, burst_bytes += bytes, burst_reads++, burst_hits += (uint64_t)hit;
}

static void window_log(const char *scene) {   /* (mu held) */
    if (on_stats && (win.opens || win.disk_reads || win.hits))
        hos_log("io: %s: %llu files opened, %llu reads from the disk (%.1f MB in %.2f s, the longest %.0f ms), %llu from the "
                "bucket (%.1f MB); the bucket holds %.1f MB", scene[0] ? scene : "before the first scene",
                (unsigned long long)win.opens, (unsigned long long)win.disk_reads, win.disk_bytes / 1e6, win.disk_ms / 1e3,
                win.max_ms, (unsigned long long)win.hits, win.hit_bytes / 1e6, held / 1e6);
    memset(&win, 0, sizeof win);
}

/* ---------------------------------------------------------------------------------------------- what each scene opened */
typedef struct { char **paths; uint32_t n, cap; uint64_t *seen; uint32_t seen_cap; } PathList;
static PathList visit;   /* (this visit's opens, for the scene in scene_loading or scene_now) */
static char visit_scene[SCENE_MAX], title[1024];

static int list_has_add(PathList *l, const char *p, size_t n) {   /* 1 when it was new */
    if ((l->n + 1) * 2 > l->seen_cap) {
        const uint32_t cap = l->seen_cap ? l->seen_cap * 2 : 1024;
        uint64_t *s = (uint64_t *)calloc(cap, 8);
        if (!s) return 0;
        for (uint32_t i = 0; i < l->seen_cap; i++)
            if (l->seen[i])
                for (uint32_t k = (uint32_t)(l->seen[i] & (cap - 1));; k = (k + 1) & (cap - 1))
                    if (!s[k]) { s[k] = l->seen[i]; break; }
        free(l->seen), l->seen = s, l->seen_cap = cap;
    }
    const uint64_t h = fnv(p, n) | 1;
    uint32_t k = (uint32_t)(h & (l->seen_cap - 1));
    for (; l->seen[k]; k = (k + 1) & (l->seen_cap - 1))
        if (l->seen[k] == h) return 0;
    if (l->n == l->cap) {
        const uint32_t cap = l->cap ? l->cap * 2 : 256;
        char **grown = (char **)realloc(l->paths, sizeof *grown * cap);
        if (!grown) return 0;
        l->paths = grown, l->cap = cap;
    }
    char *c = (char *)malloc(n + 1);
    if (!c) return 0;
    memcpy(c, p, n), c[n] = 0;
    l->seen[k] = h, l->paths[l->n++] = c;
    return 1;
}

static void list_free(PathList *l) {
    for (uint32_t i = 0; i < l->n; i++) free(l->paths[i]);
    free(l->paths), free(l->seen);
    memset(l, 0, sizeof *l);
}

static void profile_path(char *out, size_t cap, const char *scene) {
    snprintf(out, cap, "%s/cache/prefetch/%s.txt", title, scene);
}

static int scene_name_ok(const char *s) {   /* (a file name: letters, digits, _ and -) */
    if (!s[0]) return 0;
    for (const char *p = s; *p; p++)
        if (!((*p >= 'A' && *p <= 'Z') || (*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9') || *p == '_' || *p == '-'))
            return 0;
    return 1;
}

static void profile_read(const char *scene, PathList *out) {
    char path[1200], line[1024];
    if (!scene_name_ok(scene)) return;
    profile_path(path, sizeof path, scene);
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && out->n < PROFILE_MAX) {
        size_t n = strlen(line);
        while (n && (line[n - 1] == '\n' || line[n - 1] == '\r')) line[--n] = 0;
        if (n && line[0] != '#') list_has_add(out, line, n);
    }
    fclose(f);
}

/* This visit's opens into the scene's profile: what it had, then what is new, in the order first opened. Written whole under
   another name, then renamed, so a profile is never half written. */
static void profile_save(const char *scene, PathList *seen_now) {
    if (!on_learn || !title[0] || !scene_name_ok(scene) || !seen_now->n) return;
    PathList all = {0};
    profile_read(scene, &all);
    const uint32_t had = all.n;
    for (uint32_t i = 0; i < seen_now->n && all.n < PROFILE_MAX; i++) list_has_add(&all, seen_now->paths[i], strlen(seen_now->paths[i]));
    if (all.n != had) {
        char dir[1100], path[1200], tmp[1210];
        snprintf(dir, sizeof dir, "%s/cache", title), mkdir(dir, 0777);
        snprintf(dir, sizeof dir, "%s/cache/prefetch", title), mkdir(dir, 0777);
        profile_path(path, sizeof path, scene);
        snprintf(tmp, sizeof tmp, "%s.part", path);
        FILE *f = fopen(tmp, "w");
        if (f) {
            fprintf(f, "# the files %s opened, in order (host/ps5/asset_prefetch.c); delete to start again\n", scene);
            for (uint32_t i = 0; i < all.n; i++) fprintf(f, "%s\n", all.paths[i]);
            if (fclose(f) == 0) rename(tmp, path);
            else remove(tmp);
        }
    }
    list_free(&all);
}

/* ---------------------------------------------------------------------------------------------- the queue */
typedef struct { const char *path; size_t len; } Want;
static Want *queue;
static size_t qn, qcap, qat;
static PathList qlearned[1 + 16];   /* (the profiles the queue points into: the scene's, then its neighbours') */
static uint32_t nlearned;
static char ev_loading[SCENE_MAX], ev_settled[SCENE_MAX];
static int ev_pending, quit, running;
static pthread_t thread;

static void queue_add(const char *p, size_t n) {
    if (qn == qcap) {
        const size_t cap = qcap ? qcap * 2 : 4096;
        Want *grown = (Want *)realloc(queue, sizeof *grown * cap);
        if (!grown) return;
        queue = grown, qcap = cap;
    }
    queue[qn].path = p, queue[qn].len = n, qn++;
}

/* A scene's wants, its profile first (what it really opened, in order), then Data.deps' list. Into slot li of qlearned */
static void scene_wants(const char *scene, uint32_t li, Want **out, size_t *nout) {
    *out = NULL, *nout = 0;
    PathList *l = &qlearned[li];
    list_free(l);
    if (on_learn) profile_read(scene, l);
    const int s = deps_scene(scene);
    const size_t total = l->n + (s >= 0 ? dscenes[s].count : 0);
    if (!total) return;
    Want *w = (Want *)malloc(sizeof *w * total);
    if (!w) return;
    size_t n = 0;
    for (uint32_t i = 0; i < l->n; i++) w[n].path = l->paths[i], w[n].len = strlen(l->paths[i]), n++;
    if (s >= 0)
        for (uint32_t i = 0; i < dscenes[s].count; i++) {
            const uint32_t p = dlists[dscenes[s].first + i];
            const char *name = dnames + dpaths[2 * p];
            const size_t len = dpaths[2 * p + 1];
            if (l->n) {   /* (already in the profile) */
                const uint64_t h = fnv(name, len) | 1;
                int dup = 0;
                for (uint32_t k = (uint32_t)(h & (l->seen_cap - 1)); l->seen[k]; k = (k + 1) & (l->seen_cap - 1))
                    if (l->seen[k] == h) { dup = 1; break; }
                if (dup) continue;
            }
            w[n].path = name, w[n].len = len, n++;
        }
    *out = w, *nout = n;
}

/* The queue for an event: loading a scene (its own wants, all of them first) or a scene settled (the scenes it leads to,
   taken in turn a file at a time, so each gets its surest files first while the bucket has room). (mu not held) */
static void queue_build(const char *loading, const char *settled) {
    qn = qat = 0;
    for (uint32_t i = 0; i < nlearned; i++) list_free(&qlearned[i]);
    nlearned = 0;
    const char *own = loading[0] ? loading : settled;
    Want *w;
    size_t n;
    scene_wants(own, nlearned++, &w, &n);
    for (size_t i = 0; i < n; i++) queue_add(w[i].path, w[i].len);
    free(w);
    const int s = deps_scene(own);
    if (settled[0] && s >= 0) {
        Want *nw[16];
        size_t nn[16], at[16], k = 0;
        for (uint32_t i = 0; i < dscenes[s].ncount && k < 16; i++, k++) {
            const DScene *d = &dscenes[dnbrs[dscenes[s].nfirst + i]];
            char name[SCENE_MAX];
            snprintf(name, sizeof name, "%.*s", (int)d->len, dnames + d->name);
            scene_wants(name, nlearned++, &nw[k], &nn[k]);
            at[k] = 0;
        }
        for (int more = 1; more;) {
            more = 0;
            for (size_t i = 0; i < k; i++)
                if (at[i] < nn[i]) queue_add(nw[i][at[i]].path, nw[i][at[i]].len), at[i]++, more = 1;
        }
        for (size_t i = 0; i < k; i++) free(nw[i]);
    }
}

/* ---------------------------------------------------------------------------------------------- the thread */
static volatile int game_reading;   /* (the game's reads from the disk going on: the thread gives way) */

static int room_ok(uint64_t more) {   /* (the title's free memory, beyond what the game and the renderer need) */
    if (!hos_ps5_direct_room) return 1;
    const uint64_t room = hos_ps5_direct_room();
    return room > reserve_bytes + margin_bytes + more;
}

/* Let go, oldest first: FIT what the current wants do not name until need more bytes fit; UNWANTED all of what they do
   not name; ALL everything (the title's memory is short). (mu held) */
enum { FIT, UNWANTED, ALL };
static void evict(uint64_t need, int mode) {
    for (;;) {
        if (mode == FIT && held + need <= cap_bytes) return;
        int best = -1;
        for (int i = 0; i < nentries; i++) {
            const Entry *e = &entries[i];
            if (!e->used || e->pins || !e->ready || (mode != ALL && e->want_gen == gen)) continue;
            if (best < 0 || e->last_use < entries[best].last_use) best = i;
        }
        if (best < 0) return;
        drop_entry(best);
        st.evicted++;
    }
}

static void *run(void *arg) {
    (void)arg;
    char path[1200];
    pthread_mutex_lock(&mu);
    while (!quit) {
        if (ev_pending) {   /* (a scene event: a new queue, and what it no longer wants goes) */
            char loading[SCENE_MAX], settled[SCENE_MAX];
            memcpy(loading, ev_loading, sizeof loading), memcpy(settled, ev_settled, sizeof settled);
            ev_pending = 0;
            gen++;
            pthread_mutex_unlock(&mu);
            queue_build(loading, settled);
            pthread_mutex_lock(&mu);
            if (settled[0]) {
                /* (mark what the new queue names, then let go of the rest) */
                for (size_t i = 0; i < qn; i++) {
                    snprintf(path, sizeof path, PAK_ROMFS_ROOT "/%.*s", (int)queue[i].len, queue[i].path);
                    int fd, dir = 0;
                    uint64_t base, size;
                    const int64_t node = pak_romfs_find(path, &dir, NULL);
                    if (node < 0 || dir || !pak_romfs_file(node, &fd, &base, &size)) continue;
                    const int e = find_entry(fd, base);
                    if (e >= 0) entries[e].want_gen = gen;
                }
                evict(0, UNWANTED);
            }
            if (on_bucket && held && !room_ok(0)) {   /* (memory short at a scene change: give it all back) */
                evict(0, ALL);
                qat = qn;
                hos_log("io: the bucket stops: the title's free memory is near what the game needs (HOS_PS5_TEX_RESERVE_MB + "
                        "HOS_PREFETCH_MARGIN_MB)");
            }
            continue;
        }
        if (qat >= qn || !on_bucket) {
            pthread_cond_broadcast(&idle);
            pthread_cond_wait(&work, &mu);
            continue;
        }
        const Want w = queue[qat++];
        snprintf(path, sizeof path, PAK_ROMFS_ROOT "/%.*s", (int)w.len, w.path);
        int fd, dir = 0;
        uint64_t base, size;
        const int64_t node = pak_romfs_find(path, &dir, NULL);
        if (node < 0 || dir || !pak_romfs_file(node, &fd, &base, &size) || !size || size > max_file) continue;
        const int have = find_entry(fd, base);
        if (have >= 0) { entries[have].want_gen = gen; continue; }
        if (held + size > cap_bytes) evict(size, FIT);
        if (held + size > cap_bytes) { qat = qn; continue; }   /* (full of what is wanted: the rest of the queue waits) */
        if (!room_ok(size)) {   /* (the title's memory is short: give it all back and stop until the next scene) */
            evict(0, ALL);
            qat = qn;
            hos_log("io: the bucket stops: the title's free memory is near what the game needs (HOS_PS5_TEX_RESERVE_MB + "
                    "HOS_PREFETCH_MARGIN_MB)");
            continue;
        }
        uint8_t *data = (uint8_t *)malloc((size_t)size);
        const int e = data ? add_entry(fd, base, size) : -1;
        if (e < 0) { free(data); qat = qn; continue; }
        entries[e].pins = 1, entries[e].want_gen = gen, held += size;
        const uint32_t g = gen;
        pthread_mutex_unlock(&mu);
        uint64_t done = 0;
        int ok = 1;
        while (done < size && ok) {
            for (int waited = 0; game_reading > 0 && waited < 20; waited++) usleep(1000);   /* (the game's reads first) */
            const size_t piece = size - done < CHUNK ? (size_t)(size - done) : CHUNK;
            const ssize_t r = pread(fd, data + done, piece, (off_t)(base + done));
            if (r < 0 && errno == EINTR) continue;
            if (r <= 0) ok = 0;
            else done += (uint64_t)r;
        }
        pthread_mutex_lock(&mu);
        Entry *en = &entries[e];
        en->data = data, en->pins = 0;
        if (!ok || en->consumed || quit) {   /* (a short read, or the game read it whole from the disk meanwhile) */
            drop_entry(e);
            continue;
        }
        en->ready = 1, en->last_use = ++use_clock;
        st.prefetched++, st.prefetched_bytes += size;
        if (g != gen) en->want_gen = g;   /* (an event came meanwhile: the next one decides) */
    }
    running = 0;
    pthread_cond_broadcast(&idle);
    pthread_mutex_unlock(&mu);
    return NULL;
}

/* ---------------------------------------------------------------------------------------------- the game's side */
void asset_prefetch_init(const char *title_dir) {
    on_stats = env_on("HOS_IO_STATS", 1);
    on_bucket = env_on("HOS_PREFETCH", 0);
    on_learn = env_on("HOS_PREFETCH_LEARN", 1);
    cap_bytes = env_mb("HOS_PREFETCH_MB", 192ull << 20);
    max_file = env_mb("HOS_PREFETCH_FILE_MB", 16ull << 20);
    reserve_bytes = env_mb("HOS_PS5_TEX_RESERVE_MB", 2200ull << 20);   /* (gpu/vk/vk_texture.cpp ps5_tex_reserve's default) */
    margin_bytes = env_mb("HOS_PREFETCH_MARGIN_MB", 512ull << 20);
    snprintf(title, sizeof title, "%s", title_dir ? title_dir : "");
    for (unsigned i = 0; i < BUCKETS; i++) heads[i] = -1;
    char path[1100];
    snprintf(path, sizeof path, "%s/Data.deps", title);
    const int got = deps_load(path);
    if (on_bucket || on_stats)
        hos_log("io: prefetch %s%s, measuring %s, learning %s (bucket %llu MB)", on_bucket ? "on" : "off (HOS_PREFETCH=1)",
                got > 0 ? ", Data.deps read" : got < 0 ? ", Data.deps refused (another build's packs, or damaged)" :
                                                         ", no Data.deps (the profiles only)",
                on_stats ? "on" : "off", on_learn ? "on" : "off", (unsigned long long)(cap_bytes >> 20));
    if ((on_bucket || on_learn) && pthread_create(&thread, NULL, run, NULL) == 0) running = 1;
}

static void event(const char *loading, const char *settled) {   /* (mu held) */
    snprintf(ev_loading, sizeof ev_loading, "%s", loading);
    snprintf(ev_settled, sizeof ev_settled, "%s", settled);
    ev_pending = 1;
    pthread_cond_signal(&work);
}

static void visit_close(void) {   /* (mu held; a scene's visit ends: its opens into its profile) */
    if (visit_scene[0] && visit.n) {
        PathList done = visit;
        memset(&visit, 0, sizeof visit);
        char scene[SCENE_MAX];
        memcpy(scene, visit_scene, sizeof scene);
        pthread_mutex_unlock(&mu);
        profile_save(scene, &done);   /* (a small file, written by the game's thread that saw the scene change) */
        list_free(&done);
        pthread_mutex_lock(&mu);
    }
    list_free(&visit);
    visit_scene[0] = 0;
}

static char zone_now[SCENE_MAX];
static int last_evicted_zone = -1;
static asset_zone_cb zone_cb;
void asset_prefetch_on_zone(asset_zone_cb cb) { __atomic_store_n(&zone_cb, cb, __ATOMIC_RELEASE); }

/* Caller holds mu and guarantees dzones != NULL && own < nzones && path != NULL. */
static int zone_wanted_locked(uint32_t own, const char *path, size_t n) {
    int want = 0;
    for (uint32_t k = 0; !want && k <= dzones[own].ncount; k++) {
        const DZone *z = &dzones[k == 0 ? own : dznbrs[dzones[own].nfirst + k - 1]];
        for (uint32_t f = 0; !want && f < z->fcount; f++) {
            const uint32_t pi = dzfiles[z->ffirst + f];
            want = dpaths[2 * pi + 1] == n && !memcmp(dnames + dpaths[2 * pi], path, n);
        }
    }
    return want;
}

/* Whether zone_idx, or a zone it leads to, reads path (a romfs path); 1 when not known */
int asset_prefetch_zone_wanted_for(int zone_idx, const char *path) {
    if (zone_idx < 0 || !path) return 1;
    const size_t n = strlen(path);
    pthread_mutex_lock(&mu);
    int want = 1;
    if (deps && dzones && (uint64_t)zone_idx < nzones) {
        want = zone_wanted_locked((uint32_t)zone_idx, path, n);
    }
    pthread_mutex_unlock(&mu);
    return want;
}

/* Whether the current zone, or a zone it leads to, reads path (a romfs path); 1 when not known (no zones in the map) */
int asset_prefetch_zone_wanted(const char *path) {
    if (!path) return 1;
    const size_t n = strlen(path);
    pthread_mutex_lock(&mu);
    int known = 0, want = 0;
    const int s = scene_now[0] ? deps_scene(scene_now) : -1;
    if (s >= 0 && dzones) {
        known = 1;
        want = zone_wanted_locked(dscene_zone[s], path, n);
    }
    pthread_mutex_unlock(&mu);
    return known ? want : 1;
}

/* The game's current zone (its scene's: asset_prefetch_scene_now), "" before the first */
const char *asset_prefetch_zone_now(void) { return zone_now; }

void asset_prefetch_scene(const char *scene) {
    if (!scene || !scene[0]) return;
    char old_zone[SCENE_MAX], new_zone[SCENE_MAX];
    old_zone[0] = new_zone[0] = 0;
    int evict_zone = -1;
    pthread_mutex_lock(&mu);
    if (strcmp(scene, scene_now)) {
        window_log(scene_loading[0] ? scene_loading : scene_now);   /* (the window that ends: the load just seen, if any) */
        if (strcmp(visit_scene, scene)) {   /* (not the scene whose load was seen: a visit begins here) */
            visit_close();
            snprintf(visit_scene, sizeof visit_scene, "%s", scene);
        }
        snprintf(scene_now, sizeof scene_now, "%s", scene);
        scene_loading[0] = 0;
        if (on_stats) hos_log("io: scene %s", scene);
        event("", scene);
        zone_of(scene, new_zone, sizeof new_zone);
        if (strcmp(new_zone, zone_now)) {   /* (a zone change: told once, after the lock, so the callback may call in) */
            snprintf(old_zone, sizeof old_zone, "%s", zone_now);
            snprintf(zone_now, sizeof zone_now, "%s", new_zone);
            const int s = deps_scene(scene);
            if (s >= 0 && dzones) {
                const int new_zone_idx = (int)dscene_zone[s];
                if (new_zone_idx >= 0) {
                    last_evicted_zone = new_zone_idx;
                    evict_zone = new_zone_idx;
                }
            }
        } else {
            new_zone[0] = 0;
        }
    }
    pthread_mutex_unlock(&mu);
    if (evict_zone >= 0 && rx_vk_evict_unwanted_zone) rx_vk_evict_unwanted_zone(evict_zone);
    const asset_zone_cb cb = __atomic_load_n(&zone_cb, __ATOMIC_ACQUIRE);
    if (new_zone[0]) {
        if (on_stats) hos_log("io: zone %s", new_zone);
        if (cb) cb(old_zone, new_zone);
    }
}

void asset_prefetch_open(const char *path, int fd, uint64_t base, uint64_t size) {
    (void)fd, (void)base, (void)size;
    if (!path) return;
    const size_t root = sizeof(PAK_ROMFS_ROOT) - 1;
    const char *rel = !strncmp(path, PAK_ROMFS_ROOT, root) ? path + root : path;
    while (*rel == '/') rel++;
    int evict_zone = -1;
    pthread_mutex_lock(&mu);
    win.opens++;
    /* (a scene's parameters opened: its load begins, before Sequence_CurrentBanc says so) */
    static const char head[] = "Banc/GameBancParam/", tail[] = ".game__banc__GameBancParam.bgyml";
    const size_t n = strlen(rel);
    if (!strncmp(rel, head, sizeof head - 1) && n > sizeof head - 1 + sizeof tail - 1 && !strcmp(rel + n - (sizeof tail - 1), tail)) {
        char scene[SCENE_MAX];
        snprintf(scene, sizeof scene, "%.*s", (int)(n - (sizeof head - 1) - (sizeof tail - 1)), rel + sizeof head - 1);
        if (strcmp(scene, scene_now) && strcmp(scene, scene_loading)) {
            snprintf(scene_loading, sizeof scene_loading, "%s", scene);
            if (strcmp(visit_scene, scene)) {
                visit_close();
                snprintf(visit_scene, sizeof visit_scene, "%s", scene);
            }
            if (on_stats) hos_log("io: loading %s", scene);
            event(scene, "");
            const int s = deps_scene(scene);
            if (s >= 0 && dzones) {
                const int b_zone = (int)dscene_zone[s];
                if (b_zone >= 0 && b_zone != last_evicted_zone) {
                    last_evicted_zone = b_zone;
                    evict_zone = b_zone;
                }
            }
        }
    }
    if (on_learn && visit_scene[0] && visit.n < PROFILE_MAX) list_has_add(&visit, rel, n);
    pthread_mutex_unlock(&mu);
    if (evict_zone >= 0) {
        if (rx_vk_evict_unwanted_zone) rx_vk_evict_unwanted_zone(evict_zone);
        if (hos_ps5_trim_free_units) hos_ps5_trim_free_units((size_t)-1);
    }
}

int asset_prefetch_read(int fd, uint64_t base, uint64_t size, uint64_t from, void *buf, uint32_t n) {
    if (!on_bucket) {
        __atomic_add_fetch(&game_reading, 1, __ATOMIC_RELAXED);
        return 0;
    }
    pthread_mutex_lock(&mu);
    const int i = find_entry(fd, base);
    if (i < 0 || !entries[i].ready || from > size || n > size - from) {
        if (i >= 0 && !entries[i].ready && from == 0 && n >= size) entries[i].consumed = 1;   /* (read whole from the disk) */
        pthread_mutex_unlock(&mu);
        __atomic_add_fetch(&game_reading, 1, __ATOMIC_RELAXED);
        return 0;
    }
    Entry *e = &entries[i];
    e->pins++;
    const uint8_t *data = e->data;   /* (pinned: never freed meanwhile; the entries' array may move, the data does not) */
    pthread_mutex_unlock(&mu);
    memcpy(buf, data + from, n);
    const double t = now_ms();
    pthread_mutex_lock(&mu);
    e = &entries[i];
    e->pins--, e->served += n, e->last_use = ++use_clock;
    st.hits++, st.hit_bytes += n, win.hits++, win.hit_bytes += n;
    burst_note(t, 0, n, 1);
    if (e->served >= e->size && !e->pins) {   /* (the game has it whole now: it holds it from here) */
        drop_entry(i);
        st.released++;
    }
    pthread_mutex_unlock(&mu);
    return 1;
}

void asset_prefetch_disk(int fd, uint64_t base, uint32_t bytes, double ms) {
    (void)fd, (void)base;
    __atomic_sub_fetch(&game_reading, 1, __ATOMIC_RELAXED);
    pthread_mutex_lock(&mu);
    st.disk_reads++, st.disk_bytes += bytes;
    win.disk_reads++, win.disk_bytes += bytes, win.disk_ms += ms;
    if (ms > win.max_ms) win.max_ms = ms;
    burst_note(now_ms() - ms, ms, bytes, 0);
    pthread_mutex_unlock(&mu);
}

/* The game's current scene as last told (a break's report: host/ps5/ps5_bug_report.c); before the first, the one whose
   parameters were last opened (its load); "" before either */
const char *asset_prefetch_scene_now(void) {
    return scene_now[0] ? scene_now : scene_loading;
}

void asset_prefetch_stats(AssetPrefetchStats *out) {
    pthread_mutex_lock(&mu);
    *out = st;
    out->held_bytes = held;
    pthread_mutex_unlock(&mu);
}

void asset_prefetch_wait_idle(void) {
    pthread_mutex_lock(&mu);
    while (running && (ev_pending || (on_bucket && qat < qn))) pthread_cond_wait(&idle, &mu);
    pthread_mutex_unlock(&mu);
}

void asset_prefetch_stop(void) {
    pthread_mutex_lock(&mu);
    visit_close();
    quit = 1;
    pthread_cond_broadcast(&work);
    const int was = running;
    pthread_mutex_unlock(&mu);
    if (was) pthread_join(thread, NULL);
    pthread_mutex_lock(&mu);
    for (int i = 0; i < nentries; i++)
        if (entries[i].used && !entries[i].pins) drop_entry(i);
    pthread_mutex_unlock(&mu);
}
