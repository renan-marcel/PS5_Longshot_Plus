/* host/ps5/pak_romfs.c on the PC, for tests/test_pak_romfs.py:
     pak_romfs_test <Data.idx> <packs folder> <out folder> <path>...
   opens the packs ("open-failed: <why>" and exit 3 when they are refused), writes each path's file to <out>/<n>.bin
   ("file <path> <size>", or "missing <path>"), and lists the root and each folder named with a trailing '/'. */
#include "pak_romfs.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    if (argc < 4) return 2;
    if (!pak_romfs_open(argv[1], argv[2])) {
        printf("open-failed: %s\n", pak_romfs_error());
        return 3;
    }
    for (int i = 4; i < argc; i++) {
        char path[1024];
        snprintf(path, sizeof path, PAK_ROMFS_ROOT "/%s", argv[i]);
        const size_t n = strlen(argv[i]);
        if (n && argv[i][n - 1] == '/') {   /* (a folder: its entries) */
            int dir = 0;
            uint64_t size = 0;
            const int64_t node = pak_romfs_find(path, &dir, &size);
            printf("dir %s:", argv[i]);
            uint32_t cursor = 0;
            const char *name;
            size_t len;
            int is_dir;
            while (node >= 0 && dir && pak_romfs_dir_next(node, &cursor, &name, &len, &is_dir, &size))
                printf(" %.*s%s", (int)len, name, is_dir ? "/" : "");
            printf("\n");
            continue;
        }
        const int64_t size = pak_romfs_read(path, NULL, 0);
        if (size < 0) {
            printf("missing %s\n", argv[i]);
            continue;
        }
        char *buf = malloc(size ? (size_t)size : 1);
        if (!buf || pak_romfs_read(path, buf, (uint64_t)size) != size) return 4;
        char out[1200];
        snprintf(out, sizeof out, "%s/%d.bin", argv[3], i);
        FILE *f = fopen(out, "wb");
        if (!f || fwrite(buf, 1, (size_t)size, f) != (size_t)size) return 5;
        fclose(f);
        free(buf);
        printf("file %s %lld\n", argv[i], (long long)size);
    }
    printf("outside: %d %d\n", pak_romfs_path("/pak/romfsx/a"), pak_romfs_path("/app0/Data/a"));
    return 0;
}
