# Virtual amiibo on the PS5: design

Status: draft for approval · Branch: `feature/amiibo` (from `fork/develop` 5717db74)

## Intent

In *Ocarina of Time* on Switch 2, amiibo give items and some exclusive masks. The PS5 has no NFC reader, so today no
player can get them. This feature lets the player pick any amiibo from a full catalogue in the game's Insert menu, see
the figure, and "touch" it to the reader, so the game grants its rewards the way it does on the console. With a random
tag ID, the same figure can be used again and again: the game sees a new figure each time.

## Goals

- The game's own amiibo code runs and decides what to give (approach C, part A below): no hand-written list of rewards.
- An **Amiibo** tab in the Insert menu: emulation on/off, the figure chosen from the catalogue (by series, Zelda first),
  its picture, touch/remove, random tag ID, and a "Surprise me" figure.
- The catalogue is AmiiboAPI's (932 figures today), fetched by the builder on the player's PC, pictures included.
- Data a game writes to a figure (its application area) is kept per figure, in the title folder's `user/`.
- Works without the pictures (download failed, or turned off): a silhouette stands in.

## Non-goals

- Reading real figures, `.bin` dumps or emuiibo folders. (Possible later; not needed for the rewards.)
- Amiibo keys (`key_retail.bin`) or any encryption: the game only sees decrypted data through the API, which the
  runtime makes up from the catalogue, as emuiibo does.
- Writing the reward table of each figure by hand, unless part B is needed (below).
- Mii editing. The figure's owner is a fixed default Mii.

## Anti-goals (a failure even if it works)

- Any Nintendo picture, key or game-derived file in the repository, a release or a kit. Pictures are downloaded on
  the player's PC into the folder they build, like the game data (CONTRIBUTING's rule).
- emuiibo code copied in: emuiibo is GPLv2-only (its exemption is for Ryujinx alone) and this project is GPLv3. It is
  a reference for behaviour; the code is written fresh. AmiiboAPI's database is MIT: fine, credited in the kit's NOTICE.
- A run with emulation off behaving differently: with it off, `nn::nfp` acts as today (no device found).

## Calls made while writing this (the builder's check), for the person to review

- **Emulation On by default, and On means a reader is there**, figure chosen or not, as on a Switch 2, whose
  controllers always have one: the game may search and find nothing until a figure is touched. Off is today's
  behaviour (no reader). A fresh `longshot_options.ini` starts On.
- **If step 1 finds the game does not reach amiibo through imported `nn::nfp` free functions** (an applet, class
  members, `nn::nfc`, or the client inside the `sdk` module): stop and bring it back to the person before any
  service-level emulation; part B is the other way out.
- **The work that does not depend on step 1 starts at once**: the catalogue, the pictures, the tab and the state
  machine are needed by A and by B (B's rewards are chosen in the same tab). Only the `HLE(...)` names wait for step 1.
- **Reuse:** Random tag ID is the mechanism, areas stay per figure. If step 6 shows the game limits a figure some
  other way (a flag in its area or its save, or a daily clock), that limit is handled as a follow-up (B or a
  "fresh area per touch" switch), not guessed now.
- **Where it goes:** the PS5 build and the person's fork (`renan-marcel/PS5_Longshot_Plus`, PR into `develop`). The
  menu and runtime code are shared with the desktop build, so they build there too, and the tab shows "no catalogue"
  on a desktop build (its builder has no amiibo step). Upstream is a later decision.
- **Tab position:** Amiibo goes between Controls and Debug (Debug stays last, as a tool tab); `TAB_DEBUG` moves to
  5 and the checks that name it are updated in the same change.

## How emuiibo works (the reference)

emuiibo replaces the console's `nfp:user` service (a man-in-the-middle sysmodule) and answers the game's calls from a
"virtual amiibo" folder (`amiibo.json`: name, 8-byte amiibo ID, 10-byte UUID, `use_random_uuid`, dates, write counter,
Mii file; `areas/0x<access id>.bin` per game).

- **One fake device.** `ListDevices` returns one handle (player 1's controller id).
- **Device states:** `Initialized → (StartDetection) SearchingForTag → (figure connected) TagFound → (Mount) TagMounted`.
  `Unmount → TagFound`; figure removed while found/mounted → `SearchingForTag` (and `TagRemoved` exists in nfp);
  `StopDetection`/`Finalize → Initialized`. `StartDetection` is allowed from `Initialized` or `TagRemoved`.
- **Events:** activate (signalled on `SearchingForTag → TagFound`), deactivate (on removal), availability change. A
  100 ms thread polls the overlay's connected/disconnected flag and moves the state.
- **Info it returns:** `TagInfo` (UUID 10 bytes, length; with random UUID: 7 random bytes and 3 zero bytes, made anew
  on every `GetTagInfo`), `ModelInfo` (character id 3 bytes, series, model number, figure type, from the amiibo ID),
  `CommonInfo` (last write date, write counter, version, application area size `0xD8`), `RegisterInfo` (Mii charinfo,
  first write date, name ≤ 10 chars, font region).
- **Application area:** `OpenApplicationArea(access_id)` fails with "needs to be created" if the file does not exist;
  `Create`/`Recreate` write it; `Get`/`Set` read/write up to its size; `Flush`/`Restore`/`Format` succeed and do
  nothing; each write bumps the write counter and the last write date.
- **Guards:** info and area calls need `TagMounted` (`GetTagInfo` also `TagFound`), else `DeviceNotFound`.
- **Its tip:** turn emulation on before the game starts, as some games only look once.

## How Fritchii does it (the second reference, closer to the console)

Fritchii (`Frizti/Fritchii`, branch `oot-gather-fix`, v6.2) is an Eden-based Switch 2 emulator that runs OoT. Its NFC
stack is Eden/yuzu's (`src/core/hle/service/nfp/`, `nfc/common/device.cpp`), with nothing OoT- or Switch-2-specific
(no amiibo notes in its docs, no `nn::nfp` in its nx2 layer). It is **GPLv3, like Longshot**: its types and rules may
be adapted with credit in the file's header (unlike emuiibo's code). What it settles, used as written below:

- **Layouts** (`nfp_types.h`, `nfc_types.h`): `TagInfo` 0x58 = `uuid[10]`, `uuid_length` u8, 0x15 pad, `protocol` u32,
  `tag_type` u32, 0x30 pad. `ModelInfo` 0x40 = `character_id` u16, `character_variant` u8, `amiibo_type` u8,
  `model_number` u16, `series` u8, 0x39 pad. `CommonInfo` 0x40 = `WriteDate{u16 year,u8 month,u8 day}`,
  `write_counter` u16, `version` u8, pad, `application_area_size` u32 (= 0xD8), 0x34 pad. `RegisterInfo` 0x100 = Mii
  `CharInfo` (0x58), creation `WriteDate`, `amiibo_name` char[41] (UTF-8, ≤ 10 characters), `font_region` u8, 0x7A pad.
  `ApplicationArea` 0xD8 bytes. `DeviceHandle` is a u64.
- **ModelInfo from the 8-byte amiibo ID** (AmiiboAPI's `0x0100000003 4b0902`, bytes `01 00 00 00 03 4b 09 02`):
  `character_id` = bytes 0-1 kept in tag order, `character_variant` = byte 2, `amiibo_type` = byte 3 (0 figure, 1 card,
  2 yarn), `model_number` = bytes 4-5 **read big-endian** (0x034b), `series` = byte 6 (9 = The Legend of Zelda).
- **A figure's tag:** `protocol` TypeA (1), `tag_type` Type2 (2), `uuid_length` 7. Random tag ID: random bytes over
  the `uuid_length` on every `GetTagInfo` (Fritchii's `random_amiibo_id`, the same idea as emuiibo's).
- **States** (u32): Initialized 0, SearchingForTag 1, TagFound 2, TagRemoved 3, TagMounted 4, Unavailable 5,
  Finalized 6; module `State`: NonInitialized 0, Initialized 1.
- **Rules:** `StartDetection` only from Initialized/TagRemoved → SearchingForTag. A figure is found only while
  SearchingForTag → TagFound, deactivate cleared, activate signalled. Removal: unmount if mounted → TagRemoved,
  activate cleared, deactivate signalled. `StopDetection`: Initialized → ok; SearchingForTag/TagRemoved → Initialized;
  TagFound/TagMounted → close the tag first. `Mount` only from TagFound → TagMounted; `Unmount` → TagFound. Info and
  area calls need TagMounted (`GetTagInfo`: TagFound too) and return **TagRemoved** in that state, else
  **WrongDeviceState**. `GetApplicationArea`/`Set` need the area opened; `CreateApplicationArea` fails with
  **ApplicationAreaExist** if one exists; data over 0xD8 → **WrongApplicationAreaSize**; `OpenApplicationArea` with
  none → **ApplicationAreaIsNotInitialized**, another game's → **WrongApplicationAreaId**.
- **Result codes:** module NFP = 115; DeviceNotFound 64, InvalidArgument 65, WrongApplicationAreaSize 68,
  WrongDeviceState 73, NfcDisabled 80, TagRemoved 97, ApplicationAreaIsNotInitialized 128, WrongApplicationAreaId 152,
  ApplicationAreaExist 168 (Horizon's encoding: `module | description << 9`).
- **The `nfp:user` commands a game has** (0-25): Initialize, Finalize, ListDevices, Start/StopDetection, Mount,
  Unmount, Open/Get/SetApplicationArea, Flush, Restore, CreateApplicationArea, GetTagInfo, GetRegisterInfo,
  GetCommonInfo, GetModelInfo, AttachActivate/DeactivateEvent, GetState, GetDeviceState, GetNpadId,
  GetApplicationAreaSize, AttachAvailabilityChangeEvent, RecreateApplicationArea, StartDetectionWithFilter. Longshot
  replaces the SDK's client functions of the same names (`nn::nfp::Mount`, ...), one level above these commands.
- **What it leaves open:** the amiibo **settings applet** ("cabinet", `nn::nfp::AmiiboSettingsStartParam`) exists; if
  OoT opens it (to register a figure), step 1 shows it and it falls under the "stop and bring it back" rule.

## How Longshot works here today

- The runtime replaces the SDK at the `nn::` boundary (`nx2/standalone.py`): a function in `host/*.c` written
  `HLE(<mangled name>) { ... }` replaces the game's import. Every other function of an OS namespace, `nfp` among them
  (`OS_NAMESPACES`), gets a generated stub (`a64_stubs.c`) that logs its first call (`a64_unimplemented`) and returns 0.
- The game starts `NfpMgr` and `NfcDevice` threads (`docs/cpu-profile.md`): it uses nfp, and today sees nothing.
- System events are already there (`host/nn_os_sync.c`: `event_init`, `event_signal`; `hos_system_event_init`).
- The menu is Dear ImGui (`gpu/vk/vk_menu.cpp`): rows in a table (`{TAB_x, "Name", &opts.field, min, max, step, text,
  help, ...}`), `TAB_COUNT` tabs in `tab_titles`; the start screen draws a picture with an `ImTextureData` registered as
  a user texture (`gpu/vk/vk_imgui.cpp`, the logo). The menu has no PNG decoder; zstd is in the runtime.
- The builder already downloads pinned files by SHA-256 into a cache (`ps5/builder/package.py: fetch`), and Pillow is a
  build-time dependency (`nx2/prompt_requirements.txt`).

## Approaches

- **A. Implement the Switch's amiibo API (`nn::nfp`) in the runtime.** The game reads the virtual figure and decides
  the reward itself. Rules stay the game's; every figure it accepts works. Cost: finding which functions and
  signatures the Switch 2 SDK uses, and testing on a PS5.
- **B. Grant the reward directly** with an OoT patch (like the Debug tab's cheats). Fast, but not amiibo: each figure's
  reward found by hand; the game's rules are bypassed.
- **C. A first, B as the fallback** for whatever A cannot reach (a call that cannot be reproduced). **Chosen** by the
  person this is for, after studying emuiibo.

B is not built up front: it is a decision point after A's first in-game test (step 6 below).

## The design

### 1. Find the game's nfp calls (first step, gate for the rest)

The exact set of `nn::nfp` functions the game imports, and their mangled names (Switch 2 may keep some under
`nn::nfp::sdk`, which `os_facing` accepts), come from the game: the `a64_stubs.c` of a build lists every stubbed import
with its demangled name. A run with the game's amiibo screen open logs which ones it calls. This needs the person's
build and PS5; no game file leaves the PC: only the list of names (SDK symbols, not game data) is written into the
code. Signatures follow the Switch SDK's `nn::nfp` client API (switchbrew "NFC services" and libnx's `nfp.h` for the
struct layouts); a Switch 2 difference found here is written down in the doc for the HLE.

### 2. Runtime: `host/nn_nfp.c`

A new HLE file following Fritchii's rules and layouts above (adapted with credit; emuiibo only as behaviour):

- The state machine, one device handle, three events (made with the runtime's system events) and Fritchii's result
  codes for each failure.
- No polling thread: the menu's touch/remove calls `amiibo_touch()` / `amiibo_remove()` (a small C interface in
  `host/amiibo.h`, the menu side in C++), which moves the state and signals the event under one mutex.
- **Auto-touch:** with "Touch when the game asks" on (default), a figure that is selected is touched as soon as the
  game starts searching (`StartDetection`), and removed after `Unmount` + `StopDetection`. So the player picks a
  figure once and the game just finds it; the manual Touch/Remove row stays for games that ask to remove it.
- Info structs built from the catalogue entry: `ModelInfo` from the 8-byte amiibo ID (Fritchii's byte mapping above;
  checked by a test against "Link - Ocarina of Time"), `TagInfo` (TypeA, Type2, 7-byte UUID) with a fixed UUID per
  figure (derived from its ID, stable) or 7 random bytes on every read when Random tag ID is on, `CommonInfo` with
  size `0xD8`, `RegisterInfo` with the figure's name (cut to 10) and a fixed default Mii charinfo.
- Application areas: `user/amiibo/<amiibo id>/<access id>.bin` in the title folder; write counter and dates in
  `user/amiibo/<amiibo id>/state.txt`. With Random tag ID on, areas are still per figure (as emuiibo).
- Emulation off: every nfp call behaves as today's stubs (list returns no device), so nothing changes for a player who
  never opens the tab.
- Logs: one line per state change and per info call, with the `[NFP]` prefix, into the usual log / `crash_trace.txt`.

### 3. Catalogue and pictures: the builder

**The option.** The builder window gets a checkbox under the two that are there (`ps5/builder/app.py`, beside
`data_folder` and `known_skips`): **"Download amiibo (the catalogue and the figures' pictures, about N MB, once)"**,
saved in the window's settings (`amiibo`) like the others and passed as `--amiibo`. Off by default: the person ticks
it to have amiibo (a download from GitHub is the person's choice). The window's language is English like the rest.
Without it, the title folder has no `amiibo/` and the Amiibo tab says how to get it ("Build again with Download
amiibo ticked"); emulation still answers the game (no reader found).

**The pipeline step.** `ps5/builder/pipeline.py` gets an eighth step, **"Downloading the amiibo"**, after "Extracting
the game's data": `STEPS` grows to 8 and `build()` calls `amiibo(kit, work, app, a.amiibo)` last. Without the option
the step says it is skipped and ends at once (the window's progress still counts 8). It runs
`ps5/builder/amiibo.py` the way `game_data` runs `game_data.py` (`python -I -u`, the kit's `src`), and a failure
there is a warning, never a `Stop`: the title folder is whole without amiibo. `--check` reports whether the amiibo
cache is there and whether Pillow imports.

**The kit.** Pillow is not in the packaged builder (`package.py: PACKAGES`, `build_kit.sh: PYTHON_PACKAGES`): it is
added there at `nx2/prompt_requirements.txt`'s pin (`pillow==13.0.0`), so a packaged builder can make the pictures.

**What `amiibo.py` does:**

- Downloads AmiiboAPI at a **pinned commit** (zip from codeload, SHA-256 in the code) into the builder's cache
  (`<work>/amiibo-cache/`, kept like the rest of the work folder), once: a second build uses the cache, offline.
- Writes `amiibo/amiibo.idx` into the title folder: one record per figure (amiibo ID, name, series name, character
  name, picture offset/size), names transliterated to printable ASCII (the menu's glyphs are ASCII), sorted by series
  then name. Format small and fixed, read without a JSON parser.
- Writes `amiibo/figures.pak`: each picture scaled to fit 144×180 with Pillow, RGBA8, each zstd-compressed on its own
  (a figure's picture is decoded alone when chosen). Expected some tens of MB for the whole set.
- A failed download (no network, a changed archive whose SHA-256 differs) is one warning and no `amiibo/`; the build
  goes on and ends as done.
- Pinned commit bumped by hand for new figures.
- The builder's README/help text (`package.py`'s readme, `ps5/README.md`) gains a line on the option, and on the
  pictures being downloaded to the person's PC and never shared, like the title folder.

### 4. The Amiibo tab

A sixth tab, **Amiibo**, between Controls and Debug (`TAB_AMIIBO = 4`, `TAB_DEBUG = 5`, `TAB_COUNT = 6`; Motion, FPS
dev and Page move along as the enum's comment says). Rows (menu language is English, like the other tabs):

| Row | Values | Notes |
| --- | --- | --- |
| Amiibo emulation | Off / On | Default On. Off: the game finds no reader, as today. |
| Series | All, then each series (The Legend of Zelda first) | Filters the Figure row. |
| Figure | the figures of the series | Left/right steps; the picture updates. |
| Surprise me | action | Picks a random figure of the series. |
| Random tag ID | Off / On | Default On: each read is a new figure, so a figure can be used again. |
| Touch when the game asks | Off / On | Default On (auto-touch above). |
| Touch / Remove | action | Manual, for a game that asks to remove the figure. |

Beside the rows, a figure card: the picture (or a silhouette), its name, series and ID, and a status line from the
device state: "Not looking for amiibo", "The game is looking: touch to use", "On the reader", "Read". On the reader
the card glows in the menu's accent colour. The chosen figure and the switches are saved in `longshot_options.ini`
like the other settings (the figure by its amiibo ID, so a catalogue update keeps it).

The picture is loaded when the tab first shows it: decompress from `figures.pak`, make an `ImTextureData`, register it
as a user texture (as the logo), free the previous one.

### 5. Tests (game-free, `tests/`)

- The state machine and guards: a C test compiled with stubs (the repo's pattern), driving Initialize → StartDetection
  → touch → Mount → infos → areas → Unmount → remove, and the wrong-state failures.
- `ModelInfo` bytes from a known amiibo ID; random UUID shape (7 random, 3 zero, changes per read); fixed UUID stable.
- The builder's index and pack from a tiny fake AmiiboAPI tree (two figures, two small PNGs), and its reader on the
  runtime side; download failure → no `amiibo/`, build goes on.
- The pipeline: 8 steps, the amiibo step last, skipped without `--amiibo`, a warning (not a stop) on failure; the
  window's checkbox is saved and gives `--amiibo` (the existing builder checks' pattern).
- Menu rows: the tab exists, rows and defaults, options round-trip through `longshot_options.ini`.
- `python -I -B tests/run_all.py` before the PR (develop's baseline: 73 failing already, unrelated).

### 6. In-game test and the B decision

On the PS5: build with the catalogue, open the game's amiibo feature, pick "Link - Ocarina of Time" (and a non-Zelda
figure), check the reward and that Random tag ID lets the figure be used again. Then the decision: if a call cannot be
reproduced and the game will not grant a reward through A, part B (a patch that grants that reward) is designed then,
for those figures only, as its own change.

## Left to the builder

- File and struct names inside `host/nn_nfp.c`, the binary layout of `amiibo.idx` and `figures.pak`.
- The default Mii charinfo bytes (a valid neutral Mii).
- The figure card's exact look within the menu's existing style (`ui::` helpers, accent colour).
- The pinned AmiiboAPI commit (latest at build time) and its SHA-256.

## Open, needs the person

- Step 1 needs a build and a run on the person's PS5 to list the game's nfp calls.
