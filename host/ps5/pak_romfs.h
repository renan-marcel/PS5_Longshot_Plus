/* PS5: the game's romfs read from the title folder's packs (Data/<Top>.pak): a group per top folder of the romfs, its
   index at the end of its last pack, and the manifest Data.idx naming them all, made by the builder
   (ps5/builder/data_packs.py, docs/ps5-data-packs.md). Nothing in them is compressed: a file is a span of a pack, read with
   pread. host/posix/win32_posix.c's file calls send every path under PAK_ROMFS_ROOT here.

   Everything is read at the start (pak_romfs_open: the manifest, every group's index, ~23 MB in all, and the packs opened
   once each); after that nothing is allocated, locked or changed, so any number of threads read at once. */
#ifndef HOS_PAK_ROMFS_H
#define HOS_PAK_ROMFS_H
#include <stddef.h>
#include <stdint.h>

#define PAK_ROMFS_ROOT "/pak/romfs"

#ifdef __cplusplus
extern "C" {
#endif
/* The manifest, its packs and their indexes (packs_dir: the folder the packs are in); 1 when they are usable. On 0,
   pak_romfs_error says why. */
int pak_romfs_open(const char *index_path, const char *packs_dir);
const char *pak_romfs_error(void);
/* Whether a path is under PAK_ROMFS_ROOT (and the packs are open). */
int pak_romfs_path(const char *path);
/* The node of a path (a folder or a file): >= 0 with *is_dir and *size set; -1 when there is none. */
int64_t pak_romfs_find(const char *path, int *is_dir, uint64_t *size);
/* A file node's place: the pack's fd, where the file starts in it and its size. 0 for a folder or a bad node. */
int pak_romfs_file(int64_t node, int *fd, uint64_t *base, uint64_t *size);
/* A folder's entries, one by one: 1 with the name (not terminated) and kind, 0 at the end. cursor starts at 0. */
int pak_romfs_dir_next(int64_t dir_node, uint32_t *cursor, const char **name, size_t *name_len, int *is_dir,
                       uint64_t *size);
/* A whole file into buf (cap bytes): its size (copied when it fits), -1 when there is none. For readers that do not go
   through the file calls (gpu/vk/vk_game_font.h). */
int64_t pak_romfs_read(const char *path, void *buf, uint64_t cap);
#ifdef __cplusplus
}
#endif
#endif
