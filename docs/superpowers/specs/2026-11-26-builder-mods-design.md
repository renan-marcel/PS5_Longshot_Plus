# Mods chosen in the builder: design

Status: draft for approval · Branch: `feature/amiibo` for now (its own branch from `fork/develop` when built) ·
A second piece of work, after the amiibo one (`2026-11-26-amiibo-design.md`).

## Intent

Players get OoT mods made for Lichii / Eden (GameBanana and the like). Today, on the PS5, a mod means copying folders
by hand into the title folder, and a mod that changes the game's code cannot work at all. This lets the person keep
their mods in one folder the builder makes, see them listed in the builder window, tick the ones they want, and have
the build put them into the PS5 title folder: code patches applied to the game's program before it is translated, and
file replacements copied where the game on the PS5 already layers them over its own files.

## Goals

- A **mods folder** the builder creates (and opens) for the person to drop mods into, in Lichii's layout.
- The builder window **lists the mods** in it with a checkbox each, what each holds, and keeps the choice.
- The build **applies the ticked ones**:
  - `exefs` code patches (`.ips`, `.pchtxt`) applied to the game's program before the translation;
  - `romfs` file mods copied into `PPSA99198/mods/`, where `host/mods.c` layers them over the game's files
    (approach A, chosen).
- Unticking a mod and building again takes it out of the title folder.

## Non-goals

- Atmosphère cheats (`cheats/*.txt`): listed as "cheats: not supported", not applied.
- `exefs` file replacements other than patches (a whole `main` replaced, `.npdm`): listed as not supported.
- Turning mods on and off in the game's menu (possible later on top of A; not here).
- Writing mods into the `Data/` packs (approach B, not chosen).
- Downloading mods.

## Anti-goals

- A mod's files, or a patched program, in the repository, a release or a kit: they come from the person's folder into
  the person's build only (CONTRIBUTING's rule; a mod's romfs is often game-derived).
- A build that silently applies a code patch made for another version of the game: patches are matched by the
  program's build id, as Lichii does; one that does not match is listed and skipped, with a line in the log.
- Touching folders in `PPSA99198/mods/` the builder did not put there.

## How Lichii does it (the reference; GPLv3 like Longshot)

`src/core/file_sys/patch_manager.cpp` (zortos293/Lichii, Fritchii's parent):

- A mod is a folder `load/<title id>/<mod name>/` holding any of `exefs/`, `romfs/`, `romfs_ext/`, `cheats/`. Mods
  are applied in the order of their folder names; the per-game "Add-ons" list disables some by name.
- **Code patches** (`CollectPatches`, `PatchNSO`): in a mod's `exefs/`, `<build id>.ips` (IPS32 as Atmosphère uses
  it) and `*.pchtxt` (IPSwitch text, its `@nsobid-<build id>` line names the build). A patch is used only when its
  build id matches the NSO's (the header's build id, zero-padded to 64 hex characters). Patches apply in mod order to
  the decompressed NSO; `ips_layer.cpp` has the IPS32 and IPSwitch readers (offsets past the 0x100 NSO header, as
  Atmosphère). Lichii's own OoT built-ins are applied after the mods' patches.
- **File mods:** `romfs/` layered over the game's RomFS (LayeredFS), the last mod winning a path.
- **Cheats:** `cheats/<build id>.txt`, Atmosphère's dmnt format.

## How Longshot works here today

- **File mods already work at run time:** `host/mods.c` finds mods (a folder with `romfs`, one to four levels below
  the root) in `mods/` beside the executable (or `HOS_MODS`), sorts them by path, ignoring case, and `host/nn_fs.c`
  serves the winning file before the game's own: on the PS5, before the `Data/` packs. Folders starting with `.`,
  `-` or `_` are skipped. `docs/mods.md` is the contract. That this root is `PPSA99198/mods/` on the PS5 is to be
  confirmed in the game (step 5).
- **Code patches are noticed and not applied** (`exefs` "logged"): Longshot translates the program ahead of time.
- **The builder** (`ps5/builder/pipeline.py`): step 1 extracts the `.nup`'s `exefs` into `<work>/game/exefs` (kept,
  stamped by the file); step 2 translates it (`nx2/lift.py --standalone --exefs ...`), skipped when the key
  `sha1(exefs/main) + kit revision` matches the last one. Longshot's own patches (`nx2/oot_patches.py`) are applied
  inside the translation, by address. The window (`ps5/builder/app.py`) keeps its choices in `QSettings` and passes
  them as flags; it can send the title folder over FTP.

## Approaches (for the file mods)

- **A. Copy the ticked mods into `PPSA99198/mods/`** and let the runtime layer them. Packs untouched; changing file mods
  is a copy of seconds; on/off in the game possible later. **Chosen.**
- **B. Write the mods' files into the `Data/` packs.** A closed title folder, but every change rewrites the packs (the
  long FTP copy), invalidates `Data.deps` (asset prefetch keyed on the packs' build id), and a mod cannot be turned off
  without a build.

Code patches have one way only: applied to the program before the translation.

## The design

### 1. The mods folder

- Default: `mods/` beside the builder (the folder the person unpacked it to); another can be chosen in the window and
  is remembered. Made by the builder the first time, with a `README.txt` on the layout (`<mod name>/romfs/...`,
  `<mod name>/exefs/<build id>.ips` or `*.pchtxt`), so a Lichii/Eden mod folder can be dropped in as it is.
- The mods are the folders directly inside it that hold `romfs/` or `exefs/` (also one level down, so
  `mods/<title id>/<mod name>/` from an emulator's `load` folder works).

### 2. The window

A **Mods** card under the options (`app.py`):

- The folder's path, **Open folder** (creates it if missing) and **Refresh**.
- One row per mod, in apply order (folder name, ignoring case; the last wins a file), each with a checkbox, its name
  and what it holds: "files", "code patch", "code patch for another version", "cheats: not supported". Ticks are kept
  in `QSettings` by mod name; a new mod starts unticked.
- With no mods: "No mods: put each mod's folder in <path>".
- The version check of code patches needs the game's build id: known once step 1 has read the game. Before that the
  row says "code patch (checked when building)"; the window may read it from `<work>/game/exefs/main` when present.

The CLI: `--mods-dir <folder>` and `--mod <name>` (repeated) for the ticked ones.

### 3. The pipeline

`STEPS` (with the amiibo step) becomes: 1 Reading the game's program, **2 Applying the mods' code patches**, 3
Translating it to C, 4 Compiling, 5 Linking, 6 Making the title folder, 7 Listing the game's shaders, 8 Extracting the
game's data, 9 Downloading the amiibo, **10 Copying the mods**. A step with nothing to do says so and ends at once.

- **Step 2** (`ps5/builder/mods.py`, run like `game_data.py`): copies `<work>/game/exefs` to
  `<work>/game/exefs-mods`, then for each ticked mod in order, for each module of the exefs (`main`, `sdk`,
  `subsdk*`), the patches whose build id matches that module's are applied to it (the NSO decompressed and written
  back as the lifter reads it). The translation then reads `exefs-mods` when any patch applied, `exefs` otherwise.
  Written fresh after Lichii's `ips_layer.cpp` (adaptable with credit: GPLv3).
- **The translation's key** includes every module's hash (not only `main`'s), so a patch to `sdk` translates again too;
  a change of code patches costs a translation (the long step), and the window says so beside the list.
- **Longshot's own patches** (`oot_patches.py`) still apply inside the translation. A mod's patch over the same bytes
  can clash: `oot_patches.py`'s check of the original bytes stops the translation with its own message; the builder
  names the mod patches applied in that message.
- **Step 10** copies each ticked mod's `romfs/` into `PPSA99198/mods/<mod name>/romfs/`, and only that (`exefs/` is
  already in the program, `cheats/` not supported). The builder keeps a list of what it copied
  (`PPSA99198/mods/.builder-mods.txt`): a mod unticked since the last build is removed, a folder the builder did not
  put there is left alone. Copies are skipped for files already the same (size and time).
- A mod that fails (unreadable patch, a copy error) stops the build with the mod's name: a half-applied mod is worse
  than none.
- The FTP send already copies the whole title folder, `mods/` with it.

### 4. Docs

`docs/mods.md` gains the builder way (folder, ticks, the two steps, code patches applied at build time); the builder's
readme (`package.py`), `ps5/README.md` and the README's Mods section a line each.

### 5. Tests and the in-game check

Game-free (`tests/`):
- IPS32 and IPSwitch applied to a made-up NSO (bytes, the 0x100 header offset, EOF marker, build-id matching and
  mismatch), and to two modules.
- The mods listing from a fake folder: layouts, order, kinds, the one-level-down emulator layout.
- Step 10's mirror: copy, re-copy skipped, an unticked mod removed, a foreign folder kept.
- The translation key changes when `sdk` changes.
- The window's ticks become `--mod` flags (the existing builder checks' pattern).

On the PS5: a small `romfs` mod (a changed text) is seen in the game from `PPSA99198/mods/`, and a known code patch
for this version applies (its effect seen). Then `python -I -B tests/run_all.py` against develop's baseline.

## Left to the builder

- The exact look of the Mods card within the window's style; how the list scrolls.
- `mods.py`'s internal structure; how the NSO is decompressed and written back (the lifter's own reader in
  `nx2/nso2.py` first).
- The README.txt's wording.

## Open, needs the person

- Nothing before planning. The PS5 check (step 5) needs the person's console.
