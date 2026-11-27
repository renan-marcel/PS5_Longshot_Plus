/* nn::nfp: the game's amiibo calls, answered by the virtual amiibo core (host/amiibo_core.h). The 23 functions bound here are
   the game's imports (docs/amiibo-nfp-calls.md: tests/test_nfp_hle_names.py compares the two and runs these bindings on the PC).

   Each call reads its arguments as the SDK's signature gives them (AArch64: x0.., a pointer or a reference is a guest address),
   asks the core and returns the core's result code in x0 (nn::Result, 0 success). GetDeviceState returns the state itself.
   DeviceHandle is 8 bytes, the core's AMIIBO_DEVICE_HANDLE. A null or out-of-window guest pointer is never written through:
   the call answers InvalidArgument (the core's) instead. With emulation off the core's answers stand: ListDevices succeeds
   with no device, the device calls say DeviceNotFound.

   The settings applet (both StartNicknameAndOwnerSettings, StartGameDataEraser, StartRestorer) would show the system's
   amiibo settings: answered as "the applet closed, nothing changed" (0, the device's handle; StartNicknameAndOwnerSettings
   says registered, with the figure's RegisterInfo). Events: the game attaches only the availability change event
   (AttachAvailabilityChangeEvent); the core's activate and deactivate have no guest event.

   Every call logs one "[NFP]" line (GetDeviceState, polled every frame, only when the state it gives changes): which calls
   the game makes is not known yet (docs/amiibo-nfp-calls.md's "called in game"). The log reaches logs/longshot_log.txt on the
   PC; on the PS5 it goes to klog only, so there each line is also appended to <title folder>/logs/nfp.txt (up to 1 MB).
   hos_main.c gives the core its folder (<user>/amiibo) and these hooks. */
#include "hos.h"
#include "amiibo_core.h"

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef _WIN32
#include <windows.h>
#include <ntsecapi.h>   /* (RtlGenRandom, as hos_report_run.c) */
#endif

/* ---- the [NFP] lines: the host's log, and on the PS5 logs/nfp.txt too (host/ps5/ps5_logfile.c; NFP_FILE_LOG: tests/nfp_hle_test.c
   sets it on the PC) */
#if defined(__PROSPERO__) && !defined(NFP_FILE_LOG)
#define NFP_FILE_LOG 1
#endif
#ifdef NFP_FILE_LOG
void hos_ps5_logfile(const char *name, const char *line);   /* (host/ps5/ps5_logfile.c) */
#endif

#if defined(__GNUC__)
__attribute__((format(printf, 1, 2)))
#endif
static void nfp_log(const char *fmt, ...) {
    char line[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(line, sizeof line, fmt, ap);
    va_end(ap);
    hos_log("%s", line);
#ifdef NFP_FILE_LOG
    hos_ps5_logfile("nfp.txt", line);
#endif
}

void hos_system_event_init(uint64_t key, int autoclear);   /* nn_os_sync.c */
void hos_system_event_signal(uint64_t key);
void hos_system_event_clear(uint64_t key);

/* ---- the core's hooks (hos_main.c sets them): the availability event is the guest's, the others have none */
static uint64_t availability_event;   /* (the guest's SystemEventType, 0 before AttachAvailabilityChangeEvent) */

void hos_nfp_signal(int ev) {
    const uint64_t key = __atomic_load_n(&availability_event, __ATOMIC_ACQUIRE);
    if (ev == AMIIBO_EV_AVAILABILITY && key) hos_system_event_signal(key);
}

void hos_nfp_clear(int ev) {
    const uint64_t key = __atomic_load_n(&availability_event, __ATOMIC_ACQUIRE);
    if (ev == AMIIBO_EV_AVAILABILITY && key) hos_system_event_clear(key);
}

/* the random tag ID's bytes */
void hos_nfp_random(uint8_t *out, size_t n) {
#if defined(_WIN32)
    if (RtlGenRandom(out, (ULONG)n)) return;
#elif defined(__PROSPERO__)
    arc4random_buf(out, n);
    return;
#else
    FILE *f = fopen("/dev/urandom", "rb");
    if (f) {
        const size_t got = fread(out, 1, n, f);
        fclose(f);
        if (got == n) return;
    }
#endif
    for (size_t i = 0; i < n; i++) out[i] = (uint8_t)rand();   /* (no generator: still varied) */
}

/* ---- guest memory */
/* the host pointer of n guest bytes at a: NULL for a null address or one not wholly in the guest window */
static void *guest(uint64_t a, uint64_t n) { return a ? hos_guest_range(a, n) : NULL; }

/* a DeviceHandle const& argument: 0 when it is the device's, else the result code */
static uint32_t handle_rc(uint64_t ref) {
    const uint8_t *p = (const uint8_t *)guest(ref, 8);
    if (!p) return AMIIBO_RC_INVALID_ARGUMENT;
    uint64_t h;
    memcpy(&h, p, 8);
    return h == AMIIBO_DEVICE_HANDLE ? 0 : AMIIBO_RC_DEVICE_NOT_FOUND;
}

/* the device is there (initialized, emulation on): 0, else the core's result code */
static uint32_t device_rc(void) {
    uint64_t handles[1];
    int count = 0;
    const uint32_t rc = amiibo_list_devices(handles, 1, &count);
    return rc ? rc : count ? 0 : AMIIBO_RC_DEVICE_NOT_FOUND;
}

/* a DeviceHandle* out: the device's handle, when there is somewhere to write it */
static void put_handle(uint64_t a) {
    uint8_t *p = (uint8_t *)guest(a, 8);
    const uint64_t h = AMIIBO_DEVICE_HANDLE;
    if (p) memcpy(p, &h, 8);
}

/* an info call (TagInfo, ModelInfo, CommonInfo, RegisterInfo): the core fills it, then the guest's out */
static uint32_t info(uint32_t (*fill)(uint8_t *), uint64_t out, size_t size, uint64_t ref) {
    uint8_t buf[AMIIBO_REGISTER_INFO_SIZE];
    uint8_t *p = (uint8_t *)guest(out, size);
    uint32_t rc = p ? handle_rc(ref) : AMIIBO_RC_INVALID_ARGUMENT;
    if (!rc) rc = fill(buf);
    if (!rc) memcpy(p, buf, size);
    return rc;
}

/* ---- the module */
HLE(_ZN2nn3nfp10InitializeEv) {
    const uint32_t rc = amiibo_initialize();
    nfp_log("[NFP] Initialize -> %#x (emulation %s)", rc, amiibo_emulation_on() ? "on" : "off");
    RET(rc);
}

HLE(_ZN2nn3nfp8FinalizeEv) {
    __atomic_store_n(&availability_event, 0, __ATOMIC_RELEASE);   /* (the game's event is its own again: never signalled after) */
    const uint32_t rc = amiibo_finalize();
    nfp_log("[NFP] Finalize -> %#x", rc);
    RET(rc);
}

/* AttachAvailabilityChangeEvent(nn::os::SystemEventType*): the guest's event, signalled when emulation is turned on or off */
HLE(_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE) {
    if (ARG(0)) {
        hos_system_event_init(ARG(0), 0);
        __atomic_store_n(&availability_event, ARG(0), __ATOMIC_RELEASE);
    }
    nfp_log("[NFP] AttachAvailabilityChangeEvent(%#llx)", (unsigned long long)ARG(0));
    RET(0);
}

/* ListDevices(DeviceHandle* out, int* count, int max) */
HLE(_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii) {
    const int max = (int)(uint32_t)ARG(2);
    uint8_t *out = (uint8_t *)guest(ARG(0), 8);   /* (one device: one handle at most) */
    uint8_t *count_out = (uint8_t *)guest(ARG(1), 4);
    uint64_t handles[1];
    int count = 0;
    const uint32_t rc = out && count_out ? amiibo_list_devices(handles, max, &count) : AMIIBO_RC_INVALID_ARGUMENT;
    if (!rc) {
        memcpy(out, handles, (size_t)count * 8);
        const int32_t n = count;
        memcpy(count_out, &n, 4);
    }
    nfp_log("[NFP] ListDevices(max %d) -> %#x, %d device(s)", max, rc, rc ? 0 : count);
    RET(rc);
}

/* GetDeviceState(DeviceHandle const&): the state in x0 (Unavailable when there is no device) */
HLE(_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE) {
    static int last_logged = -1;
    int s = handle_rc(ARG(0)) || device_rc() ? -1 : amiibo_device_state();
    if (s < 0) s = AMIIBO_STATE_UNAVAILABLE;
    if (__atomic_exchange_n(&last_logged, s, __ATOMIC_RELAXED) != s) nfp_log("[NFP] GetDeviceState -> state %d", s);
    RET((uint32_t)s);
}

/* GetNpadId(unsigned int* out, DeviceHandle const&): player 1's controller */
HLE(_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE) {
    uint8_t *out = (uint8_t *)guest(ARG(0), 4);
    uint32_t rc = out ? handle_rc(ARG(1)) : AMIIBO_RC_INVALID_ARGUMENT;
    if (!rc) rc = device_rc();
    if (!rc) memset(out, 0, 4);
    nfp_log("[NFP] GetNpadId -> %#x", rc);
    RET(rc);
}

/* ---- the reader */
HLE(_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE) {
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = amiibo_start_detection();
    nfp_log("[NFP] StartDetection -> %#x", rc);
    RET(rc);
}

HLE(_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE) {
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = amiibo_stop_detection();
    nfp_log("[NFP] StopDetection -> %#x", rc);
    RET(rc);
}

/* Mount(DeviceHandle const&, ModelType, MountTarget) */
HLE(_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE) {
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = amiibo_mount();
    nfp_log("[NFP] Mount(model %u, target %u) -> %#x", (unsigned)ARG(1), (unsigned)ARG(2), rc);
    RET(rc);
}

HLE(_ZN2nn3nfp5FlushERKNS0_12DeviceHandleE) {
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = amiibo_flush();
    nfp_log("[NFP] Flush -> %#x", rc);
    RET(rc);
}

/* ---- the infos: Get*Info(Info* out, DeviceHandle const&) */
HLE(_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE) {
    const uint32_t rc = info(amiibo_tag_info, ARG(0), AMIIBO_TAG_INFO_SIZE, ARG(1));
    nfp_log("[NFP] GetTagInfo -> %#x", rc);
    RET(rc);
}

HLE(_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE) {
    const uint32_t rc = info(amiibo_model_info, ARG(0), AMIIBO_MODEL_INFO_SIZE, ARG(1));
    nfp_log("[NFP] GetModelInfo -> %#x", rc);
    RET(rc);
}

HLE(_ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE) {
    const uint32_t rc = info(amiibo_common_info, ARG(0), AMIIBO_COMMON_INFO_SIZE, ARG(1));
    nfp_log("[NFP] GetCommonInfo -> %#x", rc);
    RET(rc);
}

HLE(_ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE) {
    const uint32_t rc = info(amiibo_register_info, ARG(0), AMIIBO_REGISTER_INFO_SIZE, ARG(1));
    nfp_log("[NFP] GetRegisterInfo -> %#x", rc);
    RET(rc);
}

/* ---- the application area */
/* OpenApplicationArea(DeviceHandle const&, unsigned int access_id) */
HLE(_ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj) {
    const uint32_t access_id = (uint32_t)ARG(1);
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = amiibo_open_area(access_id);
    nfp_log("[NFP] OpenApplicationArea(access %08x) -> %#x", access_id, rc);
    RET(rc);
}

/* GetApplicationArea(void* out, unsigned long* out_size, DeviceHandle const&, unsigned long cap) */
HLE(_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm) {
    const uint64_t cap = ARG(3);
    const size_t want = cap < AMIIBO_AREA_SIZE ? (size_t)cap : AMIIBO_AREA_SIZE;   /* (the core copies no more) */
    uint8_t *size_out = (uint8_t *)guest(ARG(1), 8);
    size_t got = 0;
    uint32_t rc = size_out ? handle_rc(ARG(2)) : AMIIBO_RC_INVALID_ARGUMENT;
    if (!rc) rc = amiibo_get_area(guest(ARG(0), want), want, &got);
    if (!rc) {
        const uint64_t n = got;
        memcpy(size_out, &n, 8);
    }
    nfp_log("[NFP] GetApplicationArea(cap %#llx) -> %#x, %#llx bytes", (unsigned long long)cap, rc, (unsigned long long)got);
    RET(rc);
}

/* SetApplicationArea(DeviceHandle const&, void const* data, unsigned long size): a size over 0xD8 is
   WrongApplicationAreaSize, whatever the data's address (it is looked at after the size) */
HLE(_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm) {
    const uint64_t size = ARG(2);
    uint32_t rc = handle_rc(ARG(0));
    if (!rc && size > AMIIBO_AREA_SIZE) rc = AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE;
    if (!rc) rc = amiibo_set_area(guest(ARG(1), size), (size_t)size);
    nfp_log("[NFP] SetApplicationArea(size %#llx) -> %#x", (unsigned long long)size, rc);
    RET(rc);
}

/* ApplicationAreaCreateInfo (the SDK's order: accessId, pInitialData, initialDataSize): taken as { u32 access_id @0; void*
   data @8; u32 size @0x10 }, an assumption the log lines let the game's run confirm. A size over 0xD8 is
   WrongApplicationAreaSize before the data's address is looked at; else the data is the size's bytes, NULL (InvalidArgument,
   the core's) when they are not wholly in the guest window */
typedef struct { uint32_t access_id; uint64_t data; uint32_t size; } CreateInfo;
static uint32_t create_info(uint64_t a, CreateInfo *ci, const void **in) {
    const uint8_t *p = (const uint8_t *)guest(a, 0x14);
    memset(ci, 0, sizeof *ci);
    *in = NULL;
    if (!p) return AMIIBO_RC_INVALID_ARGUMENT;
    memcpy(&ci->access_id, p, 4);
    memcpy(&ci->data, p + 8, 8);
    memcpy(&ci->size, p + 0x10, 4);
    if (ci->size > AMIIBO_AREA_SIZE) return AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE;
    *in = guest(ci->data, ci->size);
    return 0;
}

/* CreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&) */
HLE(_ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    CreateInfo ci;
    const void *in;
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = create_info(ARG(1), &ci, &in);
    else memset(&ci, 0, sizeof ci);
    if (!rc) rc = amiibo_create_area(ci.access_id, in, ci.size);
    nfp_log("[NFP] CreateApplicationArea(access %08x, data %#llx, size %#x) -> %#x", ci.access_id,
            (unsigned long long)ci.data, ci.size, rc);
    RET(rc);
}

/* RecreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&) */
HLE(_ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE) {
    CreateInfo ci;
    const void *in;
    uint32_t rc = handle_rc(ARG(0));
    if (!rc) rc = create_info(ARG(1), &ci, &in);
    else memset(&ci, 0, sizeof ci);
    if (!rc) rc = amiibo_recreate_area(ci.access_id, in, ci.size);
    nfp_log("[NFP] RecreateApplicationArea(access %08x, data %#llx, size %#x) -> %#x", ci.access_id,
            (unsigned long long)ci.data, ci.size, rc);
    RET(rc);
}

/* ---- the amiibo settings applet: "it closed, nothing changed" */
/* the StartNicknameAndOwnerSettings overloads (DeviceHandle* out, bool* registered, RegisterInfo* out, ...): the handle,
   registered, the figure's RegisterInfo (zero without one) */
static void nickname_and_owner(Ctx *c, const char *which) {
    put_handle(ARG(0));
    uint8_t *registered = (uint8_t *)guest(ARG(1), 1);
    if (registered) *registered = 1;
    uint8_t *out = (uint8_t *)guest(ARG(2), AMIIBO_REGISTER_INFO_SIZE);
    uint8_t buf[AMIIBO_REGISTER_INFO_SIZE];
    const uint32_t info_rc = amiibo_register_info(buf);
    if (info_rc) memset(buf, 0, sizeof buf);
    if (out) memcpy(out, buf, sizeof buf);
    nfp_log("[NFP] StartNicknameAndOwnerSettings (%s): the applet answered closed, registered (RegisterInfo %#x) -> 0", which,
            info_rc);
    RET(0);
}

HLE(_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoERKS4_) {
    nickname_and_owner(c, "with a RegisterInfo");
}

HLE(_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    nickname_and_owner(c, "without one");
}

/* StartGameDataEraser(DeviceHandle* out, AmiiboSettingsStartParam const&, TagInfo const&) */
HLE(_ZN2nn3nfp19StartGameDataEraserEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    put_handle(ARG(0));
    nfp_log("[NFP] StartGameDataEraser: the applet answered closed, nothing erased -> 0");
    RET(0);
}

/* StartRestorer(DeviceHandle* out, AmiiboSettingsStartParam const&, TagInfo const&) */
HLE(_ZN2nn3nfp13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE) {
    put_handle(ARG(0));
    nfp_log("[NFP] StartRestorer: the applet answered closed, nothing restored -> 0");
    RET(0);
}
