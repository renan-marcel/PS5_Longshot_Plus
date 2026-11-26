// lsms: BYML, read in place (layout in byml_parser.hpp).
#include "lsms/byml_parser.hpp"

#include <limits>
#include <string>

namespace lsms::byml {

namespace detail {

struct State {
    Reader r;
    Options options;
    std::uint16_t version = 0;
    std::uint32_t keys = 0, strings = 0, root = 0;
    std::uint32_t key_count = 0, string_count = 0;

    /// A string table's count (0 for no table), or nullopt for a damaged one
    std::optional<std::uint32_t> table_count(std::uint32_t table) const {
        if (!table) return 0u;
        const auto t = r.u8(table);
        const auto n = r.u24(table + 1);
        if (!t || !n || *t != 0xC2) return std::nullopt;
        if (!r.has(std::size_t(table) + 4, std::size_t(*n) * 4)) return std::nullopt;
        return *n;
    }

    std::optional<std::string_view> table_string(std::uint32_t table, std::uint32_t count, std::uint64_t index) const {
        if (!table || index >= count) return std::nullopt;
        const auto a = r.u32(std::size_t(table) + 4 + 4 * index);
        if (!a) return std::nullopt;
        // (the next offset ends the string; the table has count + 1 of them, but a missing last one is tolerated)
        const auto b = r.u32(std::size_t(table) + 4 + 4 * (index + 1));
        const std::size_t limit = b && *b >= *a ? std::size_t(table) + *b : r.size();
        return r.cstr(std::size_t(table) + *a, limit);
    }

    struct Head {
        std::uint8_t type;
        std::uint32_t count;
    };
    Expected<Head> head(std::uint32_t offset, std::uint8_t expect) const {
        const auto t = r.u8(offset);
        const auto n = r.u24(std::size_t(offset) + 1);
        if (!t || !n) return fail(Errc::truncated, "BYML: the container at " + hex_string(offset) + " is past the end");
        if (*t != expect)
            return fail(Errc::bad_node, "BYML: the node at " + hex_string(offset) + " is a " + node_type_name(*t) +
                                            ", its parent says " + node_type_name(expect));
        if (*n > options.max_container_count)
            return fail(Errc::limit, "BYML: the container at " + hex_string(offset) + " claims " + std::to_string(*n) +
                                         " elements");
        return Head{*t, *n};
    }
};

}  // namespace detail

const char* node_type_name(std::uint8_t t) noexcept {
    switch (t) {
    case 0x20: return "hash map (32-bit)";
    case 0x21: return "hash map (64-bit)";
    case 0xA0: return "string";
    case 0xA1: return "binary";
    case 0xA2: return "file";
    case 0xC0: return "array";
    case 0xC1: return "dictionary";
    case 0xC2: return "string table";
    case 0xD0: return "bool";
    case 0xD1: return "int32";
    case 0xD2: return "float";
    case 0xD3: return "uint32";
    case 0xD4: return "int64";
    case 0xD5: return "uint64";
    case 0xD6: return "double";
    case 0xFF: return "null";
    default: return "unknown node type";
    }
}

bool is_byml(Bytes d) noexcept {
    const Reader r(d, false);
    return r.magic(0, "BY") || r.magic(0, "YB");
}

// ---------------------------------------------------------------------------------------------- Node
Expected<std::size_t> Node::size() const {
    if (!state_ || !is_container()) return std::size_t(0);
    auto h = state_->head(value_, type_);
    if (!h) return Unexpected(h.error());
    return std::size_t(h->count);
}

Expected<Node> Node::at(std::size_t index) const {
    if (!state_ || !is_array()) return fail(Errc::bad_node, "BYML: at() on a " + std::string(node_type_name(type_)));
    auto h = state_->head(value_, type_);
    if (!h) return Unexpected(h.error());
    if (index >= h->count) return fail(Errc::out_of_range, "BYML: array index " + std::to_string(index));
    const std::size_t types = std::size_t(value_) + 4;
    const std::size_t values = types + align_up(h->count, 4);
    const auto t = state_->r.u8(types + index);
    const auto v = state_->r.u32(values + 4 * index);
    if (!t || !v) return fail(Errc::truncated, "BYML: the array at " + hex_string(value_) + " runs past the end");
    return Node(state_, *t, *v);
}

Expected<Member> Node::member(std::size_t index) const {
    if (!state_ || !is_dictionary())
        return fail(Errc::bad_node, "BYML: member() on a " + std::string(node_type_name(type_)));
    auto h = state_->head(value_, type_);
    if (!h) return Unexpected(h.error());
    if (index >= h->count) return fail(Errc::out_of_range, "BYML: member index " + std::to_string(index));
    const Reader& r = state_->r;
    const std::size_t base = std::size_t(value_) + 4;
    Member m;
    if (type_ == 0xC1) {
        const std::size_t e = base + 8 * index;
        const auto key = r.u24(e);
        const auto t = r.u8(e + 3);
        const auto v = r.u32(e + 4);
        if (!key || !t || !v) return fail(Errc::truncated, "BYML: the dictionary at " + hex_string(value_) + " runs past the end");
        const auto name = state_->table_string(state_->keys, state_->key_count, *key);
        if (!name) return fail(Errc::out_of_range, "BYML: key index " + std::to_string(*key) + " is not in the key table");
        m.key = *name;
        m.value = Node(state_, *t, *v);
        return m;
    }
    // Hash maps (v7): the entries, then one type byte per entry
    const std::size_t entry = type_ == 0x20 ? 8 : 12;
    const std::size_t e = base + entry * index;
    std::optional<std::uint64_t> hash;
    if (type_ == 0x20) {
        if (const auto h32 = r.u32(e)) hash = *h32;
    } else {
        hash = r.u64(e);
    }
    const auto v = r.u32(e + entry - 4);
    const auto t = r.u8(base + entry * h->count + index);
    if (!hash || !v || !t) return fail(Errc::truncated, "BYML: the hash map at " + hex_string(value_) + " runs past the end");
    m.key_hash = *hash;
    m.hashed_key = true;
    m.value = Node(state_, *t, *v);
    return m;
}

std::optional<Node> Node::find(std::string_view key) const {
    if (!state_ || type_ != 0xC1) return std::nullopt;
    const auto n = size();
    if (!n) return std::nullopt;
    std::size_t lo = 0, hi = *n;
    while (lo < hi) {
        const std::size_t mid = lo + (hi - lo) / 2;
        const auto m = member(mid);
        if (!m) break;
        const int c = m->key.compare(key);
        if (c == 0) return m->value;
        if (c < 0)
            lo = mid + 1;
        else
            hi = mid;
    }
    for (std::size_t i = 0; i < *n; ++i) {   // (a writer that did not sort its keys)
        const auto m = member(i);
        if (m && m->key == key) return m->value;
    }
    return std::nullopt;
}

std::optional<std::string_view> Node::as_string() const {
    if (!state_ || type_ != 0xA0) return std::nullopt;
    return state_->table_string(state_->strings, state_->string_count, value_);
}

std::optional<bool> Node::as_bool() const {
    if (!state_ || type_ != 0xD0) return std::nullopt;
    return value_ != 0;
}

std::optional<std::int64_t> Node::as_int() const {
    if (!state_) return std::nullopt;
    switch (type_) {
    case 0xD1: return static_cast<std::int64_t>(static_cast<std::int32_t>(value_));
    case 0xD3: return static_cast<std::int64_t>(value_);
    case 0xD4: {
        const auto v = state_->r.u64(value_);
        if (!v) return std::nullopt;
        return static_cast<std::int64_t>(*v);
    }
    case 0xD5: {
        const auto v = state_->r.u64(value_);
        if (!v || *v > std::uint64_t(std::numeric_limits<std::int64_t>::max())) return std::nullopt;
        return static_cast<std::int64_t>(*v);
    }
    default: return std::nullopt;
    }
}

std::optional<std::uint64_t> Node::as_uint() const {
    if (!state_) return std::nullopt;
    if (type_ == 0xD3) return value_;
    if (type_ == 0xD5) return state_->r.u64(value_);
    const auto i = as_int();
    if (!i || *i < 0) return std::nullopt;
    return static_cast<std::uint64_t>(*i);
}

std::optional<double> Node::as_double() const {
    if (!state_) return std::nullopt;
    if (type_ == 0xD2) return static_cast<double>(std::bit_cast<float>(value_));
    if (type_ == 0xD6) return state_->r.f64(value_);
    if (type_ == 0xD5) {
        const auto v = state_->r.u64(value_);
        if (!v) return std::nullopt;
        return static_cast<double>(*v);
    }
    const auto i = as_int();
    if (!i) return std::nullopt;
    return static_cast<double>(*i);
}

std::optional<Bytes> Node::as_binary() const {
    if (!state_ || (type_ != 0xA1 && type_ != 0xA2)) return std::nullopt;
    const auto size = state_->r.u32(value_);
    if (!size) return std::nullopt;
    return state_->r.slice(std::size_t(value_) + (type_ == 0xA1 ? 4 : 8), *size);
}

// ---------------------------------------------------------------------------------------------- Document
Expected<Document> Document::parse(Bytes data, const Options& options) {
    if (data.size() < 0x10) return fail(Errc::truncated, "BYML: shorter than its header");
    const Reader probe(data, false);
    bool big;
    if (probe.magic(0, "BY"))
        big = true;
    else if (probe.magic(0, "YB"))
        big = false;
    else
        return fail(Errc::bad_magic, "not a BYML document");

    auto st = std::make_shared<detail::State>();
    st->r = Reader(data, big);
    st->options = options;
    st->version = *st->r.u16(2);
    if (st->version < options.min_version || st->version > options.max_version)
        return fail(Errc::unsupported_version, "BYML version " + std::to_string(st->version) + " (this parser reads " +
                                                   std::to_string(options.min_version) + " to " +
                                                   std::to_string(options.max_version) + ")");
    st->keys = *st->r.u32(4);
    st->strings = *st->r.u32(8);
    st->root = *st->r.u32(12);
    const auto kc = st->table_count(st->keys);
    if (!kc) return fail(Errc::bad_node, "BYML: the key table at " + hex_string(st->keys) + " is damaged");
    const auto sc = st->table_count(st->strings);
    if (!sc) return fail(Errc::bad_node, "BYML: the string table at " + hex_string(st->strings) + " is damaged");
    st->key_count = *kc;
    st->string_count = *sc;
    if (st->root) {
        const auto t = st->r.u8(st->root);
        if (!t) return fail(Errc::truncated, "BYML: the root is past the end");
        if (*t != 0xC0 && *t != 0xC1 && *t != 0x20 && *t != 0x21)
            return fail(Errc::bad_node, std::string("BYML: the root is a ") + node_type_name(*t));
    }
    Document d;
    d.state_ = std::move(st);
    return d;
}

std::uint16_t Document::version() const noexcept { return state_ ? state_->version : 0; }
bool Document::big_endian() const noexcept { return state_ && state_->r.big_endian(); }

std::optional<Node> Document::root() const noexcept {
    if (!state_ || !state_->root) return std::nullopt;
    return Node(state_.get(), *state_->r.u8(state_->root), state_->root);
}

std::size_t Document::key_count() const noexcept { return state_ ? state_->key_count : 0; }
std::optional<std::string_view> Document::key(std::size_t i) const {
    if (!state_) return std::nullopt;
    return state_->table_string(state_->keys, state_->key_count, i);
}
std::size_t Document::string_count() const noexcept { return state_ ? state_->string_count : 0; }
std::optional<std::string_view> Document::string(std::size_t i) const {
    if (!state_) return std::nullopt;
    return state_->table_string(state_->strings, state_->string_count, i);
}

}  // namespace lsms::byml
