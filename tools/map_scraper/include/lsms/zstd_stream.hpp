// lsms: the .zs layer. Zstandard frames, with the game's dictionaries.
//
// The game's romfs keeps most files as zstd frames (*.zs). Many need a dictionary: the frame header names it by id, and
// the dictionaries ship in romfs/Pack/ZsDic.pack.zs (zstd with no dictionary, holding a SARC of *.zsdic files).
// ZstdDictionarySet::from_zsdic_pack loads them; each frame then picks its own by the id in its header.
//
// Built over the zstd decoder in third_party/zstd (LSMS_WITH_ZSTD=1, the default). With LSMS_WITH_ZSTD=0 every call
// answers Errc::unsupported and the rest of the library still works on uncompressed .byml, .sarc and .pack files.
#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "lsms/binary_reader.hpp"
#include "lsms/expected.hpp"

namespace lsms {

struct ZstdOptions {
    std::size_t max_output = std::size_t(1) << 30;  // decompressing past this stops with Errc::too_large
};

bool zstd_available() noexcept;
/// A zstd frame's magic (28 B5 2F FD) at the start
bool is_zstd_frame(Bytes data) noexcept;

class ZstdDictionarySet {
public:
    ZstdDictionarySet();
    ~ZstdDictionarySet();
    ZstdDictionarySet(ZstdDictionarySet&&) noexcept;
    ZstdDictionarySet& operator=(ZstdDictionarySet&&) noexcept;
    ZstdDictionarySet(const ZstdDictionarySet&) = delete;
    ZstdDictionarySet& operator=(const ZstdDictionarySet&) = delete;

    /// Adds a zstd dictionary (copied); answers its id. A later dictionary with the same id replaces the earlier one.
    Expected<std::uint32_t> add(Bytes dictionary, std::string name = {});
    /// The decoder's ZSTD_DDict* for an id, or null (opaque here so that zstd.h stays out of the public headers)
    const void* find(std::uint32_t id) const noexcept;
    std::vector<std::pair<std::uint32_t, std::string>> list() const;
    std::size_t size() const noexcept;

    /// The dictionaries of romfs/Pack/ZsDic.pack.zs, as read from the file (still compressed)
    static Expected<ZstdDictionarySet> from_zsdic_pack(Bytes pack_zs, const ZstdOptions& options = {});

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/// Incremental decompression for files too large to hold twice. Feed the compressed bytes in pieces; each piece of
/// output goes to the sink as it is made. One stream may hold several frames back to back, each with its own
/// dictionary. The first piece fed for each frame must hold that frame's whole header (18 bytes at most).
class ZstdStream {
public:
    using Sink = std::function<bool(Bytes chunk)>;  // false stops the stream with Errc::limit

    explicit ZstdStream(const ZstdDictionarySet* dictionaries = nullptr, ZstdOptions options = {});
    ~ZstdStream();
    ZstdStream(ZstdStream&&) noexcept;
    ZstdStream& operator=(ZstdStream&&) noexcept;
    ZstdStream(const ZstdStream&) = delete;
    ZstdStream& operator=(const ZstdStream&) = delete;

    /// Answers true when every frame begun so far has ended (a stream may end here)
    Expected<bool> feed(Bytes input, const Sink& sink);
    std::uint64_t produced() const noexcept;
    void reset();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/// A whole buffer of one or more frames, decompressed in memory
Expected<std::vector<std::byte>> zstd_decompress(Bytes frames, const ZstdDictionarySet* dictionaries = nullptr,
                                                 const ZstdOptions& options = {});

}  // namespace lsms
