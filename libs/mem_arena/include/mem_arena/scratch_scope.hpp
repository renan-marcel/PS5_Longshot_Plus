#ifndef MEM_ARENA_SCRATCH_SCOPE_HPP
#define MEM_ARENA_SCRATCH_SCOPE_HPP

#include "mem_arena/scratch_arena.hpp"

#include <cstddef>
#include <limits>
#include <type_traits>

namespace mem_arena {

// Scopes must unwind in reverse order. The arena must outlive them and must
// stay initialized without being reset or rewound past an active scope's mark.
class ScratchScope {
public:
    explicit ScratchScope(ScratchArena& arena) noexcept : arena_(arena), mark_(arena.mark()) {}
    ~ScratchScope() { arena_.rewind(mark_); }

    ScratchScope(const ScratchScope&) = delete;
    ScratchScope& operator=(const ScratchScope&) = delete;
    ScratchScope(ScratchScope&&) = delete;
    ScratchScope& operator=(ScratchScope&&) = delete;

    void* alloc(std::size_t size, std::size_t align) noexcept { return arena_.alloc(size, align); }

    // Returns uninitialized storage. Construct elements if their type requires it.
    template<typename T>
    T* alloc_array(std::size_t count) noexcept {
        static_assert(std::is_trivially_destructible_v<T>);
        if (count > std::numeric_limits<std::size_t>::max() / sizeof(T))
            return nullptr;
        return static_cast<T*>(alloc(count * sizeof(T), alignof(T)));
    }

private:
    ScratchArena& arena_;
    std::size_t mark_;
};

} // namespace mem_arena

#endif // MEM_ARENA_SCRATCH_SCOPE_HPP
