/* tests/test_asset_tags.py: host/asset_tags.c on the PC (no game) */
#include <stdio.h>
#include <string.h>

#include "asset_tags.h"

static int failures;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL: %s\n", what); failures++; } } while (0)

static int wanted_none(const char *path) { (void)path; return 0; }
static int wanted_other(const char *path) { return !strcmp(path, "Model/Other.Other.bfres.zs"); }

int main(void) {
    char path[256];
    asset_tags_read(0x10000000, 0x100, "/pak/romfs/Model/X.X.bfres.zs");
    int id = asset_tags_lookup(0x10000080);
    CHECK(id > 0 && !strcmp(asset_tags_path(id), "Model/X.X.bfres.zs"), "a read is tagged with its romfs path");
    CHECK(!asset_tags_lookup(0x10000100), "the byte past the read is not tagged");
    asset_tags_derived(0x10000000, 0x20000000, 0x400);
    id = asset_tags_lookup(0x20000200);
    CHECK(id > 0 && !strcmp(asset_tags_path(id), "Model/X.X.bfres.zs"), "what was made from it (a decompression) is tagged too");
    asset_tags_derived(0x30000000, 0x40000000, 0x400);
    CHECK(!asset_tags_lookup(0x40000000), "made from untagged bytes: untagged");
    asset_tags_read(0x10000000, 0x100, "C:\\game\\romfs\\Model\\Y.Y.bfres.zs");
    id = asset_tags_lookup(0x10000010);
    CHECK(id > 0 && !strcmp(asset_tags_path(id), "Model/Y.Y.bfres.zs"), "a newer read over the range replaces it (any slashes)");
    id = asset_tags_lookup(0x20000010);
    CHECK(id > 0 && !strcmp(asset_tags_path(id), "Model/X.X.bfres.zs"), "what was made before keeps its file");
    asset_tags_read(0x50000000, 8u << 20, "/pak/romfs/Model/Big.Big.bfres.zs");
    id = asset_tags_lookup(0x50000000 + (7u << 20));
    CHECK(id > 0 && !strcmp(asset_tags_path(id), "Model/Big.Big.bfres.zs"), "a range over several pages is found anywhere in it");

    AssetTagTally t;
    memset(&t, 0, sizeof t);
    asset_tags_tally(&t, 0x20000100, 1u << 20, wanted_none);
    asset_tags_tally(&t, 0x60000000, 2u << 20, wanted_none);
    char line[256];
    asset_tags_line(&t, line, sizeof line);
    CHECK(!strcmp(line, "tags tagged_n=1 tagged_mb=1 untagged_n=1 untagged_mb=2 unwanted_n=1 unwanted_mb=1"),
          "the tally: tagged, untagged, and tagged with a file the zone does not want");
    memset(&t, 0, sizeof t);
    asset_tags_tally(&t, 0x20000100, 1u << 20, wanted_other);
    asset_tags_line(&t, line, sizeof line);
    CHECK(strstr(line, "unwanted_n=1"), "a file the zone does not want counts as unwanted");

    for (unsigned i = 0; i < 100000; i++) asset_tags_read(0x70000000ull + i * 0x1000ull, 0x800, "/pak/romfs/Many/File.bin");
    CHECK(asset_tags_lookup(0x70000000ull + 99999ull * 0x1000ull) > 0, "after 100,000 reads the newest is still found");
    CHECK(asset_tags_memory() < (64u << 20), "the table's memory is bounded");
    snprintf(path, sizeof path, "%s", asset_tags_path(asset_tags_lookup(0x50000000)));
    CHECK(path[0], "older tags stay readable while the pages are not reused");
    if (failures) return 1;
    printf("ok\n");
    return 0;
}
