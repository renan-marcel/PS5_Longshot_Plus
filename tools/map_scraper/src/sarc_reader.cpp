// lsms: SARC, read in place (layout in sarc_reader.hpp).
#include "lsms/sarc_reader.hpp"

#include <algorithm>
#include <string>

namespace lsms {

bool is_sarc(Bytes d) noexcept { return Reader(d, false).magic(0, "SARC"); }

std::uint32_t SarcReader::name_hash(std::string_view name, std::uint32_t key) noexcept {
    std::uint32_t h = 0;
    for (const char c : name) h = h * key + static_cast<std::uint32_t>(static_cast<std::int32_t>(static_cast<signed char>(c)));
    return h;
}

Expected<SarcReader> SarcReader::open(Bytes a) {
    if (a.size() < 0x14) return fail(Errc::truncated, "SARC: shorter than its header");
    Reader r(a, false);
    if (!r.magic(0, "SARC")) return fail(Errc::bad_magic, "not a SARC archive");
    // The byte-order mark: FF FE little-endian (every Switch title), FE FF big-endian (Wii U)
    const auto b6 = *r.u8(6), b7 = *r.u8(7);
    bool big;
    if (b6 == 0xFF && b7 == 0xFE)
        big = false;
    else if (b6 == 0xFE && b7 == 0xFF)
        big = true;
    else
        return fail(Errc::bad_magic, "SARC: byte-order mark " + hex_string(b6, 2) + " " + hex_string(b7, 2));
    r = Reader(a, big);

    SarcReader out;
    out.big_ = big;
    const std::size_t header = *r.u16(4);
    const std::size_t data_offset = *r.u32(0x0C);
    out.version_ = *r.u16(0x10);
    if (data_offset > a.size()) return fail(Errc::truncated, "SARC: the data starts past the end of the file");

    const std::size_t sfat = header;
    if (!r.magic(sfat, "SFAT")) return fail(Errc::bad_node, "SARC: no SFAT at " + hex_string(sfat));
    const auto sfat_header = r.u16(sfat + 4);
    const auto count = r.u16(sfat + 6);
    const auto key = r.u32(sfat + 8);
    if (!sfat_header || !count || !key) return fail(Errc::truncated, "SARC: SFAT header");
    out.key_ = *key;
    const std::size_t nodes = sfat + *sfat_header;
    if (!r.has(nodes, std::size_t(*count) * 16)) return fail(Errc::truncated, "SARC: SFAT nodes");

    const std::size_t sfnt = nodes + std::size_t(*count) * 16;
    if (!r.magic(sfnt, "SFNT")) return fail(Errc::bad_node, "SARC: no SFNT at " + hex_string(sfnt));
    const auto sfnt_header = r.u16(sfnt + 4);
    if (!sfnt_header) return fail(Errc::truncated, "SARC: SFNT header");
    const std::size_t names = sfnt + *sfnt_header;

    out.entries_.reserve(*count);
    for (std::size_t i = 0; i < *count; ++i) {
        const std::size_t n = nodes + i * 16;
        const std::uint32_t hash = *r.u32(n), attr = *r.u32(n + 4), begin = *r.u32(n + 8), end = *r.u32(n + 12);
        if (begin > end || data_offset + end > a.size())
            return fail(Errc::out_of_range, "SARC: file " + std::to_string(i) + "'s data lies outside the archive");
        SarcEntry e;
        e.name_hash = hash;
        e.attributes = attr;
        e.data = a.subspan(data_offset + begin, end - begin);
        if (attr >> 24) {   // has a name: its offset, in 4-byte units, from the names' start
            const auto name = r.cstr(names + std::size_t(attr & 0xFFFF) * 4, data_offset);
            if (!name) return fail(Errc::out_of_range, "SARC: file " + std::to_string(i) + "'s name lies outside SFNT");
            e.name = *name;
        }
        out.entries_.push_back(e);
    }
    return out;
}

const SarcEntry* SarcReader::find(std::string_view name) const noexcept {
    const std::uint32_t h = name_hash(name, key_);
    auto it = std::lower_bound(entries_.begin(), entries_.end(), h,
                               [](const SarcEntry& e, std::uint32_t v) { return e.name_hash < v; });
    for (; it != entries_.end() && it->name_hash == h; ++it)
        if (it->name == name) return &*it;
    for (const auto& e : entries_)   // (an archive written unsorted)
        if (e.name == name) return &e;
    return nullptr;
}

}  // namespace lsms
