/* PS5: reading the game's files ahead of it (docs/ps5-asset-prefetch.md).

   Every file the game reads from its packs goes through host/posix/win32_posix.c's CreateFileA / ReadFile, which tell this
   module. It does four things, each with its own switch (longshot_env.txt or the environment):
   - measures (phase 0, HOS_IO_STATS, on): per scene, the files opened, the bytes read from disk and the time it took, and the
     bursts of reading (a scene's load) with how much of their time was the disk's. Lines "io: ..." in the log;
   - reads ahead (phase 2, HOS_PREFETCH=1, off until measured): a thread reads, into a bucket in memory, the files the
     scene being loaded and the scenes it leads to will ask for (Data.deps, made by the builder: ps5/builder/asset_deps.py),
     and a read of the game's that the bucket holds is copied from there instead of the disk. A file is let go once the game
     has read all of it (the game holds it from then on), so the bucket holds only what is still to come;
   - lets go (phase 3): at each scene change, what neither that scene nor the ones it leads to wants; the bucket stays under
     HOS_PREFETCH_MB, and empties and stops when the title's free memory nears what the game needs (HOS_PS5_TEX_RESERVE_MB
     plus HOS_PREFETCH_MARGIN_MB);
   - learns (phase 4, HOS_PREFETCH_LEARN, on): the files each scene really opened, in order, kept in
     cache/prefetch/<scene>.txt and read first the next time (what Data.deps cannot see: what code and events load).
   Nothing here changes what the game reads: a file the bucket does not hold whole is read from its pack as before. */
#ifndef HOS_ASSET_PREFETCH_H
#define HOS_ASSET_PREFETCH_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/* After the packs are open (pak_romfs_open): the title folder, for Data.deps and cache/prefetch/. */
void asset_prefetch_init(const char *title_dir);
/* The game's current scene, as it says it (Sequence_CurrentBanc: host/hos_main.c, every half second). */
void asset_prefetch_scene(const char *scene);
/* A file of the packs the game opened: its path (under PAK_ROMFS_ROOT) and its span. */
void asset_prefetch_open(const char *path, int fd, uint64_t base, uint64_t size);
/* A read of the game's in a file's span: 1 when the bucket held it (copied into buf), 0 when the caller reads the disk and
   then calls asset_prefetch_disk with what it read and how long it took. */
int asset_prefetch_read(int fd, uint64_t base, uint64_t size, uint64_t from, void *buf, uint32_t n);
void asset_prefetch_disk(int fd, uint64_t base, uint32_t bytes, double ms);

/* (the checks: tests/test_asset_prefetch.py) */
typedef struct {
    uint64_t hits, hit_bytes, disk_reads, disk_bytes, prefetched, prefetched_bytes, released, evicted, held_bytes, entries;
} AssetPrefetchStats;
void asset_prefetch_stats(AssetPrefetchStats *out);
void asset_prefetch_wait_idle(void);
void asset_prefetch_stop(void);
#ifdef __cplusplus
}
#endif
#endif
