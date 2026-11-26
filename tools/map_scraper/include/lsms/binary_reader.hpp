// lsms: bounds-checked reads of a byte view.
//
// Every read answers std::nullopt past the end, so a parser over a damaged or hostile file stops with an error and
// never reads outside its buffer. Views only: nothing here copies or owns the bytes.
#pragma once

#include <bit>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <optional>
#include <span>
#include <string>
#include <string_view>

namespace lsms {

using Bytes = std::span<const std::byte>;

inline Bytes bytes_of(const void* data, std::size_t size) noexcept { return {static_cast<const std::byte*>(data), size}; }

inline constexpr std::size_t align_up(std::size_t v, std::size_t a) noexcept { return (v + a - 1) / a * a; }

inline std::string hex_string(std::uint64_t v, int digits = 8) {
    char buf[32];
    std::snprintf(buf, sizeof buf, "0x%0*llx", digits, static_cast<unsigned long long>(v));
    return buf;
}

class Reader {
public:
    Reader() = default;
    Reader(Bytes data, bool big_endian) noexcept : data_(data), big_(big_endian) {}

    Bytes data() const noexcept { return data_; }
    std::size_t size() const noexcept { return data_.size(); }
    bool big_endian() const noexcept { return big_; }

    bool has(std::size_t offset, std::size_t count) const noexcept {
        return offset <= data_.size() && count <= data_.size() - offset;
    }
    bool magic(std::size_t offset, std::string_view m) const noexcept {
        return has(offset, m.size()) && std::memcmp(data_.data() + offset, m.data(), m.size()) == 0;
    }

    std::optional<std::uint8_t> u8(std::size_t o) const noexcept {
        if (!has(o, 1)) return std::nullopt;
        return std::to_integer<std::uint8_t>(data_[o]);
    }
    std::optional<std::uint16_t> u16(std::size_t o) const noexcept { return uint<std::uint16_t>(o, 2); }
    std::optional<std::uint32_t> u24(std::size_t o) const noexcept { return uint<std::uint32_t>(o, 3); }
    std::optional<std::uint32_t> u32(std::size_t o) const noexcept { return uint<std::uint32_t>(o, 4); }
    std::optional<std::uint64_t> u64(std::size_t o) const noexcept { return uint<std::uint64_t>(o, 8); }
    std::optional<float> f32(std::size_t o) const noexcept {
        const auto v = u32(o);
        if (!v) return std::nullopt;
        return std::bit_cast<float>(*v);
    }
    std::optional<double> f64(std::size_t o) const noexcept {
        const auto v = u64(o);
        if (!v) return std::nullopt;
        return std::bit_cast<double>(*v);
    }
    std::optional<Bytes> slice(std::size_t o, std::size_t n) const noexcept {
        if (!has(o, n)) return std::nullopt;
        return data_.subspan(o, n);
    }
    /// The NUL-terminated string at o, read no further than limit (exclusive, and the buffer's end at most). With no
    /// NUL before the limit, the string runs to the limit.
    std::optional<std::string_view> cstr(std::size_t o, std::size_t limit = SIZE_MAX) const noexcept {
        const std::size_t end = limit < data_.size() ? limit : data_.size();
        if (o >= end) return std::nullopt;
        const char* p = reinterpret_cast<const char*>(data_.data()) + o;
        const void* nul = std::memchr(p, 0, end - o);
        const std::size_t n = nul ? static_cast<std::size_t>(static_cast<const char*>(nul) - p) : end - o;
        return std::string_view(p, n);
    }

private:
    template <class T> std::optional<T> uint(std::size_t o, std::size_t n) const noexcept {
        if (!has(o, n)) return std::nullopt;
        std::uint64_t v = 0;
        for (std::size_t i = 0; i < n; ++i)
            v = (v << 8) | std::to_integer<std::uint8_t>(data_[o + (big_ ? i : n - 1 - i)]);
        return static_cast<T>(v);
    }

    Bytes data_{};
    bool big_ = false;
};

}  // namespace lsms
