/* (longshot) The game's available-memory graph (vk_fps.cpp samples, vk_menu.cpp draws): fixed-size, time-bounded history.
   No allocations on the present path; tests/test_memory_graph.py checks the window and extrema. */
#pragma once

#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <cstdio>

namespace mkwvk::memory_graph_stats {

constexpr int64_t kSampleNs = 250'000'000;
constexpr int64_t kWindowNs = 60'000'000'000;
constexpr int kCapacity = (int)(kWindowNs / kSampleNs) + 1;

struct Sample {
    int64_t at_ns = 0;
    uint64_t used = 0;
    uint64_t total = 0;
};

struct Summary {
    Sample current{};
    uint64_t min_used = 0;
    uint64_t max_used = 0;
    int count = 0;
};

class Ring {
public:
    void clear() { next_ = 0, size_ = 0; }

    void push(int64_t at_ns, uint64_t used, uint64_t total) {
        if (!total) return;
        samples_[next_] = {at_ns, std::min(used, total), total};
        next_ = (next_ + 1) % kCapacity;
        size_ = std::min(size_ + 1, kCapacity);
    }

    /// Copy valid samples oldest first and summarize the extrema over the same visible time window.
    Summary copy(int64_t now_ns, Sample* out, int max_out) const {
        Summary result{};
        const int oldest = (next_ + kCapacity - size_) % kCapacity;
        const int64_t cutoff = now_ns > kWindowNs ? now_ns - kWindowNs : 0;
        int copied = 0;
        for (int i = 0; i < size_; i++) {
            const Sample& s = samples_[(oldest + i) % kCapacity];
            if (s.at_ns < cutoff || s.at_ns > now_ns) continue;
            if (!result.count || s.at_ns >= result.current.at_ns) result.current = s;
            if (!result.count) result.min_used = result.max_used = s.used;
            else result.min_used = std::min(result.min_used, s.used), result.max_used = std::max(result.max_used, s.used);
            result.count++;
            if (out && copied < max_out) out[copied++] = s;
        }
        return result;
    }

private:
    Sample samples_[kCapacity]{};
    int next_ = 0;
    int size_ = 0;
};

inline int text(char* out, size_t cap, uint64_t bytes) {
    constexpr uint64_t gb = 1024ull * 1024 * 1024;
    return bytes >= gb ? snprintf(out, cap, "%.1f GB", bytes / (double)gb)
                       : snprintf(out, cap, "%.0f MB", bytes / (1024.0 * 1024.0));
}

} // namespace mkwvk::memory_graph_stats
