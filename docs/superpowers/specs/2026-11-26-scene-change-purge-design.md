# Memory at a zone change (PS5): design

Status: approved for planning (2026-11-26) · Branch: `feature/zone-memory` (from `feature/amiibo`)

## The request

When the game loads another region, free what the previous region left in memory, using the assets' dependencies
(`Data.deps`) to tell what the new region does not use, and with the **zone** in those dependencies.

## What is known (2026-11-26)

- **Not inside the game.** There is no source, only the translated binary. The game's engine unloads its own region data
  and compacts its 2,400 MB texture heap (`host/oot_tex_compact.h`). Freeing guest allocations from outside would leave
  the game pointing at freed memory. What piles up is **Longshot's own**, outside the game:
  - GPU copies of the game's textures (`gpu/vk/vk_texture.cpp`), keyed by the game's storage address, let go by age
    (`RX_VK_EVICT_MIN_UNUSED`) or memory pressure only;
  - imports and their mirrors (`gpu/vk/mirror_trim.h`), trimmed only after "a while";
  - the asset prefetch bucket (`host/ps5/asset_prefetch.c`, off by default: `HOS_PREFETCH=0`).
- **The person's reports** (C:\Users\Renan\Desktop\Longshot\Atual, analysis in `memory-analysis.md` there):
  - two MEMORY_FLOOR_EXITs at 191 and 186 MiB: the **default** 220 MiB floor, not the base profile's 400, so the title
    folder most likely had no `longshot_env.txt` (no copy of it in any report);
  - one drop of 1.27 GB within 15 frames during a GPU freeze;
  - `zone_boost=1` at an exit does not mark a zone change (`zone_boost_update_mem` holds it under floor + 2200 MiB).
- **Two diagnostics are broken on the PS5:**
  - `bug-reports/*/log.txt` is empty: the ring (`host/ps5/ps5_bug_report.c` `hos_ps5_log_keep`) is fed only inside
    `host/hos_thread.c`'s `_WIN32` block (`:144-305`); on the PS5 `hos_vlog` writes to stderr (klog) only.
  - "Scene: not known yet": the `Sequence_CurrentBanc` poll (`host/hos_main.c:757`, `asset_prefetch_scene`) sits in the
    `_WIN32 || __linux__` debug-tools block (`:645-1547`); the PS5 never runs it. So the scene change is **not** seen on
    the PS5 today.
- **Memory margin = Performance does nothing on a base PS5** (`ps5_memory_delta` is Pro-only); Safe is the value that
  helps there.

## Zones in the dependencies

`ps5/builder/asset_deps.py` makes `Data.deps`: per scene, the romfs files it reads (parameters, maps, placed actors'
packs, their models `Model/*.bfres.zs`, ...) and the scenes it leads to. A scene's own maps are `Banc/<folder>/<scene>_*`:
**the folder is the zone**. In the person's game, 80 scenes fall in 33 folders (`HyruleField` holds `_Adult` and
`_Child`, `Market`, `KakarikoVillage` three, each temple one), with one exception: one folder holds the boss and fight
stages of many places (about 3 GB together), which is not a zone.

- **Rule:** a scene's zone is its maps' folder. **Except** a folder whose scenes lead to more than 4 different zones
  (counted over all its scenes' neighbours): then each of its scenes is a zone of its own. No place names in the code.
- **`Data.deps` version 2** adds a zone table: name, its scenes, its file list (the union of its scenes' lists, in first-
  wanted order), its neighbour zones (the zones of its scenes' neighbours), and each scene's zone index. Readers take
  version 1 too (no zones: each scene its own zone).

## The design (in phases; each phase is useful alone)

### Phase 1 — diagnostics that work on the PS5 (low risk)

1. **The log reaches the bug report:** `hos_vlog` calls `hos_ps5_log_keep(line, len)` on the PS5; the keep ring takes
   writers from many threads (its span reserved with an atomic add, or a mutex); the dead block in `hos_thread.c` goes.
2. **A floor exit says why first:** the memory breakdown line is printed before the report is written; the PS5's
   `[ps5] memory floor ...` lines go through `hos_log` (so into the ring).
3. **The scene is known on the PS5:** the `Sequence_CurrentBanc` read (and the helpers it needs) runs on the PS5 every
   500 ms and calls `asset_prefetch_scene(map)` (logging `map: <name>` once per change); `asset_prefetch_scene_now()`
   falls back to the scene whose parameters were last opened while none is known yet.
4. **A missing profile is said, and covered:** at start, the PS5 logs whether `longshot_env.txt` was read; the bug
   report names the floor in use and whether the file was read; without the file on a base PS5, the profile's safe
   values apply (floor 400 MiB, textures 512) and a notice says to copy the title folder again.
5. **One PS5 log-file helper:** `logs/nfp.txt`'s writer (`host/nn_nfp.c`) becomes `hos_ps5_logfile(name, line)`,
   used by nfp, mods (the mods plan's Task 1 then reuses it) and memory.

### Phase 2 — measure (`logs/memory.txt`)

From the memory-floor watch thread (`host/ps5/win32_ps5.c` `memory_floor_watch`, already sampling): one line at each
**zone** change, 5 s after it, every 60 s, and just before a floor exit. A line: time, scene, zone, free direct memory
and its largest piece, the game's committed pages, the renderer's VMA block and allocation bytes, textures (count,
bytes), mirrors' bytes over the live pools, the prefetch's held bytes, zone_boost, output and render size. The
renderer's numbers through one weak function, as `rx_vk_inflight` is reached today.

### Phase 3 — zones in `Data.deps` and in the game

- The builder writes version 2 (above); `asset_prefetch.c` reads both versions, knows the current zone from the scene,
  and has a **zone change** event: the zone changed and its scene settled.
- The prefetch's let-go (when the bucket is on) works by zone: what neither the new zone nor its neighbours want.

### Phase 4 — which files a texture came from (logging only)

- The host already sees: a romfs file read into a guest range (`host/nn_fs.c`), its `.zs` decompressed by the host
  (`host/hos_zstd.c`, source and destination ranges), and each texture the game registers, by its storage address.
- A texture whose storage lies inside the decompressed range of a file gets that file as its tag; the game's texture
  heap compaction moves textures (`host/oot_tex_compact.h`): the tag follows the texture through the remake (by the
  hash the renderer already uses to find the image it had).
- At each zone change, logged to `logs/memory.txt`: textures tagged / untagged (count, MB), and of the tagged, those
  whose file neither the new zone nor its neighbours want (count, MB). **Nothing is freed in this phase.**

### Phase 5 — the purge (designed after a measured session)

From phase 2-4's numbers: free the tagged textures the new zone does not want and that were not used since the load
began, trim the mirrors left over at once, give empty VMA blocks back. Its own design, with the numbers in hand.

## Constraints

- No game file, name list or game-derived data in the repository: zone names come from the person's game at build
  time; tests use made-up scenes.
- Every phase that touches `host/` or `gpu/` runs in the game (the person's PS5) before its PR.
- The checks run in Docker; the person asked for the full suite only at the end of the last task.

## Calls made (for the person to review)

- The zone rule's threshold (a folder leading to more than 4 zones is not a zone) is a starting value, to check against
  the person's 33 folders in the builder's report.
- Phase 1.4's safe values are the base profile's measured ones (`ps5/builder/pipeline.py:38-56`).
- Phase 4 tags by the **decompressed** range: a texture copied elsewhere by the game stays untagged, which phase 4's
  numbers will show.
