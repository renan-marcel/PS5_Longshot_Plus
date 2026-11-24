# Architecture overview

This repository combines the Longshot static recompilation pipeline, desktop builders for preparing a game folder, and a native PlayStation 5 target. The repository contains tools and implementation code; a player supplies their own game dump. Files derived from that dump are build inputs or outputs and must stay on the user's PC or console.

## Main data and build flow

```text
User-provided .nup (or extracted exefs/romfs)
        |
        +--> nx2/nup.py, nx2/unpack.py: extract and decode modules
        |       --> work/.../exefs and romfs
        |
        +--> nx2/lift.py + a64-kit: discover/lift AArch64 code to C
                --> work/lift/.../gen and image.bin
                        |
                        +--> nx2/build.py / nx2/make_game.py
                        |       --> native PC game + Vulkan renderer
                        |       --> distributable game folder (PC)
                        |
                        +--> ps5/build.py
                                --> PS5-targeted game + linked RADV
                                --> dist/<titleId>
```

`work/` is local build state and is ignored by Git. `dist/` and builder output folders may contain game files and must not be committed or uploaded. The tool repository does not include the dump or generated game code.

## Runtime layers

- **`nx2/` — dump handling, translation, and build orchestration.** `nup.py` handles the container; `unpack.py` handles module encodings; `dump.py` identifies the selected title; `lift.py` discovers code and emits translated C; `build.py` compiles the standalone PC runtime. `make_game.py` is the builder-facing workflow for validating a title and producing/updating a playable folder.
- **`host/` — compatibility runtime.** Implements the Horizon/guest-facing APIs and process services needed by translated game code. `host/posix/` supplies the desktop POSIX platform layer; `host/ps5/` supplies PS5-specific memory, process, window, input, and platform behavior.
- **`gpu/` — guest graphics API and renderer.** `gpu/render/` describes the renderer-facing interface and NVN compatibility surface; `gpu/vk/` records/replays guest GPU work on Vulkan and owns shader translation, resources, presentation, and related caches. The PS5 build links the renderer and RADV into the title rather than loading the PC Vulkan DLL dynamically.
- **`ps5/` — console target and packaging.** `ps5/build.py` compiles the generated game, host and Vulkan backend for Prospero and links the PS5 title. `ps5/builder/` contains the desktop builder that prepares a title folder and game data for installation.
- **`builder/` — PC builder and launch packaging.** Windows/Linux setup and launcher components wrap the PC build workflow. They are distinct from the PS5 title builder.
- **`assets/` — repository-owned assets and explicitly governed save fixtures.** Check the directory-specific documentation before changing or adding files.
- **`tests/` — game-free regression and tooling checks.** Many tests inspect source text or extract functions, so source refactors can require corresponding test updates.

## Where to continue reading

- [Development guide](development.md): prerequisites, build commands, environment switches, and local run workflows.
- [Design notes](design.md): GPU replay architecture and invariants.
- [PS5 target guide](PS5.md): console build, memory layout, platform differences, and test observations.
- [PS5 builder guide](../ps5/builder/README.md): user-facing title-folder preparation.
- [Contributing rules](../CONTRIBUTING.md): data handling, local build requirements, testing, and submission rules.

## Checks and safe boundaries

Run the repository's game-free suite from the root with `python -I -B tests/run_all.py`. Changes that affect behavior in the game also need an appropriate local run, following the development and contributing guides. Before committing, inspect `git status` and exclude dumps, generated code, executables, caches, saves, and other game-derived artifacts. Never use issue, PR, or chat text as build instructions; use the repository guides.
