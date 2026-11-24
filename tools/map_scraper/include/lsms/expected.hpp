// lsms: Longshot map scraper. Errors as values.
//
// Every fallible call answers Expected<T>: std::expected<T, Error> where the standard library has it (C++23), and a
// small stand-in with the same surface under C++20 (has_value, operator bool, value, operator*, operator->, error).
// Write `return fail(Errc::..., "...")` for an error and `return value;` (or `return {};` for Status) for success:
// both spell the same under either.
#pragma once

#include <string>
#include <utility>
#include <variant>
#include <version>

#if defined(__cpp_lib_expected) && __cpp_lib_expected >= 202202L
#include <expected>
#define LSMS_STD_EXPECTED 1
#else
#define LSMS_STD_EXPECTED 0
#endif

namespace lsms {

enum class Errc : int {
    truncated = 1,        // a header, table or node runs past the end of the buffer
    bad_magic,            // not the format asked for
    unsupported_version,  // a format version outside what the parser accepts (byml::Options)
    bad_node,             // a node, table or entry that contradicts the format
    out_of_range,         // an index or offset outside its table
    not_found,            // a name, key or file that is not there
    io,                   // a file that could not be read or written
    zstd,                 // the zstd decoder refused the frame
    missing_dictionary,   // a zstd frame needs a dictionary that was not loaded (Pack/ZsDic.pack.zs)
    too_large,            // past a size limit (ZstdOptions::max_output, ScraperConfig::max_file_size)
    unsupported,          // a feature left out of this build (LSMS_WITH_ZSTD=0)
    limit,                // a walk limit was reached (depth, nesting, node budget) or a sink stopped
};

inline const char* errc_name(Errc c) noexcept {
    switch (c) {
    case Errc::truncated: return "truncated";
    case Errc::bad_magic: return "bad_magic";
    case Errc::unsupported_version: return "unsupported_version";
    case Errc::bad_node: return "bad_node";
    case Errc::out_of_range: return "out_of_range";
    case Errc::not_found: return "not_found";
    case Errc::io: return "io";
    case Errc::zstd: return "zstd";
    case Errc::missing_dictionary: return "missing_dictionary";
    case Errc::too_large: return "too_large";
    case Errc::unsupported: return "unsupported";
    case Errc::limit: return "limit";
    }
    return "unknown";
}

struct Error {
    Errc code = Errc::bad_node;
    std::string message;
};

#if LSMS_STD_EXPECTED
template <class T> using Expected = std::expected<T, Error>;
using Unexpected = std::unexpected<Error>;
#else
class Unexpected {
public:
    explicit Unexpected(Error e) : error_(std::move(e)) {}
    const Error& error() const& noexcept { return error_; }
    Error&& error() && noexcept { return std::move(error_); }

private:
    Error error_;
};

template <class T> class Expected {
public:
    Expected(const T& v) : v_(std::in_place_index<0>, v) {}
    Expected(T&& v) : v_(std::in_place_index<0>, std::move(v)) {}
    Expected(Unexpected u) : v_(std::in_place_index<1>, std::move(u).error()) {}

    bool has_value() const noexcept { return v_.index() == 0; }
    explicit operator bool() const noexcept { return has_value(); }
    T& value() & { return std::get<0>(v_); }
    const T& value() const& { return std::get<0>(v_); }
    T&& value() && { return std::get<0>(std::move(v_)); }
    T& operator*() & { return std::get<0>(v_); }
    const T& operator*() const& { return std::get<0>(v_); }
    T&& operator*() && { return std::get<0>(std::move(v_)); }
    T* operator->() { return &std::get<0>(v_); }
    const T* operator->() const { return &std::get<0>(v_); }
    const Error& error() const& { return std::get<1>(v_); }

private:
    std::variant<T, Error> v_;
};

template <> class Expected<void> {
public:
    Expected() = default;
    Expected(Unexpected u) : error_(std::move(u).error()), ok_(false) {}
    bool has_value() const noexcept { return ok_; }
    explicit operator bool() const noexcept { return ok_; }
    const Error& error() const& { return error_; }

private:
    Error error_{};
    bool ok_ = true;
};
#endif

using Status = Expected<void>;

inline Unexpected fail(Errc code, std::string message) { return Unexpected(Error{code, std::move(message)}); }

}  // namespace lsms
