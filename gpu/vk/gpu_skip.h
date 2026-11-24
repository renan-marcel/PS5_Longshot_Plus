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

inline bool contains(uint64_t key) {
    const int n = count.load(std::memory_order_acquire);
    for (int i = 0; i < n; i++)
        if (keys[i].load(std::memory_order_relaxed) == key) return true;
    return false;
}

/// false when it is there already, or the list is full
inline bool add(uint64_t key) {
    std::lock_guard lk(edit_mu);
    if (!key || contains(key)) return false;
    const int n = count.load(std::memory_order_relaxed);
    if (n >= kMax) return false;
    keys[n].store(key, std::memory_order_relaxed);
    count.store(n + 1, std::memory_order_release);
    return true;
}

/// every program drawn again (a draw already reading the old count may still leave one out: harmless)
inline void clear() {
    std::lock_guard lk(edit_mu);
    count.store(0, std::memory_order_release);
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
    for (const char* q = text; q && *q;) {
        while (*q == ',' || *q == ' ' || *q == '\t') q++;
        const char* e = q;
        while ((*e >= '0' && *e <= '9') || (*e >= 'a' && *e <= 'f') || (*e >= 'A' && *e <= 'F')) e++;
        if (e - q == 16) add(strtoull(std::string(q, 16).c_str(), nullptr, 16));
        while (*e && *e != ',' && *e != ' ' && *e != '\t') e++;   // (the rest of a malformed key)
        q = e;
    }
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
