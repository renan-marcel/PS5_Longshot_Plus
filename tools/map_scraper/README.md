# lsms: the Longshot map scraper

A C++20 library (with a stable C interface) that reads the game's map and scene files and catalogues the assets they
refer to: actors, models, textures, collision, effects and sub-maps, with how often each is placed, where, and a sample
transform. It also says which romfs file holds each one, and which references point nowhere.

It runs on your PC, on your own dump. **The rule with no exceptions applies to it as to everything here
([CONTRIBUTING.md](../../CONTRIBUTING.md)): no game file, and nothing made from one, leaves the PC.** That includes the
catalogue it writes, the key census and any name tables. Its tests use synthetic buffers only.

## Layout

```
tools/map_scraper/
  CMakeLists.txt
  include/lsms/
    expected.hpp       Expected<T> / Status / Errc: std::expected under C++23, a stand-in with its surface under C++20
    binary_reader.hpp  Reader: bounds-checked reads of a std::span<const std::byte>, either byte order
    zstd_stream.hpp    the .zs layer: zstd_decompress, ZstdStream (incremental), ZstdDictionarySet (Pack/ZsDic.pack.zs)
    sarc_reader.hpp    SarcReader: SARC header, SFAT, SFNT; members as views, nothing written to disk
    byml_parser.hpp    byml::Document / Node / Member: BYML v2 to v7 read in place, hash maps included
    romfs_index.hpp    RomfsIndex: the romfs's file list (folder, list file or add()), UTF-8 paths
    map_scraper.hpp    ScraperConfig (the heuristics), Catalog, MapScraper
    json_writer.hpp    JsonWriter: streaming JSON, UTF-8 checked
    lsms.h             the C interface (extern "C")
  src/                 one .cpp per header, and c_api.cpp
  cli/main.cpp         lsms-scan
  tests/               test_main.cpp, builders.hpp (BYML, SARC and zstd frames made in memory)
```

The modules depend downward only: `binary_reader` ← `sarc_reader`, `byml_parser` ← `zstd_stream` (it opens
ZsDic.pack's SARC) ← `map_scraper` (with `romfs_index`, `json_writer`) ← `c_api`. Nothing above zstd is opaque.

## Build

```sh
cmake -S tools/map_scraper -B build/lsms -DCMAKE_BUILD_TYPE=Release
cmake --build build/lsms
ctest --test-dir build/lsms          # or build/lsms/lsms-tests
```

| Option | Default | |
|---|---|---|
| `LSMS_ZSTD` | `bundled` | `bundled`: the decoder in `third_party/zstd` (unmodified, as `nx2/build.py` builds it). `system`: the system's libzstd. `off`: no zstd (`.zs` answers `Errc::unsupported`; `.byml`, `.sarc` and `.pack` still work). |
| `LSMS_SHARED` | `OFF` | also build `lsms_c`, a shared library exporting only `lsms.h` |
| `LSMS_SANITIZE` | `OFF` | AddressSanitizer and UBSan (GCC, Clang): run the tests with it after touching a parser |

Windows (llvm-mingw or MSVC) and Linux (GCC 13, Clang 18) build it. Paths are UTF-8 throughout (`path_from_utf8`,
`utf8_of`; the CLI reads its arguments from the wide command line), never through the ANSI code page.

## Using it

### From C++

```cpp
#include "lsms/map_scraper.hpp"

lsms::MapScraper scraper;                          // default rules (see "Heuristics")
scraper.config().actor_keys.insert(scraper.config().actor_keys.begin(), "ActorId");   // a key of this title, tried first
if (auto st = scraper.load_romfs("D:/dump/romfs"); !st)        // the file index, and Pack/ZsDic.pack.zs's dictionaries
    std::fprintf(stderr, "%s\n", st.error().message.c_str());
scraper.scan_path("D:/dump/romfs/Banc");          // a folder: every file named like a map
scraper.scan_file("D:/dump/romfs/Pack/Field.pack.zs");
std::size_t missing = scraper.resolve();           // romfs paths for every record; the rest are "missing"
std::string json = scraper.to_json({.include_census = true});
```

Lower layers work alone, all on views (`std::span<const std::byte>`):

```cpp
auto raw  = lsms::zstd_decompress(file_bytes, &dictionaries);          // Expected<std::vector<std::byte>>
auto sarc = lsms::SarcReader::open(*raw);                              // Expected<SarcReader>
const lsms::SarcEntry* e = sarc->find("Banc/Field.bcett.byml");        // a view into *raw
auto doc  = lsms::byml::Document::parse(e->data);                      // Expected<byml::Document>
if (auto name = doc->root()->find("Gyaml")) std::puts(std::string(*name->as_string()).c_str());
```

Lifetimes: `SarcEntry::data` and every `byml::Node` look into the caller's buffer, so keep it alive while they are
used. A `Document` may be moved, and its Nodes keep working. Nothing throws on bad input: every parser answers `Errc`
and a message.

For a source that is not a folder, such as an archive's table of contents or this project's PS5 data packs, give
`scan_index` a `RomfsIndex` and a read callback (`Expected<std::vector<std::byte>>(std::string_view romfs_path)`).

### From C (and other languages)

```c
lsms_scraper* s = lsms_create();
lsms_add_resource_key(s, "model", "MdlName");
if (lsms_load_romfs(s, "D:/dump/romfs") != LSMS_OK) fprintf(stderr, "%s\n", lsms_last_error(s));
lsms_scan_path(s, "D:/dump/romfs/Banc");
lsms_resolve(s);
char* json = lsms_to_json(s, 1, 0);   /* pretty, no census */
/* ... */
lsms_free(json);
lsms_destroy(s);
```

Build with `-DLSMS_SHARED=ON` for `lsms_c.dll` / `liblsms_c.so`, which Python (ctypes), C# (P/Invoke) or Rust (FFI)
can load.

### From the command line

```sh
lsms-scan --romfs D:/dump/romfs --all --census --out catalogue.json      # every map in the romfs
lsms-scan --romfs D:/dump/romfs Banc/Field.bcett.byml.zs                 # one map, by its romfs path
lsms-scan --index romfs_list.txt --actor-key ActorId --resource-key model=MdlName maps/
```

## How the scraper works

1. **Layers come off by magic, not by name.** A zstd frame is decompressed with the dictionary its header names. A
   SARC is opened in memory, and its BYML and SARC members (and its zstd members named like maps) are walked. A BYML is
   parsed in place. Nesting is bounded by `max_nesting`. A member inside a pack is reported as
   `Pack/X.pack.zs:Inner/Map.byml`.
2. **Each BYML dictionary is read whole.**
   - **Transform:** found first, under the translate, rotate and scale keys, either as `[x, y, z]` or as `{X, Y, Z}`.
   - **Actor:** the best-ranked actor key holding a string, or a hash, names the placed actor. That dictionary is one
     instance of it, with that transform. A weak key such as `Name` counts only beside a transform.
3. **Its other members:**
   - **Resource keys:** the value names a resource of that key's category. It may be a string, a list of strings, or
     a dictionary with a `name_keys` member. It takes the transform of the placement around it.
   - **Path-like strings:** any other string ending in a known extension (`extension_rules`) is a reference of that
     category. Strings with spaces never count.
4. **Records are unique by (source map, category, name).** `instance_count` counts every occurrence, and
   `sample_transform` keeps the first one placed with a transform. `Catalog::aggregate()` (the JSON's `summary`)
   merges them across maps.
5. **`resolve()` looks each record up in the RomfsIndex.** It tries, in order:
   - the name itself, then the name plus `.zs`;
   - the category's `resolve_rules` (`{name}`, `{stem}`);
   - with `resolve_by_stem`, any romfs file of the same stem whose extension gives the same category.

   What stays unmatched is `missing` and is listed under `unresolved`.

Walk limits keep hostile files harmless:
- `max_depth` caps how deep the walk goes;
- a container that refers back to itself is cut;
- `max_nodes` is a node budget per map;
- `max_decompressed` and `max_file_size` cap the bytes read;
- container counts are checked against the buffer before they are used.

## Heuristics: tune them to this title

This remake's key names are not documented, and they may differ from other titles of the same format family. The
defaults in `ScraperConfig` are **starting points taken from that family** (`Gyaml`, `UnitConfigName`, `Translate`,
`Pack/Actor/{stem}.pack.zs`...), not facts about this game. To fit them:

1. Run once with the key census: `lsms-scan --romfs ... --all --census --out census.json`.
2. Read `key_census`: every key seen, how often, and whether it held strings, numbers or containers, with a sample.
3. Put the keys that hold actor names in `actor_keys`, the resource keys in `resource_keys`, and so on. Check the
   romfs layout against `resolve_rules`.
4. Run again and read `unresolved`: what is left is either a rule to add or a real orphan.

Each rule list is plain data in `ScraperConfig`, and also reachable from C (`lsms_add_*`, `lsms_set_option`).

## JSON

```json
{
  "format": "longshot-map-scraper", "format_version": 1,
  "maps_scanned": ["Banc/Field.bcett.byml.zs"],
  "assets": [{
    "asset_name_or_path": "Enemy_Octorok", "category": "actor", "instance_count": 2,
    "source_map": "Banc/Field.bcett.byml.zs", "via_key": "Gyaml",
    "sample_transform": {"translate": [1, 2, 3], "rotate": [0, 1.5, 0], "scale": [1, 1, 1]},
    "resolution": "found", "resolved_paths": ["Pack/Actor/Enemy_Octorok.pack.zs"]
  }],
  "summary":     [{"asset_name_or_path": "...", "category": "...", "instance_count": 4, "maps": ["..."], "resolution": "..."}],
  "unresolved":  [{"asset_name_or_path": "...", "category": "...", "source_map": "..."}],
  "diagnostics": [{"level": "warning", "source": "...", "message": "..."}],
  "key_census":  [{"key": "Gyaml", "count": 3, "strings": 3, "numbers": 0, "containers": 0, "other": 0, "sample": "..."}]
}
```

`sample_transform` is `null` when no placement had one, and a missing component is `null`. `resolved_paths` appears
once `resolve()` has run, and `key_census` only with `include_census`.

## Tests

`tests/test_main.cpp` needs no game file. `tests/builders.hpp` writes what the tests read:
- a little-endian BYML v7 from a small tree (`BymlWriter`);
- a SARC from (name, bytes) pairs (`make_sarc`);
- zstd frames of raw blocks (`zstd_raw`), which are valid frames that need no compressor and may name a dictionary id.

The tests cover:
- SARC lookup, hashing, sorting and damage;
- every BYML node type the writer makes, plus bad versions, magics and offsets;
- zstd: single and multiple frames, streaming in pieces, a missing dictionary, a cut frame and the output limit;
- the scraper's rules, a non-default schema, hashed names, pack → zstd → BYML layering, resolution, and JSON escaping;
- a mutation pass over valid inputs (run it under `LSMS_SANITIZE=ON`);
- the C interface.

A new case is a few lines: build the tree with `dict({...})` and `arr({...})`, wrap it with `zstd_raw` or
`make_sarc` if needed, `scan_buffer` it, and check `catalog().find(source, category, name)`.

## Known limits

- **Assets chosen at run time are invisible.** The scraper sees what the map files name. Actors spawned by code,
  by event scripts or by other actors' parameters only appear if those files are scanned too (packs' `.bgyml` members
  are walked, but only as references by extension and key). Asset names built by string concatenation in the
  executable are not in any file.
- **Hashes without names.** BYML v7 hash maps, and actors stored as numeric ids, come out as `hash:0x...` unless
  `hash_names` has them. The library does not know the hash function this title uses. A name table you build (hash
  → name) fills them in.
- **zstd dictionaries.** A frame that names a dictionary not loaded from `Pack/ZsDic.pack.zs` fails with
  `missing_dictionary` and is reported. Raw-content dictionaries (no id in the frame) are not tried by guessing.
- **BYML corners.** Type `0xA2` ("file") is read as size, alignment, then data, which is not confirmed on this title.
  Types newer than v7 are not decoded, and are skipped as unknown values. BYML v1 (with a path table) is not read.
  Binary nodes are not opened as nested BYML or SARC.
- **Big-endian** SARC and BYML (Wii U) are read, but the tests build little-endian files only.
- **Path-like strings** are recognized by extension: a name with no extension that is not under a configured key is
  not caught, and a string that happens to end in `.byml` is caught as `unknown`.
- **Resolution** is by rules, then by stem. Two files sharing a stem in one category both resolve, and the record
  lists both.
- **Memory.** Each map is held whole in memory while it is walked (decompressed, then parsed in place). `ZstdStream`
  can decompress files too big for that, but the BYML parser needs the whole document.
