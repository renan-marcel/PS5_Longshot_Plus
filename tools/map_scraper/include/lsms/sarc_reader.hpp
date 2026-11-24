// lsms: SARC archives (*.sarc, *.pack, and the inside of *.pack.zs), read in memory.
//
// Layout (all little-endian on Switch titles; big-endian is read too, by the byte-order mark):
//   0x00 "SARC", u16 header size (0x14), u16 BOM (FEFF), u32 file size, u32 data offset, u16 version (0x0100), u16 pad
//   SFAT "SFAT", u16 header size (0x0C), u16 node count, u32 hash key (0x65)
//        node[count] = u32 name hash, u32 attributes (bit 24: has a name; low 16 bits: name offset / 4),
//                      u32 data begin, u32 data end (both from the data offset); sorted by name hash
//   SFNT "SFNT", u16 header size (0x08), u16 pad, then the names, NUL-terminated, each at a 4-byte boundary
//   data
// Entries are views into the archive: nothing is copied, nothing is written to disk. Keep the archive's buffer alive
// while its entries are used.
#pragma once

#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

#include "lsms/binary_reader.hpp"
#include "lsms/expected.hpp"

namespace lsms {

struct SarcEntry {
    std::string_view name;  // empty for an entry stored by hash only
    std::uint32_t name_hash = 0;
    std::uint32_t attributes = 0;
    Bytes data;
};

bool is_sarc(Bytes data) noexcept;

class SarcReader {
public:
    static Expected<SarcReader> open(Bytes archive);
    /// SFAT's name hash: h = h * key + c over the name's bytes, as signed chars
    static std::uint32_t name_hash(std::string_view name, std::uint32_t key = 0x65) noexcept;

    std::size_t size() const noexcept { return entries_.size(); }
    const SarcEntry& operator[](std::size_t i) const { return entries_[i]; }
    std::span<const SarcEntry> entries() const noexcept { return entries_; }
    auto begin() const noexcept { return entries_.begin(); }
    auto end() const noexcept { return entries_.end(); }

    /// By exact name: a binary search on the hash, then the name
    const SarcEntry* find(std::string_view name) const noexcept;

    bool big_endian() const noexcept { return big_; }
    std::uint32_t hash_key() const noexcept { return key_; }
    std::uint16_t version() const noexcept { return version_; }

private:
    std::vector<SarcEntry> entries_;
    bool big_ = false;
    std::uint32_t key_ = 0x65;
    std::uint16_t version_ = 0;
};

}  // namespace lsms
