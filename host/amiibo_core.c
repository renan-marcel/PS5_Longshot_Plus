/* Virtual amiibo: the game-free core of nn::nfp. What and why: amiibo_core.h,
   docs/superpowers/specs/2026-11-26-amiibo-design.md ("How Fritchii does it", "2. Runtime").

   Adapted from Fritchii (Frizti/Fritchii, src/core/hle/service/nfc, GPLv3): the device states and their rules
   (nfc/common/device.cpp), the TagInfo / ModelInfo / CommonInfo / RegisterInfo layouts (nfp/nfp_types.h, nfc/nfc_types.h)
   and the result codes. What differs, being virtual: no tag data and no keys. The infos are built from the figure's 8-byte
   amiibo ID and name; an application area is a file per figure and access ID (<dir>/<amiibo id>/<access id>.bin, so each
   game keeps its own on the same figure), written as soon as the game writes it, with the write counter and the last write
   date beside it in state.txt. The tag's UUID is the figure's own (the first 7 bytes of FNV-1a-64 of its ID, little-endian),
   or random bytes on every GetTagInfo with the random tag ID on. Dates are fixed (2026-01-01): the core reads no clock.

   One mutex guards it all. The event hooks are called after it is let go, in the order the call raised them, so a hook may
   call back in (host/nn_nfp.c's signal a guest event; the menu's thread asks the state). */
#include "amiibo_core.h"

#include <stdio.h>
#include <string.h>

#ifdef _WIN32
#include <direct.h>
#include <windows.h>
static SRWLOCK mu = SRWLOCK_INIT;
#define LOCK() AcquireSRWLockExclusive(&mu)
#define UNLOCK_RAW() ReleaseSRWLockExclusive(&mu)
#define MAKE_DIR(p) _mkdir(p)
#else
#include <pthread.h>
#include <sys/stat.h>
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
#define LOCK() pthread_mutex_lock(&mu)
#define UNLOCK_RAW() pthread_mutex_unlock(&mu)
#define MAKE_DIR(p) mkdir(p, 0777)
#endif

#define YEAR 2026
#define MONTH 1
#define DAY 1
#define COUNTER_LIMIT 0xFFFFu

/* the switches and the hooks */
static int emulation, random_uid, auto_touch = 1;
static char dir[1024];
static void (*hook_signal)(int ev);
static void (*hook_clear)(int ev);
static void (*hook_random)(uint8_t *out, size_t n);

/* the device */
static int initialized;          /* (the module: Initialize called, Finalize not since) */
static int state = -1;           /* (AMIIBO_STATE_*; -1 before the first Initialize) */
static int selected;             /* (a figure picked in the menu) */
static AmiiboFigure figure;      /* (it) */
static AmiiboFigure tag;         /* (the one on the reader: TagFound, TagMounted) */

/* the mounted tag's write counter and date (state.txt), and its open area */
static unsigned counter;
static unsigned date_y = YEAR, date_m = MONTH, date_d = DAY;
static int area_open;
static uint32_t area_id;
static uint8_t area[AMIIBO_AREA_SIZE];

/* the events a locked section raised, run once the mutex is let go (unlock): a hook may call back in */
typedef struct {
    int n;
    struct { void (*hook)(int ev); int ev; } op[8];
} Pending;
static Pending pending;   /* (the locked section's: under the mutex) */

static void raise_ev(void (*hook)(int ev), int ev) {
    if (hook && pending.n < (int)(sizeof pending.op / sizeof pending.op[0])) {
        pending.op[pending.n].hook = hook;
        pending.op[pending.n].ev = ev;
        pending.n++;
    }
}

static void signal_ev(int ev) { raise_ev(hook_signal, ev); }
static void clear_ev(int ev) { raise_ev(hook_clear, ev); }

/* the mutex let go, then the hooks the section raised, in order */
static void unlock(void) {
    const Pending run = pending;
    pending.n = 0;
    UNLOCK_RAW();
    for (int i = 0; i < run.n; i++) run.op[i].hook(run.op[i].ev);
}
#define UNLOCK() unlock()

static void put16(uint8_t *p, unsigned v) {
    p[0] = (uint8_t)v;
    p[1] = (uint8_t)(v >> 8);
}

static void put32(uint8_t *p, uint32_t v) {
    put16(p, v & 0xFFFFu);
    put16(p + 2, v >> 16);
}

/* <dir>/<amiibo id>[/<leaf>], lower-case hex; 0 without a folder or when it does not fit */
static int figure_path(char *out, size_t cap, const char *leaf) {
    if (!dir[0]) return 0;
    char id[17];
    for (int i = 0; i < 8; i++) snprintf(id + 2 * i, 3, "%02x", tag.id[i]);
    const int n = leaf ? snprintf(out, cap, "%s/%s/%s", dir, id, leaf) : snprintf(out, cap, "%s/%s", dir, id);
    return n > 0 && (size_t)n < cap;
}

static int area_path(char *out, size_t cap, uint32_t access_id) {
    char leaf[16];
    snprintf(leaf, sizeof leaf, "%08x.bin", (unsigned)access_id);
    return figure_path(out, cap, leaf);
}

static void load_state(void) {
    char path[1200];
    counter = 0;
    date_y = YEAR, date_m = MONTH, date_d = DAY;
    if (!figure_path(path, sizeof path, "state.txt")) return;
    FILE *f = fopen(path, "rb");
    if (!f) return;
    unsigned c, y, m, d;
    const int got = fscanf(f, "counter=%u date=%u-%u-%u", &c, &y, &m, &d);
    fclose(f);
    if (got >= 1) counter = c > COUNTER_LIMIT ? COUNTER_LIMIT : c;
    if (got == 4 && y >= 2000 && y <= 0xFFFF && m >= 1 && m <= 12 && d >= 1 && d <= 31) date_y = y, date_m = m, date_d = d;
}

/* an area written: the file (0xD8 bytes), then the counter bumped and the date in state.txt. 0 when it could not be */
static int write_area(uint32_t access_id) {
    char path[1200];
    if (!figure_path(path, sizeof path, NULL)) return 0;
    (void)MAKE_DIR(dir);   /* (the folders, when they are not there yet) */
    (void)MAKE_DIR(path);
    if (!area_path(path, sizeof path, access_id)) return 0;
    FILE *f = fopen(path, "wb");
    if (!f) return 0;
    const int ok = fwrite(area, 1, sizeof area, f) == sizeof area;
    if (fclose(f) != 0 || !ok) return 0;
    if (counter < COUNTER_LIMIT) counter++;
    date_y = YEAR, date_m = MONTH, date_d = DAY;
    if (figure_path(path, sizeof path, "state.txt") && (f = fopen(path, "wb"))) {
        fprintf(f, "counter=%u date=%04u-%02u-%02u\n", counter, date_y, date_m, date_d);
        fclose(f);
    }
    return 1;
}

/* the area of this access ID, from its file: 1 when there is one */
static int read_area(uint32_t access_id, uint8_t *out) {
    char path[1200];
    if (!area_path(path, sizeof path, access_id)) return 0;
    FILE *f = fopen(path, "rb");
    if (!f) return 0;
    memset(out, 0, AMIIBO_AREA_SIZE);
    const size_t got = fread(out, 1, AMIIBO_AREA_SIZE, f);   /* (a shorter file: the rest zero) */
    fclose(f);
    (void)got;
    return 1;
}

static int area_exists(uint32_t access_id) {
    uint8_t scratch[AMIIBO_AREA_SIZE];
    return read_area(access_id, scratch);
}

/* the calls that need the device: not before Initialize, none with emulation off */
static uint32_t device_ok(void) {
    if (!initialized) return AMIIBO_RC_NFC_DISABLED;
    if (!emulation) return AMIIBO_RC_DEVICE_NOT_FOUND;
    return 0;
}

/* a call that needs the tag mounted: TagRemoved in that state, else WrongDeviceState */
static uint32_t need_mounted(void) {
    const uint32_t rc = device_ok();
    if (rc) return rc;
    if (state == AMIIBO_STATE_TAG_MOUNTED) return 0;
    return state == AMIIBO_STATE_TAG_REMOVED ? AMIIBO_RC_TAG_REMOVED : AMIIBO_RC_WRONG_DEVICE_STATE;
}

/* (Fritchii's LoadNfcTag) a figure is found only while the game searches */
static void touch_locked(void) {
    if (!initialized || !emulation || !selected || state != AMIIBO_STATE_SEARCHING_FOR_TAG) return;
    tag = figure;
    state = AMIIBO_STATE_TAG_FOUND;
    clear_ev(AMIIBO_EV_DEACTIVATE);
    signal_ev(AMIIBO_EV_ACTIVATE);
}

/* (Fritchii's CloseNfcTag) unmounted first, then removed */
static void remove_locked(void) {
    if (state != AMIIBO_STATE_TAG_FOUND && state != AMIIBO_STATE_TAG_MOUNTED) return;
    area_open = 0;
    state = AMIIBO_STATE_TAG_REMOVED;
    clear_ev(AMIIBO_EV_ACTIVATE);
    signal_ev(AMIIBO_EV_DEACTIVATE);
}

void amiibo_config(int emulation_on, int random_on, int auto_touch_on) {
    LOCK();
    const int changed = !emulation != !emulation_on;
    if (changed && !emulation_on) remove_locked();   /* (a figure on the reader goes with the device) */
    emulation = emulation_on != 0;
    random_uid = random_on != 0;
    auto_touch = auto_touch_on != 0;
    if (changed && initialized) signal_ev(AMIIBO_EV_AVAILABILITY);
    UNLOCK();
}

void amiibo_set_dir(const char *d) {
    LOCK();
    const char *s = d ? d : "";
    if (strlen(s) < sizeof dir) memcpy(dir, s, strlen(s) + 1);
    else dir[0] = 0;   /* (cut short it would be another folder) */
    UNLOCK();
}

void amiibo_set_hooks(void (*signal)(int ev), void (*clear)(int ev), void (*random)(uint8_t *out, size_t n)) {
    LOCK();
    hook_signal = signal;
    hook_clear = clear;
    hook_random = random;
    UNLOCK();
}

void amiibo_select(const AmiiboFigure *f) {
    LOCK();
    const int on_reader = state == AMIIBO_STATE_TAG_FOUND || state == AMIIBO_STATE_TAG_MOUNTED;
    if (on_reader && (!f || memcmp(f->id, tag.id, sizeof tag.id) != 0)) remove_locked();
    selected = f != NULL;
    if (f) {
        figure = *f;
        figure.name[sizeof figure.name - 1] = 0;
    } else {
        memset(&figure, 0, sizeof figure);
    }
    UNLOCK();
}

void amiibo_touch(void) {
    LOCK();
    touch_locked();
    UNLOCK();
}

void amiibo_remove(void) {
    LOCK();
    remove_locked();
    UNLOCK();
}

int amiibo_device_state(void) {
    LOCK();
    const int s = state;
    UNLOCK();
    return s;
}

uint32_t amiibo_initialize(void) {
    LOCK();
    initialized = 1;
    state = AMIIBO_STATE_INITIALIZED;
    area_open = 0;
    UNLOCK();
    return 0;
}

/* (Fritchii's Finalize: unmounted, detection stopped) the device left idle, the module uninitialized */
uint32_t amiibo_finalize(void) {
    LOCK();
    if (initialized) {
        remove_locked();
        state = AMIIBO_STATE_INITIALIZED;
        area_open = 0;
        initialized = 0;
    }
    UNLOCK();
    return 0;
}

uint32_t amiibo_list_devices(uint64_t *out, int max, int *count) {
    if (!out || !count || max < 1) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = initialized ? 0 : AMIIBO_RC_NFC_DISABLED;
    if (!rc) {
        *count = 0;
        if (emulation) out[(*count)++] = AMIIBO_DEVICE_HANDLE;
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_start_detection(void) {
    LOCK();
    uint32_t rc = device_ok();
    if (!rc && state != AMIIBO_STATE_INITIALIZED && state != AMIIBO_STATE_TAG_REMOVED) rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc) {
        state = AMIIBO_STATE_SEARCHING_FOR_TAG;
        if (auto_touch) touch_locked();
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_stop_detection(void) {
    LOCK();
    uint32_t rc = device_ok();
    if (!rc && state != AMIIBO_STATE_INITIALIZED) {
        remove_locked();   /* (TagFound, TagMounted: taken off first) */
        if (state == AMIIBO_STATE_SEARCHING_FOR_TAG || state == AMIIBO_STATE_TAG_REMOVED) state = AMIIBO_STATE_INITIALIZED;
        else rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_mount(void) {
    LOCK();
    uint32_t rc = device_ok();
    if (!rc && state != AMIIBO_STATE_TAG_FOUND) rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc) {
        load_state();
        area_open = 0;
        state = AMIIBO_STATE_TAG_MOUNTED;
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_unmount(void) {
    LOCK();
    const uint32_t rc = need_mounted();
    if (!rc) {
        area_open = 0;
        state = AMIIBO_STATE_TAG_FOUND;
    }
    UNLOCK();
    return rc;
}

/* TagInfo 0x58: uuid[10], uuid_length u8, 0x15 pad, protocol u32 (TypeA 1), tag_type u32 (Type2 2), 0x30 pad */
uint32_t amiibo_tag_info(uint8_t out[0x58]) {
    if (!out) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = device_ok();
    if (!rc && state != AMIIBO_STATE_TAG_FOUND && state != AMIIBO_STATE_TAG_MOUNTED)
        rc = state == AMIIBO_STATE_TAG_REMOVED ? AMIIBO_RC_TAG_REMOVED : AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc) {
        memset(out, 0, AMIIBO_TAG_INFO_SIZE);
        if (random_uid && hook_random) {
            hook_random(out, 7);
        } else {
            uint64_t h = 1469598103934665603ull;   /* (FNV-1a-64 of the ID: the figure's own, every time) */
            for (int i = 0; i < 8; i++) h = (h ^ tag.id[i]) * 1099511628211ull;
            for (int i = 0; i < 7; i++) out[i] = (uint8_t)(h >> (8 * i));
        }
        out[0x0A] = 7;
        put32(out + 0x20, 1);
        put32(out + 0x24, 2);
    }
    UNLOCK();
    return rc;
}

/* ModelInfo 0x40: character_id (ID bytes 0-1, in tag order), character_variant (2), amiibo_type (3), model_number u16
   (bytes 4-5 read big-endian), series (6), 0x39 pad */
uint32_t amiibo_model_info(uint8_t out[0x40]) {
    if (!out) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    const uint32_t rc = need_mounted();
    if (!rc) {
        memset(out, 0, AMIIBO_MODEL_INFO_SIZE);
        out[0] = tag.id[0];
        out[1] = tag.id[1];
        out[2] = tag.id[2];
        out[3] = tag.id[3];
        put16(out + 4, (unsigned)tag.id[4] << 8 | tag.id[5]);
        out[6] = tag.id[6];
    }
    UNLOCK();
    return rc;
}

/* CommonInfo 0x40: last write date {u16 year, u8 month, u8 day}, write_counter u16, version u8, pad, application area
   size u32 (0xD8), 0x34 pad */
uint32_t amiibo_common_info(uint8_t out[0x40]) {
    if (!out) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    const uint32_t rc = need_mounted();
    if (!rc) {
        memset(out, 0, AMIIBO_COMMON_INFO_SIZE);
        put16(out, date_y);
        out[2] = (uint8_t)date_m;
        out[3] = (uint8_t)date_d;
        put16(out + 4, counter);
        put32(out + 8, AMIIBO_AREA_SIZE);
    }
    UNLOCK();
    return rc;
}

/* RegisterInfo 0x100: the Mii CharInfo (0x58, all zero here), creation date (fixed), amiibo_name char[41] (UTF-8, up to 10
   characters), font_region u8, 0x7A pad */
uint32_t amiibo_register_info(uint8_t out[0x100]) {
    if (!out) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    const uint32_t rc = need_mounted();
    if (!rc) {
        memset(out, 0, AMIIBO_REGISTER_INFO_SIZE);
        put16(out + 0x58, YEAR);
        out[0x5A] = MONTH;
        out[0x5B] = DAY;
        const unsigned char *s = (const unsigned char *)tag.name;
        size_t at = 0;
        for (int chars = 0; chars < 10 && s[at]; chars++) {
            size_t len = 1;   /* (one character: its lead byte and the continuation bytes after it) */
            while (len < 4 && (s[at + len] & 0xC0) == 0x80) len++;
            if (at + len > 40) break;
            memcpy(out + 0x5C + at, s + at, len);
            at += len;
        }
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_open_area(uint32_t access_id) {
    LOCK();
    uint32_t rc = need_mounted();
    if (!rc && !read_area(access_id, area)) rc = AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED;
    if (!rc) {
        area_open = 1;
        area_id = access_id;
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_get_area(void *out, size_t cap, size_t *got) {
    if ((!out && cap) || !got) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = need_mounted();
    if (!rc && !area_open) rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc) {
        *got = cap < sizeof area ? cap : sizeof area;
        if (*got) memcpy(out, area, *got);
    }
    UNLOCK();
    return rc;
}

uint32_t amiibo_set_area(const void *in, size_t n) {
    if (!in && n) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = need_mounted();
    if (!rc && !area_open) rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc && n > sizeof area) rc = AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE;
    if (!rc) {
        memset(area, 0, sizeof area);
        if (n) memcpy(area, in, n);
        if (!write_area(area_id)) rc = AMIIBO_RC_WRONG_DEVICE_STATE;
    }
    UNLOCK();
    return rc;
}

static uint32_t recreate_locked(uint32_t access_id, const void *in, size_t n) {
    if (area_open) return AMIIBO_RC_WRONG_DEVICE_STATE;
    if (n > sizeof area) return AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE;
    memset(area, 0, sizeof area);
    if (n) memcpy(area, in, n);
    return write_area(access_id) ? 0 : AMIIBO_RC_WRONG_DEVICE_STATE;
}

uint32_t amiibo_create_area(uint32_t access_id, const void *in, size_t n) {
    if (!in && n) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = need_mounted();
    if (!rc && area_exists(access_id)) rc = AMIIBO_RC_APPLICATION_AREA_EXIST;
    if (!rc) rc = recreate_locked(access_id, in, n);
    UNLOCK();
    return rc;
}

uint32_t amiibo_recreate_area(uint32_t access_id, const void *in, size_t n) {
    if (!in && n) return AMIIBO_RC_INVALID_ARGUMENT;
    LOCK();
    uint32_t rc = need_mounted();
    if (!rc) rc = recreate_locked(access_id, in, n);
    UNLOCK();
    return rc;
}

uint32_t amiibo_area_size(uint32_t *out) {
    if (!out) return AMIIBO_RC_INVALID_ARGUMENT;
    *out = AMIIBO_AREA_SIZE;
    return 0;
}

/* the areas are on the disk as soon as they are written: nothing is left to flush */
uint32_t amiibo_flush(void) {
    LOCK();
    const uint32_t rc = need_mounted();
    UNLOCK();
    return rc;
}

/* (Fritchii's Restore: from TagFound, the tag's backup put back and mounted) nothing to put back here: it mounts */
uint32_t amiibo_restore(void) {
    LOCK();
    uint32_t rc = device_ok();
    if (!rc && state != AMIIBO_STATE_TAG_FOUND)
        rc = state == AMIIBO_STATE_TAG_REMOVED ? AMIIBO_RC_TAG_REMOVED : AMIIBO_RC_WRONG_DEVICE_STATE;
    if (!rc) {
        load_state();
        area_open = 0;
        state = AMIIBO_STATE_TAG_MOUNTED;
    }
    UNLOCK();
    return rc;
}
