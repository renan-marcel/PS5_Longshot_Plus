#pragma once

#include <cstddef>

namespace mem_arena::os_mem {

// Returns zero if the system page size is unavailable.
[[nodiscard]] std::size_t page_size() noexcept;

// Lengths must be nonzero multiples of page_size(). A reservation starts with
// no accessible pages. Returns nullptr on failure.
[[nodiscard]] void* reserve(std::size_t bytes) noexcept;

// A reservation has a single read/write prefix. Commit extends the prefix;
// decommit removes its tail. The caller must stop using any discarded bytes
// before decommit, and cannot rely on their contents after recommit.
[[nodiscard]] bool commit(void* ptr, std::size_t bytes) noexcept;
[[nodiscard]] bool decommit(void* ptr, std::size_t bytes) noexcept;

// Releases an entire reservation, including any pages still committed.
[[nodiscard]] bool release(void* ptr, std::size_t bytes) noexcept;

// Process totals for this backend. Committed bytes count read/write pages,
// independent of physical residency.
[[nodiscard]] std::size_t total_reserved_bytes() noexcept;
[[nodiscard]] std::size_t total_committed_bytes() noexcept;

} // namespace mem_arena::os_mem
