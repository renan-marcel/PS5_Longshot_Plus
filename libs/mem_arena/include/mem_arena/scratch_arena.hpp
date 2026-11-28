#ifndef MEM_ARENA_SCRATCH_ARENA_HPP
#define MEM_ARENA_SCRATCH_ARENA_HPP

#include "mem_arena/os_mem.hpp"

#include <algorithm>
#include <bit>
#include <cstddef>
#include <cstdint>

namespace mem_arena {

// A bump allocator for temporary storage. Use one thread at a time per arena.
class ScratchArena {
public:
    ScratchArena() = default;
    ~ScratchArena() { destroy(); }

    ScratchArena(const ScratchArena&) = delete;
    ScratchArena& operator=(const ScratchArena&) = delete;
    ScratchArena(ScratchArena&&) = delete;
    ScratchArena& operator=(ScratchArena&&) = delete;

    // Both sizes must be powers of two and multiples of the OS page size.
    bool init(std::size_t reserve_bytes, std::size_t commit_chunk_bytes = 2 * 1024 * 1024) noexcept {
        if (base_ != nullptr)
            return false;

        const std::size_t page = os_mem::page_size();
        if (page == 0 || !std::has_single_bit(reserve_bytes) || !std::has_single_bit(commit_chunk_bytes) ||
            reserve_bytes % page != 0 || commit_chunk_bytes % page != 0)
            return false;

        base_ = static_cast<std::byte*>(os_mem::reserve(reserve_bytes));
        if (base_ == nullptr)
            return false;

        reserved_ = reserve_bytes;
        chunk_ = commit_chunk_bytes;
        return true;
    }

    // On release failure, keep the reservation and its state so the caller can retry.
    bool destroy() noexcept {
        if (base_ == nullptr)
            return true;
        if (!os_mem::release(base_, reserved_))
            return false;

        base_ = nullptr;
        reserved_ = chunk_ = committed_ = used_ = peak_ = 0;
        return true;
    }

    // Returns raw storage. A zero size, invalid alignment, or failed allocation returns nullptr.
    void* alloc(std::size_t size, std::size_t align) noexcept {
        if (base_ == nullptr || size == 0 || !std::has_single_bit(align))
            return nullptr;

        const auto address = reinterpret_cast<std::uintptr_t>(base_ + used_);
        const std::size_t misalignment = address & (align - 1);
        const std::size_t padding = misalignment == 0 ? 0 : align - misalignment;
        const std::size_t remaining = reserved_ - used_;
        if (padding > remaining || size > remaining - padding)
            return nullptr;

        const std::size_t offset = used_ + padding;
        const std::size_t end = offset + size;
        if (end > committed_) {
            const std::size_t next = round_up_within(end, chunk_, reserved_);
            if (!os_mem::commit(base_ + committed_, next - committed_))
                return nullptr;
            committed_ = next;
        }

        used_ = end;
        peak_ = std::max(peak_, used_);
        return base_ + offset;
    }

    [[nodiscard]] std::size_t mark() const noexcept { return used_; }

    // A mark belongs to this arena's current allocation sequence. Rewinding
    // invalidates later allocations and leaves their pages committed for reuse.
    bool rewind(std::size_t saved_mark) noexcept {
        if (saved_mark > used_)
            return false;
        used_ = saved_mark;
        return true;
    }

    // Invalidates all allocations and keeps at most the requested warm prefix,
    // rounded up to pages. Returns false if the now-unused tail could not be decommitted.
    bool reset_and_decommit(std::size_t keep_warm_bytes = 4 * 1024 * 1024) noexcept {
        used_ = 0;
        if (keep_warm_bytes >= committed_)
            return true;

        const std::size_t keep = round_up_within(keep_warm_bytes, os_mem::page_size(), committed_);
        if (keep < committed_ && !os_mem::decommit(base_ + keep, committed_ - keep))
            return false;
        committed_ = keep;
        return true;
    }

    [[nodiscard]] std::size_t used_bytes() const noexcept { return used_; }
    [[nodiscard]] std::size_t committed_bytes() const noexcept { return committed_; }
    [[nodiscard]] std::size_t reserved_bytes() const noexcept { return reserved_; }
    [[nodiscard]] std::size_t peak_bytes() const noexcept { return peak_; }

private:
    static std::size_t round_up_within(std::size_t bytes, std::size_t granularity,
                                       std::size_t limit) noexcept {
        const std::size_t remainder = bytes % granularity;
        const std::size_t padding = remainder == 0 ? 0 : granularity - remainder;
        return bytes + std::min(padding, limit - bytes);
    }

    std::byte* base_ = nullptr;
    std::size_t reserved_ = 0;
    std::size_t chunk_ = 0;
    std::size_t committed_ = 0;
    std::size_t used_ = 0;
    std::size_t peak_ = 0;
};

} // namespace mem_arena

#endif // MEM_ARENA_SCRATCH_ARENA_HPP
