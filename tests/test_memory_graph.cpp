#include "../gpu/vk/memory_stats.h"

#include <cstdio>
#include <cstring>

using namespace mkwvk::memory_graph_stats;

#define CHECK(name, condition) do { if (!(condition)) { std::fprintf(stderr, "FAIL %s at line %d\n", name, __LINE__); return 1; } } while (0)

int main() {
    Ring ring;
    Sample samples[kCapacity]{};
    Summary s = ring.copy(1'000'000'000, samples, kCapacity);
    CHECK("empty history", s.count == 0);

    ring.push(1'000'000'000, 40, 100);
    ring.push(1'250'000'000, 60, 100);
    ring.push(1'500'000'000, 200, 100);   // (clamped to the game's total)
    s = ring.copy(1'500'000'000, samples, kCapacity);
    CHECK("visible count", s.count == 3);
    CHECK("chronological samples", samples[0].used == 40 && samples[1].used == 60 && samples[2].used == 100);
    CHECK("current sample", s.current.at_ns == 1'500'000'000 && s.current.used == 100 && s.current.total == 100);
    CHECK("window extrema", s.min_used == 40 && s.max_used == 100);

    s = ring.copy(kWindowNs + 1'250'000'000, samples, kCapacity);
    CHECK("old samples expire at window boundary", s.count == 2 && samples[0].at_ns == 1'250'000'000);

    char formatted[24];
    text(formatted, sizeof formatted, 3ull * 1024 * 1024 * 1024 + 512ull * 1024 * 1024);
    CHECK("memory units", !std::strcmp(formatted, "3.5 GB"));
    ring.clear();
    CHECK("disable clears the history", ring.copy(2'000'000'000, samples, kCapacity).count == 0);
    return 0;
}
