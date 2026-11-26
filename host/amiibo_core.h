/* Virtual amiibo: the game-free core of nn::nfp (docs/superpowers/specs/2026-11-26-amiibo-design.md, "2. Runtime").

   One virtual NFC device. The state machine, the info structs and the application areas follow Fritchii's rules and
   layouts (Adapted from Fritchii (Frizti/Fritchii, src/core/hle/service/nfc, GPLv3)); host/nn_nfp.c binds the game's
   nn::nfp calls to the functions here, and the renderer's menu picks, touches and removes a figure. No Ctx, no game:
   tests/amiibo_core_test.c runs it on the PC.

   Threads: any. One mutex guards everything; the event hooks are called with it held (they must not call back in). */
#ifndef HOS_AMIIBO_CORE_H
#define HOS_AMIIBO_CORE_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A figure of the catalogue: its 8-byte amiibo ID (AmiiboAPI's head + tail, in tag order) and its name (UTF-8). */
typedef struct {
    uint8_t id[8];
    char name[41];
} AmiiboFigure;

/* nfp result codes: module 115 | description << 9 (Horizon's encoding). 0 is success. */
#define AMIIBO_RC_DEVICE_NOT_FOUND 0x8073u                     /* 64 */
#define AMIIBO_RC_INVALID_ARGUMENT 0x8273u                     /* 65 */
#define AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE 0x8873u          /* 68 */
#define AMIIBO_RC_WRONG_DEVICE_STATE 0x9273u                   /* 73 */
#define AMIIBO_RC_TAG_REMOVED 0xC273u                          /* 97 */
#define AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED 0x10073u /* 128 */
#define AMIIBO_RC_WRONG_APPLICATION_AREA_ID 0x13073u           /* 152 */
#define AMIIBO_RC_APPLICATION_AREA_EXIST 0x15073u              /* 168 */
/* (and one more, for a call before Initialize, as Fritchii's nfp service answers it) */
#define AMIIBO_RC_NFC_DISABLED 0xA073u                         /* 80 */

/* Device states (u32, as GetDeviceState gives them). */
#define AMIIBO_STATE_INITIALIZED 0
#define AMIIBO_STATE_SEARCHING_FOR_TAG 1
#define AMIIBO_STATE_TAG_FOUND 2
#define AMIIBO_STATE_TAG_REMOVED 3
#define AMIIBO_STATE_TAG_MOUNTED 4
#define AMIIBO_STATE_UNAVAILABLE 5
#define AMIIBO_STATE_FINALIZED 6

/* Events, for the hooks: what host/nn_nfp.c makes system events of. */
#define AMIIBO_EV_ACTIVATE 0
#define AMIIBO_EV_DEACTIVATE 1
#define AMIIBO_EV_AVAILABILITY 2

/* The one device's handle, as amiibo_list_devices gives it. */
#define AMIIBO_DEVICE_HANDLE 1u

/* Sizes of what the info calls fill. */
#define AMIIBO_TAG_INFO_SIZE 0x58
#define AMIIBO_MODEL_INFO_SIZE 0x40
#define AMIIBO_COMMON_INFO_SIZE 0x40
#define AMIIBO_REGISTER_INFO_SIZE 0x100
#define AMIIBO_AREA_SIZE 0xD8

/* The switches (the menu's): emulation on (a device is listed), a random tag ID on every GetTagInfo, touch the selected
   figure as soon as the game searches. Defaults: off, off, on. Turning emulation on or off signals the availability
   event while initialized. */
void amiibo_config(int emulation, int random_uid, int auto_touch);
/* The user/amiibo folder (UTF-8): <dir>/<amiibo id>/<access id>.bin and state.txt. Without one, areas fail cleanly. */
void amiibo_set_dir(const char *dir);
/* signal/clear: an event (AMIIBO_EV_*); random: n random bytes (the random tag ID). Any may be NULL. */
void amiibo_set_hooks(void (*signal)(int ev), void (*clear)(int ev), void (*random)(uint8_t *out, size_t n));

/* The menu's side. select: the figure to touch next (copied; NULL: none; another figure removes the one on the reader).
   touch: put it on the reader (only while the game searches). remove: take it off. */
void amiibo_select(const AmiiboFigure *f);
void amiibo_touch(void);
void amiibo_remove(void);
/* The device state (AMIIBO_STATE_*), -1 before the first Initialize. */
int amiibo_device_state(void);

/* The nfp calls, each returning a result code (0 success). */
uint32_t amiibo_initialize(void);
uint32_t amiibo_finalize(void);
uint32_t amiibo_list_devices(uint64_t *out, int max, int *count);
uint32_t amiibo_start_detection(void);
uint32_t amiibo_stop_detection(void);
uint32_t amiibo_mount(void);
uint32_t amiibo_unmount(void);
uint32_t amiibo_tag_info(uint8_t out[0x58]);
uint32_t amiibo_model_info(uint8_t out[0x40]);
uint32_t amiibo_common_info(uint8_t out[0x40]);
uint32_t amiibo_register_info(uint8_t out[0x100]);
uint32_t amiibo_open_area(uint32_t access_id);
uint32_t amiibo_get_area(void *out, size_t cap, size_t *got);
uint32_t amiibo_set_area(const void *in, size_t n);
uint32_t amiibo_create_area(uint32_t access_id, const void *in, size_t n);
uint32_t amiibo_recreate_area(uint32_t access_id, const void *in, size_t n);
uint32_t amiibo_area_size(uint32_t *out);
uint32_t amiibo_flush(void);
uint32_t amiibo_restore(void);

#ifdef __cplusplus
}
#endif
#endif
