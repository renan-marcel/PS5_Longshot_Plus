// lsms: BYML documents (*.byml, *.bgyml, *.bcett.byml), read in place.
//
// Header (v2 and later): "BY" (big-endian) or "YB" (little-endian), u16 version, u32 key table offset,
// u32 string table offset, u32 root offset (0: an empty document). Nodes:
//   0xA0 string       value: index into the string table
//   0xA1 binary       value: offset to u32 size, then the bytes                                     (v4+)
//   0xA2 file         value: offset to u32 size, u32 alignment, then the bytes                       (v5+, see README)
//   0xC0 array        at offset: u8 type, u24 count, count type bytes (padded to 4), count u32 values
//   0xC1 dictionary   at offset: u8 type, u24 count, count entries of u24 key index, u8 type, u32 value (sorted by key)
//   0xC2 string table at offset: u8 type, u24 count, (count + 1) u32 offsets from the table, the strings
//   0x20 hash map 32  at offset: u8 type, u24 count, count of (u32 hash, u32 value), then count type bytes   (v7)
//   0x21 hash map 64  at offset: u8 type, u24 count, count of (u64 hash, u32 value), then count type bytes   (v7)
//   0xD0 bool, 0xD1 int32, 0xD2 float, 0xD3 uint32 (inline); 0xD4 int64, 0xD5 uint64, 0xD6 double (value: offset)
//   0xFF null
// A Node is a 16-byte handle (state, type, value); every accessor checks its reads, so a damaged document answers
// errors and nullopt, never a read out of bounds. The Document keeps the parsed state alive for its Nodes (it may be
// moved; the Nodes keep working), but the bytes themselves stay the caller's: keep the buffer alive while Nodes are used.
#pragma once

#include <cstdint>
#include <memory>
#include <optional>
#include <string_view>

#include "lsms/binary_reader.hpp"
#include "lsms/expected.hpp"

namespace lsms::byml {

enum class NodeType : std::uint8_t {
    hash_map32 = 0x20,
    hash_map64 = 0x21,
    string = 0xA0,
    binary = 0xA1,
    file = 0xA2,
    array = 0xC0,
    dictionary = 0xC1,
    string_table = 0xC2,
    boolean = 0xD0,
    int32 = 0xD1,
    float32 = 0xD2,
    uint32 = 0xD3,
    int64 = 0xD4,
    uint64 = 0xD5,
    float64 = 0xD6,
    null = 0xFF,
};

const char* node_type_name(std::uint8_t type) noexcept;
/// "BY" or "YB" at the start
bool is_byml(Bytes data) noexcept;

struct Options {
    std::uint16_t min_version = 2;
    std::uint16_t max_version = 10;  // v7 is the newest known; later ones are tried, with the node types known so far
    std::uint32_t max_container_count = 1u << 24;
};

namespace detail {
struct State;
}
struct Member;

class Node {
public:
    Node() = default;

    std::uint8_t raw_type() const noexcept { return type_; }
    NodeType type() const noexcept { return static_cast<NodeType>(type_); }
    std::uint32_t raw_value() const noexcept { return value_; }
    /// A container's offset in the document: its identity (cycle checks)
    std::uint32_t offset() const noexcept { return value_; }
    bool valid() const noexcept { return state_ != nullptr; }

    bool is_dictionary() const noexcept { return type_ == 0xC1 || type_ == 0x20 || type_ == 0x21; }
    bool is_array() const noexcept { return type_ == 0xC0; }
    bool is_container() const noexcept { return is_dictionary() || is_array(); }
    bool is_string() const noexcept { return type_ == 0xA0; }
    bool is_number() const noexcept { return type_ >= 0xD1 && type_ <= 0xD6; }

    /// A container's element count; 0 for anything else
    Expected<std::size_t> size() const;
    /// An array's element
    Expected<Node> at(std::size_t index) const;
    /// A dictionary's or hash map's member, in stored order
    Expected<Member> member(std::size_t index) const;
    /// A dictionary's member by key (binary search, then a linear pass for unsorted writers); never for hash maps
    std::optional<Node> find(std::string_view key) const;

    std::optional<std::string_view> as_string() const;
    std::optional<bool> as_bool() const;
    std::optional<std::int64_t> as_int() const;
    std::optional<std::uint64_t> as_uint() const;
    std::optional<double> as_double() const;
    std::optional<Bytes> as_binary() const;

private:
    friend class Document;
    Node(const detail::State* state, std::uint8_t type, std::uint32_t value) noexcept
        : state_(state), type_(type), value_(value) {}

    const detail::State* state_ = nullptr;
    std::uint8_t type_ = 0xFF;
    std::uint32_t value_ = 0;
};

struct Member {
    std::string_view key;      // empty in a hash map
    std::uint64_t key_hash = 0;  // a hash map's key
    bool hashed_key = false;
    Node value;
};

class Document {
public:
    static Expected<Document> parse(Bytes data, const Options& options = {});

    std::uint16_t version() const noexcept;
    bool big_endian() const noexcept;
    /// nullopt for an empty document (root offset 0)
    std::optional<Node> root() const noexcept;

    std::size_t key_count() const noexcept;
    std::optional<std::string_view> key(std::size_t index) const;
    std::size_t string_count() const noexcept;
    std::optional<std::string_view> string(std::size_t index) const;

private:
    std::shared_ptr<const detail::State> state_;
};

}  // namespace lsms::byml
