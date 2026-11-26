/* PS5: when the title breaks, a report in bug-reports/ of the title folder, as the Bug report row of the menu writes one
   (gpu/vk/vk_bug_report.h) but made at the moment of the break, from what is still in memory:

     bug-reports/<UTC date>_<UTC time>_<kind>/      kind: crash (a fault, a trap of the game's code, the memory floor) or
       report.txt                                   freeze (the GPU stopped for 2 s), one of each kind at most per run
       log.txt          the last 64 KB of this run's log (the console keeps no log file: host/hos_thread.c hands each batch
                        it writes to hos_ps5_log_keep)
       longshot_env.txt, longshot_options.ini, crash_trace.txt   copies, when there

   Called on the failing thread, in a signal handler or on the way out: no allocation, fixed buffers, open/read/write, and
   snprintf (as the crash trace beside it already uses). Nothing is sent anywhere. host/ps5/win32_ps5.c gathers the facts
   and calls it (hos_ps5_bug_report); tests/test_ps5_bug_report.py runs it on the PC. */
#include "ps5_bug_report.h"

#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define KEEP_CAP (64u * 1024u)
static char keep_ring[KEEP_CAP];
static size_t keep_total;   /* (bytes ever kept: the ring's next byte is keep_total % KEEP_CAP) */

/* (every thread that logs keeps its lines: host/hos_thread.c hos_vlog. A spin lock, held for one short copy, so lines stay whole;
   the report's reader, which may run in a signal handler on a thread that holds it, tries it a while and reads anyway) */
static int keep_lock;
static int keep_try(long spins) {
    for (long i = 0; spins < 0 || i < spins; i++)
        if (!__atomic_exchange_n(&keep_lock, 1, __ATOMIC_ACQUIRE)) return 1;
    return 0;
}
static void keep_unlock(void) { __atomic_store_n(&keep_lock, 0, __ATOMIC_RELEASE); }

void hos_ps5_log_keep(const char *s, size_t n) {
    if (!s) return;
    if (n >= KEEP_CAP) s += n - KEEP_CAP, n = KEEP_CAP;
    keep_try(-1);
    const size_t total = __atomic_load_n(&keep_total, __ATOMIC_RELAXED);
    const size_t at = total % KEEP_CAP, first = n < KEEP_CAP - at ? n : KEEP_CAP - at;
    memcpy(keep_ring + at, s, first);
    memcpy(keep_ring, s + first, n - first);
    __atomic_store_n(&keep_total, total + n, __ATOMIC_RELEASE);
    keep_unlock();
}

static int write_all(int fd, const char *p, size_t n) {
    while (n) {
        const ssize_t w = write(fd, p, n);
        if (w < 0 && errno == EINTR) continue;
        if (w <= 0) return 0;
        p += w, n -= (size_t)w;
    }
    return 1;
}

static void put_file(const char *dir, const char *name, const char *text, size_t n) {
    char path[1024];
    if (snprintf(path, sizeof path, "%s/%s", dir, name) >= (int)sizeof path) return;
    const int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd < 0) return;
    (void)write_all(fd, text, n);
    fsync(fd);
    close(fd);
}

static void copy_file(const char *from, const char *dir, const char *name) {
    static char buf[16384];
    char path[1024];
    const int in = open(from, O_RDONLY);
    if (in < 0) return;
    if (snprintf(path, sizeof path, "%s/%s", dir, name) >= (int)sizeof path) { close(in); return; }
    const int out = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (out >= 0) {
        for (;;) {
            const ssize_t r = read(in, buf, sizeof buf);
            if (r < 0 && errno == EINTR) continue;
            if (r <= 0 || !write_all(out, buf, (size_t)r)) break;
        }
        fsync(out);
        close(out);
    }
    close(in);
}

int hos_ps5_bug_report_write(const char *title_dir, const char *kind, const char *reason, const char *detail,
                             const char *facts, char *made, size_t made_cap) {
    static char dir[1024], text[8192];
    if (!title_dir || !title_dir[0] || !kind || !reason) return 0;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm t;
    gmtime_r(&ts.tv_sec, &t);
    char root[1024];
    if (snprintf(root, sizeof root, "%s/bug-reports", title_dir) >= (int)sizeof root) return 0;
    mkdir(root, 0777);
    int made_ok = 0;
    for (int n = 0; n < 10 && !made_ok; n++) {   /* (two of one kind in the same second: _2, _3...) */
        int len = snprintf(dir, sizeof dir, "%s/%04d-%02d-%02d_%02d-%02d-%02d_%s", root, t.tm_year + 1900, t.tm_mon + 1, t.tm_mday,
                           t.tm_hour, t.tm_min, t.tm_sec, kind);
        if (n && len > 0) len += snprintf(dir + len, sizeof dir - (size_t)len, "_%d", n + 1);
        if (len <= 0 || len >= (int)sizeof dir) return 0;
        made_ok = mkdir(dir, 0777) == 0;
        if (!made_ok && errno != EEXIST) return 0;
    }
    if (!made_ok) return 0;

    const int n = snprintf(text, sizeof text,
        "Longshot on the PS5: the title broke (%s)\n"
        "Written at the moment it broke, in bug-reports/ of the title folder (host/ps5/ps5_bug_report.c). Attach this folder\n"
        "to an issue; nothing in it was sent anywhere.\n\n"
        "### What happened\n%s%s%s\n\n"
        "### When (UTC)\n%04d-%02d-%02d %02d:%02d:%02d\n\n"
        "### What the title knew\n%s\n"
        "### Beside this file\n"
        "log.txt: the last 64 KB of this run's log. longshot_env.txt, longshot_options.ini, crash_trace.txt: copies, when there.\n",
        kind, reason, detail && detail[0] ? ": " : "", detail ? detail : "", t.tm_year + 1900, t.tm_mon + 1, t.tm_mday, t.tm_hour,
        t.tm_min, t.tm_sec, facts ? facts : "");
    put_file(dir, "report.txt", text, n < 0 ? 0 : (size_t)n < sizeof text ? (size_t)n : sizeof text - 1);

    /* the log's last bytes, oldest first, from the start of a line */
    const int locked = keep_try(1000000);   /* (not held for good: a thread stopped inside keep, the bytes are read as they are) */
    const size_t total = __atomic_load_n(&keep_total, __ATOMIC_ACQUIRE);
    const size_t have = total < KEEP_CAP ? total : KEEP_CAP, start = total < KEEP_CAP ? 0 : total % KEEP_CAP;
    static char log[KEEP_CAP];
    for (size_t i = 0; i < have; i++) log[i] = keep_ring[(start + i) % KEEP_CAP];
    if (locked) keep_unlock();
    size_t from = 0;
    if (total > KEEP_CAP)
        while (from < have && log[from++] != '\n') {}
    put_file(dir, "log.txt", log + from, have - from);

    char src[1024];
    if (snprintf(src, sizeof src, "%s/longshot_env.txt", title_dir) < (int)sizeof src) copy_file(src, dir, "longshot_env.txt");
    if (snprintf(src, sizeof src, "%s/longshot_options.ini", title_dir) < (int)sizeof src) copy_file(src, dir, "longshot_options.ini");
    if (snprintf(src, sizeof src, "%s/logs/crash_trace.txt", title_dir) < (int)sizeof src) copy_file(src, dir, "crash_trace.txt");
    if (made && made_cap) snprintf(made, made_cap, "%s", dir);
    return 1;
}
