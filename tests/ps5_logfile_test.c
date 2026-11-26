/* tests/test_ps5_logfile.py: host/ps5/ps5_logfile.c on the PC, its title folder a temp folder, its cap PS5_LOGFILE_CAP 1024 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "ps5_logfile.h"

static char title[1024], trace_path[2048];
const char *hos_ps5_trace_path(void) { return trace_path; }

static int failures;
#define CHECK(c, what) do { if (!(c)) { printf("FAIL: %s\n", what); failures++; } } while (0)

static size_t slurp(const char *name, char *out, size_t cap) {
    char path[2100];
    snprintf(path, sizeof path, "%s/logs/%s", title, name);
    FILE *f = fopen(path, "rb");
    if (!f) return (size_t)-1;
    size_t got = fread(out, 1, cap - 1, f);
    fclose(f);
    out[got] = 0;
    return got;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    snprintf(title, sizeof title, "%s", argv[1]);
    snprintf(trace_path, sizeof trace_path, "%s/logs/crash_trace.txt", title);
    char path[2100];
    /* a.txt already past the cap from an earlier run: this run starts it over */
    snprintf(path, sizeof path, "%s/logs", title);
    mkdir(path, 0777);
    snprintf(path, sizeof path, "%s/logs/a.txt", title);
    FILE *old = fopen(path, "wb");
    for (int i = 0; i < 2000; i++) fputc('x', old);
    fclose(old);

    hos_ps5_logfile("a.txt", "first a");
    hos_ps5_logfile("b.txt", "first b");
    hos_ps5_logfile("a.txt", "second a");
    char text[8192];
    CHECK(slurp("a.txt", text, sizeof text) != (size_t)-1, "a.txt written");
    CHECK(!strcmp(text, "first a\nsecond a\n"), "a.txt started over, its lines in order, flushed at once");
    CHECK(slurp("b.txt", text, sizeof text) != (size_t)-1 && !strcmp(text, "first b\n"), "b.txt is a file of its own");

    char line[64];
    for (int i = 0; i < 200; i++) {
        snprintf(line, sizeof line, "line %03d of b", i);
        hos_ps5_logfile("b.txt", line);
    }
    size_t got = slurp("b.txt", text, sizeof text);
    CHECK(got >= 1024 && got < 1024 + 200, "b.txt stops at its cap");
    const char *full = strstr(text, "b.txt is full");
    const char *end = full ? strchr(full, '\n') : NULL;
    CHECK(end && !end[1], "one last line says b.txt is full, none after");
    hos_ps5_logfile("a.txt", "third a");
    CHECK(slurp("a.txt", text, sizeof text) != (size_t)-1 && strstr(text, "third a\n"), "a full b.txt leaves a.txt going");

    /* no title folder known: nothing written, no crash */
    trace_path[0] = 0;
    hos_ps5_logfile("c.txt", "nowhere");
    CHECK(slurp("c.txt", text, sizeof text) == (size_t)-1, "without the title folder no file is made");
    if (failures) return 1;
    printf("ok\n");
    return 0;
}
