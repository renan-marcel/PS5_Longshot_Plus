# Longshot on the PS5

Private working repository for porting [Longshot](https://git.magicbean.dev/MagicBeanDev/Longshot) (static
recompilation of The Legend of Zelda: Ocarina of Time for Switch 2, the continuation of Hookshot) to the PS5.

Status (2026-11-16): PS5_Hookshot's port is merged onto Longshot, the title builds, and it plays on the console.
A new game runs from the title screen through the opening to Link's house (10 minutes, autosave made); a later start
loads that autosave, walks out of the house and around Kokiri Forest. Frame rates the log gives: 59.9 at the title and
in movies, about 40 in the opening's scenes, 50 in Link's house, 35 in the forest (measured with a screenshot taken
every 120 presents). No crash or GPU fault in five runs. Not tried: beyond the forest, sound by ear, a real controller.
Players build it with the desktop builder, `ps5/builder` (an AppImage and a portable Windows folder). Its option Download amiibo fetches the amiibo pictures on the player's PC into the title folder; they are not shared.

Frame generation is on from the start, at 2x, the Frame generation row's default on the console: the menu changes it and
`longshot_options.ini` keeps it. On the console the row names its values for what they do to the game: "2x (game at
30 fps)" holds the game at half the display's rate, and "Fill to 60 fps" (the row's Auto) leaves the game at its own
rate and makes frames only for the refreshes it misses. At 2x PS5_MihawkGen's network makes one frame between each two
of the game's, so the
forest's 31.5 game frames are 63 shown a second, evenly, on the 60 Hz mode. `HOS_PS5_HZ=120` takes the 119.88 Hz mode:
with `RX_VK_FRAMEGEN_MULT=3` 90 are shown (the network's), with `4` 120 (the renderer's own interpolation: the network
did not start at 4x), the game held at 30 in both. Measured, not judged by eye.

Base PS5: it runs on one (players' consoles, with the builder's base profile; no run of it was logged here). What was
measured is its memory: on the Pro in the base console's mode (`attribute3` 0x140040 in `param.json`: kernel
"proc gen:2", 12,016 MiB of direct memory against the Pro mode's 13,232) the title loads the autosave and plays Kokiri
Forest for the test's 230 s with no fault and no "memory short" line: 9.7 GB taken, 1.9 GB free at the least against
3.2 GB. The processor and GPU are still the Pro's there, so the base console's frame rate was not measured here: in play
on a base console, with frame generation on, about 20 frames a second fewer are shown than on a Pro.

Resolution: the console starts at the docked profile with the full picture (the Balanced preset), 1920x1080. The
Output resolution chosen in the menu (`output_res=` in `longshot_options.ini`) picks the display mode at the next start
when it is 1920x1080, 2560x1440 or 3840x2160; `HOS_PS5_DISPLAY` overrides it. In Kokiri Forest, where the processor is
the limit: 35 fps at PS5_Hookshot's handheld profile at half the picture, 31 to 32 at 1920x1080, 29 at 2560x1440, about
3 GB of memory free in each. Textures are at most 1024 texels (135 MB more than at PS5_Hookshot's 512 in the forest; 2048
takes 540 MB more and the renderer past its own 2560 MB). Hyrule Castle Town, which ran out of memory at 1024 before the
port kept a reserve for the game, has not been played at it: `RX_VK_TEX_MAX_DIM=512` is the old limit. At 3840x2160 a Pro plays the forest at about 40 frames a second shown with
frame generation on (the owner's play, 2026-11-16; not measured from the log).

The title is **PPSA99198, Longshot**, so PS5_Hookshot's PPSA99024 on a console is left alone.

## Branches

| Branch | What it is |
|---|---|
| `main` | The port. Starts at Longshot `ceccd963` (2026-11-15) plus this folder. |
| `upstream-main` | Longshot's `main`, untouched. Update it with `git fetch upstream && git push origin upstream/main:upstream-main`, then merge into `main`. |
| `ref/ps5-hookshot` | mihawk-99's PS5_Hookshot at `ps5-v0.1.0-beta.2` (`275b9873`): Hookshot as a native PS5 title. Reference only. Its GitHub repository is gone (404 on 2026-11-15), so this branch is a copy to keep. |

Remotes on the working clone: `origin` (this repository), `upstream` (Longshot on magicbean.dev).

## Vulkan driver

[PS5_Vulkan](https://github.com/mihawk-99/PS5_Vulkan) is a submodule at `ps5/deps/PS5_Vulkan`, pinned at
`7f492b4c` (its `main` on 2026-11-15, and the revision PS5_Hookshot beta.2 built against).

```
git submodule update --init ps5/deps/PS5_Vulkan
```

PS5_Vulkan builds RADV from PS5_Mesa and needs the payload SDK. PS5_Hookshot beta.2 pinned these beside it:

| Project | Revision |
|---|---|
| PS5_Mesa ([renan-marcel/PS5_Mesa](https://github.com/renan-marcel/PS5_Mesa)) | `0f86253f674c425052948eb3cb116c81e646a734` |
| PS5_PayloadSDK ([renan-marcel/PS5_PayloadSDK](https://github.com/renan-marcel/PS5_PayloadSDK)) | `88d6e41ec7ee7e76d871ff14cd78b5cc4c8e5989` |
| PS5_MihawkGen (frame generation) | `c57232a9f16bcb6df5fe07c9bb631518f2b1cc0e` |

Headers `gpu/vk` was compiled with there: Vulkan-Headers `v1.4.345`, SPIRV-Headers `vulkan-sdk-1.4.341.0`,
VMA `v3.3.0`.

## What the merge decided

`git merge ref/ps5-hookshot` stopped on 13 files. What was not a plain "both sides":

- `gpu/vk/vk_progcache.cpp`: Longshot moved the program cache out of `vk_shader.cpp`. The port's held writes during the
  preparation (`kDiskHold`: a write into the title folder costs ~60 ms) are here now, and every reader flushes first.
- `gpu/vk/vk_texture.cpp`: the port aged textures in milliseconds; Longshot's compaction reads the age in presents. The
  age stays in presents, 30 on the console (about the port's one second) and 60 elsewhere.
- `gpu/vk/vk_draw.cpp`: Longshot's pipeline cache save is kept; the port's lines timing the save are left out.
- `gpu/vk/vk_framegen.cpp`: PS5_MihawkGen's frames come first, before FSR 3.1's.
- `host/posix/win32_posix.c`: a new thread takes the process's affinity through `scePthreadSetaffinity`.
- `host/ps5/win32_ps5.h`: a small `std::atomic_ref`, which the SDK's C++ library lacks and Longshot's back end uses.
- `host/ps5/hos_sdl_ps5.c`: stand-ins for the calls `hos_sdl.h` gained (text input, clipboard, Steam pads).
- The game is looked for in `/data/longshotplus/roms` first (with `/data/longshot/roms`, `/data/eglantineps5/roms`, and `/data/lichii/roms/oot` as automatic fallbacks), under the name the dump has.

## Building

For players there is the builder (`ps5/builder/README.md`). A developer's whole build, with the dependencies
`ps5/builder/build_kit.sh` fetches and builds into `.local/`:

```
export PS5_VULKAN=<a built PS5_Vulkan at 7f492b4c> PS5_MIHAWKGEN=<PS5_MihawkGen>
LONGSHOT_LIFT_JOBS=1 OOT_WORK=$PWD/work/lift python -I nx2/lift.py --standalone --write --exefs <exefs> --work $PWD/work/lift
python -I ps5/build.py --jobs N
```

The lift holds about 6 GB and more as it writes (it was stopped for want of memory with less than ~10 GB free); each
compile of a lifted chunk about 1.4 GB. The compile took 40 minutes at 6 jobs.

Install and run (the control payload `ps5vkctl` on the console, port 9111):

```
PS5_HOST=<console address> python3 $PS5_VULKAN/tools/deploy-title-folder.py dist/PPSA99198
PS5_HOST=<console address> python3 ps5/tools/run.py NAME --seconds 150      # klog in work/runs/NAME.klog
```

`ps5/tools/to-kokiri.sh NAME` starts a new game and presses A through the opening. To steer a run by hand, start it with
`--env HOS_INPUT_LIVE=/app0/input.txt --env RX_VK_SHOTS=/app0/shots --env RX_VK_SHOT_EVERY=120`, then
`ps5/tools/live.py press '0:A,5:LDOWN/2500'` and `ps5/tools/live.py shot`. From the autosave in Link's house,
`LDOWN/2500` walks out into the forest.

The capture tools see only the console's shell, not the title: for screenshots of the Insert menu add
`--env RX_VK_SHOT_MENU=1` (the menu drawn into each shot) and steer it with `--env 'RX_VK_MENU_SCRIPT=45:INS,48:TABR,...'`
(keys in docs/development.md). `--env HOS_PS5_LANG_ID=<number>` stands in for the console's language (the
SCE_SYSTEM_PARAM_LANG numbers: 1 English (US), 17 Portuguese (Brazil), 12 Finnish, which the game does not have).

## Test console

| What | Where |
|---|---|
| Address | `PS5_HOST` (its address on your network) |
| FTP | port `2121` |
| ps5debug-NG | port `744` |
| klogsrv (kernel log) | port `3232` |
| ELF loader | port `9021` |
| Game | `/data/homebrew/PPSA99198/Data/`: The Legend of Zelda: Ocarina of Time's romfs, extracted from its `.nup` (program `0400486024DEC000`, update v131072) by the builder |

On 2026-11-15 only the ELF loader answered: FTP, ps5debug-NG and klogsrv have to be loaded before a test run.

Notes from the PS5_Hookshot build on this console:

- Its title installed as `/data/homebrew/PPSA99024`.
- `link()` and `symlink()` fail on `/data` (errno 45): a title that wants the game elsewhere needs a real copy (25 GB)
  or to read it in place.
- The FTP server decrypts SELF files on read by default: send `SELF` to switch that off before comparing hashes.

## Rules

- No game files, keys or built titles in this repository: everything a build makes comes from the game copy.
- Longshot is GPL-3.0 (see `LICENSE`); the port keeps that licence.
