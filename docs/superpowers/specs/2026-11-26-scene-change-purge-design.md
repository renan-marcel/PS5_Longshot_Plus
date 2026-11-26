# Memory let go at a scene change (PS5): feasibility and first step

Status: registered, not designed yet · A third piece of work, after amiibo and mods.

## The request

When the game loads another region, free what the previous region left in memory.

## What was found (2026-11-26)

- **Not a collector inside the game.** There is no source, only the translated binary (`nx2/oot_patches.py` patches by
  address, host hooks). The game's engine already unloads its own scene data and compacts its 2,400 MB texture heap
  (`host/oot_tex_compact.h`). Freeing guest allocations from outside would leave the game pointing at freed memory: a
  collector needs to know what points at what, which the translated code does not say.
- **What piles up is Longshot's own, outside the game:**
  - GPU copies of the game's textures (`gpu/vk/vk_texture.cpp`), keyed by the game's storage, let go by age
    (`RX_VK_EVICT_MIN_UNUSED`) or memory pressure only;
  - imports and their mirrors (`gpu/vk/mirror_trim.h`): after a large scene's pools give way to a smaller one's at the
    same addresses, the mirror keeps the old size (measured on desktop: ~225 MB entering Castle Town Market from Hyrule
    Field); trimmed only after "a while" (`mirrors_trim`, `RX_VK_MIRROR_TRIM`);
  - the asset prefetch bucket (`host/ps5/asset_prefetch.c`): already lets go at each scene change.
- **The person's `Log/crash_trace.txt`:** free memory falls from 4,537 MiB to about 2,000 MiB at zone changes
  (`zone_boost=1`), where the GPU freezes are logged.
- **The scene change is already seen:** `Sequence_CurrentBanc` read every half second (`host/hos_main.c:757`,
  `asset_prefetch_scene`); the prefetch sees a scene's parameters opened, before that.

## The idea (to design after measuring)

At a scene change (or when its load ends), on the renderer's side:

1. evict GPU textures not sampled since the load began;
2. trim the mirrors left over at once (not after "a while"), waiting for the GPU as `trims_settle` does;
3. give the Vulkan memory blocks left empty back to the system;
4. log free memory before and after each change.

Risks: evicting what the new scene also uses (made again: stutter; the evict-and-remake loop `vk_texture.cpp`
documents), GPU work still using what is let go. Measured on the PS5 only.

## First step: measure (no change to behaviour)

A log line per scene change, on the PS5: free memory, and how much each of the three holds (textures' GPU bytes and
count, mirrors' bytes over the live pools, prefetch bucket), at the change and 5 s after. From one session over the
usual transitions (Hyrule Field ↔ Castle Town ↔ Kakariko), decide which of 1-3 is worth building. Use the `measure`
skill for the before/after.
