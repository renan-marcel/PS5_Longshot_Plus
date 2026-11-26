/* host/nn_nfp.c's bindings run on the PC (tests/test_nfp_hle_names.py): compiled unchanged with host/amiibo_core.c against
   a stand-in hos.h (the test writes it), guest memory being test_mem. Each imp_ is called as the lifted game calls it: the
   arguments in x0.., the result in x0. argv[1]: an empty folder for the application areas. */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "amiibo_core.h"
#include "hos.h"

uint8_t test_mem[TEST_MEM_SIZE];

/* ---- stand-ins: the host's log and nn_os_sync.c's system events */
static char last_line[1024];
static int lines, state_lines, bad_lines;
void hos_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(last_line, sizeof last_line, fmt, ap);
    va_end(ap);
    lines++;
    if (strncmp(last_line, "[NFP] ", 6)) bad_lines++;
    if (strstr(last_line, "GetDeviceState")) state_lines++;
}
static uint64_t ev_init_key = 0, ev_signal_key = 0, ev_clear_key = 0;
static int ev_init_mode = -1, ev_signals, ev_clears;
void hos_system_event_init(uint64_t key, int autoclear) { ev_init_key = key, ev_init_mode = autoclear; }
void hos_system_event_signal(uint64_t key) { ev_signal_key = key, ev_signals++; }
void hos_system_event_clear(uint64_t key) { ev_clear_key = key, ev_clears++; }

/* ---- host/nn_nfp.c's: the hooks hos_main.c gives the core, and the bindings */
void hos_nfp_signal(int ev);
void hos_nfp_clear(int ev);
void hos_nfp_random(uint8_t *out, size_t n);
#define NFP(name) void imp__ZN2nn3nfp##name(Ctx *c)
NFP(29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoERKS4_);
NFP(29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE);
NFP(19StartGameDataEraserEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE);
NFP(13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE);
NFP(29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE);
NFP(10InitializeEv);
NFP(8FinalizeEv);
NFP(14GetDeviceStateERKNS0_12DeviceHandleE);
NFP(9GetNpadIdEPjRKNS0_12DeviceHandleE);
NFP(11ListDevicesEPNS0_12DeviceHandleEPii);
NFP(14StartDetectionERKNS0_12DeviceHandleE);
NFP(13StopDetectionERKNS0_12DeviceHandleE);
NFP(5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE);
NFP(19OpenApplicationAreaERKNS0_12DeviceHandleEj);
NFP(18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm);
NFP(18SetApplicationAreaERKNS0_12DeviceHandleEPKvm);
NFP(23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE);
NFP(5FlushERKNS0_12DeviceHandleE);
NFP(21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE);
NFP(10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE);
NFP(15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE);
NFP(13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE);
NFP(12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE);

static int failures;
#define CHECK(cond, what) do { if (!(cond)) { printf("FAIL line %d: %s\n", __LINE__, what); failures++; } } while (0)

/* a call: up to four arguments, x0 after it */
static uint64_t call(void (*fn)(Ctx *), uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3) {
    Ctx c;
    memset(&c, 0, sizeof c);
    c.x[0] = a0, c.x[1] = a1, c.x[2] = a2, c.x[3] = a3;
    c.x[4] = 0xDEADull;   /* (garbage above the arguments, as a real call has) */
    fn(&c);
    return c.x[0];
}
#define CALL(name, a0, a1, a2, a3) call(imp__ZN2nn3nfp##name, a0, a1, a2, a3)

static uint64_t g64(uint64_t a) { uint64_t v; memcpy(&v, test_mem + a, 8); return v; }
static uint32_t g32(uint64_t a) { uint32_t v; memcpy(&v, test_mem + a, 4); return v; }
static void p64(uint64_t a, uint64_t v) { memcpy(test_mem + a, &v, 8); }
static void p32(uint64_t a, uint32_t v) { memcpy(test_mem + a, &v, 4); }
static int all_bytes(uint64_t a, size_t n, uint8_t b) {
    for (size_t i = 0; i < n; i++)
        if (test_mem[a + i] != b) return 0;
    return 1;
}

/* guest addresses (test_mem) */
enum {
    EVENT = 0x100, HANDLES = 0x200, COUNT = 0x280, HANDLE = 0x300, NPAD = 0x320, OUT_HANDLE = 0x340, REGISTERED = 0x360,
    TAG = 0x400, MODEL = 0x500, COMMON = 0x580, REGISTER = 0x600, CREATE_INFO = 0x800, DATA = 0x900, AREA = 0xA00,
    AREA_SIZE = 0xB00, PARAM = 0xC00, BIG = 0x1000
};

#define OK 0u

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    amiibo_set_dir(argv[1]);
    amiibo_set_hooks(hos_nfp_signal, hos_nfp_clear, hos_nfp_random);
    p64(HANDLE, AMIIBO_DEVICE_HANDLE);

    /* before Initialize: the core's answer; a device call too */
    CHECK(CALL(11ListDevicesEPNS0_12DeviceHandleEPii, HANDLES, COUNT, 4, 0) == AMIIBO_RC_NFC_DISABLED, "ListDevices before Initialize");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_UNAVAILABLE, "GetDeviceState before Initialize");

    /* the availability event: the guest's, kept for the hook */
    CALL(29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE, EVENT, 0, 0, 0);
    CHECK(ev_init_key == EVENT && ev_init_mode == 0, "AttachAvailabilityChangeEvent inits the guest event (manual clear)");
    CHECK(CALL(10InitializeEv, 0, 0, 0, 0) == OK, "Initialize");

    /* emulation off (the default): no device, success; the device calls answer DeviceNotFound */
    p32(COUNT, 77);
    CHECK(CALL(11ListDevicesEPNS0_12DeviceHandleEPii, HANDLES, COUNT, 4, 0) == OK, "ListDevices, emulation off: success");
    CHECK(g32(COUNT) == 0, "ListDevices, emulation off: count 0");
    CHECK(CALL(14StartDetectionERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_RC_DEVICE_NOT_FOUND, "StartDetection, emulation off");
    CHECK(CALL(5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE, HANDLE, 0, 3, 0) == AMIIBO_RC_DEVICE_NOT_FOUND,
          "Mount, emulation off");

    /* emulation on: the core signals the availability change, on the guest's event */
    amiibo_config(1, 0, 1);
    CHECK(ev_signals == 1 && ev_signal_key == EVENT, "the availability change signals the guest's event");

    /* ListDevices: the handle and the count written; null outs refused, nothing written */
    p32(COUNT, 77);
    p64(HANDLES, 0);
    CHECK(CALL(11ListDevicesEPNS0_12DeviceHandleEPii, HANDLES, COUNT, 4, 0) == OK, "ListDevices");
    CHECK(g32(COUNT) == 1 && g64(HANDLES) == AMIIBO_DEVICE_HANDLE, "ListDevices writes one handle and the count");
    CHECK(CALL(11ListDevicesEPNS0_12DeviceHandleEPii, 0, COUNT, 4, 0) == AMIIBO_RC_INVALID_ARGUMENT, "ListDevices, no out");
    CHECK(CALL(11ListDevicesEPNS0_12DeviceHandleEPii, HANDLES, 0, 4, 0) == AMIIBO_RC_INVALID_ARGUMENT, "ListDevices, no count");
    CHECK(all_bytes(0, 0x100, 0), "nothing written at guest address 0");

    /* GetNpadId: player 1 */
    p32(NPAD, 0xFFFFFFFFu);
    CHECK(CALL(9GetNpadIdEPjRKNS0_12DeviceHandleE, NPAD, HANDLE, 0, 0) == OK && g32(NPAD) == 0, "GetNpadId writes 0");
    CHECK(CALL(9GetNpadIdEPjRKNS0_12DeviceHandleE, 0, HANDLE, 0, 0) == AMIIBO_RC_INVALID_ARGUMENT, "GetNpadId, no out");
    p64(BIG, 99);
    CHECK(CALL(9GetNpadIdEPjRKNS0_12DeviceHandleE, NPAD, BIG, 0, 0) == AMIIBO_RC_DEVICE_NOT_FOUND, "another handle: not found");

    /* GetDeviceState: in x0, logged only when it changes */
    const int before = state_lines;
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_INITIALIZED, "GetDeviceState: Initialized");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_INITIALIZED, "GetDeviceState again");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_INITIALIZED, "GetDeviceState again");
    CHECK(state_lines == before + 1, "GetDeviceState logged once for the same state");

    /* the settings applet with nothing mounted: closed, handle written, registered, an empty RegisterInfo */
    memset(test_mem + REGISTER, 0xAB, 0x100);
    p64(OUT_HANDLE, 0);
    test_mem[REGISTERED] = 0;
    CHECK(CALL(29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE,
               OUT_HANDLE, REGISTERED, REGISTER, PARAM) == OK, "StartNicknameAndOwnerSettings: 0");
    CHECK(g64(OUT_HANDLE) == AMIIBO_DEVICE_HANDLE && test_mem[REGISTERED] == 1, "the handle written, registered");
    CHECK(all_bytes(REGISTER, 0x100, 0), "no figure: the RegisterInfo zeroed");
    CHECK(CALL(29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE,
               0, 0, 0, PARAM) == OK, "StartNicknameAndOwnerSettings with null outs: 0, nothing written");
    CHECK(all_bytes(0, 0x100, 0), "nothing written at guest address 0");

    /* a figure: touched as the game searches (auto-touch), mounted */
    AmiiboFigure link = {{0x01, 0x00, 0x00, 0x00, 0x03, 0x4b, 0x09, 0x02}, "Link (Ocarina of Time)"};
    amiibo_select(&link);
    CHECK(CALL(14StartDetectionERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == OK, "StartDetection");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_TAG_FOUND, "TagFound");
    CHECK(state_lines == before + 2, "GetDeviceState logged at the change");
    CHECK(CALL(10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE, TAG, HANDLE, 0, 0) == OK && test_mem[TAG + 0x0A] == 7,
          "GetTagInfo: the 7-byte UUID");
    CHECK(CALL(10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE, 0, HANDLE, 0, 0) == AMIIBO_RC_INVALID_ARGUMENT, "GetTagInfo, no out");
    CHECK(CALL(5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE, HANDLE, 0, 3, 0) == OK, "Mount");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_TAG_MOUNTED, "TagMounted");
    CHECK(CALL(12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE, MODEL, HANDLE, 0, 0) == OK && test_mem[MODEL + 6] == 0x09,
          "GetModelInfo");
    CHECK(CALL(13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE, COMMON, HANDLE, 0, 0) == OK &&
          g32(COMMON + 8) == AMIIBO_AREA_SIZE, "GetCommonInfo");
    CHECK(CALL(15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE, REGISTER, HANDLE, 0, 0) == OK &&
          !memcmp(test_mem + REGISTER + 0x5C, "Link (Ocar", 11), "GetRegisterInfo: the name, 10 characters");

    /* the settings applet with a figure: its RegisterInfo */
    memset(test_mem + REGISTER, 0, 0x100);
    test_mem[REGISTERED] = 0;
    p64(OUT_HANDLE, 0);
    CHECK(CALL(29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoERKS4_,
               OUT_HANDLE, REGISTERED, REGISTER, PARAM) == OK, "StartNicknameAndOwnerSettings (6 args): 0");
    CHECK(g64(OUT_HANDLE) == AMIIBO_DEVICE_HANDLE && test_mem[REGISTERED] == 1 &&
          !memcmp(test_mem + REGISTER + 0x5C, "Link (Ocar", 11), "the handle, registered, the figure's RegisterInfo");
    p64(OUT_HANDLE, 0);
    CHECK(CALL(19StartGameDataEraserEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE, OUT_HANDLE, PARAM, TAG, 0) == OK &&
          g64(OUT_HANDLE) == AMIIBO_DEVICE_HANDLE, "StartGameDataEraser: 0, the handle");
    p64(OUT_HANDLE, 0);
    CHECK(CALL(13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE, OUT_HANDLE, PARAM, TAG, 0) == OK &&
          g64(OUT_HANDLE) == AMIIBO_DEVICE_HANDLE, "StartRestorer: 0, the handle");
    CHECK(CALL(13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE, 0, PARAM, TAG, 0) == OK,
          "StartRestorer, no out: 0");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_TAG_MOUNTED, "the applets changed nothing");

    /* the application area: none yet; created from ApplicationAreaCreateInfo {access id @0, data @8, size @0x10} */
    const uint32_t access = 0x01006A80u;
    CHECK(CALL(19OpenApplicationAreaERKNS0_12DeviceHandleEj, HANDLE, access, 0, 0) == AMIIBO_RC_APPLICATION_AREA_IS_NOT_INITIALIZED,
          "OpenApplicationArea: none yet");
    for (int i = 0; i < 0x20; i++) test_mem[DATA + i] = (uint8_t)(0x40 + i);
    p32(CREATE_INFO, access);
    p32(CREATE_INFO + 4, 0xCCCCCCCCu);   /* (padding) */
    p64(CREATE_INFO + 8, DATA);
    p32(CREATE_INFO + 0x10, 0x20);
    CHECK(CALL(21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE, HANDLE, CREATE_INFO, 0, 0) == OK,
          "CreateApplicationArea");
    CHECK(strstr(last_line, "01006a80") && strstr(last_line, "0x900") && strstr(last_line, "0x20"),
          "CreateApplicationArea logs the access id, the data and the size");
    CHECK(CALL(21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE, HANDLE, CREATE_INFO, 0, 0) ==
          AMIIBO_RC_APPLICATION_AREA_EXIST, "CreateApplicationArea again: exists");
    p32(CREATE_INFO + 0x10, 0xD9);
    CHECK(CALL(23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE, HANDLE, CREATE_INFO, 0, 0) ==
          AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE, "RecreateApplicationArea, 0xD9 bytes: refused by size");
    p64(CREATE_INFO + 8, TEST_MEM_SIZE - 0x10);   /* (data at the window's end: a size over 0xD8 still the size's error) */
    p32(CREATE_INFO + 0x10, 0x1000);
    CHECK(CALL(23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE, HANDLE, CREATE_INFO, 0, 0) !=
          OK, "RecreateApplicationArea, out of the window: refused");
    CHECK(CALL(23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE, HANDLE, 0, 0, 0) ==
          AMIIBO_RC_INVALID_ARGUMENT, "RecreateApplicationArea, no info");

    /* opened, read: GetApplicationArea(out, out_size, handle, cap) */
    CHECK(CALL(19OpenApplicationAreaERKNS0_12DeviceHandleEj, HANDLE, access, 0, 0) == OK, "OpenApplicationArea");
    memset(test_mem + AREA, 0xEE, 0x100);
    p64(AREA_SIZE, 0);
    CHECK(CALL(18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm, AREA, AREA_SIZE, HANDLE, 0xD8) == OK, "GetApplicationArea");
    CHECK(g64(AREA_SIZE) == 0xD8 && test_mem[AREA] == 0x40 && test_mem[AREA + 0x1F] == 0x5F && test_mem[AREA + 0x20] == 0 &&
          test_mem[AREA + 0xD8] == 0xEE, "GetApplicationArea: 0xD8 bytes, the size written, nothing past them");
    p64(AREA_SIZE, 0);
    CHECK(CALL(18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm, AREA, AREA_SIZE, HANDLE, 0x10) == OK && g64(AREA_SIZE) == 0x10,
          "GetApplicationArea, a smaller cap");
    CHECK(CALL(18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm, AREA, 0, HANDLE, 0xD8) == AMIIBO_RC_INVALID_ARGUMENT,
          "GetApplicationArea, no size out");

    /* written: SetApplicationArea(handle, data, size), then read back */
    for (int i = 0; i < 0xD8; i++) test_mem[DATA + i] = (uint8_t)i;
    CHECK(CALL(18SetApplicationAreaERKNS0_12DeviceHandleEPKvm, HANDLE, DATA, 0xD8, 0) == OK, "SetApplicationArea");
    CHECK(CALL(18SetApplicationAreaERKNS0_12DeviceHandleEPKvm, HANDLE, DATA, 0xD9, 0) == AMIIBO_RC_WRONG_APPLICATION_AREA_SIZE,
          "SetApplicationArea, 0xD9 bytes");
    CHECK(CALL(5FlushERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == OK, "Flush");
    CHECK(CALL(18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm, AREA, AREA_SIZE, HANDLE, 0xD8) == OK &&
          test_mem[AREA + 0xD7] == 0xD7, "the area read back");
    char path[2048];
    snprintf(path, sizeof path, "%s/01000000034b0902/01006a80.bin", argv[1]);
    FILE *f = fopen(path, "rb");
    CHECK(f != NULL, "the area's file");
    if (f) fclose(f);

    /* removed, stopped, finalized */
    CHECK(CALL(13StopDetectionERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == OK, "StopDetection");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_INITIALIZED, "Initialized again");
    CHECK(CALL(8FinalizeEv, 0, 0, 0, 0) == OK, "Finalize");
    CHECK(CALL(14GetDeviceStateERKNS0_12DeviceHandleE, HANDLE, 0, 0, 0) == AMIIBO_STATE_UNAVAILABLE, "Unavailable after Finalize");

    /* the hooks: activate / deactivate have no guest event; the random bytes are filled */
    const int signals = ev_signals, clears = ev_clears;
    hos_nfp_signal(AMIIBO_EV_ACTIVATE);
    hos_nfp_clear(AMIIBO_EV_DEACTIVATE);
    CHECK(ev_signals == signals && ev_clears == clears, "no guest event for activate / deactivate");
    hos_nfp_clear(AMIIBO_EV_AVAILABILITY);
    CHECK(ev_clears == clears + 1 && ev_clear_key == EVENT, "the availability event cleared");
    uint8_t r1[16] = {0}, r2[16] = {0};
    hos_nfp_random(r1, sizeof r1);
    hos_nfp_random(r2, sizeof r2);
    CHECK(memcmp(r1, r2, sizeof r1) != 0, "random bytes");

    CHECK(lines > 20 && bad_lines == 0, "every log line starts with [NFP]");
    if (failures) {
        printf("%d failure(s); last log line: %s\n", failures, last_line);
        return 1;
    }
    printf("PASS (%d log lines)\n", lines);
    return 0;
}
