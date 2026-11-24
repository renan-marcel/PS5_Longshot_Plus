# Hookshot on the PS5

This fork builds Hookshot (the static recompilation of *The Legend of Zelda: Ocarina of Time* for Nintendo Switch 2)
as a native PS5 title, **PPSA99198**, on my homebrew stack: Mesa's RADV from
[PS5_Vulkan](https://github.com/mihawk-99/PS5_Vulkan) and the platform layer of my
[PS5_PayloadSDK](https://github.com/mihawk-99/PS5_PayloadSDK) fork. Upstream is
[NotRexed/Hookshot](https://github.com/NotRexed/Hookshot) (the `upstream` remote); everything else here is upstream's.

> [!IMPORTANT]
> No game files, keys or anything made from the game are in this repository or its releases. The title is built on a
> PC from your own copy of the game, and what that build makes from the game (`image.bin`, the lifted C, the
> executable) stays on your PC and your console.

## The route

| Step | What | Where |
| --- | --- | --- |
| Lift | The game's ARM64 code to C, from your `.nup`, as upstream does it | `nx2/nup.py --only exefs`, `nx2/lift.py --standalone --write` |
| Compile | The lifted game, `host/` and `gpu/vk` for `x86_64-sie-ps5` (Zen 2) | `ps5/build.py` |
| Link | One executable with RADV linked in, signed as the console's fake SELF | `ps5/tools/link.sh` (PS5_VulkanTemplate's link) |
| Data | The game's whole romfs from your `.nup` into the title folder's `Data/`, as plain files, damaged dump files replaced | `ps5/builder/game_data.py` (`nx2/nup.py` extract) |
| Install | `dist/PPSA99198` with its `Data/` to `/data/homebrew/PPSA99198`; the console reads every game file from `Data/` and never the `.nup` | FTP, `host/hos_main.c` |

Players do all of it with the Longshot PS5 Builder, a desktop program for Linux and Windows that carries everything but
the game (`ps5/builder/README.md`). For development, `ps5/builder/build_kit.sh` fetches PS5_Mesa, PS5_PayloadSDK and
PS5_MihawkGen at the revisions the build was played with into `.local/`, builds RADV and the SDK once, and the title
is `dist/PPSA99198`. By hand, with those in place, the steps are:

```sh
python3 -I nx2/nup.py <your game.nup> --only exefs --extract work/game
mkdir -p work/lift/image
OOT_WORK=$PWD/work/lift python3 -I nx2/lift.py --standalone --write --exefs $PWD/work/game/exefs --work $PWD/work/lift
ps5/tools/build-ffmpeg.sh
python3 -I ps5/build.py
```

The Python packages are upstream's (`lz4 numpy capstone "unicorn>=2.1,<2.2" zstandard`). The Vulkan, SPIR-V and VMA
headers are upstream's pins (`scripts/linux/deps.sh`) in `.local/ps5-deps/cpm`.

## What is the PS5's

Upstream's Linux build is the base: `host/` with `host/posix`'s Win32 calls, and `gpu/vk`. The PS5 changes are behind
`__PROSPERO__` in upstream's files and in `host/ps5/`:

| Linux build | PS5 | File |
| --- | --- | --- |
| SDL3 or SDL2 (window, controllers, sound, microphones) | VK_KHR_display, the DualSense through scePad, sceAudioOut; no microphone | `host/ps5/hos_sdl_ps5.c`, `host/ps5/platform.c` (PS5_VulkanTemplate's) |
| The guest window at 16 TiB, all of it readable, pages made on first touch | at 64 GiB, 64 GiB of it, reserved and committed in 64 KiB units of direct memory, as on Windows; large commits backed on first touch. A unit's memory is zeroed before it is mapped where the game looks (`host/ps5/zero_first.h`; `HOS_PS5_ZERO_FIRST=0`: after, as it was, which lost the stores another thread made meanwhile; `HOS_PS5_ZERO_WAIT_US`, a test's, waits before the zeros) | `host/ps5/win32_ps5.c`, `host/hos.h`, `host/hos_main.c` |
| `hookshot_vk.so` and `libvulkan.so.1` loaded at run time | linked in; `dlopen`/`dlsym` answer from a table | `host/ps5/win32_ps5.c` |
| Thread and fiber stacks from mmap | reserved in full, 256 KiB backed and grown on fault, freed once the thread has ended; at most 16 MiB (`HOS_PS5_STACK_MB`) | `host/ps5/win32_ps5.c` |
| futex, gettid, /proc, /sys | `_umtx_op`, `pthread_getthreadid_np`, the console's known layout | `host/posix/win32_posix.c` |
| A mutex's object looked up by its address at every lock (a per-thread cache, then the shared table) | found by an index kept in the game's own mutex (`HOS_MUTEX_IX`, on here; `=0` is the lookup) | `host/nn_os_sync.c` |
| `_exit` | the shell's exit (`sceSystemServiceLoadExec("exit")`) | `host/ps5/win32_ps5.c` |

**Why the window moved.** The console grants no address space at or above 1 TiB, RADV keeps [8, 12) GiB for its
32-bit window and [256, 512) GiB for device memory, and the platform's heap reserves 16 GiB at 128 GiB. At 64 GiB with
64 GiB of guest space (the guest's heap from guest 16 GiB), all of it lands in host [64, 128) GiB.

**Guest pages carry the GPU bits.** The renderer imports the game's memory pools straight from these pages
(`VK_EXT_external_memory_host`); RADV grants the GPU access with a protection change, and any later protection change
without the GPU bits would make the GPU fault on the pool. So guest pages are mapped with the GPU bits from the start. A
discard unmaps whole 64 KiB units and puts their direct memory on a free list that the next commit takes first.

**param.json.** `attribute3` is 139722816, as ProsperoEden's: the Pro's larger memory pool and the high CPU clock
together.

## Status

- [x] Lift on the PC (100% of 17.6 M instructions, 143 s)
- [x] The runtime and the Vulkan back end compile for the console
- [x] Link
- [x] First boot on the Pro: title, menus and movies at 60 fps; play in Link's house and Kokiri Forest
- [x] Foliage drawn every other frame only (2026-11-10): gone in Kokiri Forest with storage buffers bound from multiples of
      256, and in the Sacred Meadow with the page table of guest memory on the console's guest layout (2026-11-16); the
      cause is under "Open questions"
- [x] Frame generation: [PS5_MihawkGen](https://github.com/mihawk-99/PS5_MihawkGen) makes the frames between the game's (below)
- [x] Stalls of 1.8 s in play: the test tools' own (below), none in a player's run
- [ ] Frame rate in play: 33-40 fps in Kokiri Forest where the PC build is GPU-bound at 60 (shown at twice that with frame
      generation)
- [ ] A scene's first frames: 0.3-0.6 s, 3 s where its shaders are met for the first time
- [ ] Memory: Hyrule Castle Town ran out on arrival with textures of up to 1024 texels (two runs of three); the console's
      default is 512 (`RX_VK_TEX_MAX_DIM`), where the town plays with 180-500 MiB of 13.2 GB free and a few shaders still
      fail to translate for want of memory. The heap gives back what a burst of shader compiles took (PS5_PayloadSDK 55a2de0: 2.0 GB
      mapped after a start that compiles every pipeline, where it stayed at 3.4 with 0.7 in use). Images come from 32 MB
      blocks and the recordings' descriptor pools are an eighth of upstream's (`RX_VK_DESC_POOL_DIV=8`): the town's lowest
      free memory went from 558 to 911 MiB at the same frame rate. With less than 1 GB free every texture unused for a
      second goes, an image of 1 MB and up gets memory of its own, and a game page that finds no memory waits up to
      10 s for some to come back. A save that holds 8.3 GB of game pages in the town now leaves it for Hyrule Field,
      and ran out there a minute later with 9.2 GB of game pages (before the images' own memory). `HOS_PS5_ZERO_SCAN=1`
      counts the game's backed 64 KiB units that hold only zeros: ~800 MiB of 7.5 GB in the town, 430 MiB of them
      backed for the GPU's imports before the game wrote them. So game memory is imported by 4 MB chunks here, not
      16 (`RX_VK_IMPORT_CHUNK_MB`, and `RX_VK_IMPORT_SPAN_MB` 16, not 64): about 190 MiB more free at the end of a
      walk in the town on a PS5 Pro. The mesh shaders' scratch ring is 128 MiB, where
      it was 320 (PS5_Mesa 0f86253: an entry of 64 KiB, the game's shaders keeping 20 KiB at most). Still open: the
      same save, left once the town has wholly loaded, ran out at the loading screen with 9.2 GB of game pages (before
      the smaller ring); the heap's 850 MiB in use, and textures other than ASTC are not yet made smaller for it

Local `main` is upstream's `main` of 2026-11-10 (2877284, past v2.0.14's line) with PR #1438 (AMD resolve keys, image fallback past VMA's budget) and RufflezAU's
Steam Deck texture eviction by age in milliseconds (`RX_VK_EVICT_MIN_MS`, 1000; read once a present here, not at each touch).

## What a test run must not do

The console's file system holds every `open` in the title's folder for ~1.8 s when a large file there is replaced or deleted
(`HOS_PS5_TIMING=1` measures it). The renderer replaces its 54 MB pipeline cache every 300 presents while new pipelines come;
a run that reads `HOS_INPUT_LIVE` (an `fopen` 30 times a second) or writes `RX_VK_SHOTS` there stands still each time, and so
did every run made with `to-kokiri.sh` and `flash-run.sh`. `play-run.sh` has neither: timed presses (`HOS_INPUT_SCRIPT`) and
the log. Its slowest frame in steady play is 42-44 ms.

A run's switches are not in the player's `hookshot_env.txt`, which takes neither paths nor an input script: `ps5/tools/run.py`
writes them to `hookshot_test_env.txt` in the title folder, read in its place and without its limits (the console starts a title
with no environment to set `HOS_ENV_FILE` in), and removes the file when the run ends.

## Finding a fault against the PC

The same lift builds for the PC (`RX_CPM=.local/ps5-deps/cpm OOT_WORK=work/lift python -I nx2/build.py --standalone`), and
`ps5/tools/pc-run.sh` runs it with no window and no sound from a copy of the console's save (`ps5/tools/save.py backup`).
`RX_VK_MIRROR=0` there is the console's path (the game's memory read in place). The switches that found the foliage fault, on
both: `RX_VK_FLASH=1` (one-frame flashes counted), `RX_VK_PEEK=<gpu addresses>` (a word followed frame by frame),
`RX_VK_LOG_PROGS_AT=<from>:<to>` (every compute dispatch of those frames), `RX_VK_DRAW_STATS_ON=<program>` (the statistics
capture armed by a program's first dispatch) and `RX_VK_DRAW_STATS_ADDRS`. The capture counts task and mesh shader
invocations only where the driver offers them (`meshShaderQueries`): RADV does not on the console, and a query pool made with
those counts all the same hung the GPU at the first capture.

## Frame generation

With [PS5_MihawkGen](https://github.com/mihawk-99/PS5_MihawkGen) checked out beside this repository (`PS5_MIHAWKGEN` names
another place), `ps5/build.py` compiles its generator into the renderer and puts its network in the title folder
(`framegen/network.fgw`). Its network then makes the frames between the game's at 2x and 3x; above that, and with
`RX_VK_MIHAWKGEN=0` or without the checkout, the renderer's own interpolation does. FSR 3.1's frame generation is off on the
console (`RX_VK_FSR_FG=0`). PS5_MihawkGen is GPL-3.0-or-later, as this repository is.

The menu's Frame generation by row chooses who makes the frames on the console: the renderer's own interpolation
(Built-in FG) or PS5_MihawkGen's network (MihawkGen, the default). The network is loaded only where the row names it, so
the renderer's own leaves its memory to the game; a change of the row applies at once. The row and the FPS counter say
"MihawkGen FG" when the network made the frames, at the Frame generation row's Auto too.

Frame generation steps down with the console's free memory, whatever the row names. Under the textures' reserve
(`HOS_PS5_TEX_RESERVE_MB`, 1024 MiB) the renderer's own makes the frames, and under half of it none are made and
their images go back to the console (about 256 MiB at 3840x2160). It steps up one step at a time, from none at one and
a half times the reserve and to the row's generator at twice it, once the memory has stayed there for ten askings
(about ten seconds at 60 fps), so memory that comes and goes does not turn the frames on and off. Off in the menu
gives the images back too. The rows' lines say when memory has stepped it down.

### Lossless Scaling's frame generation

With the player's own `Lossless.dll` (from Lossless Scaling, which is not part of this repository and is not
distributed with it) the Frame generation by row also offers Lossless Scaling: its frame generation's compute
shaders are read from that file at run time and run on the console's GPU. The file goes in a `lossless` folder in
the title's folder (`/data/homebrew/PPSA99025/lossless/Lossless.dll`); ProsperoEden's own
(`/data/prosperoeden/user/lossless/`) is looked in after it, and `RX_VK_LSFG_DIR` names another place first. Without
the file the row does not show the value. It makes the frames of 2x to 4x and of Auto; above 4x the renderer's own
does.

The code is 26 files from [PS5SX2](https://github.com/Swordpdf/PS5SX2) (`ps5/coreorbis/orbis-shims/lsfg`,
GPL-3.0-or-later), which took them from the Eden emulator, which took them from
[lsfg-vk](https://github.com/PancakeTAS/lsfg-vk): 23 as they are in `third_party/lsfg`, and the three changed for Longshot
in `gpu/vk/lsfg`. Each folder's `PROVENANCE.md` has the revisions and what was changed. Not built on Windows or Linux:
`ps5/build.py` alone compiles them.

## Threaded rendering

On the console the Threaded rendering row's On is the recorder thread alone (`RX_VK_RECORDER=thread`): the replay's
commands go to the driver from a thread of their own, while the replay itself stays on the game's thread. The row never
starts the render thread there (`RX_VK_ASYNC=1` still does, for testing): the buffer pools have no mirrors on the
console, so a replay behind the game reads memory the game has moved on from, and with it a base PS5 hung. Auto is Off.
A change applies after a restart. `RX_VK_DESC_POOL_DIV` stays at the console's 8 and `RX_VK_RECORDER_OWN` stays off.

Measured on the PS5 Pro (Kokiri Forest after loading the save, 1080p, MihawkGen 2x, two runs each, alternated, the
recorder thread with `RX_VK_RECORDER_OWN=1` and `RX_VK_DESC_POOL_DIV=4`, as #40's report): the game at 34.7 to 35.1 fps
either way; the replay's time a frame 22.6 and 23.4 ms without, 19.7 and 20.2 with; about 0.7 of a core more and about
140 MiB less free memory (the most of that the descriptor pools' 4, not taken here); no faults or late frames. On a base
PS5, #40 reports 21 to 22 fps going to 25 to 28 with those settings at 1920x1080 and 120 Hz. Not yet measured: the
recorder thread alone with the console's defaults, and a base PS5 with this build.

## Open questions

- **The foliage fault's cause (answered 2026-11-16).** A program that follows a pointer no bound buffer holds reads it
  through the page table of guest memory, whose two windows were the PC's: 8 GB from 0x1000000000 and 4 GB from
  0x7f00000000 (spirv_emit_context.cpp `kGuestPages*`, gpu/vk/page_table_census.h `kPageWindows`). The console's guest
  window is 64 GiB, with its heap from 0x400000000 (host/hos.h): no address of the game's was in either window, no page
  was mapped and every followed pointer read 0, which left the culling pass's lists empty. Under `__PROSPERO__` the windows
  are now 8 GB from 0x400000000 and 4 GB from 0xf00000000 (tests/test_ps5_page_windows.py). Binding from multiples of 256
  (gpu/vk/vk_main.cpp) had taken the fault away in Kokiri Forest only: in the Sacred Meadow, with the camera on the crowns,
  `RX_VK_FLASH` counted 400 flashes in 400 presents before the windows changed and 0 in about 2,000 after. Not retested:
  the console's windows with the binding from multiples of 256 taken out.

## Driver and SDK gaps (PS5_Vulkan, PS5_PayloadSDK)

- **`setvbuf` with a large buffer.** After `setvbuf(stream, NULL, _IOFBF, 9 MiB)` every thread started later had no
  thread-local data, and the game crashed 7 s into each start. The renderer asks for no stream buffer of its own on the
  console (gpu/vk/vk_shader.cpp).
- `pthread_getaffinity_np` / `pthread_setaffinity_np` do nothing; `scePthreadGetaffinity` / `scePthreadSetaffinity` are used.

## Known gaps

- Motion controls: the game sees a pad lying still (scePad's sensors are not read yet).
- Microphone (humming the ocarina): none.
- `RX_VK_FORCE_MESH_FALLBACK=1` (upstream's compute mesh path) ran out of memory in Link's house.
- Preparing every shader before play (`hookshot_shaders.bin` beside `eboot.bin`, from `nx2/shader_census.py` on the PC) works and
  shows its progress, but its 4,128 compute programs alone go at ~1.3 a second.
