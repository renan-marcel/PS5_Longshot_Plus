#pragma once
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

static inline uint64_t zone_now_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000ULL + (uint64_t)(ts.tv_nsec / 1000000ULL);
}

__attribute__((weak)) volatile uint64_t g_zone_boost_until_ms = 0;
__attribute__((weak)) volatile uint64_t g_last_draw_key = 0;
__attribute__((weak)) volatile uint64_t g_last_stage0_key = 0;
__attribute__((weak)) volatile uint64_t g_last_stage1_key = 0;
__attribute__((weak)) volatile uint64_t g_last_gfx_key = 0;
__attribute__((weak)) volatile uint64_t g_last_gfx_stage0 = 0;
__attribute__((weak)) volatile uint64_t g_last_gfx_stage1 = 0;
__attribute__((weak)) volatile uint64_t g_last_cs_key = 0;
__attribute__((weak)) volatile int64_t  g_last_present_seen = 0;
__attribute__((weak)) volatile uint64_t g_ps5_free_mem_mb = 0;
__attribute__((weak)) volatile int      g_zone_boost_mem_hold = 0;

/* (longshot) the shader probe's last line (vk_draw.cpp probe_dispatch, RX_VK_PROBE_PROG and the last freeze's program): what
   the last watched dispatch was given, written before each one; the PS5's watchdog copies it into logs/crash_trace.txt when
   the GPU stops presenting (host/ps5/win32_ps5.c memory_floor_watch). A sequence count, odd while it is written, so a copy
   never takes half of one line and half of the next */
#define ZONE_PROBE_LINE 3072
__attribute__((weak)) char g_probe_line[ZONE_PROBE_LINE];
__attribute__((weak)) volatile uint32_t g_probe_seq = 0;

static inline void zone_probe_publish(const char *line) {
    __atomic_fetch_add(&g_probe_seq, 1, __ATOMIC_ACQ_REL);   /* (odd: being written) */
    size_t n = strlen(line);
    if (n >= ZONE_PROBE_LINE) n = ZONE_PROBE_LINE - 1;
    for (size_t i = 0; i < n; i++) __atomic_store_n(&g_probe_line[i], line[i], __ATOMIC_RELAXED);
    __atomic_store_n(&g_probe_line[n], 0, __ATOMIC_RELAXED);
    __atomic_fetch_add(&g_probe_seq, 1, __ATOMIC_ACQ_REL);   /* (even: whole) */
}

/* 1 with the last whole line in out (cap bytes), 0 when there is none or it kept changing */
static inline int zone_probe_take(char *out, size_t cap) {
    for (int tries = 0; tries < 8; tries++) {
        const uint32_t a = __atomic_load_n(&g_probe_seq, __ATOMIC_ACQUIRE);
        if (!a || (a & 1)) continue;
        size_t i = 0;
        for (; i + 1 < cap && i < ZONE_PROBE_LINE; i++)
            if (!(out[i] = __atomic_load_n(&g_probe_line[i], __ATOMIC_RELAXED))) break;
        out[i] = 0;
        if (__atomic_load_n(&g_probe_seq, __ATOMIC_ACQUIRE) == a) return out[0] != 0;
    }
    return 0;
}

static inline void zone_boost_trigger(void) {
    const char *sec_env = getenv("RX_VK_ZONE_BOOST_SEC");
    int sec = sec_env ? atoi(sec_env) : 90;
    if (sec <= 0) return;
    uint64_t target = zone_now_ms() + (uint64_t)sec * 1000ULL;
    uint64_t cur = __atomic_load_n(&g_zone_boost_until_ms, __ATOMIC_RELAXED);
    if (target > cur) {
        __atomic_store_n(&g_zone_boost_until_ms, target, __ATOMIC_RELAXED);
    }
}

static inline void zone_boost_update_mem(uint64_t free_mb, uint64_t floor_mb) {
    __atomic_store_n(&g_ps5_free_mem_mb, free_mb, __ATOMIC_RELAXED);
    if (free_mb < floor_mb + 2200ULL) {
        __atomic_store_n(&g_zone_boost_mem_hold, 1, __ATOMIC_RELAXED);
        zone_boost_trigger();
    } else if (free_mb >= floor_mb + 2900ULL) {
        __atomic_store_n(&g_zone_boost_mem_hold, 0, __ATOMIC_RELAXED);
    }
}

static inline int zone_boost_active(void) {
    uint64_t until = __atomic_load_n(&g_zone_boost_until_ms, __ATOMIC_RELAXED);
    int hold = __atomic_load_n(&g_zone_boost_mem_hold, __ATOMIC_RELAXED);
    if (until != 0) {
        if (zone_now_ms() < until) return 1;
        __atomic_store_n(&g_zone_boost_until_ms, 0, __ATOMIC_RELAXED);
    }
    return hold ? 1 : 0;
}

#ifdef __cplusplus
}
#endif
