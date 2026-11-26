/* (longshot) Which romfs file guest bytes came from (host/asset_tags.c): a file read tags its guest range, what is made from
   tagged bytes (the game's zstd decode) is tagged with the same file, and a texture's storage address then says which file it
   came from. Fed on the PS5 (host/nn_fs.c, host/hos_zstd.c); read by the renderer at a zone change (gpu/vk/vk_texture.cpp),
   which counts what the new zone does not want (logs/memory.txt). Logging only: nothing is freed by it.

   Bounded: a fixed table of 2 MiB pages, a few ranges each (the newest kept), and up to 8192 file names. */
#ifndef HOS_ASSET_TAGS_H
#define HOS_ASSET_TAGS_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/* A file read into [dst, dst + len): path as the host has it (any slashes); its part after the last "romfs/" is the tag */
void asset_tags_read(uint64_t dst, uint64_t len, const char *path);
/* [dst, dst + len) was made from what is at src: tagged with src's file, when it has one */
void asset_tags_derived(uint64_t src, uint64_t dst, uint64_t len);
/* The tag at addr (> 0), 0 none; its romfs path ("" for 0) */
int asset_tags_lookup(uint64_t addr);
const char *asset_tags_path(int id);

typedef struct { uint64_t tagged_n, tagged_bytes, untagged_n, untagged_bytes, unwanted_n, unwanted_bytes; } AssetTagTally;
/* One texture (its storage's guest address, its bytes) into the tally; wanted(path): the new zone wants that file */
void asset_tags_tally(AssetTagTally *t, uint64_t storage, uint64_t bytes, int (*wanted)(const char *path));
/* "tags tagged_n= tagged_mb= untagged_n= untagged_mb= unwanted_n= unwanted_mb=" */
void asset_tags_line(const AssetTagTally *t, char *line, size_t cap);
/* The table's memory, in bytes (fixed) */
size_t asset_tags_memory(void);
#ifdef __cplusplus
}
#endif
#endif
