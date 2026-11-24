# PS5: reading the game's files ahead of it

On the PS5 the game reads its files from the title folder's packs (`Data/*.pak` through `Data.idx`:
[ps5-data-packs.md](ps5-data-packs.md)). This page covers the layer that measures those reads, learns what each scene
reads, and can read a scene's files into memory before the game asks for them.

It works in phases:

| Phase | What | Where | Switch (`longshot_env.txt` or the environment) |
|---|---|---|---|
| 0 | Measure: per scene, the files opened, the bytes read from disk and the time; each burst of reading (a scene's load) with the disk's share of it | `host/ps5/asset_prefetch.c` | `HOS_IO_STATS` (on) |
| 1 | The prefetch map `Data.deps`: for each scene, the files it will read and the scenes it leads to | `ps5/builder/asset_deps.py` (builder step 7) | always made |
| 2 | Read ahead into a bucket; a game read the bucket holds is copied from memory | `asset_prefetch.c` | `HOS_PREFETCH=1` (off until measured) |
| 3 | Release: on each scene change, what neither the scene nor its neighbours want; a cap; empty under memory pressure | `asset_prefetch.c` | `HOS_PREFETCH_MB` (192), `HOS_PREFETCH_MARGIN_MB` (512) |
| 4 | Learn: the files each scene really opened, in order, read first on the next visit | `asset_prefetch.c` → `cache/prefetch/<scene>.txt` | `HOS_PREFETCH_LEARN` (on) |

None of this changes the game's own behaviour:
- The engine's distances, LOD and far-delete groups are left as shipped.
- Nothing the engine has loaded is freed by this layer. The bucket only holds bytes the game has not read yet.
- A file the bucket does not hold whole is read from its pack, as before.

## How the game's state is known

- **The scene being loaded:** the game opens `Banc/GameBancParam/<scene>.game__banc__GameBancParam.bgyml` when a scene
  starts loading. The file layer sees that open before the game says anything, and the read-ahead of that scene's files
  starts there, in parallel with the game's own reads.
- **The current scene:** `host/hos_main.c` reads the game's `Sequence_CurrentBanc` every half second, the same value
  behind the log's `map:` lines. This value is a `GameBancParam` name, the key of `Data.deps`. Once a scene has settled,
  the scenes it leads to are read ahead, taken in turn a file at a time so that each gets its most certain files first.

## Data.deps (phase 1)

Made by the builder after the packs are written, beside `Data.idx`, with the same build id: the game takes it only with
those packs. A title folder made before can get one by hand: `python -I ps5/builder/asset_deps.py <title folder>`.
The format is described at the top of `asset_deps.py`.

What a scene needs, followed from the game's files. The rules were read off a real dump, and each is the smallest that
held there:

1. **Parameters:** `Banc/GameBancParam/<scene>…bgyml`, followed through `$parent`.
2. **Maps:** the parameters' `Banc.Main` (`Work/Banc/Scene/<folder>/<name>.bcett.json`) is
   `Banc/<folder>/<name>_*.bcett.byml.zs`. Other scenes' maps named in the parameters are *neighbours*, not this scene's
   maps. Kokiri Forest's parameters name the Lost Woods, Hyrule Field, the Deku Tree and the Enemy Museum; counting those
   as its own had tripled its list.
3. **Actors:** the maps' `Actors` lists, by `Gyaml`, give `Pack/Actor/<Gyaml>.pack.zs`, most-placed first. Entries with
   `Src`/`Dst` are links between actors and `Rails` are paths; neither is an actor.
4. **What each placed actor's pack names outside itself:**
   - `?Path` and `Work/Path.gyml` files that are loose in the romfs;
   - its models, `Model/<ModelProjectName>.<FmdbName>.bfres.zs`.
5. **Named actors:** the packs only (never their models) of the actors those packs name through
   `Work/Actor/<name>…ActorParam.gyml`. These are spawn lists and dictionaries: what may come. A forest's actors name
   every boss of the Enemy Museum.
6. **Neighbours:** the scenes named by the parameters (rule 2) and by `NextBancParamName` in the maps' actors.

Files of the resident packs (`Pack/*.pack.zs` outside `Pack/Actor`) are left out, because the game holds those from its
start. The list is ordered by how certain each file is: parameters and maps first, then the placed actors' packs, their
small files, their models, and the named actors' packs last.

On a full dump: 80 scenes, made in about 30 s, a 1.3 MB file. A scene lists 79 MB at the median and 294 MB at most
(Market, adult), compressed as stored.

Textures are not followed: their names sit inside the `.bfres` files. The profiles (phase 4) catch them after a first
visit.

## The bucket (phases 2 and 3)

- **The read-ahead thread:** one thread reads the queued files into memory in 1 MB pieces. Between pieces it gives way
  while one of the game's reads is going on.
- **A game read:** under the lock, the file is looked up by its pack and offset, and pinned; the copy is made unlocked.
  Once the game has read a file whole, the bucket lets it go, because the game holds it from then on. The bucket
  therefore holds only what is still to come, and never duplicates what the engine has loaded.
- **A file the game read from disk meanwhile:** it is dropped when its read-ahead ends.
- **On each settled scene:** what neither the scene's list nor its neighbours' lists name is let go.
- **The cap:** the bucket stays under `HOS_PREFETCH_MB`. When the queue's files no longer fit beside what is still wanted,
  the rest of the queue waits for the next scene.
- **Memory pressure:** the game, the renderer and the textures share the title's memory, and a failed allocation of the
  game's ends the title (`gpu/vk/vk_texture.cpp`). So the bucket empties and stops while the title's free memory
  (`hos_ps5_direct_room`) is under `HOS_PS5_TEX_RESERVE_MB + HOS_PREFETCH_MARGIN_MB + the file`.
- **Large files:** a file above `HOS_PREFETCH_FILE_MB` (16) is never read ahead.

## The profiles (phase 4)

While a scene is loading or played, every file the game opens is noted, in the order of its first opening. When the scene
changes, the new ones are appended to `cache/prefetch/<scene>.txt` (at most 6000 lines; the file is written under another
name, then renamed). On the next load of that scene, or when it is a neighbour, its profile is queued before `Data.deps`'
list. The profile covers what no file names: code-spawned actors, events, textures. To start a profile again, delete its
file.

## Reading the measurements (phase 0)

```
io: loading HyruleField_Child
io: a burst of reading (HyruleField_Child): 2.84 s, the disk 0.41 s of it (14%), 1630 reads, 96.2 MB, 0 from the bucket
io: scene HyruleField_Child
io: KokiriForest_Child: 1102 files opened, 1650 reads from the disk (98.0 MB in 0.47 s, the longest 38 ms), 0 from the bucket (0.0 MB); the bucket holds 0.0 MB
```

The burst line answers whether the bucket can help. The disk's share of a load is the most it can save. If the share is
small, the time goes to decompression, building the scene and shader work, and reading ahead will not shorten it. With
`HOS_PREFETCH=1` the same lines show how much came from the bucket.

## Not done

- **Release by the player's position in open fields:** the bucket holds only files not yet read, so a position-based
  release would rarely free anything. The engine's own far-delete is left as it is.
- **Rooms in dungeons:** the scene is known, the current room is not. `DefaultDungeonRoomIndex` and `DungeonParam` would
  order a dungeon's list by room once the room can be read.
- **Textures in `Data.deps`:** this needs a `.bfres` reader; for now the profiles hold them.

## Checks

`tests/test_asset_prefetch.py` compiles `asset_prefetch.c` with AddressSanitizer against a pack of its own, with a
`Data.deps` made by the builder's writer. It covers:
- measuring only;
- the profile's order;
- read-ahead and hits, byte for byte;
- release after a whole read;
- neighbours, and releasing on a scene change;
- the cap and the memory floor;
- a profiled file read ahead;
- another build's map refused;
- the hooks in `win32_posix.c` and `hos_main.c`.
