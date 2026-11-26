// The amiibo catalogue (ps5/builder/amiibo.py): amiibo.idx lists the figures, figures.pak holds their pictures.
//   amiibo.idx: "LSAMIIBO", u32 version (1), u32 count, then count records of 136 bytes (little-endian):
//               id[8], u64 pic_offset, u32 pic_size (0: no picture), u16 w, u16 h, name[48], series[32], character[32]
//   figures.pak: the pictures one after another, each a zstd frame of w*h*4 RGBA8 bytes (at most 144x180).
// Nothing in the files is trusted: a short file, a size past a file's end or a picture of the wrong size is refused.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <sys/types.h>
#include <vector>
#include "zstd.h"

namespace mkwvk::amiibo {

struct Figure {
    uint8_t id[8] = {};
    std::string name, series, character;
    uint64_t pic_offset = 0;
    uint32_t pic_size = 0;
    uint16_t w = 0, h = 0;
};

constexpr uint16_t MAX_W = 144, MAX_H = 180;
constexpr uint32_t MAX_FIGURES = 100000;
constexpr size_t RECORD = 136;

namespace detail {
inline uint32_t le32(const uint8_t* p) { return p[0] | (p[1] << 8) | (p[2] << 16) | ((uint32_t)p[3] << 24); }
inline uint16_t le16(const uint8_t* p) { return (uint16_t)(p[0] | (p[1] << 8)); }
inline uint64_t le64(const uint8_t* p) { return le32(p) | ((uint64_t)le32(p + 4) << 32); }
inline std::string cstr(const uint8_t* p, size_t n) {
    size_t k = 0;
    while (k < n && p[k]) k++;
    return std::string((const char*)p, k);
}
inline std::string join(const std::string& dir, const char* name) {
    if (dir.empty() || dir.back() == '/' || dir.back() == '\\') return dir + name;
    return dir + "/" + name;
}
inline int seek64(FILE* f, uint64_t off, int whence) {
#ifdef _WIN32
    return _fseeki64(f, (long long)off, whence);
#else
    return fseeko(f, (off_t)off, whence);
#endif
}
inline int64_t tell64(FILE* f) {
#ifdef _WIN32
    return _ftelli64(f);
#else
    return (int64_t)ftello(f);
#endif
}
}  // namespace detail

/// The figures of <dir>/amiibo.idx, in file order; false (out empty) when the file is missing, short or not version 1
inline bool load(const std::string& dir, std::vector<Figure>& out) {
    out.clear();
    FILE* f = fopen(detail::join(dir, "amiibo.idx").c_str(), "rb");
    if (!f) return false;
    uint8_t head[16];
    bool ok = fread(head, 1, 16, f) == 16 && memcmp(head, "LSAMIIBO", 8) == 0 && detail::le32(head + 8) == 1;
    const uint32_t count = ok ? detail::le32(head + 12) : 0;
    ok = ok && count <= MAX_FIGURES;
    for (uint32_t i = 0; ok && i < count; i++) {
        uint8_t r[RECORD];
        if (fread(r, 1, RECORD, f) != RECORD) { ok = false; break; }
        Figure g;
        memcpy(g.id, r, 8);
        g.pic_offset = detail::le64(r + 8);
        g.pic_size = detail::le32(r + 16);
        g.w = detail::le16(r + 20);
        g.h = detail::le16(r + 22);
        g.name = detail::cstr(r + 24, 48);
        g.series = detail::cstr(r + 72, 32);
        g.character = detail::cstr(r + 104, 32);
        out.push_back(std::move(g));
    }
    fclose(f);
    if (!ok) out.clear();
    return ok;
}

/// The figure's picture as w*h*4 RGBA8 in rgba; false (rgba empty) when it has none, the pack is missing or short of it,
/// the size is 0 or over 144x180, or the frame does not decompress to exactly w*h*4 bytes
inline bool picture(const std::string& dir, const Figure& fig, std::vector<uint8_t>& rgba) {
    rgba.clear();
    if (fig.pic_size == 0 || fig.w == 0 || fig.h == 0 || fig.w > MAX_W || fig.h > MAX_H) return false;
    FILE* f = fopen(detail::join(dir, "figures.pak").c_str(), "rb");
    if (!f) return false;
    bool ok = detail::seek64(f, 0, SEEK_END) == 0;
    const int64_t len = ok ? detail::tell64(f) : -1;
    ok = ok && len >= 0 && fig.pic_offset <= (uint64_t)len && fig.pic_size <= (uint64_t)len - fig.pic_offset &&
         detail::seek64(f, fig.pic_offset, SEEK_SET) == 0;
    std::vector<uint8_t> frame;
    if (ok) {
        frame.resize(fig.pic_size);
        ok = fread(frame.data(), 1, frame.size(), f) == frame.size();
    }
    fclose(f);
    if (!ok) return false;
    const size_t want = (size_t)fig.w * fig.h * 4;
    if (ZSTD_getFrameContentSize(frame.data(), frame.size()) != want) return false;
    rgba.resize(want);
    const size_t got = ZSTD_decompress(rgba.data(), rgba.size(), frame.data(), frame.size());
    if (ZSTD_isError(got) || got != want) { rgba.clear(); return false; }
    return true;
}

/// The id as 16 lowercase hex digits
inline std::string id_hex(const uint8_t id[8]) {
    static const char d[] = "0123456789abcdef";
    std::string s;
    for (int i = 0; i < 8; i++) { s += d[id[i] >> 4]; s += d[id[i] & 15]; }
    return s;
}

/// The index of the figure with that id (hex, any case, an optional 0x), or -1
inline int find(const std::vector<Figure>& v, const std::string& hex) {
    std::string h = hex;
    if (h.size() > 2 && h[0] == '0' && (h[1] == 'x' || h[1] == 'X')) h = h.substr(2);
    for (char& c : h) if (c >= 'A' && c <= 'F') c = (char)(c - 'A' + 'a');
    for (size_t i = 0; i < v.size(); i++) if (id_hex(v[i].id) == h) return (int)i;
    return -1;
}

}  // namespace mkwvk::amiibo
