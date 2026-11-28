#include "mem_arena/os_mem.hpp"

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <mutex>
#include <new>

#include <pthread.h>
#include <sys/mman.h>
#include <unistd.h>

namespace mem_arena::os_mem {
namespace {

struct Reservation {
    std::uintptr_t address;
    std::size_t reserved;
    std::size_t committed;
    Reservation* next;
};

// A statically initialized POSIX mutex remains usable during arena teardown.
struct ReservationsMutex {
    pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

    void lock() noexcept {
        if (pthread_mutex_lock(&mutex) != 0) std::abort();
    }

    void unlock() noexcept {
        if (pthread_mutex_unlock(&mutex) != 0) std::abort();
    }
};

constinit ReservationsMutex reservations_mutex;
constinit Reservation* reservations = nullptr;
constinit std::atomic<std::size_t> reserved_total{0};
constinit std::atomic<std::size_t> committed_total{0};

bool valid_length(std::size_t bytes) noexcept {
    const auto page = page_size();
    return bytes != 0 && page != 0 && bytes % page == 0;
}

// Only OS operations look up a reservation. Bump allocations within an
// arena's committed prefix bypass this list and lock.
Reservation* find_reservation(std::uintptr_t address) noexcept {
    for (auto* node = reservations; node; node = node->next) {
        if (address >= node->address && address - node->address < node->reserved) return node;
    }
    return nullptr;
}

bool discard(void* ptr, std::size_t bytes) noexcept {
    if (mmap(ptr, bytes, PROT_NONE, MAP_PRIVATE | MAP_ANON | MAP_FIXED, -1, 0) != MAP_FAILED)
        return true;

#ifdef MADV_FREE
    // Some systems cannot replace this mapping. MADV_FREE allows lazy reclaim
    // and can leave its old contents visible if the pages are recommitted soon.
    return madvise(ptr, bytes, MADV_FREE) == 0 && mprotect(ptr, bytes, PROT_NONE) == 0;
#else
    return false;
#endif
}

} // namespace

std::size_t page_size() noexcept {
    static const std::size_t page = [] {
        const long bytes = sysconf(_SC_PAGESIZE);
        return bytes > 0 ? static_cast<std::size_t>(bytes) : std::size_t{0};
    }();
    return page;
}

void* reserve(std::size_t bytes) noexcept {
    if (!valid_length(bytes)) return nullptr;
    auto* node = new (std::nothrow) Reservation;
    if (!node) return nullptr;

    void* ptr = mmap(nullptr, bytes, PROT_NONE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (!ptr || ptr == MAP_FAILED) {
        if (ptr == nullptr) munmap(ptr, bytes);
        delete node;
        return nullptr;
    }

    std::lock_guard lock(reservations_mutex);
    *node = {reinterpret_cast<std::uintptr_t>(ptr), bytes, 0, reservations};
    reservations = node;
    reserved_total.fetch_add(bytes, std::memory_order_relaxed);
    return ptr;
}

bool commit(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard lock(reservations_mutex);
    auto* node = find_reservation(address);
    if (!node || address - node->address != node->committed || bytes > node->reserved - node->committed)
        return false;
    if (mprotect(ptr, bytes, PROT_READ | PROT_WRITE) != 0) return false;

    node->committed += bytes;
    committed_total.fetch_add(bytes, std::memory_order_relaxed);
    return true;
}

bool decommit(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard lock(reservations_mutex);
    auto* node = find_reservation(address);
    if (!node || bytes > node->committed || address - node->address != node->committed - bytes)
        return false;
    if (!discard(ptr, bytes)) return false;

    node->committed -= bytes;
    committed_total.fetch_sub(bytes, std::memory_order_relaxed);
    return true;
}

bool release(void* ptr, std::size_t bytes) noexcept {
    if (!ptr || !valid_length(bytes)) return false;

    const auto address = reinterpret_cast<std::uintptr_t>(ptr);
    std::lock_guard lock(reservations_mutex);
    auto** link = &reservations;
    while (*link && (*link)->address != address) link = &(*link)->next;
    auto* node = *link;
    if (!node || node->reserved != bytes) return false;
    if (munmap(ptr, bytes) != 0) return false;

    committed_total.fetch_sub(node->committed, std::memory_order_relaxed);
    reserved_total.fetch_sub(bytes, std::memory_order_relaxed);
    *link = node->next;
    delete node;
    return true;
}

std::size_t total_reserved_bytes() noexcept {
    return reserved_total.load(std::memory_order_relaxed);
}

std::size_t total_committed_bytes() noexcept {
    return committed_total.load(std::memory_order_relaxed);
}

} // namespace mem_arena::os_mem
