// lsms: the .zs layer over third_party/zstd's decoder (only stable zstd API: no ZSTD_STATIC_LINKING_ONLY).
#include "lsms/zstd_stream.hpp"

#include <algorithm>
#include <string>

#include "lsms/sarc_reader.hpp"

#ifndef LSMS_WITH_ZSTD
#define LSMS_WITH_ZSTD 1   // (CMakeLists.txt sets it; a build by hand gets zstd unless it says otherwise)
#endif
#if LSMS_WITH_ZSTD
#include <zstd.h>
#endif

namespace lsms {

bool zstd_available() noexcept { return LSMS_WITH_ZSTD != 0; }

bool is_zstd_frame(Bytes d) noexcept {
    return d.size() >= 4 && d[0] == std::byte{0x28} && d[1] == std::byte{0xB5} && d[2] == std::byte{0x2F} &&
           d[3] == std::byte{0xFD};
}

// ---------------------------------------------------------------------------------------------- dictionaries
struct ZstdDictionarySet::Impl {
    struct Dict {
        std::uint32_t id;
        std::string name;
        void* ddict;  // ZSTD_DDict*
    };
    std::vector<Dict> dicts;

    ~Impl() {
#if LSMS_WITH_ZSTD
        for (auto& d : dicts) ZSTD_freeDDict(static_cast<ZSTD_DDict*>(d.ddict));
#endif
    }
};

ZstdDictionarySet::ZstdDictionarySet() : impl_(std::make_unique<Impl>()) {}
ZstdDictionarySet::~ZstdDictionarySet() = default;
ZstdDictionarySet::ZstdDictionarySet(ZstdDictionarySet&&) noexcept = default;
ZstdDictionarySet& ZstdDictionarySet::operator=(ZstdDictionarySet&&) noexcept = default;

Expected<std::uint32_t> ZstdDictionarySet::add(Bytes dictionary, std::string name) {
#if !LSMS_WITH_ZSTD
    (void)dictionary;
    (void)name;
    return fail(Errc::unsupported, "built without zstd (LSMS_WITH_ZSTD=0)");
#else
    ZSTD_DDict* dd = ZSTD_createDDict(dictionary.data(), dictionary.size());   // (copies the bytes)
    if (!dd) return fail(Errc::zstd, "zstd refused the dictionary " + name);
    const std::uint32_t id = ZSTD_getDictID_fromDDict(dd);
    auto& list = impl_->dicts;
    const auto same = std::find_if(list.begin(), list.end(), [&](const Impl::Dict& d) { return d.id == id; });
    if (same != list.end()) {
        ZSTD_freeDDict(static_cast<ZSTD_DDict*>(same->ddict));
        *same = Impl::Dict{id, std::move(name), dd};
    } else {
        list.push_back(Impl::Dict{id, std::move(name), dd});
    }
    return id;
#endif
}

const void* ZstdDictionarySet::find(std::uint32_t id) const noexcept {
    for (const auto& d : impl_->dicts)
        if (d.id == id) return d.ddict;
    return nullptr;
}

std::vector<std::pair<std::uint32_t, std::string>> ZstdDictionarySet::list() const {
    std::vector<std::pair<std::uint32_t, std::string>> out;
    for (const auto& d : impl_->dicts) out.emplace_back(d.id, d.name);
    return out;
}

std::size_t ZstdDictionarySet::size() const noexcept { return impl_->dicts.size(); }

Expected<ZstdDictionarySet> ZstdDictionarySet::from_zsdic_pack(Bytes pack_zs, const ZstdOptions& options) {
    // Pack/ZsDic.pack.zs: a zstd frame (no dictionary) around a SARC whose members are the dictionaries (*.zsdic)
    auto raw = zstd_decompress(pack_zs, nullptr, options);
    if (!raw) return Unexpected(raw.error());
    auto sarc = SarcReader::open(*raw);
    if (!sarc) return Unexpected(Error{sarc.error().code, "ZsDic.pack: " + sarc.error().message});
    ZstdDictionarySet set;
    bool named = false;
    for (const auto& e : *sarc) named = named || e.name.ends_with(".zsdic");
    for (const auto& e : *sarc) {
        if (named && !e.name.ends_with(".zsdic")) continue;
        auto id = set.add(e.data, std::string(e.name));
        if (!id) return Unexpected(id.error());
    }
    if (set.size() == 0) return fail(Errc::not_found, "ZsDic.pack holds no dictionary");
    return set;
}

// ---------------------------------------------------------------------------------------------- the stream
struct ZstdStream::Impl {
    const ZstdDictionarySet* dicts = nullptr;
    ZstdOptions options;
    std::vector<std::byte> chunk;
    std::uint64_t produced = 0;
    bool at_frame_start = true;
    std::uint32_t current_dict = 0;
#if LSMS_WITH_ZSTD
    ZSTD_DCtx* dc = nullptr;
    ~Impl() { ZSTD_freeDCtx(dc); }
#endif
};

ZstdStream::ZstdStream(const ZstdDictionarySet* dictionaries, ZstdOptions options) : impl_(std::make_unique<Impl>()) {
    impl_->dicts = dictionaries;
    impl_->options = options;
#if LSMS_WITH_ZSTD
    impl_->dc = ZSTD_createDCtx();
    // (a frame may ask for a window up to 2 GiB; the default limit, 128 MiB, would refuse the game's large files.
    // The output limit in ZstdOptions still bounds what is kept)
    if (impl_->dc) ZSTD_DCtx_setParameter(impl_->dc, ZSTD_d_windowLogMax, sizeof(void*) == 8 ? 31 : 30);
    impl_->chunk.resize(ZSTD_DStreamOutSize());
#endif
}
ZstdStream::~ZstdStream() = default;
ZstdStream::ZstdStream(ZstdStream&&) noexcept = default;
ZstdStream& ZstdStream::operator=(ZstdStream&&) noexcept = default;

std::uint64_t ZstdStream::produced() const noexcept { return impl_->produced; }

void ZstdStream::reset() {
    impl_->produced = 0;
    impl_->at_frame_start = true;
#if LSMS_WITH_ZSTD
    if (impl_->dc) ZSTD_DCtx_reset(impl_->dc, ZSTD_reset_session_only);
#endif
}

Expected<bool> ZstdStream::feed(Bytes input, const Sink& sink) {
#if !LSMS_WITH_ZSTD
    (void)input;
    (void)sink;
    return fail(Errc::unsupported, "built without zstd (LSMS_WITH_ZSTD=0)");
#else
    Impl& s = *impl_;
    if (!s.dc) return fail(Errc::zstd, "zstd could not make a decoder");
    ZSTD_inBuffer in{input.data(), input.size(), 0};
    bool full = false;   // the last call filled the output: more may be waiting with no more input
    auto step = [&]() -> Status {
        ZSTD_outBuffer out{s.chunk.data(), s.chunk.size(), 0};
        const std::size_t ret = ZSTD_decompressStream(s.dc, &out, &in);
        if (ZSTD_isError(ret)) {
            const std::string why = ZSTD_getErrorName(ret);
            reset();
            return fail(Errc::zstd, "zstd: " + why);
        }
        full = out.pos == out.size;
        if (out.pos) {
            s.produced += out.pos;
            if (s.produced > s.options.max_output)
                return fail(Errc::too_large, "decompressed past " + std::to_string(s.options.max_output) + " bytes");
            if (sink && !sink(Bytes(s.chunk.data(), out.pos))) return fail(Errc::limit, "the reader stopped the stream");
        }
        if (ret == 0) s.at_frame_start = true;
        return {};
    };
    while (in.pos < in.size) {
        if (s.at_frame_start) {
            // A new frame: give the decoder the dictionary its header names (0: none)
            const Bytes rest = input.subspan(in.pos);
            const std::uint32_t id = is_zstd_frame(rest) ? ZSTD_getDictID_fromFrame(rest.data(), rest.size()) : 0;
            if (id != s.current_dict) {
                const void* dd = id && s.dicts ? s.dicts->find(id) : nullptr;
                if (id && !dd)
                    return fail(Errc::missing_dictionary, "the frame needs zstd dictionary " + std::to_string(id) +
                                                              ", which is not loaded (romfs Pack/ZsDic.pack.zs)");
                ZSTD_DCtx_reset(s.dc, ZSTD_reset_session_only);
                ZSTD_DCtx_refDDict(s.dc, static_cast<const ZSTD_DDict*>(dd));
                s.current_dict = id;
            }
            s.at_frame_start = false;
        }
        if (auto st = step(); !st) return Unexpected(st.error());
    }
    while (full && !s.at_frame_start) {   // (input used up, output still held back)
        if (auto st = step(); !st) return Unexpected(st.error());
    }
    return s.at_frame_start;
#endif
}

Expected<std::vector<std::byte>> zstd_decompress(Bytes frames, const ZstdDictionarySet* dictionaries,
                                                 const ZstdOptions& options) {
    if (!zstd_available()) return fail(Errc::unsupported, "built without zstd (LSMS_WITH_ZSTD=0)");
    if (!is_zstd_frame(frames)) return fail(Errc::bad_magic, "not a zstd frame");
    std::vector<std::byte> out;
#if LSMS_WITH_ZSTD
    const unsigned long long hint = ZSTD_getFrameContentSize(frames.data(), frames.size());
    if (hint != ZSTD_CONTENTSIZE_ERROR && hint != ZSTD_CONTENTSIZE_UNKNOWN) {
        if (hint > options.max_output)
            return fail(Errc::too_large, "the frame holds " + std::to_string(hint) + " bytes, past the limit");
        out.reserve(static_cast<std::size_t>(hint));
    }
#endif
    ZstdStream stream(dictionaries, options);
    auto done = stream.feed(frames, [&](Bytes chunk) {
        out.insert(out.end(), chunk.begin(), chunk.end());
        return true;
    });
    if (!done) return Unexpected(done.error());
    if (!*done) return fail(Errc::truncated, "the zstd frame ends early");
    return out;
}

}  // namespace lsms
