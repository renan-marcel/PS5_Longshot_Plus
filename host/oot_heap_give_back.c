/* (longshot) The pages under what OoT's heaps free, measured and, when asked, given back to the console
   (HOS_PS5_HEAP_GIVE_BACK).

   The game's memory is one heap of ~6.9 GB (SetMemoryHeapSize) split into sead heaps. On the Switch 2 it is all the game's
   from the start; on the PS5 the runtime backs each 64 KiB unit when the game first touches it (host/ps5/win32_ps5.c), and
   nothing gives a unit back when the game frees what was in it: a zone change frees a scene's heaps into their parents, and
   the guest pages only grow (3.7 to 4.3 GB of the heap in 100 s between Hyrule Field and the Market, nothing given back,
   then the memory floor's exit).

   nx2/oot_patches.py puts hos_oot_heap_free first in f_803b44e0, sead::ExpHeap::free(heap x0, pointer x1) in this build
   (vtable 0x84c172c8 +0x38; host/oot_heap_retry.c reads the same heaps). It returns nothing and the free runs after it,
   once, whatever it did. The block is read as host/heap_give_back.h says (its header only, never the payload):

   - off (the default): nothing is read.
   - observe: per heap, the blocks freed and their bytes; those under 256 KiB (GB_LARGE) counted apart with the whole
     units in them that had memory; for the larger ones the whole units inside their payload, those with memory, and
     those an import or a pool of the GPU's holds (left out). Nothing is written to the game's memory.
   - reclaim: as observe, and the larger blocks' whole units with memory that no GPU import or pool holds are given back
     (hos_ps5_decommit) before the free runs. While the free has not run the block is its caller's alone: no other thread
     of the game can be handed it. The GPU's side is held still for the time it takes: the renderer splits the range by
     its imports and pools and calls back with its pool locks held, so no import can start in a run until it is given
     back (gpu/vk/vk_memory.cpp memory_guest_discard). Without the renderer (before it is up) nothing is given back. A unit
     given back reads as zero and is backed again when the game touches it (host/mkw_glue.c commit_on_touch).

   PS5 only: elsewhere the hook returns at once (Windows and Linux back pages their own way). The counts go into
   logs/memory.txt's "heap" and "heaps" lines (host/ps5/win32_ps5.c mem_write). */
#include "hos.h"
#include "heap_give_back.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { HEAP_NAME = 0x20, HEAP_LIST_KIND = 0x80, HEAP_FLAGS = 0xa8 };
/* (the free's own checks, f_803b44e0: the plain ExpHeap path only, its vtable's +0x40 and +0xa0 its own; other heaps' are
   left alone) */
#define FREE_VT40 0x834911d0ULL
#define FREE_VTA0 0x80517d30ULL

enum { MODE_OFF, MODE_OBSERVE, MODE_RECLAIM };

int64_t rx_guest_discard(uint64_t lo, uint64_t hi, void (*free_run)(void *ctx, uint64_t run_lo, uint64_t run_hi), void *ctx);
#ifdef __PROSPERO__
int hos_ps5_unit_backed(uintptr_t addr);
int hos_ps5_decommit(void *addr, size_t size);
#endif

static int give_back_mode(void) {
    static volatile int mode = -1;
    int m = __atomic_load_n(&mode, __ATOMIC_RELAXED);
    if (m >= 0) return m;
    const char *e = getenv("HOS_PS5_HEAP_GIVE_BACK");
    m = !e || !*e || !strcmp(e, "0") || !strcmp(e, "off") ? MODE_OFF : !strcmp(e, "observe") ? MODE_OBSERVE :
        !strcmp(e, "reclaim") ? MODE_RECLAIM : -2;
#ifndef __PROSPERO__
    if (m != MODE_OFF) hos_log("heap: HOS_PS5_HEAP_GIVE_BACK=%s is for the PS5: off here", e), m = MODE_OFF;
#endif
    if (m == -2) hos_log("heap: HOS_PS5_HEAP_GIVE_BACK=%s: not off, observe or reclaim: off", e), m = MODE_OFF;
    else if (m != MODE_OFF) hos_log("heap: HOS_PS5_HEAP_GIVE_BACK=%s", m == MODE_OBSERVE ? "observe" : "reclaim");
    __atomic_store_n(&mode, m, __ATOMIC_RELAXED);
    return m;
}

/* ---- the counts, per heap (a fixed table; heaps past it go to its last slot, "other") ---- */
enum { SLOTS = 256 };
typedef struct {
    uint64_t heap;              /* (0: free slot; ~0: other) */
    char name[40];
    uint64_t n, bytes;          /* every block freed here */
    uint64_t small_n, small_bytes, small_backed;   /* under GB_LARGE; the whole units in them that had memory */
    uint64_t large_n, large_bytes;
    uint64_t units, backed, gpu, unproven, given;  /* the larger blocks' whole units: with memory, the GPU's, not shown
                                                      to be the CPU's alone (no renderer), given back */
} HeapStat;
static HeapStat stats[SLOTS];
static uint64_t skipped[GB_WHY_N + 2];   /* (gb_why, then: not the plain ExpHeap path, a heap that frees nothing) */

static void name_of(uint64_t heap, char *out, size_t cap) {
    out[0] = 0;
    const uint64_t s = hos_guest_range(heap + HEAP_NAME, 8) ? G64(heap + HEAP_NAME) : 0;
    size_t i = 0;
    for (; s && i + 1 < cap && hos_guest_range(s + i, 1); i++) {
        const char ch = *(const char *)GP(s + i);
        if (ch < 32 || ch >= 127) break;
        out[i] = ch == ' ' || ch == ':' || ch == '/' ? '_' : ch;   /* (one word in logs/memory.txt's "heaps" line) */
    }
    out[i] = 0;
}

static HeapStat *stat_of(uint64_t heap) {
    uint32_t i = (uint32_t)((heap * 0x9E3779B97F4A7C15ULL) >> 56) % (SLOTS - 1);
    for (int k = 0; k < SLOTS - 1; k++, i = (i + 1) % (SLOTS - 1)) {
        uint64_t have = __atomic_load_n(&stats[i].heap, __ATOMIC_ACQUIRE);
        if (have == heap) return &stats[i];
        if (!have) {
            if (__atomic_compare_exchange_n(&stats[i].heap, &have, heap, 0, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
                name_of(heap, stats[i].name, sizeof stats[i].name);
                return &stats[i];
            }
            if (have == heap) return &stats[i];
        }
    }
    __atomic_store_n(&stats[SLOTS - 1].heap, ~0ULL, __ATOMIC_RELAXED);
    return &stats[SLOTS - 1];
}
#define ADD(field, v) __atomic_add_fetch(&(field), (uint64_t)(v), __ATOMIC_RELAXED)

static uint64_t r64(void *ctx, uint64_t a) { (void)ctx; uint64_t v; memcpy(&v, GP(a), 8); return v; }
static uint16_t r16(void *ctx, uint64_t a) { (void)ctx; uint16_t v; memcpy(&v, GP(a), 2); return v; }

#ifdef __PROSPERO__
static uint64_t backed_in(uint64_t lo, uint64_t hi) {   /* (whole units [lo, hi) with memory now: the unit table, no access) */
    uint64_t n = 0;
    for (uint64_t u = lo; u < hi; u += GB_UNIT) n += hos_ps5_unit_backed((uintptr_t)GP(u)) ? GB_UNIT : 0;
    return n;
}
typedef struct { int reclaim; uint64_t backed, given; } Runs;
static void free_run(void *ctx, uint64_t lo, uint64_t hi) {   /* (the renderer's pool locks held: memory_guest_discard) */
    Runs *r = (Runs *)ctx;
    const uint64_t b = backed_in(lo, hi);
    r->backed += b;
    if (r->reclaim && b && hos_ps5_decommit(GP(lo), (size_t)(hi - lo))) r->given += b;
}
#endif

void hos_oot_heap_free(Ctx *c) {
    const int mode = give_back_mode();
    if (mode == MODE_OFF) return;
#ifdef __PROSPERO__
    const uint64_t heap = c->x[0], p = c->x[1];
    if (!p || !hos_guest_range(heap, 0xb0)) return;
    const uint64_t vt = G64(heap);
    if (!hos_guest_range(vt, 0xa8) || G64(vt + 0x40) != FREE_VT40 || G64(vt + 0xa0) != FREE_VTA0 ||
        *(const uint32_t *)GP(heap + HEAP_LIST_KIND) != 1) {
        ADD(skipped[GB_WHY_N], 1);
        return;
    }
    const uint32_t flags = *(const uint32_t *)GP(heap + HEAP_FLAGS);
    if (flags & 2) {   /* (the free returns at once for such a heap) */
        ADD(skipped[GB_WHY_N + 1], 1);
        return;
    }
    const uint64_t start = G64(heap + GB_HEAP_START), size = G64(heap + GB_HEAP_SIZE);
    if (!hos_guest_range(start, size)) {
        ADD(skipped[GB_OUTSIDE], 1);
        return;
    }
    const GbMem mem = {r64, r16, NULL};
    GbBlock b;
    const gb_why why = gb_block(&mem, start, size, (uint16_t)(flags >> 16), p, &b);
    if (why != GB_OK) {
        ADD(skipped[why], 1);
        return;
    }
    HeapStat *s = stat_of(heap);
    ADD(s->n, 1), ADD(s->bytes, b.size);
    uint64_t ulo = 0, uhi = 0;
    const int whole = gb_units(b.lo, b.hi, &ulo, &uhi);
    if (b.size < GB_LARGE) {
        ADD(s->small_n, 1), ADD(s->small_bytes, b.size);
        if (whole) ADD(s->small_backed, backed_in(ulo, uhi));
        return;
    }
    ADD(s->large_n, 1), ADD(s->large_bytes, b.size);
    if (!whole) return;
    ADD(s->units, uhi - ulo);
    Runs r = {mode == MODE_RECLAIM, 0, 0};
    const int64_t kept = rx_guest_discard(ulo, uhi, free_run, &r);
    if (kept < 0) {
        ADD(s->unproven, uhi - ulo);
        return;
    }
    ADD(s->gpu, (uint64_t)kept), ADD(s->backed, r.backed), ADD(s->given, r.given);
#else
    (void)c;
#endif
}

/* logs/memory.txt's "heap" line (cumulative, every heap together); 0 with the switch off */
int hos_oot_heap_line(char *out, size_t cap) {
    if (give_back_mode() == MODE_OFF) return 0;
    HeapStat t;
    memset(&t, 0, sizeof t);
    for (int i = 0; i < SLOTS; i++) {
        const HeapStat *s = &stats[i];
        if (!__atomic_load_n(&s->heap, __ATOMIC_ACQUIRE)) continue;
        t.n += s->n, t.bytes += s->bytes, t.small_n += s->small_n, t.small_bytes += s->small_bytes;
        t.small_backed += s->small_backed, t.large_n += s->large_n, t.large_bytes += s->large_bytes, t.units += s->units;
        t.backed += s->backed, t.gpu += s->gpu, t.unproven += s->unproven, t.given += s->given;
    }
    uint64_t skip = 0;
    for (int i = 1; i < GB_WHY_N + 2; i++) skip += skipped[i];
    return snprintf(out, cap, "heap mode=%s freed_n=%llu freed_mb=%llu small_n=%llu small_mb=%llu small_backed_mb=%llu "
                    "large_n=%llu large_mb=%llu units_mb=%llu backed_mb=%llu gpu_mb=%llu unproven_mb=%llu given_mb=%llu skipped=%llu",
                    give_back_mode() == MODE_OBSERVE ? "observe" : "reclaim", (unsigned long long)t.n,
                    (unsigned long long)(t.bytes >> 20), (unsigned long long)t.small_n, (unsigned long long)(t.small_bytes >> 20),
                    (unsigned long long)(t.small_backed >> 20), (unsigned long long)t.large_n,
                    (unsigned long long)(t.large_bytes >> 20), (unsigned long long)(t.units >> 20),
                    (unsigned long long)(t.backed >> 20), (unsigned long long)(t.gpu >> 20), (unsigned long long)(t.unproven >> 20),
                    (unsigned long long)(t.given >> 20), (unsigned long long)skip);
}

/* logs/memory.txt's "heaps" line: the k heaps with the most whole units with memory under what they freed (cumulative),
   each name:backed_mb/gpu_mb/small_backed_mb; 0 with the switch off */
static uint64_t weight(const HeapStat *s) { return s->backed + s->gpu + s->small_backed; }
int hos_oot_heap_top(char *out, size_t cap, int k) {
    if (give_back_mode() == MODE_OFF || !cap) return 0;
    int best[16], n = 0;
    if (k > 16) k = 16;
    for (int i = 0; i < SLOTS; i++) {   /* (the k heaviest, heaviest first: an insertion into a short sorted list) */
        if (!__atomic_load_n(&stats[i].heap, __ATOMIC_ACQUIRE) || !weight(&stats[i])) continue;
        int at = n;
        while (at > 0 && weight(&stats[best[at - 1]]) < weight(&stats[i])) at--;
        if (at >= k) continue;
        if (n < k) n++;
        for (int j = n - 1; j > at; j--) best[j] = best[j - 1];
        best[at] = i;
    }
    size_t used = (size_t)snprintf(out, cap, "heaps");
    for (int j = 0; j < n && used < cap; j++) {
        const HeapStat *s = &stats[best[j]];
        used += (size_t)snprintf(out + used, cap - used, " %s:%llu/%llu/%llu", s->heap == ~0ULL ? "other" : s->name[0] ? s->name : "?",
                                 (unsigned long long)(s->backed >> 20), (unsigned long long)(s->gpu >> 20),
                                 (unsigned long long)(s->small_backed >> 20));
    }
    return (int)(used < cap ? used : cap - 1);
}
