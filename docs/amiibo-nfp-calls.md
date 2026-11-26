# The game's nn::nfp imports

The amiibo feature answers the game's `nn::nfp` calls in `host/nn_nfp.c`, which binds each function below
(`tests/test_nfp_hle_names.py` compares the two). This page records which `nn::nfp` / `nn::nfc` functions the game imports. It lists
symbol names only, no game bytes. Regenerate the list from a build's work folder:

    python -I scripts/list_nfp_imports.py <work folder>

It reads `lift/sa/gen/a64_stubs.c` and prints `mangled<TAB>demangled`; the demangled column needs `c++filt` on PATH, and the
table below was demangled with it. The build listed 23 imports, all in `nn::nfp`, none in `nn::nfc`.

| mangled | demangled | called in game |
|---|---|---|
| `_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoERKS4_` | `nn::nfp::StartNicknameAndOwnerSettings(DeviceHandle*, bool*, RegisterInfo*, AmiiboSettingsStartParam const&, TagInfo const&, RegisterInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp29StartNicknameAndOwnerSettingsEPNS0_12DeviceHandleEPbPNS0_12RegisterInfoERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE` | `nn::nfp::StartNicknameAndOwnerSettings(DeviceHandle*, bool*, RegisterInfo*, AmiiboSettingsStartParam const&, TagInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp19StartGameDataEraserEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE` | `nn::nfp::StartGameDataEraser(DeviceHandle*, AmiiboSettingsStartParam const&, TagInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp13StartRestorerEPNS0_12DeviceHandleERKNS0_24AmiiboSettingsStartParamERKNS0_7TagInfoE` | `nn::nfp::StartRestorer(DeviceHandle*, AmiiboSettingsStartParam const&, TagInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp29AttachAvailabilityChangeEventEPNS_2os15SystemEventTypeE` | `nn::nfp::AttachAvailabilityChangeEvent(nn::os::SystemEventType*)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp10InitializeEv` | `nn::nfp::Initialize()` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp8FinalizeEv` | `nn::nfp::Finalize()` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE` | `nn::nfp::GetDeviceState(DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp9GetNpadIdEPjRKNS0_12DeviceHandleE` | `nn::nfp::GetNpadId(unsigned int*, DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp11ListDevicesEPNS0_12DeviceHandleEPii` | `nn::nfp::ListDevices(DeviceHandle*, int*, int)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp14StartDetectionERKNS0_12DeviceHandleE` | `nn::nfp::StartDetection(DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp13StopDetectionERKNS0_12DeviceHandleE` | `nn::nfp::StopDetection(DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp5MountERKNS0_12DeviceHandleENS0_9ModelTypeENS0_11MountTargetE` | `nn::nfp::Mount(DeviceHandle const&, ModelType, MountTarget)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp19OpenApplicationAreaERKNS0_12DeviceHandleEj` | `nn::nfp::OpenApplicationArea(DeviceHandle const&, unsigned int)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp18GetApplicationAreaEPvPmRKNS0_12DeviceHandleEm` | `nn::nfp::GetApplicationArea(void*, unsigned long*, DeviceHandle const&, unsigned long)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp18SetApplicationAreaERKNS0_12DeviceHandleEPKvm` | `nn::nfp::SetApplicationArea(DeviceHandle const&, void const*, unsigned long)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp23RecreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE` | `nn::nfp::RecreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp5FlushERKNS0_12DeviceHandleE` | `nn::nfp::Flush(DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp21CreateApplicationAreaERKNS0_12DeviceHandleERKNS0_25ApplicationAreaCreateInfoE` | `nn::nfp::CreateApplicationArea(DeviceHandle const&, ApplicationAreaCreateInfo const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp10GetTagInfoEPNS0_7TagInfoERKNS0_12DeviceHandleE` | `nn::nfp::GetTagInfo(TagInfo*, DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp15GetRegisterInfoEPNS0_12RegisterInfoERKNS0_12DeviceHandleE` | `nn::nfp::GetRegisterInfo(RegisterInfo*, DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp13GetCommonInfoEPNS0_10CommonInfoERKNS0_12DeviceHandleE` | `nn::nfp::GetCommonInfo(CommonInfo*, DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |
| `_ZN2nn3nfp12GetModelInfoEPNS0_9ModelInfoERKNS0_12DeviceHandleE` | `nn::nfp::GetModelInfo(ModelInfo*, DeviceHandle const&)` | not yet known (see the [NFP] log after Task 3) |

## The settings applet calls

Both `StartNicknameAndOwnerSettings` overloads, `StartGameDataEraser` and `StartRestorer` open the system's amiibo-settings
applet. The host answers each as "the applet closed, nothing changed" and logs the call. The reason: the core always answers
`GetRegisterInfo`, so the registration applet should not be needed. If the `[NFP]` log shows the game calling them, revisit.

## What the list says about the game

- There is no `AttachActivateEvent` or `AttachDeactivateEvent`: the game polls `GetDeviceState` rather than waiting on
  events. (`AttachAvailabilityChangeEvent` is imported.)
- There is no `GetApplicationAreaSize`: the game passes its own size to `GetApplicationArea`.
- There is no `Restore`.
- Which of these the game calls while playing is not yet known: the stubs log to stderr, which the PS5 does not keep, so
  the "called in game" column is filled from the `[NFP]` log lines the host answers add. On the PS5 they are also written
  to `logs/nfp.txt` in the title folder (up to 1 MB a run); on the PC they are in `logs/longshot_log.txt`.
