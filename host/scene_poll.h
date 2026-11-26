/* (longshot) The scene the game is in, polled (host/hos_main.c hos_ps5_scene_poll, on the PS5): at most one read every
   SCENE_POLL_MS, and a change only for a name that is not empty and not the last one seen. Rules only, no game:
   tests/test_ps5_scene.py runs them. */
#ifndef HOS_SCENE_POLL_H
#define HOS_SCENE_POLL_H
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define SCENE_POLL_MS 500

typedef struct {
    uint64_t last_ms;   /* (when the last read was let through; 0 before the first) */
    int read_once;
    char last[128];     /* (the last scene seen, "" before the first) */
} ScenePoll;
#define SCENE_POLL_INIT {0, 0, ""}

/* Whether a read is due now (now_ms from any clock that does not go back); a yes counts as the read */
static inline int scene_poll_due(ScenePoll *p, uint64_t now_ms) {
    if (p->read_once && now_ms - p->last_ms < SCENE_POLL_MS) return 0;
    p->read_once = 1;
    p->last_ms = now_ms;
    return 1;
}

/* Whether name is a new scene; a yes keeps it as the last one seen */
static inline int scene_poll_changed(ScenePoll *p, const char *name) {
    if (!name || !name[0] || !strcmp(name, p->last)) return 0;
    snprintf(p->last, sizeof p->last, "%s", name);
    return 1;
}
#endif
