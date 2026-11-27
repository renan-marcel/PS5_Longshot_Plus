/* (longshot) The rules of host/oot_heap_give_back.c, game-free: which bytes a block that sead::ExpHeap::free (OoT's
   f_803b44e0) is about to free holds, and which whole 64 KiB units of them may go back to the console. Read from the build's
   own code (tryAlloc's block maker f_801e8d00, and the free), not from a run:

   A block B, its header 0x20 bytes: +0x12 u16 the heap's id (heap +0xa8 >> 16; 0xffff a free block's), +0x14 u16 the
   alignment's padding (under 64 KiB), +0x18 u64 the payload's size. The payload P = B + 0x20 + padding, and the next block's
   header starts at P + size. Two shapes:
   - no padding (P = B + 0x20): [P - 8] is B + 0x18, the size: bit 0 clear (sizes are rounded up to 8);
   - padding (P > B + 0x20): tryAlloc wrote B | 1 at [P - 8] (orr x13, x8, #1; stur x13, [x11, #-8]): the field points at B.
   The free reads [P - 8] the same way (bit 0 set: B = [P - 8] - 1, else B = P - 0x20), checks P inside the heap
   ([heap +0x28] + 0xe0 up to its end, [heap +0x30] bytes on) and the id, and writes only headers: B's ([B, P)) and the next
   block's ([P + size, ...)) when it joins them. The payload [P, P + size) it never reads or writes.

   gb_block checks a block the way the free does, and more (the padding that makes [P - 8] agree with B, sizes that wrap);
   anything that does not fit is left alone (gb_why says why). Only header bytes before P are read: nothing in the payload. */
#ifndef HOS_HEAP_GIVE_BACK_H
#define HOS_HEAP_GIVE_BACK_H
#include <stdint.h>

#define GB_UNIT 0x10000ULL              /* (the console's commit unit: host/ps5/win32_ps5.c UNIT) */
#define GB_LARGE (256ULL << 10)         /* (a block this large or larger may give units back; smaller ones are counted only) */
enum { GB_HEADER = 0x20, GB_ID = 0x12, GB_PAD = 0x14, GB_SIZE = 0x18 };
enum { GB_HEAP_START = 0x28, GB_HEAP_SIZE = 0x30, GB_HEAP_FIRST = 0xe0 };   /* (the free's: P below start + 0xe0 is not freed) */

typedef enum { GB_OK, GB_NULL, GB_OUTSIDE, GB_BAD_LINK, GB_BAD_PAD, GB_FOREIGN, GB_BAD_SIZE, GB_WHY_N } gb_why;

typedef struct {
    uint64_t (*r64)(void *ctx, uint64_t addr);
    uint16_t (*r16)(void *ctx, uint64_t addr);
    void *ctx;
} GbMem;

typedef struct {
    uint64_t block;      /* B */
    uint64_t lo, hi;     /* the payload [P, P + size) */
    uint64_t size;
    int padded;          /* 1: [P - 8] held B | 1 */
} GbBlock;

/* The block whose payload is at p in the heap [start, start + size), its id heap_id; GB_OK fills *out */
static inline gb_why gb_block(const GbMem *m, uint64_t start, uint64_t size, uint16_t heap_id, uint64_t p, GbBlock *out) {
    if (!p) return GB_NULL;
    if (size > UINT64_MAX - start || start > UINT64_MAX - GB_HEAP_FIRST) return GB_OUTSIDE;
    const uint64_t end = start + size;
    if (p < start + GB_HEAP_FIRST || p >= end || p - start < GB_HEADER) return GB_OUTSIDE;
    const uint64_t link = m->r64(m->ctx, p - 8);
    uint64_t b;
    int padded;
    if (link & 1) {   /* (padding: the field points at B) */
        b = link - 1;
        padded = 1;
        if (b < start || b > p - GB_HEADER - 1) return GB_BAD_LINK;   /* (B below P with room for a padding of 1 or more) */
        if ((uint64_t)m->r16(m->ctx, b + GB_PAD) != p - b - GB_HEADER) return GB_BAD_PAD;
    } else {          /* (no padding: [P - 8] is the size itself) */
        b = p - GB_HEADER;
        padded = 0;
        if (b < start) return GB_BAD_LINK;
        if (m->r16(m->ctx, b + GB_PAD) != 0) return GB_BAD_PAD;
    }
    if (m->r16(m->ctx, b + GB_ID) != heap_id) return GB_FOREIGN;   /* (another heap's, or free already: 0xffff) */
    const uint64_t n = m->r64(m->ctx, b + GB_SIZE);
    if (!padded && n != link) return GB_BAD_SIZE;   /* (the same 8 bytes read twice: changed in between) */
    if (n > end - p) return GB_BAD_SIZE;            /* (past the heap's end, or wrapping) */
    out->block = b, out->lo = p, out->hi = p + n, out->size = n, out->padded = padded;
    return GB_OK;
}

/* The whole units inside [lo, hi): [*ulo, *uhi), 0 when there is none */
static inline int gb_units(uint64_t lo, uint64_t hi, uint64_t *ulo, uint64_t *uhi) {
    if (hi <= lo || lo > UINT64_MAX - (GB_UNIT - 1)) return 0;
    const uint64_t a = (lo + GB_UNIT - 1) & ~(GB_UNIT - 1), b = hi & ~(GB_UNIT - 1);
    if (a >= b) return 0;
    *ulo = a, *uhi = b;
    return 1;
}

static inline const char *gb_why_name(gb_why w) {
    static const char *const names[GB_WHY_N] = {"ok", "null", "outside", "bad_link", "bad_pad", "foreign", "bad_size"};
    return (unsigned)w < GB_WHY_N ? names[w] : "?";
}
#endif
