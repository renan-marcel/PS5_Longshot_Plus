# Memory at a zone change (phases 1-4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On the PS5, bug reports carry the log and the scene, a missing profile is covered, `logs/memory.txt` measures memory at each zone change, `Data.deps` knows the zones, and each GPU texture is tagged with the file it came from (logged, nothing freed yet).

**Architecture:** Host-side only (host/, host/ps5/, gpu/vk counters, ps5/builder/asset_deps.py). One PS5 log-file helper; the scene poll enabled on the PS5; zones derived at build time from the maps' folders; a game-free interval map links file reads and zstd outputs to texture storage.

**Tech Stack:** C11 (host), C++20 (gpu/vk), Python 3 (builder).

**Spec:** `docs/superpowers/specs/2026-11-26-scene-change-purge-design.md`

## Global Constraints

- Branch `feature/zone-memory` (from `feature/amiibo`).
- No game file, scene/zone name list or game-derived data in the repository; tests use made-up scenes and files.
- Zone rule: a scene's zone is its own maps' folder (`Banc/<folder>/<scene>_*`); a folder of **more than 4** scenes is not a zone (each of its scenes is its own). No place names in code.
- `Data.deps` version 2 adds zones; every reader accepts version 1 (each scene its own zone).
- PS5 log files: `<title folder>/logs/<name>` through one helper, 1 MB cap, started afresh when already past it.
- Safe values without `longshot_env.txt` on a base PS5: `HOS_PS5_MEM_FLOOR_MB=400`, `RX_VK_TEX_MAX_DIM=512`, `RX_VK_TEX_SKIP_MB=2`, `HOS_PS5_TEX_RESERVE_MB=1800` (the base profile's, `ps5/builder/pipeline.py`); a PS5 Pro (`HOS_PS5_RENDER_MB` ≥ 3200 is how the code tells it; without the file it cannot) is treated as base.
- Nothing is freed by this plan (phase 5 is its own design).
- Checks in Docker (`longshot-tests`), focused per task; the full suite once, at the end of the last task (the person's rule).

## Review Focus

1. **Several game threads logging at once** while the watchdog writes a bug report: no torn ring, no deadlock in the signal path. Task 2.
2. **A scene name the game has not set yet** (empty string, garbage before boot): no scene change logged, no crash in the poll. Task 4.
3. **A `Data.deps` of version 1 or from other packs** with the version-2 reader: zones fall back to scenes; a SHA mismatch is refused as today. Task 5.
4. **The game reads a file into a buffer it reuses** for another file before the first is decompressed: the newer read wins the range; no stale tag. Task 7.
5. **Texture heap compaction moves a tagged texture**: the remade texture keeps the tag. Task 7.

---

### Task 1: One PS5 log-file helper

**Files:** Create `host/ps5/ps5_logfile.c`, `host/ps5/ps5_logfile.h`; Modify `host/nn_nfp.c`; Test `tests/test_ps5_logfile.py`.

**Interfaces:** Produces `void hos_ps5_logfile(const char *name, const char *line);` (append line + `\n` to `<title>/logs/<name>`, one mutex, fflush per line, 1 MB cap per name with one closing line, a file past the cap at first open started afresh; a no-op off the PS5; the title folder from `hos_ps5_trace_path()` as nn_nfp.c does today).

- [ ] **Step 1:** Failing test: the helper compiled with a test switch pointing at a temp folder: two names → two files, order kept, 1 KB test cap → closing line then nothing, a file past the cap at open started afresh; `tests/nfp_hle_test.c`'s file checks pass through the helper.
- [ ] **Step 2–4:** FAIL; move nn_nfp.c's writer into the helper (nn_nfp calls `hos_ps5_logfile("nfp.txt", ...)`); PASS (`tests/test_ps5_logfile.py`, `tests/test_nfp_hle_names.py`).
- [ ] **Step 5:** Commit `refactor(ps5): one helper for the logs/ files (nfp.txt first)`.

### Task 2: The log reaches the bug report

**Files:** Modify `host/hos_thread.c` (`hos_vlog`; remove the dead `__PROSPERO__` block at ~169-174), `host/ps5/ps5_bug_report.c` (`hos_ps5_log_keep` for many writers); Test `tests/test_ps5_bug_report.py` (extend).

**Interfaces:** `void hos_ps5_log_keep(const char *s, size_t n);` unchanged signature, now safe from many threads (span reserved with `__atomic_fetch_add` on `keep_total`, copy into the reserved span; the reader in the signal path takes no lock).

- [ ] **Step 1:** Failing test: by source cut (`tests/srccut.py`), `hos_vlog` calls `hos_ps5_log_keep` under `__PROSPERO__` **outside** the `_WIN32` block; compiled test of `ps5_bug_report.c`'s ring with 8 threads × 10,000 lines of known text: the written log.txt holds only whole known lines (at most one torn at the wrap) and its size is ≤ 64 KB.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `fix(ps5): the bug report's log.txt holds the log (it was fed on Windows only)`.

### Task 3: A floor exit says why; a missing profile is said and covered

**Files:** Modify `host/ps5/win32_ps5.c` (`memory_floor_watch`: breakdown line before the report; its `fprintf(stderr, "[ps5] ...")` memory lines through `hos_log`), `host/hos_main.c` (`load_longshot_env` returns whether the file was read; on the PS5 without it: the safe values of Global Constraints set with `setenv(..., 0)`, and a `hos_log` notice "longshot_env.txt not found: the PS5 profile's safe values are used; copy the whole title folder again"), `host/ps5/ps5_bug_report.c` (report.txt gains "Memory floor: N MiB" and "longshot_env.txt: read | not found"); Test `tests/test_ps5_bug_report.py`, `tests/test_ps5_env_missing.py`.

**Interfaces:** Produces `int hos_longshot_env_read(void);` (1 when the file was read) and `uint64_t hos_ps5_floor_mb(void);` for the report.

- [ ] **Step 1:** Failing tests: report.txt text has both new lines (compiled report writer with stand-ins); `load_longshot_env` cut and run against a temp folder without the file sets exactly the four safe values and does not override one already in the environment; with the file, nothing is added; source cut: the breakdown `hos_log` precedes `ps5_bug_report_write` in the floor-exit branch.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `fix(ps5): a floor exit logs its breakdown first; without longshot_env.txt the base profile's safe values apply`.

### Task 4: The scene is known on the PS5

**Files:** Modify `host/hos_main.c` (move `oot_singleton`, `oot_gamedata_string` and the `Sequence_CurrentBanc` read out of the `_WIN32 || __linux__` debug-tools block; on the PS5, in `hos_oot_lift_player`'s `#else`, every 500 ms: read the map, and on a change call `asset_prefetch_scene(map)` and `hos_log("map: %s", map)`), `host/ps5/asset_prefetch.c` (`asset_prefetch_scene_now()` returns the last opened scene parameters' name while no scene is known); Test `tests/test_ps5_scene.py`.

**Interfaces:** `const char *asset_prefetch_scene_now(void);` unchanged; produces `const char *asset_prefetch_zone_now(void);` stub returning the scene (Task 5 makes it the zone).

- [ ] **Step 1:** Failing tests: source cuts show the helpers compiled for `__PROSPERO__`; the poll compiled against stand-ins (a fake game-data string that changes, empty, then "SceneA", "SceneA", "SceneB") calls `asset_prefetch_scene` exactly twice and logs twice; the fallback returns the parameters' scene before any `asset_prefetch_scene` call.
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `fix(ps5): the scene is read on the PS5 (bug reports, prefetch, map: lines)`.
- [ ] **Step 6 (the person, PS5):** after Tasks 1-4, a short session: a bug report made from the Gameplay tab's Bug report has a log.txt and a scene; `logs/` exists. (Batched with Task 8's run if preferred.)

### Task 5: Zones in `Data.deps` (builder and game)

**Files:** Modify `ps5/builder/asset_deps.py` (zones, `VERSION = 2`, encode/decode, `--report` lists zones), `host/ps5/asset_prefetch.c` (read v1 and v2; current zone; a zone-change event when the zone changes and its scene settles; let-go by zone), `host/ps5/asset_prefetch.h`; Test `tests/test_asset_prefetch.py` (extend), `tests/asset_prefetch_test.c` (extend).

**Interfaces:**
- Builder: `zones(rows: dict) -> tuple[list[str], dict[str, int]]` (zone names; scene → zone index) by the rule; `encode(rows, bid, zones)` writes v2: header `version 2`, a zone table after the neighbours (`u64 zones offset, u64 zone count` in the header's spare words, each zone `u32 name off, u32 name len, u32 first scene entry, u32 scene count, u32 first file entry, u32 file count, u32 first neighbour zone, u32 neighbour count`) and a `u32 zone index` per scene; `decode` returns `{scene: (files, neighbours, bytes, zone)}` plus `zones: {zone: (scenes, files, neighbour zones)}` (v1: each scene its own zone). Exact field placement is the implementer's; the C reader and Python reader must agree (the round-trip test pins it).
- Game: `const char *asset_prefetch_zone_now(void);` and `typedef void (*asset_zone_cb)(const char *old_zone, const char *new_zone); void asset_prefetch_on_zone(asset_zone_cb cb);` (called once per settled zone change, on the watch thread's next tick).

- [ ] **Step 1:** Failing tests: made-up scenes `A_Adult, A_Child` (maps in `Banc/A/`), `B` (`Banc/B/`), and six stages in `Banc/Stages/` leading to six different zones → zones `A` (2 scenes), `B`, and each stage alone; v2 round-trip in Python and C agree on scene → zone and zone files; a v1 file read by both readers gives each scene its own zone; scene `A_Adult` → `A_Child` is no zone change, `A_Child` → `B` is one (callback once, with "A", "B").
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat(ps5): zones in the prefetch map (Data.deps v2) and a zone-change event`.

### Task 6: `logs/memory.txt`

**Files:** Modify `host/ps5/win32_ps5.c` (`memory_floor_watch`: lines at a zone change, 5 s after, every 60 s, before a floor exit), `gpu/vk/vk_memory.cpp` or `vk_texture.cpp` (a `rx_vk_memory_stats` weak function like `rx_vk_inflight`); Test `tests/test_ps5_memory_log.py`.

**Interfaces:** Produces `void rx_vk_memory_stats(char *out, size_t n);` (one `key=value` run: `vma_block_mb`, `vma_alloc_mb`, `tex_n`, `tex_mb`, `mirror_over_mb`, `out_w`, `out_h`, `render_w`, `render_h`) and the line format `t=<s> why=<zone|after|tick|floor> scene=<name> zone=<name> free_mb=<n> largest_mb=<n> committed_mb=<n> prefetch_mb=<n> zone_boost=<0|1> <rx_vk_memory_stats>`.

- [ ] **Step 1:** Failing test: the line builder (a pure function cut from win32_ps5.c, or a new `host/ps5/memory_line.h`) given made-up numbers gives exactly the format above; the scheduler (pure) given a timeline (zone change at 10 s, ticks) emits `zone` at 10, `after` at 15, `tick` every 60 s, `floor` when asked; the renderer's function exists and fills every key (source check).
- [ ] **Step 2–4:** FAIL, implement, PASS.
- [ ] **Step 5:** Commit `feat(ps5): logs/memory.txt at each zone change, after it and every minute`.

### Task 7: Which file a texture came from (logged only)

**Files:** Create `host/asset_tags.c`, `host/asset_tags.h` (game-free interval map); Modify `host/nn_fs.c` (a romfs read records `(guest dst, len) → path`), `host/hos_zstd.c` (`hos_zstd_stream` records `(src, dst, produced)` on every call, also when native zstd is off, before it answers 0), `gpu/vk/vk_texture.cpp` (`create()` asks the tag of its storage address; the remake after compaction keeps it), `host/ps5/win32_ps5.c` (at a zone change, a `tags` line in memory.txt); Test `tests/test_asset_tags.py` + `tests/asset_tags_test.c`.

**Interfaces:**
- `void asset_tags_read(uint64_t dst, uint64_t len, const char *path);` — a file read into [dst, dst+len); a later read over the range replaces it.
- `void asset_tags_derived(uint64_t src, uint64_t dst, uint64_t len);` — bytes at [dst, dst+len) came from what is tagged at src.
- `int asset_tags_lookup(uint64_t addr, char *path, size_t cap);` — 1 with the path when tagged.
- `void asset_tags_texture(uint64_t storage, uint64_t bytes, int created);` / the renderer's per-texture tag kept in its Texture entry; `void asset_tags_report(const char *const *wanted, int nwanted, char *line, size_t cap);` — `tags tagged_n=… tagged_mb=… untagged_n=… untagged_mb=… unwanted_n=… unwanted_mb=…` (unwanted: tagged with a file not in the new zone's or its neighbours' lists).

- [ ] **Step 1:** Failing test (game-free, compiled with sanitizers): a read of "Model/X.bfres.zs" at 0x1000/0x100, a derived 0x1000→0x9000/0x400, lookup at 0x9200 gives the path; a new read over 0x1000 replaces the old tag for new derivations, not for 0x9000's existing one; a texture at 0x9100 tagged; one at 0x20000 untagged; the report against a wanted list without "Model/X.bfres.zs" counts it unwanted; 100,000 ranges stay under a fixed memory bound (oldest dropped).
- [ ] **Step 2–4:** FAIL, implement, PASS; source checks for the three hooks (nn_fs read, zstd record before the native switch, texture create/remake).
- [ ] **Step 5:** Commit `feat(ps5): tag each texture with the file it came from, and log what a zone change leaves unwanted`.

### Task 8: Docs, the full checks, the session on the PS5

**Files:** Modify `docs/ps5-asset-prefetch.md` (zones, v2), `docs/PS5.md` (logs/memory.txt, log.txt fixed, the env notice), this spec's status.

- [ ] **Step 1:** Docs from the code.
- [ ] **Step 2:** `python -I -B tests/run_all.py` in Docker → no failing check outside `C:\Users\Renan\Desktop\Longshot\tools\docker\baseline-feature-amiibo-bc59bbd3.txt`.
- [ ] **Step 3 (the person, PS5):** a new kit and build (`build_kit.sh` in Docker, then the builder); a session over Hyrule Field ↔ Castle Town ↔ Kakariko; send `logs/memory.txt`, `logs/nfp.txt` and any `bug-reports/`. That session's numbers decide phase 5.
- [ ] **Step 4:** Commit `docs: memory at a zone change (phases 1-4)`. The PR waits for the person.
