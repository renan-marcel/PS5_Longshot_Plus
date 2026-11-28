#include <mem_arena/os_mem.hpp>
#include <mem_arena/scratch_arena.hpp>
#include <mem_arena/scratch_scope.hpp>

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <limits>
#include <memory>
#include <type_traits>

namespace {

using mem_arena::ScratchArena;
using mem_arena::ScratchScope;
namespace os_mem = mem_arena::os_mem;

static_assert(!std::is_copy_constructible_v<ScratchArena>);
static_assert(!std::is_copy_constructible_v<ScratchScope>);
static_assert(!std::is_move_constructible_v<ScratchScope>);

#define CHECK(condition)                                                        \
    do {                                                                        \
        if (!(condition)) {                                                     \
            std::fprintf(stderr, "%s:%d: %s\n", __func__, __LINE__, #condition);   \
            return false;                                                       \
        }                                                                       \
    } while (false)

bool alignment() {
    const auto page = os_mem::page_size();
    ScratchArena arena;
    CHECK(arena.init(8 * page, page));
    for (const auto align : std::array<std::size_t, 5>{8, 16, 64, 4096, 2 * page}) {
        CHECK(arena.alloc(1, 1));
        const void* ptr = arena.alloc(17, align);
        CHECK(ptr);
        CHECK(reinterpret_cast<std::uintptr_t>(ptr) % align == 0);
    }
    return true;
}

bool demand_commit() {
    const auto page = os_mem::page_size();
    const auto reserved = os_mem::total_reserved_bytes();
    const auto committed = os_mem::total_committed_bytes();
    {
        ScratchArena arena;
        CHECK(arena.init(8 * page, 2 * page));
        CHECK(arena.reserved_bytes() == 8 * page);
        CHECK(os_mem::total_reserved_bytes() == reserved + 8 * page);
        CHECK(arena.committed_bytes() == 0);
        CHECK(os_mem::total_committed_bytes() == committed);

        auto* first = static_cast<unsigned char*>(arena.alloc(2 * page, 1));
        CHECK(first);
        first[2 * page - 1] = 17;
        CHECK(arena.committed_bytes() == 2 * page);
        CHECK(os_mem::total_committed_bytes() == committed + 2 * page);

        auto* next = static_cast<unsigned char*>(arena.alloc(1, 1));
        CHECK(next);
        *next = 29;
        CHECK(first[2 * page - 1] == 17);
        CHECK(arena.committed_bytes() == 4 * page);
        CHECK(os_mem::total_committed_bytes() == committed + 4 * page);
        CHECK(arena.used_bytes() == 2 * page + 1);
        CHECK(arena.peak_bytes() == arena.used_bytes());
    }
    CHECK(os_mem::total_reserved_bytes() == reserved);
    CHECK(os_mem::total_committed_bytes() == committed);
    return true;
}

bool nested_scopes() {
    const auto page = os_mem::page_size();
    ScratchArena arena;
    CHECK(arena.init(4 * page, page));
    {
        ScratchScope outer(arena);
        auto* values = outer.alloc_array<std::uint32_t>(2);
        CHECK(values);
        std::construct_at(values, 42);
        std::construct_at(values + 1, 81);
        const auto saved = arena.mark();
        void* inner_address = nullptr;
        {
            ScratchScope inner(arena);
            inner_address = inner.alloc(page, 64);
            CHECK(inner_address);
            static_cast<unsigned char*>(inner_address)[page - 1] = 63;
            CHECK(arena.used_bytes() > saved);
        }
        CHECK(arena.mark() == saved);
        CHECK(values[0] == 42 && values[1] == 81);
        CHECK(outer.alloc(page, 64) == inner_address);
        CHECK(outer.alloc_array<std::uint32_t>(std::numeric_limits<std::size_t>::max()) == nullptr);
    }
    CHECK(arena.used_bytes() == 0);
    CHECK(arena.peak_bytes() > 0);
    return true;
}

bool reset_and_decommit() {
    const auto page = os_mem::page_size();
    const auto committed = os_mem::total_committed_bytes();
    ScratchArena arena;
    CHECK(arena.init(8 * page, page));
    auto* block = static_cast<unsigned char*>(arena.alloc(6 * page, 1));
    CHECK(block);
    block[5 * page] = 19;
    CHECK(arena.reset_and_decommit(page + 1));
    CHECK(arena.used_bytes() == 0);
    CHECK(arena.peak_bytes() == 6 * page);
    CHECK(arena.committed_bytes() == 2 * page);
    CHECK(os_mem::total_committed_bytes() == committed + 2 * page);
    CHECK(arena.alloc(3 * page, 1) == block);
    block[2 * page] = 21;
    CHECK(arena.committed_bytes() == 3 * page);
    CHECK(arena.reset_and_decommit(0));
    CHECK(arena.committed_bytes() == 0);
    CHECK(os_mem::total_committed_bytes() == committed);
    return true;
}

bool exhaustion_and_invalid_inputs() {
    const auto page = os_mem::page_size();
    ScratchArena arena;
    CHECK(!arena.init(0, page));
    CHECK(!arena.init(3 * page, page));
    CHECK(!arena.init(2 * page, page / 2));
    CHECK(!arena.init(4 * page, 3 * page));
    CHECK(arena.init(2 * page, 4 * page));
    CHECK(arena.alloc(2 * page + 1, 1) == nullptr);
    CHECK(arena.alloc(1, 3) == nullptr);
    CHECK(arena.alloc(std::numeric_limits<std::size_t>::max(), 8) == nullptr);
    CHECK(arena.used_bytes() == 0 && arena.committed_bytes() == 0);
    CHECK(arena.alloc(2 * page, 1));
    CHECK(arena.alloc(1, 1) == nullptr);
    CHECK(arena.used_bytes() == 2 * page);
    CHECK(arena.committed_bytes() == 2 * page);
    CHECK(arena.destroy());
    CHECK(arena.reserved_bytes() == 0 && arena.peak_bytes() == 0);
    CHECK(arena.alloc(1, 1) == nullptr);
    return true;
}

bool backend_accounting() {
    const auto page = os_mem::page_size();
    const auto reserved = os_mem::total_reserved_bytes();
    const auto committed = os_mem::total_committed_bytes();
    auto* ptr = static_cast<std::byte*>(os_mem::reserve(4 * page));
    CHECK(ptr);
    CHECK(!os_mem::commit(ptr + 1, page));
    CHECK(os_mem::commit(ptr, 2 * page));
    CHECK(!os_mem::commit(ptr, page));
    CHECK(!os_mem::decommit(ptr, page));
    CHECK(!os_mem::release(ptr, 2 * page));
    CHECK(os_mem::total_reserved_bytes() == reserved + 4 * page);
    CHECK(os_mem::total_committed_bytes() == committed + 2 * page);
    CHECK(os_mem::decommit(ptr + page, page));
    CHECK(os_mem::total_committed_bytes() == committed + page);
    CHECK(os_mem::release(ptr, 4 * page));
    CHECK(os_mem::total_reserved_bytes() == reserved);
    CHECK(os_mem::total_committed_bytes() == committed);
    return true;
}

}  // namespace

int main() {
    const std::array tests{
        alignment,
        demand_commit,
        nested_scopes,
        reset_and_decommit,
        exhaustion_and_invalid_inputs,
        backend_accounting,
    };
    std::size_t failures = 0;
    for (const auto test : tests) {
        if (!test()) {
            ++failures;
        }
    }
    std::printf("ScratchArena: %zu/%zu checks passed\n", tests.size() - failures, tests.size());
    return failures != 0;
}
