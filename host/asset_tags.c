/* (longshot) Which romfs file guest bytes came from: asset_tags.h. A range is kept in each 2 MiB page it covers (at most
   MAX_PAGES of them), in a slot ring per page bucket, so the newest range over an address wins and old ones fall out as new
   ones come; a lookup scans one bucket. File names are interned (up to NAMES). One lock. */
#include "asset_tags.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>

#define PAGE_SHIFT 21u        /* (2 MiB) */
#define BUCKETS 16384u
#define SLOTS 8u              /* (ranges kept per bucket, the newest first to be found) */
#define MAX_PAGES 512u        /* (a range of more than 1 GiB is tagged in its first 1 GiB) */
#define NAMES 8192u
#define NAME_LEN 160u

typedef struct { uint64_t lo, hi; uint32_t id; } Slot;
static Slot slots[BUCKETS][SLOTS];
static uint8_t next_slot[BUCKETS];
static char names[NAMES][NAME_LEN];
static uint32_t nnames;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;

static uint32_t bucket(uint64_t page) { return (uint32_t)((page * 0x9E3779B97F4A7C15ull) >> 50) % BUCKETS; }

static uint32_t name_id(const char *path) {   /* (mu held) 0 when the table is full */
    const char *rel = path;
    for (const char *p = path; *p; p++)
        if ((p[0] == 'r' || p[0] == 'R') && !strncmp(p + 1, "omfs", 4) && (p[5] == '/' || p[5] == '\\')) rel = p + 6;
    if (rel == path) {   /* (the game's own path, host/nn_fs.c's: its mount name first, "rom:/Model/...") */
        const char *colon = strchr(path, ':');
        if (colon && colon > path + 1 && !memchr(path, '/', (size_t)(colon - path)) && !memchr(path, '\\', (size_t)(colon - path)))
            rel = colon + 1;
    }
    while (*rel == '/' || *rel == '\\') rel++;
    char norm[NAME_LEN];
    size_t n = 0;
    for (; rel[n] && n + 1 < NAME_LEN; n++) norm[n] = rel[n] == '\\' ? '/' : rel[n];
    norm[n] = 0;
    for (uint32_t i = 0; i < nnames; i++)
        if (!strcmp(names[i], norm)) return i + 1;
    if (nnames >= NAMES) return 0;
    memcpy(names[nnames], norm, n + 1);
    return ++nnames;
}

static void put(uint64_t lo, uint64_t len, uint32_t id) {   /* (mu held) */
    if (!len || !id) return;
    const uint64_t hi = lo + len, first = lo >> PAGE_SHIFT;
    uint64_t last = (hi - 1) >> PAGE_SHIFT;
    if (last - first >= MAX_PAGES) last = first + MAX_PAGES - 1;
    for (uint64_t p = first; p <= last; p++) {
        const uint32_t b = bucket(p);
        slots[b][next_slot[b]] = (Slot){lo, hi, id};
        next_slot[b] = (uint8_t)((next_slot[b] + 1) % SLOTS);
    }
}

static uint32_t find(uint64_t addr) {   /* (mu held) the newest range over addr */
    const uint32_t b = bucket(addr >> PAGE_SHIFT);
    for (uint32_t k = 1; k <= SLOTS; k++) {
        const Slot *s = &slots[b][(next_slot[b] + SLOTS - k) % SLOTS];
        if (s->id && addr >= s->lo && addr < s->hi) return s->id;
    }
    return 0;
}

void asset_tags_read(uint64_t dst, uint64_t len, const char *path) {
    if (!path) return;
    pthread_mutex_lock(&mu);
    put(dst, len, name_id(path));
    pthread_mutex_unlock(&mu);
}

void asset_tags_derived(uint64_t src, uint64_t dst, uint64_t len) {
    pthread_mutex_lock(&mu);
    const uint32_t id = find(src);
    if (id) put(dst, len, id);
    pthread_mutex_unlock(&mu);
}

int asset_tags_lookup(uint64_t addr) {
    pthread_mutex_lock(&mu);
    const uint32_t id = find(addr);
    pthread_mutex_unlock(&mu);
    return (int)id;
}

const char *asset_tags_path(int id) { return id > 0 && (uint32_t)id <= NAMES ? names[id - 1] : ""; }

void asset_tags_tally(AssetTagTally *t, uint64_t storage, uint64_t bytes, int (*wanted)(const char *path)) {
    const int id = asset_tags_lookup(storage);
    if (!id) {
        t->untagged_n++, t->untagged_bytes += bytes;
        return;
    }
    t->tagged_n++, t->tagged_bytes += bytes;
    if (wanted && !wanted(asset_tags_path(id))) t->unwanted_n++, t->unwanted_bytes += bytes;
}

void asset_tags_line(const AssetTagTally *t, char *line, size_t cap) {
    snprintf(line, cap, "tags tagged_n=%llu tagged_mb=%llu untagged_n=%llu untagged_mb=%llu unwanted_n=%llu unwanted_mb=%llu",
             (unsigned long long)t->tagged_n, (unsigned long long)(t->tagged_bytes >> 20), (unsigned long long)t->untagged_n,
             (unsigned long long)(t->untagged_bytes >> 20), (unsigned long long)t->unwanted_n,
             (unsigned long long)(t->unwanted_bytes >> 20));
}

size_t asset_tags_memory(void) { return sizeof slots + sizeof next_slot + sizeof names; }
