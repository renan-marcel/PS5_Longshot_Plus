// lsms tests: synthetic files, built in memory. No game file is needed (or allowed) to test the library.
//
//   BymlWriter   a little-endian BYML v7 document from a tree of BValue (dictionaries, arrays, strings, numbers, bools)
//   make_sarc    a little-endian SARC from (name, bytes) pairs
//   zstd_raw     a zstd frame of raw (stored) blocks: a valid frame with no compressor at hand, optionally naming a
//                dictionary id in its header
#pragma once

#include <algorithm>
#include <bit>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <string_view>
#include <tuple>
#include <utility>
#include <variant>
#include <vector>

#include "lsms/sarc_reader.hpp"

namespace lsms_test {

using ByteVec = std::vector<std::byte>;

struct BValue;
using BArray = std::vector<BValue>;
using BDict = std::map<std::string, BValue>;

struct BValue {
    std::variant<bool, std::int32_t, float, std::string, std::shared_ptr<BArray>, std::shared_ptr<BDict>, std::uint32_t> v;
    BValue(bool b) : v(b) {}
    BValue(int i) : v(static_cast<std::int32_t>(i)) {}
    BValue(float f) : v(f) {}
    BValue(double f) : v(static_cast<float>(f)) {}
    BValue(const char* s) : v(std::string(s)) {}
    BValue(std::string s) : v(std::move(s)) {}
    BValue(BArray a) : v(std::make_shared<BArray>(std::move(a))) {}
    BValue(BDict d) : v(std::make_shared<BDict>(std::move(d))) {}
    static BValue hash(std::uint32_t h) {
        BValue b(0);
        b.v = h;
        return b;
    }
};

inline BValue arr(std::initializer_list<BValue> items) { return BValue(BArray(items)); }
inline BValue dict(std::initializer_list<std::pair<const std::string, BValue>> items) { return BValue(BDict(items)); }

class ByteOut {
public:
    ByteVec bytes;
    std::size_t size() const { return bytes.size(); }
    void u8(std::uint32_t v) { bytes.push_back(std::byte(v & 0xFF)); }
    void u16(std::uint32_t v) { for (int i = 0; i < 2; ++i) u8(v >> (8 * i)); }
    void u24(std::uint32_t v) { for (int i = 0; i < 3; ++i) u8(v >> (8 * i)); }
    void u32(std::uint32_t v) { for (int i = 0; i < 4; ++i) u8(v >> (8 * i)); }
    void text(std::string_view s) { for (char c : s) u8(static_cast<unsigned char>(c)); }
    void align(std::size_t a) { while (bytes.size() % a) u8(0); }
    void put32(std::size_t at, std::uint32_t v) { for (int i = 0; i < 4; ++i) bytes[at + i] = std::byte((v >> (8 * i)) & 0xFF); }
};

inline std::size_t align_up_(std::size_t v, std::size_t a) { return (v + a - 1) / a * a; }

class BymlWriter {
public:
    ByteVec write(const BValue& root, std::uint16_t version = 7) {
        collect(root);
        out_.text("YB");
        out_.u16(version);
        out_.u32(0);
        out_.u32(0);
        out_.u32(0);
        const std::uint32_t keys = table(keys_);
        const std::uint32_t strings = table(strings_);
        const auto [type, root_offset] = encode(root);
        (void)type;
        out_.put32(4, keys);
        out_.put32(8, strings);
        out_.put32(12, root_offset);
        return out_.bytes;
    }

private:
    void collect(const BValue& v) {
        if (auto* s = std::get_if<std::string>(&v.v)) strings_.insert(*s);
        if (auto* a = std::get_if<std::shared_ptr<BArray>>(&v.v))
            for (const auto& x : **a) collect(x);
        if (auto* d = std::get_if<std::shared_ptr<BDict>>(&v.v))
            for (const auto& [k, x] : **d) {
                keys_.insert(k);
                collect(x);
            }
    }

    std::uint32_t table(const std::set<std::string>& s) {
        if (s.empty()) return 0;
        out_.align(4);
        const std::size_t at = out_.size();
        out_.u8(0xC2);
        out_.u24(static_cast<std::uint32_t>(s.size()));
        const std::size_t offsets = out_.size();
        for (std::size_t i = 0; i <= s.size(); ++i) out_.u32(0);
        std::size_t i = 0;
        for (const auto& str : s) {
            out_.put32(offsets + 4 * i++, static_cast<std::uint32_t>(out_.size() - at));
            out_.text(str);
            out_.u8(0);
        }
        out_.put32(offsets + 4 * i, static_cast<std::uint32_t>(out_.size() - at));
        out_.align(4);
        return static_cast<std::uint32_t>(at);
    }

    static std::uint32_t index_of(const std::set<std::string>& s, const std::string& v) {
        return static_cast<std::uint32_t>(std::distance(s.begin(), s.find(v)));
    }

    std::pair<std::uint8_t, std::uint32_t> encode(const BValue& v) {
        if (auto* b = std::get_if<bool>(&v.v)) return {0xD0, *b ? 1u : 0u};
        if (auto* i = std::get_if<std::int32_t>(&v.v)) return {0xD1, static_cast<std::uint32_t>(*i)};
        if (auto* f = std::get_if<float>(&v.v)) return {0xD2, std::bit_cast<std::uint32_t>(*f)};
        if (auto* u = std::get_if<std::uint32_t>(&v.v)) return {0xD3, *u};
        if (auto* s = std::get_if<std::string>(&v.v)) return {0xA0, index_of(strings_, *s)};
        if (auto* a = std::get_if<std::shared_ptr<BArray>>(&v.v)) {
            std::vector<std::pair<std::uint8_t, std::uint32_t>> items;
            for (const auto& x : **a) items.push_back(encode(x));   // (children first: their offsets go in here)
            out_.align(4);
            const auto at = static_cast<std::uint32_t>(out_.size());
            out_.u8(0xC0);
            out_.u24(static_cast<std::uint32_t>(items.size()));
            for (const auto& it : items) out_.u8(it.first);
            out_.align(4);
            for (const auto& it : items) out_.u32(it.second);
            return {0xC0, at};
        }
        const auto& d = *std::get<std::shared_ptr<BDict>>(v.v);
        std::vector<std::tuple<std::uint32_t, std::uint8_t, std::uint32_t>> items;
        for (const auto& [k, x] : d) {
            const auto e = encode(x);
            items.emplace_back(index_of(keys_, k), e.first, e.second);
        }
        out_.align(4);
        const auto at = static_cast<std::uint32_t>(out_.size());
        out_.u8(0xC1);
        out_.u24(static_cast<std::uint32_t>(items.size()));
        for (const auto& [k, t, val] : items) {
            out_.u24(k);
            out_.u8(t);
            out_.u32(val);
        }
        return {0xC1, at};
    }

    ByteOut out_;
    std::set<std::string> keys_, strings_;
};

inline ByteVec make_sarc(std::vector<std::pair<std::string, ByteVec>> files, std::uint32_t key = 0x65) {
    std::sort(files.begin(), files.end(), [&](const auto& a, const auto& b) {
        return lsms::SarcReader::name_hash(a.first, key) < lsms::SarcReader::name_hash(b.first, key);
    });
    ByteOut names;
    std::vector<std::uint32_t> name_at;
    for (const auto& f : files) {
        name_at.push_back(static_cast<std::uint32_t>(names.size()));
        names.text(f.first);
        names.u8(0);
        names.align(4);
    }
    ByteOut data;
    std::vector<std::pair<std::uint32_t, std::uint32_t>> ranges;
    for (const auto& f : files) {
        data.align(8);
        const auto b = static_cast<std::uint32_t>(data.size());
        data.bytes.insert(data.bytes.end(), f.second.begin(), f.second.end());
        ranges.emplace_back(b, static_cast<std::uint32_t>(data.size()));
    }
    const std::size_t sfat = 0x14, sfnt = sfat + 0x0C + files.size() * 16;
    const std::size_t data_offset = align_up_(sfnt + 8 + names.size(), 8);

    ByteOut o;
    o.text("SARC");
    o.u16(0x14);
    o.u16(0xFEFF);
    o.u32(static_cast<std::uint32_t>(data_offset + data.size()));
    o.u32(static_cast<std::uint32_t>(data_offset));
    o.u16(0x0100);
    o.u16(0);
    o.text("SFAT");
    o.u16(0x0C);
    o.u16(static_cast<std::uint32_t>(files.size()));
    o.u32(key);
    for (std::size_t i = 0; i < files.size(); ++i) {
        o.u32(lsms::SarcReader::name_hash(files[i].first, key));
        o.u32(0x01000000u | (name_at[i] / 4));
        o.u32(ranges[i].first);
        o.u32(ranges[i].second);
    }
    o.text("SFNT");
    o.u16(8);
    o.u16(0);
    o.bytes.insert(o.bytes.end(), names.bytes.begin(), names.bytes.end());
    while (o.size() < data_offset) o.u8(0);
    o.bytes.insert(o.bytes.end(), data.bytes.begin(), data.bytes.end());
    return o.bytes;
}

inline ByteVec zstd_raw(const ByteVec& content, std::uint32_t dict_id = 0) {
    ByteOut o;
    o.u32(0xFD2FB528u);
    const std::size_t n = content.size();
    // Frame header descriptor: single segment (no window byte), the content size's field, the dictionary id's field
    std::uint32_t fcs_flag = n < 256 ? 0 : n < 65536 + 256 ? 1 : 2;
    o.u8((fcs_flag << 6) | 0x20 | (dict_id ? 3 : 0));
    if (dict_id) o.u32(dict_id);
    if (fcs_flag == 0) o.u8(static_cast<std::uint32_t>(n));
    else if (fcs_flag == 1) o.u16(static_cast<std::uint32_t>(n - 256));
    else o.u32(static_cast<std::uint32_t>(n));
    std::size_t at = 0;
    do {
        const std::size_t part = std::min<std::size_t>(n - at, 128 * 1024);
        const bool last = at + part == n;
        o.u24(static_cast<std::uint32_t>((part << 3) | (0u << 1) | (last ? 1u : 0u)));   // raw block
        o.bytes.insert(o.bytes.end(), content.begin() + at, content.begin() + at + part);
        at += part;
    } while (at < n);
    return o.bytes;
}


}  // namespace lsms_test
