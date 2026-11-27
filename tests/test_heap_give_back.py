"""The pages under what OoT's heaps free, measured and given back (HOS_PS5_HEAP_GIVE_BACK: host/heap_give_back.h,
host/oot_heap_give_back.c, gpu/vk/vk_memory.cpp memory_guest_discard, nx2/oot_patches.py patch_heap_free). Game-free:

- the rules (host/heap_give_back.h, as it is): a block with no padding ([P - 8] its size) and one with padding ([P - 8]
  B | 1), each found; a pointer outside the heap, a link below it or past P, a padding that disagrees with the link, another
  heap's id (or a free block's 0xffff), a size past the heap's end or wrapping: each left alone, for its reason; the whole
  units of a range, also near 2^64; over 20000 made-up headers, what is found never leaves the heap or the payload;
- the hook (host/oot_heap_give_back.c, as it is, built for the PS5 over a guest memory of its own) wired by the patch
  itself into a stand-in f_803b44e0 that counts its runs: off reads and counts nothing; observe counts per heap (bytes,
  blocks under 256 KiB and their whole units with memory, the larger ones' whole units with memory, those the GPU holds)
  and leaves every byte of the guest memory as it was; reclaim gives back only whole units inside a large payload, never
  one a GPU import holds even in part, only while the renderer's locks are held, and leaves both headers (B's and the next
  block's) as they were; a block made again where units were given back is freed as any other; without the renderer
  nothing is given back. Every free runs the game's free once, whatever the mode or the block;
- the renderer's split (memory_guest_discard, cut from vk_memory.cpp): a range less every kind of import and every pool the
  game registered, a span's partly covered unit left out whole, overlapping and wider spans, ranges not in whole units
  refused; pools_mu and bg_mu both held while each run is handed out;
- nx2/oot_patches.py puts the call first in f_803b44e0, with no return (the free always runs), once, the supported build only.

python -I -B tests/test_heap_give_back.py [--cc gcc] [--cxx g++]
"""
import argparse
import inspect
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cc", "{cc}", "--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
import oot_patches  # noqa: E402
from srccut import block  # noqa: E402

# ---- 1. the rules, alone ----
RULES = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "heap_give_back.h"
static unsigned char g[1 << 20];   /* (guest addresses 0x100000 on) */
#define BASE 0x100000ull
static uint64_t r64(void *c, uint64_t a) { (void)c; uint64_t v = 0; if (a >= BASE && a + 8 <= BASE + sizeof g) memcpy(&v, g + (a - BASE), 8); return v; }
static uint16_t r16(void *c, uint64_t a) { (void)c; uint16_t v = 0; if (a >= BASE && a + 2 <= BASE + sizeof g) memcpy(&v, g + (a - BASE), 2); return v; }
static void w64(uint64_t a, uint64_t v) { memcpy(g + (a - BASE), &v, 8); }
static void w16(uint64_t a, uint16_t v) { memcpy(g + (a - BASE), &v, 2); }
static int fails;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL: %s (line %d)\n", what, __LINE__); fails++; } } while (0)
static const GbMem M = {r64, r16, NULL};
#define START BASE
#define SIZE (sizeof g)
#define ID 0x1234
static void block_at(uint64_t b, uint16_t pad, uint64_t size, uint16_t id) {
    w16(b + GB_ID, id), w16(b + GB_PAD, pad), w64(b + GB_SIZE, size);
    if (pad) w64(b + GB_HEADER + pad - 8, b | 1);
}
int main(void) {
    GbBlock o;
    memset(g, 0, sizeof g);
    /* no padding: P = B + 0x20, [P - 8] the size */
    block_at(BASE + 0x1000, 0, 0x5000, ID);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_OK && o.block == BASE + 0x1000 && !o.padded &&
          o.lo == BASE + 0x1020 && o.hi == BASE + 0x6020 && o.size == 0x5000, "a block with no padding, [P - 8] its size");
    /* padding: [P - 8] = B | 1 */
    block_at(BASE + 0x8000, 0x1e0, 0x3000, ID);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x8200, &o) == GB_OK && o.block == BASE + 0x8000 && o.padded &&
          o.lo == BASE + 0x8200 && o.hi == BASE + 0xb200, "a padded block: [P - 8] points at B");
    w16(BASE + 0x8000 + GB_PAD, 0x1d0);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x8200, &o) == GB_BAD_PAD, "a padding that disagrees with the link");
    w16(BASE + 0x8000 + GB_PAD, 0x1e0);
    w64(BASE + 0x8200 - 8, (BASE - 0x100) | 1);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x8200, &o) == GB_BAD_LINK, "a link below the heap");
    w64(BASE + 0x8200 - 8, (BASE + 0x8200 - 0x10) | 1);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x8200, &o) == GB_BAD_LINK, "a link with no room for a header before P");
    block_at(BASE + 0x8000, 0x1e0, 0x3000, ID);
    /* no padding, but the header says there is */
    w16(BASE + 0x1000 + GB_PAD, 8);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_BAD_PAD, "a padding with no link");
    w16(BASE + 0x1000 + GB_PAD, 0);
    /* another heap's, or free already */
    w16(BASE + 0x1000 + GB_ID, 0xffff);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_FOREIGN, "a free block (0xffff): a second free");
    w16(BASE + 0x1000 + GB_ID, ID + 1);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_FOREIGN, "another heap's block");
    w16(BASE + 0x1000 + GB_ID, ID);
    /* sizes */
    w64(BASE + 0x1000 + GB_SIZE, SIZE);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_BAD_SIZE, "a size past the heap's end");
    w64(BASE + 0x1000 + GB_SIZE, UINT64_MAX - 0x17);   /* (even: with no padding [P - 8] is the size, and an odd one a link) */
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_BAD_SIZE, "a size that wraps");
    w64(BASE + 0x1000 + GB_SIZE, UINT64_MAX - 0x10);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_BAD_LINK, "an odd size: read as a link, and refused");
    w64(BASE + 0x1000 + GB_SIZE, SIZE - 0x1020);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x1020, &o) == GB_OK && o.hi == START + SIZE, "a payload up to the heap's end");
    block_at(BASE + 0x8000, 0x1e0, (SIZE - 0x8200) + 8, ID);
    CHECK(gb_block(&M, START, SIZE, ID, BASE + 0x8200, &o) == GB_BAD_SIZE, "a padded block past the heap's end");
    /* the heap's bounds */
    CHECK(gb_block(&M, START, SIZE, ID, 0, &o) == GB_NULL, "a null pointer");
    CHECK(gb_block(&M, START, SIZE, ID, START + GB_HEAP_FIRST - 8, &o) == GB_OUTSIDE, "below the heap's first block");
    CHECK(gb_block(&M, START, SIZE, ID, START + SIZE, &o) == GB_OUTSIDE, "at the heap's end");
    CHECK(gb_block(&M, UINT64_MAX - 0x100, 0x1000, ID, UINT64_MAX - 0x10, &o) == GB_OUTSIDE, "a heap that wraps");
    /* whole units */
    uint64_t a, b;
    CHECK(gb_units(0x10001, 0x30000, &a, &b) && a == 0x20000 && b == 0x30000, "the whole units of a range");
    CHECK(!gb_units(0x10001, 0x2ffff, &a, &b), "no whole unit");
    CHECK(gb_units(0x20000, 0x30000, &a, &b) && a == 0x20000 && b == 0x30000, "a range of whole units");
    CHECK(!gb_units(UINT64_MAX - 0x100, UINT64_MAX, &a, &b), "a range near 2^64");
    CHECK(!gb_units(0x30000, 0x20000, &a, &b), "a range backwards");
    /* made-up headers: whatever is found stays inside the heap and its payload; its units inside the payload */
    srand(7);
    int found = 0;
    for (int i = 0; i < 20000; i++) {   /* (a block made as tryAlloc makes it, then one header byte broken half the time) */
        const uint64_t blk = BASE + 0x40000 + (uint64_t)(rand() % 64) * 8;
        const uint16_t pad = rand() % 2 ? 0 : (uint16_t)(8 + (rand() % 64) * 8);
        const uint64_t want = (uint64_t)(rand() % 0x20000) * 8 + (rand() % 8 == 0 ? SIZE : 0);   /* (some past the end) */
        memset(g + 0x40000, 0, 0x1000);
        block_at(blk, pad, want, ID);
        const uint64_t p = blk + GB_HEADER + pad;
        if (rand() % 2) g[(blk - BASE) + (uint64_t)(rand() % (GB_HEADER + pad))] ^= (unsigned char)(1 + rand() % 255);
        if (gb_block(&M, START, SIZE, ID, p, &o) == GB_OK) {
            found++;
            CHECK(o.block >= START && o.block + GB_HEADER <= o.lo && o.lo == p && o.hi >= o.lo && o.hi <= START + SIZE,
                  "a made-up block found outside its heap");
            if (gb_units(o.lo, o.hi, &a, &b)) CHECK(a >= o.lo && b <= o.hi, "units outside the payload");
        }
    }
    CHECK(found > 0, "no made-up block was found: the property was not tried");
    if (fails) return 1;
    printf("PASS: the rules: both paddings, every refusal for its reason, whole units, %d made-up blocks inside their heap\n", found);
    return 0;
}
'''

# ---- 2. the hook, as it is, over a guest memory of its own ----
HOS_H = r'''#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef struct { uint64_t x[32]; uint8_t n, z, c, v; } Ctx;
#define A64_NOESC
#define MEM_SIZE (64u << 20)
extern unsigned char mem[MEM_SIZE];
#define GP(a) ((void *)(mem + (a)))
#define G64(a) (*(uint64_t *)GP(a))
int hos_guest_range(uint64_t a, uint64_t n);
void hos_log(const char *fmt, ...);
'''

FIXTURE = r'''#include "hos.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
unsigned char mem[MEM_SIZE];
int hos_guest_range(uint64_t a, uint64_t n) { return a >= 0x1000 && n <= MEM_SIZE && a <= MEM_SIZE - n; }
void hos_log(const char *fmt, ...) { va_list ap; va_start(ap, fmt); vprintf(fmt, ap); va_end(ap); putchar('\n'); }
void hos_oot_heap_free(Ctx *c);
int hos_oot_heap_line(char *out, size_t cap);
int hos_oot_heap_top(char *out, size_t cap, int k);
void f_803b44e0(Ctx *__restrict A64_NOESC c);   /* (lifted.c: the patch's text) */
extern int frees;

#define UNIT 0x10000ull
static unsigned char backed[MEM_SIZE / UNIT];
static int locks_held, renderer_absent, decommits, fails;
static uint64_t gpu_lo, gpu_hi;   /* (an import, any bytes) */
static uint64_t pay_lo[32], pay_hi[32];
static int npay;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL: %s (line %d)\n", what, __LINE__); fails++; } } while (0)
int hos_ps5_unit_backed(uintptr_t host) { const uint64_t g = host - (uintptr_t)mem; return g < MEM_SIZE && backed[g / UNIT]; }
int hos_ps5_decommit(void *addr, size_t size) {
    const uint64_t lo = (uint64_t)((unsigned char *)addr - mem), hi = lo + size;
    decommits++;
    CHECK(locks_held, "a unit given back with the renderer's locks not held");
    CHECK(!(lo % UNIT) && !(hi % UNIT) && hi > lo, "a range of part units given back");
    CHECK(!(lo < gpu_hi && gpu_lo < hi), "a unit an import holds was given back");
    int inside = 0;
    for (int i = 0; i < npay; i++) inside |= lo >= pay_lo[i] && hi <= pay_hi[i];
    CHECK(inside, "a range outside every payload given back");
    for (uint64_t u = lo; u < hi; u += UNIT) backed[u / UNIT] = 0;
    memset(mem + lo, 0, size);   /* (it reads as zero after: reserved again) */
    return 1;
}
int64_t rx_guest_discard(uint64_t lo, uint64_t hi, void (*free_run)(void *, uint64_t, uint64_t), void *ctx) {
    if (renderer_absent) return -1;
    const uint64_t a = gpu_lo & ~(UNIT - 1), b = (gpu_hi + UNIT - 1) & ~(UNIT - 1);
    uint64_t kept = 0;
    locks_held = 1;
    if (gpu_hi > gpu_lo && a < hi && lo < b) {
        const uint64_t ka = a > lo ? a : lo, kb = b < hi ? b : hi;
        if (ka > lo) free_run(ctx, lo, ka);
        kept = kb - ka;
        if (kb < hi) free_run(ctx, kb, hi);
    } else {
        free_run(ctx, lo, hi);
    }
    locks_held = 0;
    return (int64_t)kept;
}

#define HEAP 0x1000ull
#define VT 0x2000ull
#define START 0x100000ull
#define HSIZE (60ull << 20)
#define ID 0x1234
static void w64(uint64_t a, uint64_t v) { memcpy(mem + a, &v, 8); }
static void w32(uint64_t a, uint32_t v) { memcpy(mem + a, &v, 4); }
static void w16(uint64_t a, uint16_t v) { memcpy(mem + a, &v, 2); }
static uint64_t block_at(uint64_t b, uint16_t pad, uint64_t size, uint16_t id) {   /* (its payload) */
    w16(b + 0x12, id), w16(b + 0x14, pad), w64(b + 0x18, size);
    if (pad) w64(b + 0x20 + pad - 8, b | 1);
    pay_lo[npay] = b + 0x20 + pad, pay_hi[npay] = b + 0x20 + pad + size, npay++;
    memset(mem + b + 0x20 + pad + size, 0xA5, 0x20);   /* (the next block's header: must stay as it is) */
    return b + 0x20 + pad;
}
static uint64_t sum(void) { uint64_t s = 1469598103934665603ull; for (size_t i = 0; i < MEM_SIZE; i++) s = (s ^ mem[i]) * 1099511628211ull; return s; }
static void free_block(uint64_t p) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = HEAP, c.x[1] = p;
    const int before = frees;
    f_803b44e0(&c);
    CHECK(frees == before + 1, "the game's free did not run exactly once");
}
static uint64_t field(const char *line, const char *key) {
    const char *at = strstr(line, key);
    return at ? strtoull(at + strlen(key), NULL, 10) : ~0ull;
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "off";
    memset(mem, 0, sizeof mem);
    w64(HEAP, VT), w64(VT + 0x40, 0x834911d0ull), w64(VT + 0xa0, 0x80517d30ull);
    w32(HEAP + 0x80, 1), w32(HEAP + 0xa8, (uint32_t)ID << 16), w64(HEAP + 0x28, START), w64(HEAP + 0x30, HSIZE);
    w64(HEAP + 0x20, 0x3000), memcpy(mem + 0x3000, "Test Heap", 10);
    /* a large block, no padding: 8 MiB from 0x110000 (128 whole units); an import over part of its units 0x200000 and
       0x3f0000 and all between (exactly 2 MiB of whole units left out) */
    const uint64_t b1 = 0x110000 - 0x20, p1 = block_at(b1, 0, 8u << 20, ID);
    /* a large padded one: 4 MiB from 0x1000000 (64 units), its header 0x200 below */
    const uint64_t b3 = 0x1000000 - 0x200, p3 = block_at(b3, 0x1e0, 4u << 20, ID);
    /* 16 small ones, 128 KiB each from a unit's start (2 whole units each: 2 MiB in all) */
    uint64_t small[16];
    for (int i = 0; i < 16; i++) small[i] = block_at(0x2000000 + (uint64_t)i * 0x40000 - 0x20, 0, 128u << 10, ID);
    /* a free block freed again */
    const uint64_t p4 = block_at(0x3000000 - 0x20, 0, 300u << 10, 0xffff);
    for (uint64_t u = 0; u < MEM_SIZE / UNIT; u++) backed[u] = 1;
    gpu_lo = 0x208000, gpu_hi = 0x3fff00;
    unsigned char h1[0x20], h3[0x200], n1[0x20], n3[0x20];
    memcpy(h1, mem + b1, sizeof h1), memcpy(h3, mem + b3, sizeof h3);
    memcpy(n1, mem + p1 + (8u << 20), sizeof n1), memcpy(n3, mem + p3 + (4u << 20), sizeof n3);
    renderer_absent = !strcmp(mode, "norenderer");
    const uint64_t s0 = sum();
    free_block(p1), free_block(p3), free_block(p4);
    for (int i = 0; i < 16; i++) free_block(small[i]);
    free_block(0);                                   /* (a null pointer: the free's own business) */
    char line[1024] = "", top[1024] = "";
    const int has = hos_oot_heap_line(line, sizeof line);
    hos_oot_heap_top(top, sizeof top, 12);
    printf("%s\n%s\n", line, top);
    if (!strcmp(mode, "off")) {
        CHECK(!has && !decommits && sum() == s0, "off: something was counted, given back or changed");
    } else if (!strcmp(mode, "observe") || !strcmp(mode, "norenderer")) {
        CHECK(!decommits && sum() == s0, "observe: the guest memory was changed or a unit given back");
        CHECK(field(line, " freed_n=") == 18 && field(line, " small_n=") == 16 && field(line, " large_n=") == 2,
              "observe: the blocks counted");
        CHECK(field(line, " small_mb=") == 2 && field(line, " small_backed_mb=") == 2 && field(line, " large_mb=") == 12,
              "observe: the small blocks and their whole units with memory");
        CHECK(strstr(line, "skipped=1"), "observe: the second free of a free block left alone");
        if (renderer_absent) {
            CHECK(field(line, " unproven_mb=") == 12 && field(line, " backed_mb=") == 0 && field(line, " gpu_mb=") == 0,
                  "no renderer: nothing shown to be the CPU's alone");
            CHECK(strstr(top, "Test_Heap:0/0/2"), "no renderer: the heap by name");
        } else {
            CHECK(field(line, " units_mb=") == 12 && field(line, " gpu_mb=") == 2 && field(line, " backed_mb=") == 10 &&
                  field(line, " unproven_mb=") == 0 && field(line, " given_mb=") == 0, "observe: the large blocks' units");
            CHECK(strstr(top, "Test_Heap:10/2/2"), "observe: the heap by name");
        }
    } else if (!strcmp(mode, "reclaim")) {
        CHECK(decommits == 3, "reclaim: the runs given back (two around the import, one for the padded block)");
        CHECK(field(line, " given_mb=") == 10 && field(line, " gpu_mb=") == 2, "reclaim: 10 MiB given back, 2 left to the GPU");
        for (uint64_t u = 0x110000; u < 0x910000; u += UNIT)
            CHECK(backed[u / UNIT] == (u >= 0x200000 && u < 0x400000), "reclaim: a unit of the large block");
        for (uint64_t u = 0x1000000; u < 0x1400000; u += UNIT) CHECK(!backed[u / UNIT], "reclaim: a unit of the padded block");
        for (int i = 0; i < 16; i++) CHECK(backed[small[i] / UNIT], "reclaim: a small block's unit given back");
        CHECK(backed[b1 / UNIT] && backed[b3 / UNIT] && backed[0x910000 / UNIT] && backed[0x1400000 / UNIT],
              "reclaim: a unit holding a header given back");
        CHECK(!memcmp(h1, mem + b1, sizeof h1) && !memcmp(h3, mem + b3, sizeof h3) && !memcmp(n1, mem + p1 + (8u << 20), sizeof n1) &&
              !memcmp(n3, mem + p3 + (4u << 20), sizeof n3), "reclaim: a header changed");
        /* the address made again: a block whose header lies in units given back (it read as zero; the game wrote it) */
        for (uint64_t u = 0x150000; u < 0x1a0000; u += UNIT) backed[u / UNIT] = 1;   /* (backed again as the game touched them) */
        const int before = decommits;
        free_block(block_at(0x150000, 0, 256u << 10, ID));
        CHECK(decommits == before + 1, "reclaim: a block made again where units were given back is freed as any other");
        CHECK(!backed[0x160000 / UNIT] && backed[0x150000 / UNIT], "reclaim: the block made again: its payload's units only");
    }
    if (fails) return 1;
    printf("PASS: %s\n", mode);
    return 0;
}
'''

LIFTED = '''#include "a64.h"
int frees;
void f_803b44e0(Ctx *__restrict A64_NOESC c) {
    frees++;
    (void)c;
}
void f_803b4400(Ctx *__restrict A64_NOESC c) {
    (void)c;
}
'''

# ---- 3. the renderer's split, cut from vk_memory.cpp ----
DISCARD = r'''#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <map>
#include <mutex>
#include <vector>
#include "import_reach.h"
struct Mu { bool held = false; void lock() { assert(!held); held = true; } void unlock() { held = false; } };
struct Pool { uint64_t lo, hi, memory; };
std::map<uint64_t, Pool> imported;
import_reach::Reach live_reach;
std::deque<decltype(imported)::node_type> retired_pools, evicted_pools;
Mu pools_mu, bg_mu;
std::map<uint64_t, uint64_t> bg_inflight;
std::vector<std::pair<uint64_t, Pool>> bg_ready;
struct DeadImport { uint64_t lo, bytes; };
std::deque<DeadImport> dead_imports;
struct GuestPool { uint64_t lo = 0, hi = 0, glo = 0, ghi = 0; };
std::vector<GuestPool> guest_pools;
@CUT@
static std::vector<std::pair<uint64_t, uint64_t>> runs;
static void run(void*, uint64_t a, uint64_t b) { assert(pools_mu.held && bg_mu.held); runs.emplace_back(a, b); }
static uint64_t split(uint64_t lo, uint64_t hi) { runs.clear(); return memory_guest_discard(lo, hi, run, nullptr); }
static void add(uint64_t lo, uint64_t hi) { imported.emplace(lo, Pool{lo, hi, 1}); live_reach.add(hi - lo); }
using R = std::vector<std::pair<uint64_t, uint64_t>>;
int main() {
    const uint64_t U = 0x10000;
    assert(split(0, 4 * U) == 0 && runs == R({{0, 4 * U}}));                       // (nothing imported: one run)
    assert(split(U + 1, 4 * U) == 0 && runs.empty());                              // (not whole units: refused)
    add(U + 0x4000, U + 0x5000);                                                    // (inside unit 1, in part)
    assert(split(0, 4 * U) == U && runs == R({{0, U}, {2 * U, 4 * U}}));
    add(U + 0x8000, 2 * U + 0xa000);                                                // (overlapping, over units 1-2)
    add(2 * U, 3 * U + 0x1000);                                                     // (and 2-3)
    assert(split(0, 5 * U) == 3 * U && runs == R({{0, U}, {4 * U, 5 * U}}));
    assert(split(2 * U, 3 * U) == U && runs.empty());                               // (wider than the range)
    assert(memory_guest_imported(U + 0x4000, U + 0x4001) && !memory_guest_imported(0, U));
    imported.clear(), live_reach = {};
    retired_pools.push_back(decltype(imported)::node_type{});
    { std::map<uint64_t, Pool> m; m.emplace(6 * U, Pool{6 * U, 7 * U, 1}); retired_pools.back() = m.extract(6 * U); }
    { std::map<uint64_t, Pool> m; m.emplace(8 * U, Pool{8 * U, 9 * U, 0}); evicted_pools.push_back(m.extract(8 * U)); }   // (memory freed: no longer held)
    dead_imports.push_back({10 * U, U});
    bg_inflight.emplace(12 * U, 12 * U + 1);
    bg_ready.emplace_back(14 * U, Pool{14 * U, 15 * U, 1});
    GuestPool g; g.lo = 16 * U, g.hi = 17 * U; guest_pools.push_back(g);
    assert(split(5 * U, 18 * U) == 5 * U);   // (retired, dead, in flight, ready, a registered pool: a unit each)
    assert(runs == R({{5 * U, 6 * U}, {7 * U, 10 * U}, {11 * U, 12 * U}, {13 * U, 14 * U}, {15 * U, 16 * U}, {17 * U, 18 * U}}));
    assert(!memory_guest_imported(16 * U, 17 * U));   // (a registered pool is no import: the old check is as it was)
    assert(!pools_mu.held && !bg_mu.held);
    std::puts("PASS: the renderer's split: every kind of import and the registered pools left out in whole units, the locks held");
    return 0;
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cc", default="gcc")
    p.add_argument("--cxx", default="g++")
    a = p.parse_args()

    # the patch: first in f_803b44e0, no return, once, the supported build only
    out = oot_patches.patch_heap_free(LIFTED)
    head = oot_patches.HEAP_FREE_HEAD
    assert out.count(head + oot_patches.HEAP_FREE_CALL) == 1, "the hook is not the first line of f_803b44e0"
    assert "return" not in oot_patches.HEAP_FREE_CALL, "the hook can skip the game's free"
    assert out.count("void hos_oot_heap_free(Ctx *c);\n") == 1 and out.count("hos_oot_heap_free(c)") == 1
    assert "void f_803b4400(Ctx *__restrict A64_NOESC c) {\n    (void)c;" in out, "another function was changed"
    assert oot_patches.patch_heap_free(out) == out, "a second run changed the text"
    assert oot_patches.patch_heap_free("void f_80000000(Ctx *c) {}\n") is None
    assert "patch_heap_free(out) if protect_hearts else" in inspect.getsource(oot_patches.patch_file), \
        "the hook is made on builds other than the supported one"
    print("PASS: nx2/oot_patches.py: the hook first in f_803b44e0, no return, once, the supported build only")

    cc, cxx = shutil.which(a.cc) or shutil.which("gcc") or shutil.which("clang"), shutil.which(a.cxx) or shutil.which("g++")
    if not cc or not cxx:
        print("SKIP: no C or C++ compiler")
        return
    exe_name = "x.exe" if os.name == "nt" else "x"
    with tempfile.TemporaryDirectory(prefix="heap-give-back-") as tmp:
        tmp = Path(tmp)
        # 1. the rules
        (tmp / "rules").mkdir()
        (tmp / "rules" / "rules.c").write_text(RULES, encoding="utf-8")
        exe = tmp / "rules" / exe_name
        subprocess.run([cc, "-std=c11", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "host"),
                        str(tmp / "rules" / "rules.c"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: the rules\n" + r.stderr)
        # 2. the hook as it is, for the PS5, over its own guest memory, wired by the patch's own text
        d = tmp / "hook"
        d.mkdir()
        (d / "hos.h").write_text(HOS_H, encoding="utf-8")
        (d / "a64.h").write_text('#include "hos.h"\n', encoding="utf-8")
        (d / "fixture.c").write_text(FIXTURE, encoding="utf-8")
        (d / "lifted.c").write_text(out, encoding="utf-8")
        for name in ("oot_heap_give_back.c", "heap_give_back.h"):   # (beside the stand-in hos.h: quotes look there first)
            (d / name).write_text((ROOT / "host" / name).read_text(encoding="utf-8"), encoding="utf-8")
        exe = d / exe_name
        subprocess.run([cc, "-std=gnu11", "-O1", "-Wall", "-Wextra", "-Werror", "-D__PROSPERO__", "-I", str(d),
                        str(d / "fixture.c"), str(d / "lifted.c"), str(d / "oot_heap_give_back.c"), "-o", str(exe)], check=True)
        env = {k: v for k, v in os.environ.items() if k != "HOS_PS5_HEAP_GIVE_BACK"}
        for mode, value in (("off", None), ("observe", "observe"), ("reclaim", "reclaim"), ("norenderer", "reclaim"),
                            ("off", "sideways")):
            e = dict(env, HOS_PS5_HEAP_GIVE_BACK=value) if value else env
            r = subprocess.run([str(exe), mode], env=e, capture_output=True, text=True)
            if r.returncode:
                raise SystemExit("FAIL (%s, HOS_PS5_HEAP_GIVE_BACK=%s):\n%s%s" % (mode, value, r.stdout, r.stderr))
            print("PASS: the hook, HOS_PS5_HEAP_GIVE_BACK=%s (%s)" % (value or "unset", mode))
        # 3. the renderer's split
        memory = (ROOT / "gpu/vk/vk_memory.cpp").read_text(encoding="utf-8")
        cut = "\n".join(block(memory, m) for m in ("template <class Seen>\nbool import_spans_locked(",
                                                   "int memory_guest_imported(", "uint64_t memory_guest_discard("))
        (tmp / "discard.cpp").write_text(DISCARD.replace("@CUT@", cut), encoding="utf-8")
        exe = tmp / ("d.exe" if os.name == "nt" else "d")
        subprocess.run([cxx, "-std=c++20", "-O1", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT / "gpu/vk"),
                        str(tmp / "discard.cpp"), "-o", str(exe)], check=True)
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        print(r.stdout.strip())
        if r.returncode:
            raise SystemExit("FAIL: the renderer's split\n" + r.stderr)
    print("PASS: HOS_PS5_HEAP_GIVE_BACK: the rules, the hook in every mode, the renderer's split")


if __name__ == "__main__":
    main()
