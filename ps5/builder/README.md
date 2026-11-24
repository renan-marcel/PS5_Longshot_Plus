# PS5 Longshot Plus Builder

A desktop tool: a player chooses their own game file and gets the PS5 title folder (`PPSA99198`) to copy to
`/data/homebrew` on the console. Nothing has to be installed: the package carries its own Python, compiler and kit.

| File | What it is |
|---|---|
| `build_kit.sh` | The kit from a fresh clone on Linux, with no game: fetches and builds RADV, FFmpeg, the SDK and the rest at pinned revisions, compiles the runtime and the renderer (`ps5/build.py --kit`), runs `make_kit.py`. |
| `make_kit.py` | Lays the kit out in `dist/kit`: everything of the title that is not made from the game, compiled already. No game content. |
| `pipeline.py` | The build: the game's program read out of the `.nup`, translated to C, compiled, linked with the kit, signed, laid out. Python only, the same on every system. `--game --out --model base|pro [--memory GB] [--jobs N]`; `--check` checks the builder's own parts with no game. |
| `game_data.py`, `data_packs.py` | Step 7, the game's data: packs with per-group indexes and the `Data.idx` manifest (the default), or loose files with `--data-folder` (`docs/ps5-data-packs.md`). |
| `known_gpu_hangs.txt` | The shaders known to hang the PS5's GPU, a program key a line: written into the title folder's `longshot_env.txt` as `RX_VK_GPU_SKIP=<key>,...`, so the game leaves them out (what they draw there is missing). `--no-known-skips`, or the window's *Skip shaders known to hang the GPU* turned off, leaves the line out. A shader the Debug tab's *GPU freeze shader* names (`logs/crash_trace.txt`) is added here as a line, with where it froze. |
| `app.py` | The window (PyQt6): game file, output folder, the console's model, Build, the five steps, a progress bar, the log, Stop, and Send to PS5 over FTP. Runs `pipeline.py` as a process. `--self-test` opens it and runs the check. |
| `package.py` | The packages, both made on Linux: `--system linux-x64` an AppImage, `--system windows-x64` a portable folder in a zip (cross-built). python-build-standalone, llvm-mingw's LLVM (its clang has the PS5 target), `ps5-native-tool` and the lifter's helper library for the system, the kit. Every download is checked by SHA-256. |
| `launcher.c` | Windows: `PS5LongshotPlusBuilder.exe`, the portable folder's start. No installer. |

```
bash ps5/builder/build_kit.sh                                  # the kit (30 to 60 minutes the first time)
python3 -I ps5/builder/package.py --system linux-x64           # dist/builder/PS5LongshotPlusBuilder-<version>-x86_64.AppImage
python3 -I ps5/builder/package.py --system windows-x64         # dist/builder/PS5LongshotPlusBuilder-<version>-windows-x64.zip
```

## Releases

`.github/workflows/builder-release.yml` runs when a release is **published** on GitHub: it builds the kit
(ubuntu-24.04), makes both packages (ubuntu-22.04), starts each on its own system (`--check` and the window's
`--self-test` on ubuntu-22.04 and windows-latest), and only then attaches the four files to the release:

    PS5LongshotPlusBuilder-<tag>-x86_64.AppImage        (+ .sha256)
    PS5LongshotPlusBuilder-<tag>-windows-x64.zip        (+ .sha256)

To cut one: `gh release create ps5-v0.1.0 --title "..." --notes "..."` (or the Releases page). The tag names the
files. "Run workflow" on the Actions page does everything but the upload and keeps the packages as the run's
artifacts: a rehearsal. No game file is used anywhere in it.

The Windows package is a folder: unpack the zip anywhere and start `PS5LongshotPlusBuilder.exe`. It is not one file: the
compiler, Python and the kit are 880 MB unpacked, and a single self-unpacking program would unpack them at every start.

## Memory

**Memory to use** in the window (`--memory GB`; Automatic: what is free, read again as the build goes) is what the build keeps
to. Lower is slower, never different: the title folder made within 3 GB played the forest test on a Pro like the one built
with all the memory (26.4 and 26.7 against 26.5 fps, the same free memory, no fault).

Measured on Zelda's real game (`.nup`), the PSS of the builder and every process it starts, on a 16-thread Linux PC:

| | v0.1.4 (Automatic) | now, Automatic | now, within 3 GB | now, within 2 GB |
|---|---|---|---|---|
| Translating it to C | 11.7 GB (7 workers; 5.05 GB with one) | 6.4 GB (9 workers, as the free memory allowed), 4 min | 1.83 GB, 9.5 min (one process) | 1.82 GB (one process) |
| Compiling for the console | 16.5 GB, then a compiler killed for want of memory | 16.7 GB of the ~19 GB free, 16 min, none killed | 2.43 GB, 69 min (2 at once, parts of ~1.3 GB) | 1.94 GB, 121 min (1 at once, parts of ~0.9 GB) |
| Linking, making the title folder (~1 minute) | 2.1-2.3 GB, then 3.0 GB for ~30 s | the same | the same | the same |
| Listing the game's shaders | 1.1-1.3 GB | the same | the same | the same |
| The whole build | stopped in the compile | 21 min | 81 min | 132 min |

What changed:

- **The translation** (`nx2/compact_bodies.py`): a64-kit's lifter held every function as a dict of its instructions, a dict
  entry, a tuple and two ints for each of Zelda's 24 million: 3.4 GB of the 4.1 GB it held after finding the functions.
  They are runs of addresses now, each instruction read from the image again when asked for; the lifted C and the image
  are the same, byte for byte. Each further translation process is a forked copy that comes to own ~0.5-0.7 GB (Python's
  reference counts write to the pages it shares), so within a budget under 5 GB it runs in one.
- **The compile** (`pipeline.py` `compile_game`): one lifted file, `code_028.c`, is a single 10 MB function that took
  4.3 GB and 408 s to compile; the giants are compiled cut into pieces (`nx2/split_giants.py`, as the PC build does:
  721 MB, 145 s). A chunk (24 MB of C, ~1.6 GB) whose need is past what one compile may take is compiled as parts cut at
  its functions' heads. A compile starts only when its need fits (`Gate`): within `--memory` with those running, else in
  the memory free less 1.5 GB. One always runs.
- **Not changed yet:** `ps5-native-tool` (PS5_Vulkan's `tooling/native`) holds the whole executable several times over:
  `link` 2.8 GB, `self --sign` 3.1 GB, `--inspect` 2.1 GB for the 604 MB ELF, ~30 s in all. On a PC with 2 GB free that
  much is paged for those seconds, as is the link's 2.3 GB (ld.lld). Making the native tool stream the file (sign keeps
  the input, a copy of it, the output and a copy rebuilt from the output to hash) is the next step.

## The console's profile

The folder is built for one model (`pipeline.py` `MODELS`), chosen in the window or with `--model`:

| | `attribute3` in `param.json` | `longshot_env.txt` |
|---|---|---|
| PS5 Pro (`pro`) | `0x8540040`: High CPU Frequency, 13,232 MiB | nothing: the title's own defaults (textures of at most 1024 texels) |
| PS5 / PS5 Slim (`base`) | `0x140040`: a base-generation process, 12,016 MiB | `RX_VK_TEX_MAX_DIM=512` |

The base profile runs on a base PS5. Its memory was measured on a Pro, which runs the title in the base console's mode
with that value (ps5/README.md). The base folder, sent to the Pro, started as a base-generation process (12,016 MiB) and played the
forest test for its 230 s with 2.0 GB free at the least and no fault. A start as a player has it (no test switches)
shows the title reading the folder's `longshot_env.txt`; the 512-texel line's effect in play was not measured in that
start (a test run's own switches file takes the place of `longshot_env.txt`, and a player's file may not script input).

## State (2026-11-16)

- **The kit from a fresh clone** (`build_kit.sh`, no game) has the same runtime objects as a whole build's, but for the
  version stamp. An AppImage made from it built a title from the game's `exefs`; that title has not run on the console
  yet (the earlier packages' titles did: Kokiri Forest at 32 to 34 fps, Pro and base profile).
- **Linux**: the AppImage (278 MB) passes `--check` and `--self-test` here, runs a whole build from the read-only image
  with nothing installed, and its lifter needs no compiler.
- **Windows**: the zip (279 MB) is cross-built here. Under Wine its Python, compiler, linker, signing tool and helper
  library run, one game file compiles to the same object as on Linux, and a link and signing from the same objects gives
  the same `eboot.bin` byte for byte. Wine cannot load numpy or Qt (its own gaps), so the lifter and the window have
  **not** run on Windows: the workflow's `check-windows` job is their first real run.
- **The workflow ran on GitHub** on 2026-11-16: a rehearsal, then the release **v0.1.0**, every job passing, the Windows
  check on windows-latest among them (the lifter's parts and the window started there for the first time). The
  published AppImage, downloaded again, matches its checksum and passes `--check`. The released kit was compiled on the
  runner (clang 18): a title built with it has not run on a console, and a whole build has not run on a Windows PC.
- **Reading a `.nup`**: v0.1.0 could not. The game's main program is ZBIC-compressed in a real dump, and the library
  that unpacks it (`third_party/zbic`) was built on first use, by a compiler a player does not have: the build stopped
  at its first step, on Windows and on Linux. Every test until then had given the folder of program files unpacked
  earlier. Since v0.1.1 the library comes ready in each package and `--check` asks for it; the real game file's program,
  read from the console's copy by the packaged Linux and Windows builders (the Windows one under Wine), comes out the
  same as the files every build was made from.
- **v0.1.1 and v0.1.2 on Linux could not unpack the game's program**: "ZBIC: decompression failed (-2 of 63201744
  bytes)". Their `zbic.so` was compiled by the release runner's GCC 11, and that build wrote ZBIC frames and read none
  (the same sources by GCC 14 or clang read them; the Windows library, compiled by the pinned LLVM, was right). The fix
  for v0.1.0 had been tried with a library made on this PC, not with the published AppImage. Since v0.1.3 both systems'
  library is compiled by the pinned LLVM and has a self-test (`zbic_check.c`) that `--check` runs, so the release's own
  check jobs fail on a library that does not read what it writes. The other helper, `liba64emit.so`, was compared on
  400,000 of the game's instructions: the runner's GCC 11 build and this PC's give the same C.
- **macOS**: not packaged.
