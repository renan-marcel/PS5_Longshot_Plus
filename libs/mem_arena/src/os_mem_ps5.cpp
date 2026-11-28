#include "mem_arena/os_mem.hpp"

#include <ps5platform/kernel.h>

#include <algorithm>
#include <atomic>
#include <cstdint>
#include <mutex>
#include <vector>

namespace mem_arena::os_mem {
namespace {

constexpr std::size_t kReserveAlign = 2ull * 1024 * 1024;
constexpr int kCpuRwProt = PS5_KERNEL_PROT_CPU_READ | PS5_KERNEL_PROT_CPU_WRITE;

struct Reservation {
    std::uintptr_t address;
    std::size_t reserved;
    std::size_t committed;
};

struct CommittedBlock {
    std::uintptr_t address;
    std::size_t size;
    int64_t phys_addr;
};

std::mutex g_mem_mutex;
std::vector<Reservation> g_reservations;
std::vector<CommittedBlock> g_blocks;
std::atomic<std::size_t> g_reserved_total{0};
std::atomic<std::size_t> g_committed_total{0};

bool valid_length(std::size_t bytes) noexcept {
    const std::size_t page = page_size();
    return bytes != 0 && page != 0 && bytes % page == 0;
}

Reservation* find_reservation(std::uintptr_t address) noexcept {
    for (Reservation& r : g_reservations) {
        if (address >= r.address && address - r.address < r.reserved) {
            return &r;
        }
    }
    return nullptr;
}

// PS5 sceKernelMunmap releases both the physical mapping and the virtual range,
// so decommitted slices must be re-reserved at their fixed address for reuse.
bool unmap_and_release_blocks(std::uintptr_t lo, std::uintptr_t hi, bool re_reserve) noexcept {
    for (std::size_t i = g_blocks.size(); i > 0;) {
        --i;
        const CommittedBlock b = g_blocks[i];
        const std::uintptr_t b_end = b.address + b.size;
        if (b.address < lo || b_end > hi) continue;

        void* place = reinterpret_cast<void*>(b.address);
        if (sceKernelMunmap(place, b.size) != 0) {
            return false;
        }
        sceKernelReleaseDirectMemory(b.phys_addr, b.size);
        if (re_reserve) {
            void* reserved = place;
            if (sceKernelReserveVirtualRange(&reserved, b.size, PS5_KERNEL_MAP_FIXED,
                                             PS5_KERNEL_DIRECT_ALIGNMENT) != 0 ||
                reserved != place) {
                return false;
            }
        }
        g_blocks.erase(g_blocks.begin() + static_cast<std::ptrdiff_t>(i));
    }
    return true;
}

} // namespace

std::size_t page_size() noexcept {
    return PS5_KERNEL_DIRECT_ALIGNMENT;
}

void* reserve(std::size_t bytes) noexcept {
    if (!valid_length(bytes)) return nullptr;

    const std::size_t align = bytes >= kReserveAlign ? kReserveAlign : PS5_KERNEL_DIRECT_ALIGNMENT;
    void* ptr = nullptr;
    if (sceKernelReserveVirtualRange(&ptr, bytes, 0, align) != 0 || ptr == nullptr) {
        return nullptr;
    }

    std::lock_guard<std::mutex> lock(g_mem_mutex);
    g_reservations.push_back({reinterpret_cast<std::uintptr_t>(ptr), bytes, 0});
    g_reserved_total.fetch_add(bytes, std::memory_order_relaxed);
    return ptr;
}

bool commit(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard<std::mutex> lock(g_mem_mutex);
    Reservation* res = find_reservation(address);
    if (!res || address - res->address != res->committed || bytes > res->reserved - res->committed) {
        return false;
    }

    int64_t phys_addr = 0;
    const int64_t total_dm = sceKernelGetDirectMemorySize();
    if (sceKernelAllocateDirectMemory(0, total_dm, bytes, PS5_KERNEL_DIRECT_ALIGNMENT,
                                      PS5_KERNEL_DIRECT_TYPE_CPU, &phys_addr) != 0) {
        return false;
    }

    void* place = ptr;
    if (sceKernelMapDirectMemory(&place, bytes, kCpuRwProt, PS5_KERNEL_MAP_FIXED,
                                 phys_addr, PS5_KERNEL_DIRECT_ALIGNMENT) != 0 ||
        place != ptr) {
        sceKernelReleaseDirectMemory(phys_addr, bytes);
        return false;
    }

    g_blocks.push_back({address, bytes, phys_addr});
    res->committed += bytes;
    g_committed_total.fetch_add(bytes, std::memory_order_relaxed);
    return true;
}

bool decommit(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard<std::mutex> lock(g_mem_mutex);
    Reservation* res = find_reservation(address);
    if (!res || bytes > res->committed || address - res->address != res->committed - bytes) {
        return false;
    }

    if (!unmap_and_release_blocks(address, address + bytes, true)) {
        return false;
    }

    res->committed -= bytes;
    g_committed_total.fetch_sub(bytes, std::memory_order_relaxed);
    return true;
}

bool release(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard<std::mutex> lock(g_mem_mutex);
    auto it = std::find_if(g_reservations.begin(), g_reservations.end(),
                           [address](const Reservation& r) { return r.address == address; });
    if (it == g_reservations.end() || it->reserved != bytes) {
        return false;
    }

    if (it->committed > 0) {
        if (!unmap_and_release_blocks(address, address + it->committed, true)) {
            return false;
        }
        g_committed_total.fetch_sub(it->committed, std::memory_order_relaxed);
    }

    if (sceKernelMunmap(ptr, bytes) != 0) {
        return false;
    }

    g_reserved_total.fetch_sub(bytes, std::memory_order_relaxed);
    g_reservations.erase(it);
    return true;
}

std::size_t total_reserved_bytes() noexcept {
    return g_reserved_total.load(std::memory_order_relaxed);
}

std::size_t total_committed_bytes() noexcept {
    return g_committed_total.load(std::memory_order_relaxed);
}

} // namespace mem_arena::os_mem
