/* (longshot, PS5) the title folder's logs/ files (ps5_logfile.h). The title folder is the crash trace's folder's folder
   (host/ps5/win32_ps5.c hos_ps5_trace_path: <title>/logs/crash_trace.txt), as the break's report finds it. A handful of
   names, each opened once: nfp.txt (host/nn_nfp.c), memory.txt (win32_ps5.c), mods.txt (host/mods.c). */
#include "ps5_logfile.h"

#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

#ifndef PS5_LOGFILE_CAP
#define PS5_LOGFILE_CAP (1L << 20)   /* (1 MB a file: then one line saying so, and no more) */
#endif
#define FILES 8

const char *hos_ps5_trace_path(void);   /* (host/ps5/win32_ps5.c) */

static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static struct {
    char name[32];
    FILE *f;
    int state;   /* (1 open, 2 closed: none could be opened, or full) */
} files[FILES];

static FILE *open_one(const char *name) {
    const char *trace = hos_ps5_trace_path();
    const char *cut = trace ? strstr(trace, "/logs/crash_trace.txt") : NULL;
    char path[1024];
    const int n = cut ? snprintf(path, sizeof path, "%.*s/logs", (int)(cut - trace), trace) : -1;
    if (n <= 0 || (size_t)n + 1 + strlen(name) + 1 > sizeof path) return NULL;
    (void)mkdir(path, 0777);   /* (the logs/ folder, when it is not there yet) */
    snprintf(path + n, sizeof path - (size_t)n, "/%s", name);
    FILE *f = fopen(path, "a");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    if (ftell(f) >= PS5_LOGFILE_CAP) {   /* (full from the runs before: this run's lines start it over) */
        fclose(f);
        f = fopen(path, "w");
    }
    return f;
}

void hos_ps5_logfile(const char *name, const char *line) {
    if (!name || !line || strlen(name) >= sizeof files[0].name) return;
    pthread_mutex_lock(&mu);
    int i = 0;
    while (i < FILES && files[i].state && strcmp(files[i].name, name)) i++;
    if (i < FILES && !files[i].state) {
        snprintf(files[i].name, sizeof files[i].name, "%s", name);
        files[i].f = open_one(name);
        files[i].state = files[i].f ? 1 : 2;
    }
    if (i < FILES && files[i].state == 1) {
        FILE *f = files[i].f;
        fputs(line, f);
        fputc('\n', f);
        if (ftell(f) >= PS5_LOGFILE_CAP) {
            fprintf(f, "%s is full (%ld KB): no more lines in it this run (they are still in the log)\n", name,
                    (long)(PS5_LOGFILE_CAP >> 10));
            fclose(f);
            files[i].f = NULL;
            files[i].state = 2;
        } else {
            fflush(f);
        }
    }
    pthread_mutex_unlock(&mu);
}
