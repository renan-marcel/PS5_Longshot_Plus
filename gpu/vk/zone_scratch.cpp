#include "zone_scratch.h"

#include "compat/longshot_env.h"
#include "vk_internal.h"
#include "zone_boost.h"

#if !defined(_WIN32)
#include "mem_arena/scratch_arena.hpp"
#include "mem_arena/os_mem.hpp"

#include <algorithm>
#include <atomic>
#include <new>
#include <pthread.h>
#endif

namespace mkwvk {

bool zone_scratch_enabled() noexcept {
    static const bool enabled = env_on("LONGSHOT_ZONE_SCRATCH_ARENA");
    return enabled;
}

#if !defined(_WIN32)
namespace {

constexpr std::size_t kThreadArenaReserveBytes = 64ull * 1024 * 1024;
constexpr std::size_t kThreadArenaChunkBytes = 2ull * 1024 * 1024;
constexpr std::size_t kThreadArenaKeepWarmBytes = 4ull * 1024 * 1024;

struct ArenaNode {
    std::atomic<std::size_t> peak{0};
    ArenaNode* next = nullptr;
};

pthread_mutex_t g_registry_mu = PTHREAD_MUTEX_INITIALIZER;
ArenaNode* g_registry_head = nullptr;

std::atomic<uint64_t> g_decommit_epoch{0};
std::atomic<uint64_t> g_gpu_safe_val{0};
std::atomic<bool> g_init_failed{false};

struct ThreadScratch {
    mem_arena::ScratchArena arena;
    ArenaNode* node = nullptr;
    uint64_t local_epoch = 0;
    uint32_t active_scopes = 0;
    bool initialized = false;
    bool init_failed = false;

    ~ThreadScratch() {
        if (node) {
            pthread_mutex_lock(&g_registry_mu);
            ArenaNode** link = &g_registry_head;
            while (*link && *link != node) link = &(*link)->next;
            if (*link == node) *link = node->next;
            pthread_mutex_unlock(&g_registry_mu);
            delete node;
            node = nullptr;
        }
    }

    bool ensure_init() noexcept {
        if (initialized) return true;
        if (init_failed) return false;

        if (!arena.init(kThreadArenaReserveBytes, kThreadArenaChunkBytes)) {
            init_failed = true;
            g_init_failed.store(true, std::memory_order_relaxed);
            static std::atomic<int> logged{0};
            if (logged.fetch_add(1, std::memory_order_relaxed) < 8) {
                logf("vk: zone_scratch: ScratchArena::init(%zu) failed; falling back to heap",
                     kThreadArenaReserveBytes);
            }
            return false;
        }

        auto* n = new (std::nothrow) ArenaNode();
        if (n) {
            pthread_mutex_lock(&g_registry_mu);
            n->next = g_registry_head;
            g_registry_head = n;
            pthread_mutex_unlock(&g_registry_mu);
            node = n;
        }

        local_epoch = g_decommit_epoch.load(std::memory_order_acquire);
        initialized = true;
        return true;
    }

    void maybe_decommit(uint64_t completed_val) noexcept {
        if (!initialized || active_scopes != 0) return;
        const uint64_t epoch = g_decommit_epoch.load(std::memory_order_acquire);
        if (epoch == local_epoch) return;
        const uint64_t safe_val = g_gpu_safe_val.load(std::memory_order_acquire);
        if (completed_val < safe_val) return;
        if (arena.reset_and_decommit(kThreadArenaKeepWarmBytes)) {
            local_epoch = epoch;
        }
        if (node) {
            node->peak.store(arena.peak_bytes(), std::memory_order_relaxed);
        }
    }
};

// Track whether this thread has already created its ThreadScratch without
// forcing initialization when querying quiescent state.
thread_local ThreadScratch* g_tls_ptr = nullptr;

ThreadScratch& get_tls() noexcept {
    thread_local ThreadScratch tls;
    g_tls_ptr = &tls;
    return tls;
}

} // namespace

ZoneScratchScope::ZoneScratchScope() noexcept {
    if (!zone_scratch_enabled()) return;
    ThreadScratch& tls = get_tls();
    if (!tls.ensure_init()) return;
    mark_ = tls.arena.mark();
    tls.active_scopes++;
    state_ = &tls;
    active_ = true;
}

ZoneScratchScope::~ZoneScratchScope() {
    if (!active_) return;
    auto* tls = static_cast<ThreadScratch*>(state_);
    tls->arena.rewind(mark_);
    if (tls->node) {
        tls->node->peak.store(tls->arena.peak_bytes(), std::memory_order_relaxed);
    }
    if (tls->active_scopes > 0) tls->active_scopes--;
    if (tls->active_scopes == 0 &&
        g_decommit_epoch.load(std::memory_order_acquire) != tls->local_epoch) {
        tls->maybe_decommit(vk_timeline_completed());
    }
}

void* ZoneScratchScope::alloc(std::size_t size, std::size_t align) noexcept {
    if (!active_ || size == 0) return nullptr;
    auto* tls = static_cast<ThreadScratch*>(state_);
    void* p = tls->arena.alloc(size, align);
    if (!p) {
        static std::atomic<int> logged{0};
        if (logged.fetch_add(1, std::memory_order_relaxed) < 16) {
            logf("vk: zone_scratch: alloc(%zu, %zu) failed (used=%zu reserved=%zu); falling back to heap",
                 size, align, tls->arena.used_bytes(), tls->arena.reserved_bytes());
        }
    }
    return p;
}

void zone_scratch_on_present(uint64_t submitted_val, uint64_t completed_val) noexcept {
    if (!zone_scratch_enabled()) return;
    static int prev_boost = 0;
    const int cur_boost = zone_boost_active();
    if (prev_boost && !cur_boost) {
        g_gpu_safe_val.store(submitted_val, std::memory_order_release);
        g_decommit_epoch.fetch_add(1, std::memory_order_release);
    }
    prev_boost = cur_boost;
    zone_scratch_quiescent(completed_val);
}

void zone_scratch_quiescent(uint64_t completed_val) noexcept {
    if (!zone_scratch_enabled()) return;
    if (g_tls_ptr) g_tls_ptr->maybe_decommit(completed_val);
}

std::size_t zone_scratch_committed_bytes() noexcept {
    if (!zone_scratch_enabled()) return 0;
    return mem_arena::os_mem::total_committed_bytes();
}

std::size_t zone_scratch_reserved_bytes() noexcept {
    if (!zone_scratch_enabled()) return 0;
    return mem_arena::os_mem::total_reserved_bytes();
}

std::size_t zone_scratch_peak_bytes() noexcept {
    if (!zone_scratch_enabled()) return 0;
    std::size_t best = 0;
    pthread_mutex_lock(&g_registry_mu);
    for (ArenaNode* n = g_registry_head; n; n = n->next) {
        best = std::max(best, n->peak.load(std::memory_order_relaxed));
    }
    pthread_mutex_unlock(&g_registry_mu);
    return best;
}

bool zone_scratch_error() noexcept {
    return g_init_failed.load(std::memory_order_relaxed);
}

#else

ZoneScratchScope::ZoneScratchScope() noexcept = default;
ZoneScratchScope::~ZoneScratchScope() = default;
void* ZoneScratchScope::alloc(std::size_t, std::size_t) noexcept { return nullptr; }
void zone_scratch_on_present(uint64_t, uint64_t) noexcept {}
void zone_scratch_quiescent(uint64_t) noexcept {}
std::size_t zone_scratch_committed_bytes() noexcept { return 0; }
std::size_t zone_scratch_reserved_bytes() noexcept { return 0; }
std::size_t zone_scratch_peak_bytes() noexcept { return 0; }
bool zone_scratch_error() noexcept { return false; }

#endif

} // namespace mkwvk
