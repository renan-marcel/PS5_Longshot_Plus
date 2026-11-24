#pragma once
// (longshot) Shaders the player left out from the Debug tab's GPU freeze shader row (gpu/vk/vk_menu.cpp): their programs'
// draws and dispatches are not recorded (vk_draw.cpp draw, dispatch), so a game whose GPU stops on one goes on past the place
// it stopped, without what that program draws or computes there. Saved in longshot_options.ini as gpu_skip=<key>,<key>.
//
// The suspect is the program the PS5's watchdog named when the GPU last stopped presenting for 2 s (host/ps5/win32_ps5.c
// memory_floor_watch: the last GPU_FREEZE_2S line in logs/crash_trace.txt, its prog_key and is_compute).
//
// The list is read on every draw and dispatch and changed from the menu: a fixed array of atomics, no lock to read.
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

namespace gpu_skip {

constexpr int kMax = 32;
inline std::atomic<uint64_t> keys[kMax];
inline std::atomic<int> count{0};
inline std::mutex edit_mu;

/// The builder's list (ps5/builder/known_gpu_hangs.txt, written into longshot_env.txt as RX_VK_GPU_SKIP=<key>,...): the
/// shaders known to hang the GPU, left out from the start of every run. Read once, never changed after; not written to the
/// ini, so the line taken out of longshot_env.txt draws them again. keys_in parses the same text as from_text
inline std::vector<uint64_t> keys_in(const char* text) {
    std::vector<uint64_t> out;
    for (const char* q = text; q && *q;) {
        while (*q == ',' || *q == ' ' || *q == '\t') q++;
        const char* e = q;
        while ((*e >= '0' && *e <= '9') || (*e >= 'a' && *e <= 'f') || (*e >= 'A' && *e <= 'F')) e++;
        if (e - q == 16) {
            const uint64_t k = strtoull(std::string(q, 16).c_str(), nullptr, 16);
            bool seen = !k;
            for (const uint64_t o : out) seen |= o == k;
            if (!seen) out.push_back(k);
        }
        while (*e && *e != ',' && *e != ' ' && *e != '\t') e++;   // (the rest of a malformed key)
        q = e;
    }
    return out;
}
inline const std::vector<uint64_t>& from_build() {
    static const std::vector<uint64_t> list = keys_in(getenv("RX_VK_GPU_SKIP"));
    return list;
}
/// (the Skipped shaders row's Enter: the builder's list drawn again too, for this run)
inline std::atomic<bool> build_off{false};
inline bool from_build_has(uint64_t key) {
    if (build_off.load(std::memory_order_relaxed)) return false;
    for (const uint64_t k : from_build())
        if (k == key) return true;
    return false;
}

/// (the player's list only: the one add, clear and the ini work on)
inline bool mine_has(uint64_t key) {
    const int n = count.load(std::memory_order_acquire);
    for (int i = 0; i < n; i++)
        if (keys[i].load(std::memory_order_relaxed) == key) return true;
    return false;
}

inline bool contains(uint64_t key) { return mine_has(key) || from_build_has(key); }

/// false when the player's list has it already, or is full
inline bool add(uint64_t key) {
    std::lock_guard lk(edit_mu);
    if (!key || mine_has(key)) return false;
    const int n = count.load(std::memory_order_relaxed);
    if (n >= kMax) return false;
    keys[n].store(key, std::memory_order_relaxed);
    count.store(n + 1, std::memory_order_release);
    return true;
}

/// The player's own list emptied (a draw already reading the old count may still leave one out: harmless)
inline void clear() {
    std::lock_guard lk(edit_mu);
    count.store(0, std::memory_order_release);
}

/// (the Skipped shaders row's Enter) every program drawn again: the player's list emptied and saved so, the builder's
/// left aside until the next start
inline void restore_all() {
    clear();
    build_off.store(true, std::memory_order_relaxed);
}

/// How many are left out now: the player's and the builder's
inline int total() {
    int n = count.load(std::memory_order_acquire);
    if (!build_off.load(std::memory_order_relaxed))
        for (const uint64_t k : from_build()) {
            bool mine = false;
            for (int i = 0, m = count.load(std::memory_order_acquire); i < m; i++)
                mine |= keys[i].load(std::memory_order_relaxed) == k;
            n += !mine;
        }
    return n;
}

inline std::vector<uint64_t> list() {
    std::vector<uint64_t> out;
    const int n = count.load(std::memory_order_acquire);
    for (int i = 0; i < n; i++) out.push_back(keys[i].load(std::memory_order_relaxed));
    return out;
}

/// "53fcaee4dc45c6ee,0123456789abcdef": the ini's gpu_skip= value
inline std::string to_text() {
    std::string out;
    char hex[20];
    for (const uint64_t k : list()) {
        snprintf(hex, sizeof hex, "%016llx", (unsigned long long)k);
        if (!out.empty()) out += ',';
        out += hex;
    }
    return out;
}

/// the ini's value: keys of 16 hex digits, separated by commas or spaces; anything else is passed over
inline void from_text(const char* text) {
    clear();
    for (const uint64_t k : keys_in(text)) add(k);
}

/// (the Skipped shaders row's line) every key left out now, the builder's marked so: "53fcaee4dc45c6ee (build), ..."
inline std::string describe() {
    std::string out;
    char hex[20];
    const std::vector<uint64_t> mine = list();
    const auto put = [&](uint64_t k, const char* tag) {
        snprintf(hex, sizeof hex, "%016llx", (unsigned long long)k);
        if (!out.empty()) out += ", ";
        out += hex;
        out += tag;
    };
    for (const uint64_t k : mine) put(k, "");
    if (!build_off.load(std::memory_order_relaxed))
        for (const uint64_t k : from_build()) {
            bool listed = false;
            for (const uint64_t m : mine) listed |= m == k;
            if (!listed) put(k, " (build)");
        }
    return out;
}

/// The program the GPU was running when it last stopped presenting, in a run before this one
struct Freeze {
    bool found = false;
    uint64_t key = 0;
    bool compute = false;
    long long present = 0;   // (the frame it stopped at)
};

/// From crash_trace.txt's text: its last GPU_FREEZE_2S line, whatever came after it (the restarts of the runs after a freeze
/// that ended one: BOOT_WATCHDOG_ACTIVE lines, the first start's restarts among them)
inline Freeze last_freeze(const std::string& trace) {
    std::vector<std::string> lines;
    for (size_t at = 0; at < trace.size();) {
        const size_t end = trace.find('\n', at);
        lines.push_back(trace.substr(at, end == std::string::npos ? std::string::npos : end - at));
        at = end == std::string::npos ? trace.size() : end + 1;
    }
    Freeze f;
    for (size_t i = lines.size(); i-- > 0;) {
        const std::string& l = lines[i];
        if (l.find("GPU_FREEZE_2S") == std::string::npos) continue;
        const size_t k = l.find("prog_key="), c = l.find("is_compute="), p = l.find("present=");
        if (k == std::string::npos || l.size() < k + 9 + 16) continue;
        f.key = strtoull(l.substr(k + 9, 16).c_str(), nullptr, 16);
        f.compute = c != std::string::npos && l.size() > c + 11 && l[c + 11] == '1';
        f.present = p != std::string::npos ? atoll(l.c_str() + p + 8) : 0;
        f.found = f.key != 0;
        break;
    }
    return f;
}

}   // namespace gpu_skip
