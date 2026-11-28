#pragma once

#include <cstddef>
#include <cstdint>
#include <cstring>
#include <limits>
#include <type_traits>
#include <vector>

namespace mkwvk {

/// True when LONGSHOT_ZONE_SCRATCH_ARENA is enabled (default 0 / false).
bool zone_scratch_enabled() noexcept;

/// Called once per present on the replay thread to detect zone_boost 1 -> 0
/// transitions and schedule epoch-synchronized reset_and_decommit(4 MiB).
void zone_scratch_on_present(uint64_t submitted_val, uint64_t completed_val) noexcept;

/// Called at top-level quiescent points on persistent worker threads so idle
/// thread-local arenas decommit once the GPU passes the transition timeline value.
void zone_scratch_quiescent(uint64_t completed_val) noexcept;

/// Process-wide ScratchArena telemetry for logs/memory.txt.
std::size_t zone_scratch_committed_bytes() noexcept;
std::size_t zone_scratch_reserved_bytes() noexcept;
std::size_t zone_scratch_peak_bytes() noexcept;
bool zone_scratch_error() noexcept;

/// RAII scope over the calling thread's ScratchArena when LONGSHOT_ZONE_SCRATCH_ARENA=1.
/// When disabled (0), this is a zero-cost no-op and alloc_array() returns nullptr silently.
class ZoneScratchScope {
public:
    ZoneScratchScope() noexcept;
    ~ZoneScratchScope();

    ZoneScratchScope(const ZoneScratchScope&) = delete;
    ZoneScratchScope& operator=(const ZoneScratchScope&) = delete;
    ZoneScratchScope(ZoneScratchScope&&) = delete;
    ZoneScratchScope& operator=(ZoneScratchScope&&) = delete;

    void* alloc(std::size_t size, std::size_t align) noexcept;

    template<typename T>
    T* alloc_array(std::size_t count) noexcept {
        static_assert(std::is_trivially_destructible_v<T>);
        if (count == 0) return nullptr;
        if (count > std::numeric_limits<std::size_t>::max() / sizeof(T)) return nullptr;
        return static_cast<T*>(alloc(count * sizeof(T), alignof(T)));
    }

    bool active() const noexcept { return active_; }

private:
    void* state_ = nullptr;
    std::size_t mark_ = 0;
    bool active_ = false;
};

/// Ephemeral typed buffer backed by ZoneScratchScope when enabled, falling back
/// to std::vector<T> when disabled or when the arena allocation returns nullptr.
/// Must be declared *after* its ZoneScratchScope so it unwinds before the scope.
template<typename T>
struct ScratchBuf {
    static_assert(std::is_trivially_destructible_v<T>);

    T* ptr = nullptr;
    std::size_t count = 0;
    std::vector<T> fallback;

    void resize(ZoneScratchScope& scope, std::size_t n) {
        ptr = nullptr;
        count = n;
        fallback.clear();
        if (n == 0) return;
        if (T* p = scope.alloc_array<T>(n)) {
            ptr = p;
            return;
        }
        fallback.resize(n);
        ptr = fallback.data();
    }

    void assign_zero(ZoneScratchScope& scope, std::size_t n) {
        ptr = nullptr;
        count = n;
        fallback.clear();
        if (n == 0) return;
        if (T* p = scope.alloc_array<T>(n)) {
            std::memset(p, 0, n * sizeof(T));
            ptr = p;
            return;
        }
        fallback.assign(n, T{});
        ptr = fallback.data();
    }

    T* data() noexcept { return ptr; }
    const T* data() const noexcept { return ptr; }
    std::size_t size() const noexcept { return count; }
    bool empty() const noexcept { return count == 0; }
    T& operator[](std::size_t i) noexcept { return ptr[i]; }
    const T& operator[](std::size_t i) const noexcept { return ptr[i]; }
};

} // namespace mkwvk
