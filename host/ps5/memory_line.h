/* (longshot, PS5) logs/memory.txt's lines and when they are written (host/ps5/win32_ps5.c memory_floor_watch): at each zone
   change, 5 s after it, every 60 s, and just before a memory floor exit. Rules only: tests/test_ps5_memory_log.py runs them.
   One line: t=<s> why=<zone|after|tick|floor> scene=<name> zone=<name> free_mb= largest_mb= committed_mb= prefetch_mb=
   zone_boost=, then the renderer's own key=value run (gpu/vk/vk_vma.cpp rx_vk_memory_stats). */
#ifndef HOS_PS5_MEMORY_LINE_H
#define HOS_PS5_MEMORY_LINE_H
#include <stdint.h>
#include <stdio.h>

#define MEM_TICK_MS 60000u
#define MEM_AFTER_MS 5000u

typedef struct {
    int started;
    uint64_t tick_at;    /* (the next "tick") */
    uint64_t after_at;   /* (the "after" line due, 0 none) */
} MemSched;
#define MEM_SCHED_INIT {0, 0, 0}

/* What is due at now_ms (any clock that does not go back), zone_changed: a zone change since the last call; NULL none */
static inline const char *mem_sched_due(MemSched *m, uint64_t now_ms, int zone_changed) {
    if (!m->started) {
        m->started = 1;
        m->tick_at = now_ms + MEM_TICK_MS;
        return "tick";
    }
    if (zone_changed) {
        m->after_at = now_ms + MEM_AFTER_MS;
        return "zone";
    }
    if (m->after_at && now_ms >= m->after_at) {
        m->after_at = 0;
        return "after";
    }
    if (now_ms >= m->tick_at) {
        m->tick_at = now_ms + MEM_TICK_MS;
        return "tick";
    }
    return NULL;
}

static inline int memory_line(char *out, size_t cap, double t_s, const char *why, const char *scene, const char *zone,
                              uint64_t free_mb, uint64_t largest_mb, uint64_t committed_mb, uint64_t prefetch_mb, int zone_boost,
                              const char *renderer) {
    return snprintf(out, cap, "t=%.1f why=%s scene=%s zone=%s free_mb=%llu largest_mb=%llu committed_mb=%llu prefetch_mb=%llu "
                    "zone_boost=%d%s%s", t_s, why, scene && scene[0] ? scene : "-", zone && zone[0] ? zone : "-",
                    (unsigned long long)free_mb, (unsigned long long)largest_mb, (unsigned long long)committed_mb,
                    (unsigned long long)prefetch_mb, zone_boost, renderer && renderer[0] ? " " : "", renderer ? renderer : "");
}
#endif
