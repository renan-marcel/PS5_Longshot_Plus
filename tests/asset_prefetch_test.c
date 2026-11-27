/* The driver of tests/test_asset_prefetch.py: host/ps5/asset_prefetch.c against a pack of its own (no game file).

   asset_prefetch_test <title dir> <pack file> <files list> <command>...
   The files list: "<romfs path>\t<offset>\t<size>" per line, the files of the pack. Commands, in order:
     open:<path>      the game opens a file (as win32_posix.c's CreateFileA tells the module)
     read:<path>      the game reads it whole (as ReadFile: the bucket, else the pack); prints "hit|disk <path> <fnv>"
     scene:<name>     the game's current scene (as host/hos_main.c tells it)
     wait             until the module's thread has nothing left to do
     room:<MB>        the title's free memory from now on (host/ps5/win32_ps5.c's hos_ps5_direct_room)
     stats            prints the module's counters
     zone             prints "zone <the current zone>"; every zone change prints "zone-change <old> -> <new>"
     stop             stops the module (its profiles are written) */
#include <fcntl.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "../host/ps5/asset_prefetch.h"
#include "../host/ps5/pak_romfs.h"

typedef struct { char path[512]; uint64_t off, size; } F;
static F files[256];
static int nfiles, pack_fd = -1;
static uint8_t bid[16] = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16};
static uint64_t room_mb = 1u << 20;

void hos_log(const char *fmt, ...) {
    va_list a;
    va_start(a, fmt);
    printf("log: ");
    vprintf(fmt, a);
    printf("\n");
    va_end(a);
    fflush(stdout);
}
uint64_t hos_ps5_direct_room(void) { return room_mb << 20; }
const uint8_t *pak_romfs_build_id(void) { return bid; }

int64_t pak_romfs_find(const char *path, int *is_dir, uint64_t *size) {
    const size_t root = sizeof(PAK_ROMFS_ROOT);   /* (the root and its '/') */
    if (strncmp(path, PAK_ROMFS_ROOT "/", root)) return -1;
    for (int i = 0; i < nfiles; i++)
        if (!strcmp(files[i].path, path + root)) {
            if (is_dir) *is_dir = 0;
            if (size) *size = files[i].size;
            return i;
        }
    return -1;
}
int pak_romfs_file(int64_t node, int *fd, uint64_t *base, uint64_t *size) {
    if (node < 0 || node >= nfiles) return 0;
    *fd = pack_fd, *base = files[node].off, *size = files[node].size;
    return 1;
}

static void on_zone(const char *old_zone, const char *new_zone) { printf("zone-change %s -> %s\n", old_zone, new_zone); }

static uint64_t fnv(const uint8_t *p, size_t n) {
    uint64_t h = 1469598103934665603ull;
    for (size_t i = 0; i < n; i++) h = (h ^ p[i]) * 1099511628211ull;
    return h;
}

int main(int argc, char **argv) {
    if (argc < 4) return 2;
    if (getenv("TEST_OTHER_BUILD")) bid[0] ^= 0xFF;
    pack_fd = open(argv[2], O_RDONLY);
    FILE *list = fopen(argv[3], "r");
    if (pack_fd < 0 || !list) return 2;
    char line[700];
    while (nfiles < 256 && fgets(line, sizeof line, list)) {
        unsigned long long off, size;
        char path[512];
        if (sscanf(line, "%511[^\t]\t%llu\t%llu", path, &off, &size) == 3) {
            snprintf(files[nfiles].path, sizeof files[nfiles].path, "%s", path);
            files[nfiles].off = off, files[nfiles].size = size, nfiles++;
        }
    }
    fclose(list);
    asset_prefetch_init(argv[1]);
    asset_prefetch_on_zone(on_zone);
    for (int i = 4; i < argc; i++) {
        const char *c = argv[i];
        char full[600];
        if (!strncmp(c, "open:", 5) || !strncmp(c, "read:", 5)) {
            snprintf(full, sizeof full, PAK_ROMFS_ROOT "/%s", c + 5);
            const int64_t node = pak_romfs_find(full, NULL, NULL);
            if (node < 0) { printf("missing %s\n", c + 5); continue; }
            int fd;
            uint64_t base, size;
            pak_romfs_file(node, &fd, &base, &size);
            if (c[0] == 'o') { asset_prefetch_open(full, fd, base, size); continue; }
            uint8_t *buf = (uint8_t *)malloc(size ? size : 1);
            const int hit = asset_prefetch_read(fd, base, size, 0, buf, (uint32_t)size);
            if (!hit) {
                const ssize_t r = pread(fd, buf, size, (off_t)base);
                asset_prefetch_disk(fd, base, r > 0 ? (uint32_t)r : 0, 0.5);
            }
            printf("%s %s %016llx\n", hit ? "hit" : "disk", c + 5, (unsigned long long)fnv(buf, size));
            free(buf);
        } else if (!strncmp(c, "scene:", 6)) {
            asset_prefetch_scene(c + 6);
        } else if (!strcmp(c, "wait")) {
            asset_prefetch_wait_idle();
        } else if (!strncmp(c, "room:", 5)) {
            room_mb = strtoull(c + 5, NULL, 10);
        } else if (!strcmp(c, "stats")) {
            AssetPrefetchStats s;
            asset_prefetch_stats(&s);
            printf("stats hits=%llu disk=%llu prefetched=%llu released=%llu evicted=%llu held=%llu entries=%llu\n",
                   (unsigned long long)s.hits, (unsigned long long)s.disk_reads, (unsigned long long)s.prefetched,
                   (unsigned long long)s.released, (unsigned long long)s.evicted, (unsigned long long)s.held_bytes,
                   (unsigned long long)s.entries);
        } else if (!strcmp(c, "zone")) {
            printf("zone %s\n", asset_prefetch_zone_now());
        } else if (!strcmp(c, "stop")) {
            asset_prefetch_stop();
        }
        fflush(stdout);
    }
    close(pack_fd);
    return 0;
}
