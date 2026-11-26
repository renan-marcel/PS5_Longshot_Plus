/* Game-free: the virtual amiibo core (host/amiibo_core.c), driven as the game's nfp calls and the menu would.
   Run by tests/test_amiibo_core.py: amiibo_core_test <dir>, <dir> an empty folder for user/amiibo. Prints PASS or the
   first failed check, and exits 1 on a failure. */
#include "amiibo_core.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int signals[3], clears[3];
static void on_signal(int ev) { if (ev >= 0 && ev < 3) signals[ev]++; }
static void on_clear(int ev) { if (ev >= 0 && ev < 3) clears[ev]++; }
static void on_random(uint8_t *out, size_t n) { memset(out, 0xA5, n); }

static int failed;
#define CHECK(cond) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, #cond); failed = 1; return; } } while (0)
#define RC(call, want) do { uint32_t rc_ = (call); if (rc_ != (uint32_t)(want)) { \
    printf("FAIL line %d: %s gave 0x%x, want 0x%x\n", __LINE__, #call, (unsigned)rc_, (unsigned)(want)); failed = 1; return; } } while (0)

static uint32_t u32le(const uint8_t *p) { return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static unsigned u16le(const uint8_t *p) { return p[0] | (unsigned)p[1] << 8; }

static const AmiiboFigure LINK = {{0x01, 0x00, 0x00, 0x00, 0x03, 0x4b, 0x09, 0x02}, "Link - Ocarina of Time"};
static const AmiiboFigure EPONA = {{0x01, 0x05, 0x00, 0x00, 0x03, 0x4c, 0x09, 0x02}, "\xc3\x89pona de Hyrule"};
static char dir[1024];

static size_t file_size(const char *path, uint8_t *head, size_t n) {
    FILE *f = fopen(path, "rb");
    if (!f) return (size_t)-1;
    fseek(f, 0, SEEK_END);
    const long size = ftell(f);
    fseek(f, 0, SEEK_SET);
    const size_t read = head ? fread(head, 1, n, f) : n;
    fclose(f);
    if (read != n) return (size_t)-1;
    return (size_t)size;
}

static void the_brief(void) {
    uint64_t handles[4] = {0};
    int count = -1;
    uint8_t tag[0x58], tag2[0x58], model[0x40], common[0x40], reg[0x100];

    CHECK(amiibo_device_state() == -1);
    RC(amiibo_tag_info(tag), AMIIBO_RC_NFC_DISABLED);   /* (before Initialize) */
    RC(amiibo_initialize(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
    RC(amiibo_list_devices(handles, 4, &count), 0);
    CHECK(count == 1 && handles[0] == AMIIBO_DEVICE_HANDLE);
    RC(amiibo_list_devices(handles, 0, &count), AMIIBO_RC_INVALID_ARGUMENT);
    amiibo_config(0, 0, 0);
    CHECK(signals[AMIIBO_EV_AVAILABILITY] == 1);
    count = -1;
    RC(amiibo_list_devices(handles, 4, &count), 0);
    CHECK(count == 0);
    amiibo_config(1, 0, 0);
    CHECK(signals[AMIIBO_EV_AVAILABILITY] == 2);

    RC(amiibo_tag_info(tag), AMIIBO_RC_WRONG_DEVICE_STATE);
    RC(amiibo_mount(), AMIIBO_RC_WRONG_DEVICE_STATE);
    RC(amiibo_start_detection(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_SEARCHING_FOR_TAG);
    RC(amiibo_start_detection(), AMIIBO_RC_WRONG_DEVICE_STATE);
    amiibo_touch();   /* (no figure selected) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_SEARCHING_FOR_TAG);
    CHECK(signals[AMIIBO_EV_ACTIVATE] == 0);

    amiibo_select(&LINK);
    amiibo_touch();
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_FOUND);
    CHECK(signals[AMIIBO_EV_ACTIVATE] == 1 && clears[AMIIBO_EV_DEACTIVATE] == 1);
    RC(amiibo_model_info(model), AMIIBO_RC_WRONG_DEVICE_STATE);   /* (found, not mounted) */
    RC(amiibo_tag_info(tag), 0);   /* (GetTagInfo: TagFound too) */

    RC(amiibo_mount(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_MOUNTED);
    memset(model, 0xEE, sizeof model);
    RC(amiibo_model_info(model), 0);
    CHECK(model[0] == 0x01 && model[1] == 0x00 && model[2] == 0x00 && model[3] == 0x00);
    CHECK(u16le(model + 4) == 0x034b && model[6] == 0x09);
    for (int i = 7; i < 0x40; i++) CHECK(model[i] == 0);

    memset(tag, 0xEE, sizeof tag);
    RC(amiibo_tag_info(tag), 0);
    CHECK(tag[10] == 7 && u32le(tag + 0x20) == 1 && u32le(tag + 0x24) == 2);
    for (int i = 7; i < 10; i++) CHECK(tag[i] == 0);
    for (int i = 11; i < 0x20; i++) CHECK(tag[i] == 0);
    for (int i = 0x28; i < 0x58; i++) CHECK(tag[i] == 0);
    RC(amiibo_tag_info(tag2), 0);
    CHECK(memcmp(tag, tag2, 7) == 0);   /* (random off: the figure's own, every read) */
    int all_a5 = 1;
    for (int i = 0; i < 7; i++) all_a5 &= tag[i] == 0xA5;
    CHECK(!all_a5);
    amiibo_config(1, 1, 0);
    RC(amiibo_tag_info(tag2), 0);
    for (int i = 0; i < 7; i++) CHECK(tag2[i] == 0xA5);
    CHECK(tag2[10] == 7);
    amiibo_config(1, 0, 0);
    RC(amiibo_tag_info(tag2), 0);
    CHECK(memcmp(tag, tag2, 7) == 0);

    RC(amiibo_common_info(common), 0);
    CHECK(u32le(common + 8) == 0xD8);
    CHECK(u16le(common + 0) == 2026 && common[2] == 1 && common[3] == 1 && u16le(common + 4) == 0);
    memset(reg, 0xEE, sizeof reg);
    RC(amiibo_register_info(reg), 0);
    CHECK(memcmp(reg + 0x5C, "Link - Oca", 10) == 0 && reg[0x5C + 10] == 0);
    for (int i = 0; i < 0x58; i++) CHECK(reg[i] == 0);   /* (the Mii charinfo: there, all zero) */
    CHECK(u16le(reg + 0x58) == 2026 && reg[0x5A] == 1 && reg[0x5B] == 1);
    uint32_t size = 0;
    RC(amiibo_area_size(&size), 0);
    CHECK(size == 0xD8);

    /* application areas */
    uint8_t area[0xD9], back[0xD8];
    for (int i = 0; i < (int)sizeof area; i++) area[i] = (uint8_t)(i * 7 + 1);
    size_t got = 0;
    RC(amiibo_get_area(back, sizeof back, &got), AMIIBO_RC_WRONG_DEVICE_STATE);   /* (not opened) */
    RC(amiibo_open_area(0x01006a80), AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED);
    RC(amiibo_create_area(0x01006a80, area, 0xD8), 0);
    RC(amiibo_create_area(0x01006a80, area, 0xD8), AMIIBO_RC_APPLICATION_AREA_EXIST);
    RC(amiibo_recreate_area(0x01006a80, area, 0xD9), AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE);
    RC(amiibo_open_area(0x01006a80), 0);
    memset(back, 0, sizeof back);
    RC(amiibo_get_area(back, 16, &got), 0);
    CHECK(got == 16 && memcmp(back, area, 16) == 0);
    RC(amiibo_get_area(back, sizeof back, &got), 0);
    CHECK(got == 0xD8 && memcmp(back, area, 0xD8) == 0);
    RC(amiibo_set_area(area, 0xD9), AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE);
    uint8_t now[0x20];
    for (int i = 0; i < (int)sizeof now; i++) now[i] = (uint8_t)(0xF0 - i);
    RC(amiibo_set_area(now, sizeof now), 0);
    RC(amiibo_recreate_area(0x01006a80, area, 0xD8), AMIIBO_RC_WRONG_DEVICE_STATE);   /* (an open area) */
    RC(amiibo_flush(), 0);
    RC(amiibo_unmount(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_FOUND);
    RC(amiibo_get_area(back, sizeof back, &got), AMIIBO_RC_WRONG_DEVICE_STATE);
    RC(amiibo_mount(), 0);
    RC(amiibo_open_area(0x01006a80), 0);
    RC(amiibo_get_area(back, sizeof back, &got), 0);
    CHECK(got == 0xD8 && memcmp(back, now, sizeof now) == 0);
    RC(amiibo_common_info(common), 0);
    CHECK(u16le(common + 4) == 2);   /* (create, set) */

    char path[1200];
    snprintf(path, sizeof path, "%s/01000000034b0902/01006a80.bin", dir);
    uint8_t disk[0xD8];
    CHECK(file_size(path, disk, sizeof disk) == 0xD8);
    CHECK(memcmp(disk, now, sizeof now) == 0);
    snprintf(path, sizeof path, "%s/01000000034b0902/state.txt", dir);
    char state[64] = {0};
    FILE *sf = fopen(path, "rb");
    CHECK(sf != NULL);
    CHECK(fread(state, 1, sizeof state - 1, sf) > 0);
    fclose(sf);
    CHECK(strncmp(state, "counter=2 date=2026-01-01", 25) == 0);

    /* removal */
    const int deact = signals[AMIIBO_EV_DEACTIVATE], act_clears = clears[AMIIBO_EV_ACTIVATE];
    amiibo_remove();
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_REMOVED);
    CHECK(signals[AMIIBO_EV_DEACTIVATE] == deact + 1 && clears[AMIIBO_EV_ACTIVATE] == act_clears + 1);
    RC(amiibo_model_info(model), AMIIBO_RC_TAG_REMOVED);
    RC(amiibo_tag_info(tag), AMIIBO_RC_TAG_REMOVED);
    RC(amiibo_open_area(0x01006a80), AMIIBO_RC_TAG_REMOVED);
    RC(amiibo_mount(), AMIIBO_RC_WRONG_DEVICE_STATE);
    RC(amiibo_restore(), AMIIBO_RC_TAG_REMOVED);
    RC(amiibo_start_detection(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_SEARCHING_FOR_TAG);

    RC(amiibo_stop_detection(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
    RC(amiibo_stop_detection(), 0);   /* (Initialized: ok) */
    RC(amiibo_finalize(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
    RC(amiibo_list_devices(handles, 4, &count), AMIIBO_RC_NFC_DISABLED);
    RC(amiibo_initialize(), 0);
    count = -1;
    RC(amiibo_list_devices(handles, 4, &count), 0);
    CHECK(count == 1);
}

/* A second figure: its own areas and UUID; another figure selected takes the first off the reader; restore mounts. */
static void another_figure(void) {
    uint8_t tag_link[0x58], tag[0x58], reg[0x100];
    RC(amiibo_start_detection(), 0);
    amiibo_touch();
    RC(amiibo_tag_info(tag_link), 0);
    const int deact = signals[AMIIBO_EV_DEACTIVATE];
    amiibo_select(&EPONA);   /* (Link was on the reader) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_REMOVED && signals[AMIIBO_EV_DEACTIVATE] == deact + 1);
    RC(amiibo_start_detection(), 0);
    amiibo_touch();
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_FOUND);
    RC(amiibo_tag_info(tag), 0);
    CHECK(memcmp(tag, tag_link, 7) != 0);
    RC(amiibo_restore(), 0);   /* (TagFound: mounts) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_MOUNTED);
    RC(amiibo_register_info(reg), 0);
    CHECK(memcmp(reg + 0x5C, "\xc3\x89pona de H", 11) == 0 && reg[0x5C + 11] == 0);   /* (10 characters, not bytes) */
    RC(amiibo_open_area(0x01006a80), AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED);   /* (Link's is Link's) */
    RC(amiibo_stop_detection(), 0);   /* (mounted: taken off first) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
    amiibo_select(NULL);
    RC(amiibo_start_detection(), 0);
    amiibo_touch();
    CHECK(amiibo_device_state() == AMIIBO_STATE_SEARCHING_FOR_TAG);
    RC(amiibo_stop_detection(), 0);
}

/* Auto-touch: a selected figure is found as soon as the game searches, and taken off by StopDetection. */
static void auto_touch(void) {
    amiibo_config(1, 0, 1);
    amiibo_select(&LINK);
    const int act = signals[AMIIBO_EV_ACTIVATE];
    RC(amiibo_start_detection(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_FOUND && signals[AMIIBO_EV_ACTIVATE] == act + 1);
    RC(amiibo_mount(), 0);
    uint8_t back[0xD8];
    size_t got = 0;
    RC(amiibo_open_area(0x01006a80), 0);   /* (Link's area, from the disk) */
    RC(amiibo_get_area(back, sizeof back, &got), 0);
    CHECK(got == 0xD8 && back[0] == 0xF0);
    RC(amiibo_unmount(), 0);
    const int deact = signals[AMIIBO_EV_DEACTIVATE];
    RC(amiibo_stop_detection(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED && signals[AMIIBO_EV_DEACTIVATE] == deact + 1);
    RC(amiibo_start_detection(), 0);   /* (again: found again) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_TAG_FOUND);
    RC(amiibo_stop_detection(), 0);
    amiibo_select(NULL);
    RC(amiibo_start_detection(), 0);   /* (nothing selected: it searches) */
    CHECK(amiibo_device_state() == AMIIBO_STATE_SEARCHING_FOR_TAG);
    RC(amiibo_stop_detection(), 0);
    amiibo_config(1, 0, 0);
}

/* Emulation off: no device listed, the device's calls find none, the menu's touch does nothing. */
static void emulation_off(void) {
    amiibo_config(0, 0, 1);
    amiibo_select(&LINK);
    uint64_t handles[2];
    int count = -1;
    RC(amiibo_list_devices(handles, 2, &count), 0);
    CHECK(count == 0);
    RC(amiibo_start_detection(), AMIIBO_RC_DEVICE_NOT_FOUND);
    amiibo_touch();
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
    uint8_t tag[0x58];
    RC(amiibo_tag_info(tag), AMIIBO_RC_DEVICE_NOT_FOUND);
    RC(amiibo_finalize(), 0);
    RC(amiibo_initialize(), 0);
    amiibo_config(1, 0, 0);
    count = -1;
    RC(amiibo_list_devices(handles, 2, &count), 0);
    CHECK(count == 1);
}

/* No folder set: an area cannot be made, and that is said cleanly. */
static void no_dir(void) {
    amiibo_set_dir(NULL);
    amiibo_select(&LINK);
    RC(amiibo_start_detection(), 0);
    amiibo_touch();
    RC(amiibo_mount(), 0);
    uint8_t a[4] = {1, 2, 3, 4};
    RC(amiibo_open_area(0x01006a80), AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED);
    RC(amiibo_create_area(0x01006a80, a, sizeof a), AMIIBO_RC_WRONG_DEVICE_STATE);
    RC(amiibo_finalize(), 0);
    CHECK(amiibo_device_state() == AMIIBO_STATE_INITIALIZED);
}

/* The hooks call back into the core (host/nn_nfp.c's signal a guest event, the menu's thread asks the state): they run after
   the core's mutex is let go, so this neither deadlocks nor sees a half-made change. */
static int seen_state[3] = {-9, -9, -9}, reentered;
static void reenter_signal(int ev) {
    if (ev >= 0 && ev < 3) seen_state[ev] = amiibo_device_state();
    reentered++;
}
static void reenter_clear(int ev) {
    (void)ev;
    (void)amiibo_device_state();
    reentered++;
}
static void hooks_reenter(void) {
    amiibo_set_hooks(reenter_signal, reenter_clear, on_random);
    amiibo_set_dir(dir);
    RC(amiibo_initialize(), 0);
    amiibo_config(0, 0, 1);   /* (emulation off and on: the availability event, twice) */
    amiibo_config(1, 0, 1);
    CHECK(seen_state[AMIIBO_EV_AVAILABILITY] == AMIIBO_STATE_INITIALIZED);
    amiibo_select(&LINK);
    RC(amiibo_start_detection(), 0);   /* (auto-touch: activate signalled, deactivate cleared) */
    CHECK(seen_state[AMIIBO_EV_ACTIVATE] == AMIIBO_STATE_TAG_FOUND);
    amiibo_select(&EPONA);   /* (another figure: the one on the reader removed, deactivate signalled) */
    CHECK(seen_state[AMIIBO_EV_DEACTIVATE] == AMIIBO_STATE_TAG_REMOVED);
    RC(amiibo_finalize(), 0);
    CHECK(reentered >= 6);
    amiibo_set_hooks(on_signal, on_clear, on_random);
}

int main(int argc, char **argv) {
    if (argc < 2) {
        printf("usage: amiibo_core_test <dir>\n");
        return 2;
    }
    snprintf(dir, sizeof dir, "%s", argv[1]);
    amiibo_config(1, 0, 0);
    amiibo_set_dir(dir);
    amiibo_set_hooks(on_signal, on_clear, on_random);
    the_brief();
    if (!failed) another_figure();
    if (!failed) auto_touch();
    if (!failed) emulation_off();
    if (!failed) no_dir();
    if (!failed) hooks_reenter();
    if (failed) return 1;
    printf("PASS\n");
    return 0;
}
