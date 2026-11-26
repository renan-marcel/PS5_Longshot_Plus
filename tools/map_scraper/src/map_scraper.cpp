// lsms: the map scraper's walk, its catalogue and the JSON export.
//
// The walk, for each map:
//   1. Layers come off by magic: a zstd frame is decompressed (its dictionary picked by the id in its header), a SARC is
//      opened and its BYML / SARC members (and zstd members with a map's name) are walked in turn, a BYML is parsed.
//   2. Each BYML dictionary is read as a whole: its transform first (translate / rotate / scale keys, as [x, y, z] or
//      {X, Y, Z}), then its actor key (the best-ranked actor key holding a string or a hash; a weak key such as "Name"
//      only beside a transform): that dictionary is one placement of the actor, with that transform.
//   3. Its other members: a resource key's string (or list of strings, or dictionary with a name key) is a resource
//      of that key's category, with the transform of the placement around it; any other string that ends in a known
//      extension is a reference of that extension's category. Containers are walked the same way, depth first.
// Nothing about one title's schema is fixed here: every key and extension comes from ScraperConfig.
#include "lsms/map_scraper.hpp"

#include <algorithm>
#include <fstream>
#include <limits>
#include <set>
#include <system_error>
#include <unordered_set>

#include "lsms/byml_parser.hpp"
#include "lsms/json_writer.hpp"
#include "lsms/sarc_reader.hpp"

namespace lsms {

namespace {

std::string lower(std::string_view s) {
    std::string o(s);
    for (char& c : o)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return o;
}

bool ends_with_any(std::string_view lower_name, const std::vector<std::string>& lower_suffixes) {
    for (const auto& s : lower_suffixes)
        if (lower_name.ends_with(s)) return true;
    return false;
}

std::string record_key(std::string_view source, Category c, std::string_view name) {
    std::string k;
    k.reserve(source.size() + name.size() + 4);
    k.append(source);
    k.push_back('\x1f');
    k.push_back(static_cast<char>('0' + static_cast<int>(c)));
    k.push_back('\x1f');
    k.append(name);
    return k;
}

Expected<std::vector<std::byte>> read_file(const std::filesystem::path& p, std::size_t max_size) {
    std::error_code ec;
    const auto size = std::filesystem::file_size(p, ec);
    if (ec) return fail(Errc::io, "cannot read " + utf8_of(p) + ": " + ec.message());
    if (size > max_size) return fail(Errc::too_large, utf8_of(p) + " is larger than max_file_size");
    std::ifstream in(p, std::ios::binary);
    if (!in) return fail(Errc::io, "cannot open " + utf8_of(p));
    std::vector<std::byte> data(static_cast<std::size_t>(size));
    if (size && !in.read(reinterpret_cast<char*>(data.data()), static_cast<std::streamsize>(size)))
        return fail(Errc::io, "reading " + utf8_of(p) + " stopped early");
    return data;
}

}  // namespace

// ---------------------------------------------------------------------------------------------- names
std::string_view category_name(Category c) noexcept {
    switch (c) {
    case Category::actor: return "actor";
    case Category::model: return "model";
    case Category::texture: return "texture";
    case Category::collision: return "collision";
    case Category::effect: return "effect";
    case Category::submap: return "submap";
    case Category::unknown: return "unknown";
    }
    return "unknown";
}

std::optional<Category> category_from_name(std::string_view name) noexcept {
    for (const Category c : kAllCategories)
        if (lower(name) == category_name(c)) return c;
    return std::nullopt;
}

std::string_view resolution_name(Resolution r) noexcept {
    switch (r) {
    case Resolution::found: return "found";
    case Resolution::missing: return "missing";
    default: return "not_checked";
    }
}

std::string_view level_name(Diagnostic::Level l) noexcept {
    switch (l) {
    case Diagnostic::Level::warning: return "warning";
    case Diagnostic::Level::error: return "error";
    default: return "info";
    }
}

// ---------------------------------------------------------------------------------------------- Catalog
const AssetRecord* Catalog::find(std::string_view source, Category c, std::string_view name) const {
    const auto it = index_.find(record_key(source, c, name));
    return it == index_.end() ? nullptr : &records_[it->second];
}

AssetRecord& Catalog::upsert(std::string_view source, Category c, std::string_view name, bool& created) {
    auto [it, inserted] = index_.try_emplace(record_key(source, c, name), records_.size());
    created = inserted;
    if (inserted) {
        AssetRecord r;
        r.name = std::string(name);
        r.category = c;
        r.source_map = std::string(source);
        records_.push_back(std::move(r));
    }
    return records_[it->second];
}

KeyStat& Catalog::census(std::string_view key) {
    auto it = census_.find(key);
    if (it == census_.end()) it = census_.emplace(std::string(key), KeyStat{}).first;
    return it->second;
}

std::vector<const AssetRecord*> Catalog::sorted() const {
    std::vector<const AssetRecord*> out;
    out.reserve(records_.size());
    for (const auto& r : records_) out.push_back(&r);
    std::sort(out.begin(), out.end(), [](const AssetRecord* a, const AssetRecord* b) {
        if (a->source_map != b->source_map) return a->source_map < b->source_map;
        if (a->category != b->category) return a->category < b->category;
        return a->name < b->name;
    });
    return out;
}

std::vector<AggregateRecord> Catalog::aggregate() const {
    std::map<std::pair<Category, std::string>, AggregateRecord> by;
    for (const auto& r : records_) {
        AggregateRecord& a = by[{r.category, r.name}];
        if (a.maps.empty()) {
            a.name = r.name;
            a.category = r.category;
        }
        a.instance_count += r.instance_count;
        a.maps.push_back(r.source_map);
        if (r.resolution == Resolution::found ||
            (r.resolution == Resolution::missing && a.resolution == Resolution::not_checked))
            a.resolution = r.resolution;
    }
    std::vector<AggregateRecord> out;
    out.reserve(by.size());
    for (auto& [k, a] : by) {
        std::sort(a.maps.begin(), a.maps.end());
        out.push_back(std::move(a));
    }
    return out;
}

std::vector<const AssetRecord*> Catalog::unresolved() const {
    std::vector<const AssetRecord*> out;
    for (const AssetRecord* r : sorted())
        if (r->resolution == Resolution::missing) out.push_back(r);
    return out;
}

void Catalog::clear() {
    records_.clear();
    index_.clear();
    maps_.clear();
    diagnostics_.clear();
    census_.clear();
}

// ---------------------------------------------------------------------------------------------- the walker
struct MapScraper::Impl {
    ScraperConfig cfg;
    Catalog catalog;
    std::shared_ptr<const ZstdDictionarySet> dicts;
    std::shared_ptr<const RomfsIndex> index;

    // The config, compiled at the start of each scan (keys normalized for lookups)
    std::unordered_map<std::string, std::size_t> actor_rank;
    std::unordered_set<std::string> weak_actor, name_keys, tr, rot, scl, cx, cy, cz;
    std::unordered_map<std::string, Category> resource;
    std::vector<std::pair<std::string, Category>> extensions;  // lower case, longest first
    std::vector<std::string> map_suffixes;                       // lower case

    // One map's walk
    std::string source;
    std::size_t nodes = 0;
    bool budget_noted = false, depth_noted = false;
    std::vector<std::uint32_t> path;  // the containers from the root to here (cycle check)

    std::string norm(std::string_view k) const { return cfg.case_insensitive_keys ? lower(k) : std::string(k); }

    void compile() {
        auto set_of = [&](const std::vector<std::string>& keys) {
            std::unordered_set<std::string> s;
            for (const auto& k : keys) s.insert(norm(k));
            return s;
        };
        actor_rank.clear();
        for (std::size_t i = 0; i < cfg.actor_keys.size(); ++i) actor_rank.try_emplace(norm(cfg.actor_keys[i]), i);
        weak_actor = set_of(cfg.weak_actor_keys);
        name_keys = set_of(cfg.name_keys);
        tr = set_of(cfg.translate_keys);
        rot = set_of(cfg.rotate_keys);
        scl = set_of(cfg.scale_keys);
        cx = set_of(cfg.x_keys);
        cy = set_of(cfg.y_keys);
        cz = set_of(cfg.z_keys);
        resource.clear();
        for (const auto& r : cfg.resource_keys) resource.try_emplace(norm(r.key), r.category);
        extensions.clear();
        for (const auto& e : cfg.extension_rules) extensions.emplace_back(lower(e.suffix), e.category);
        std::stable_sort(extensions.begin(), extensions.end(),
                         [](const auto& a, const auto& b) { return a.first.size() > b.first.size(); });
        map_suffixes.clear();
        for (const auto& s : cfg.map_suffixes) map_suffixes.push_back(lower(s));
    }

    void diag(Diagnostic::Level level, std::string message) {
        catalog.add_diagnostic(Diagnostic{level, source, std::move(message)});
    }

    std::optional<Category> category_by_extension(std::string_view s) const {
        if (s.empty() || s.size() > 1024) return std::nullopt;
        if (s.find_first_of(" \t\r\n") != std::string_view::npos) return std::nullopt;
        std::string l = lower(s);
        if (l.ends_with(".zs")) l.resize(l.size() - 3);
        for (const auto& [suffix, cat] : extensions)
            if (l.size() > suffix.size() && l.ends_with(suffix)) return cat;
        return std::nullopt;
    }

    void record(Category c, std::string_view name, std::string_view via, const Transform* t) {
        if (name.empty()) return;
        bool created = false;
        AssetRecord& r = catalog.upsert(source, c, name, created);
        if (created) r.via_key = std::string(via);
        ++r.instance_count;
        if (!r.sample_transform && t && !t->empty()) r.sample_transform = *t;
    }

    std::string key_text(const byml::Member& m) const {
        if (!m.hashed_key) return std::string(m.key);
        if (const auto it = cfg.hash_names.find(m.key_hash); it != cfg.hash_names.end()) return it->second;
        return hex_string(m.key_hash, m.key_hash > 0xFFFFFFFFull ? 16 : 8);
    }

    /// An actor's name from a string, or from a hash (uint32 / uint64) through hash_names
    std::optional<std::string> name_of(const byml::Node& v) const {
        if (const auto s = v.as_string()) {
            if (s->empty()) return std::nullopt;
            return std::string(*s);
        }
        if (v.raw_type() == 0xD3 || v.raw_type() == 0xD5) {
            const auto h = v.as_uint();
            if (!h) return std::nullopt;
            if (const auto it = cfg.hash_names.find(*h); it != cfg.hash_names.end()) return it->second;
            return "hash:" + hex_string(*h, *h > 0xFFFFFFFFull ? 16 : 8);
        }
        return std::nullopt;
    }

    std::optional<Vec3> vec3(const byml::Node& v) const {
        if (v.is_array()) {
            const auto n = v.size();
            if (!n || *n < 3) return std::nullopt;
            double c[3];
            for (std::size_t i = 0; i < 3; ++i) {
                const auto e = v.at(i);
                if (!e) return std::nullopt;
                const auto d = e->as_double();
                if (!d) return std::nullopt;
                c[i] = *d;
            }
            return Vec3{float(c[0]), float(c[1]), float(c[2])};
        }
        if (v.is_dictionary()) {
            const auto n = v.size();
            if (!n) return std::nullopt;
            std::optional<double> x, y, z;
            for (std::size_t i = 0; i < *n && i < 16; ++i) {
                const auto m = v.member(i);
                if (!m) continue;
                const std::string k = norm(key_text(*m));
                if (cx.count(k)) x = m->value.as_double();
                else if (cy.count(k)) y = m->value.as_double();
                else if (cz.count(k)) z = m->value.as_double();
            }
            if (x && y && z) return Vec3{float(*x), float(*y), float(*z)};
        }
        return std::nullopt;
    }

    void census(const std::string& key, const byml::Node& v) {
        if (!cfg.key_census) return;
        KeyStat& s = catalog.census(key);
        ++s.count;
        if (const auto str = v.as_string()) {
            ++s.strings;
            if (s.sample.empty()) s.sample = std::string(str->substr(0, 80));
        } else if (v.is_number()) {
            ++s.numbers;
        } else if (v.is_container()) {
            ++s.containers;
        } else {
            ++s.other;
        }
    }

    void path_like(std::string_view s, std::string_view via, const Transform* t) {
        if (!cfg.scan_path_like_strings) return;
        if (const auto c = category_by_extension(s)) record(*c, s, via, t);
    }

    void walk(const byml::Node& n, std::size_t depth, const Transform* outer, std::optional<Category> inherited,
              std::string_view via) {
        if (!n.is_container()) return;
        if (++nodes > cfg.max_nodes) {
            if (!budget_noted) diag(Diagnostic::Level::warning, "the node budget (max_nodes) ran out; the rest is not walked");
            budget_noted = true;
            return;
        }
        if (depth > cfg.max_depth) {
            if (!depth_noted) diag(Diagnostic::Level::warning, "nesting deeper than max_depth is not walked");
            depth_noted = true;
            return;
        }
        if (std::find(path.begin(), path.end(), n.offset()) != path.end()) {
            diag(Diagnostic::Level::warning, "a container refers back to itself at " + hex_string(n.offset()));
            return;
        }
        path.push_back(n.offset());
        if (n.is_dictionary())
            walk_dictionary(n, depth, outer, inherited);
        else
            walk_array(n, depth, outer, inherited, via);
        path.pop_back();
    }

    void walk_array(const byml::Node& n, std::size_t depth, const Transform* outer, std::optional<Category> inherited,
                    std::string_view via) {
        const auto count = n.size();
        if (!count) {
            diag(Diagnostic::Level::warning, count.error().message);
            return;
        }
        for (std::size_t i = 0; i < *count; ++i) {
            const auto e = n.at(i);
            if (!e) {
                diag(Diagnostic::Level::warning, e.error().message);
                return;
            }
            if (const auto s = e->as_string()) {
                if (inherited)
                    record(*inherited, *s, via, outer);
                else
                    path_like(*s, via, outer);
            } else if (e->is_container()) {
                walk(*e, depth + 1, outer, inherited, via);
            }
        }
    }

    struct Entry {
        std::string text;  // the key as written (or the hash, named when hash_names has it)
        std::string key;   // normalized
        byml::Node value;
    };

    void walk_dictionary(const byml::Node& n, std::size_t depth, const Transform* outer,
                         std::optional<Category> inherited) {
        const auto count = n.size();
        if (!count) {
            diag(Diagnostic::Level::warning, count.error().message);
            return;
        }
        std::vector<Entry> entries;
        entries.reserve(std::min<std::size_t>(*count, 4096));   // (a damaged count must not reserve gigabytes)
        for (std::size_t i = 0; i < *count; ++i) {
            const auto m = n.member(i);
            if (!m) {
                diag(Diagnostic::Level::warning, m.error().message);
                break;
            }
            Entry e{key_text(*m), {}, m->value};
            e.key = norm(e.text);
            census(e.text, e.value);
            entries.push_back(std::move(e));
        }

        // This dictionary's transform, if it has one; otherwise the placement around it applies
        Transform t;
        for (const auto& e : entries) {
            if (!t.translate && tr.count(e.key)) t.translate = vec3(e.value);
            else if (!t.rotate && rot.count(e.key)) t.rotate = vec3(e.value);
            else if (!t.scale && scl.count(e.key)) t.scale = vec3(e.value);
        }
        const bool placed = !t.empty();
        const Transform* here = placed ? &t : outer;

        // Its actor: the best-ranked actor key with a name (weak keys count only beside a transform)
        std::size_t actor = entries.size(), best = std::numeric_limits<std::size_t>::max();
        std::string actor_name;
        for (std::size_t i = 0; i < entries.size(); ++i) {
            std::size_t rank;
            if (const auto it = actor_rank.find(entries[i].key); it != actor_rank.end())
                rank = it->second;
            else if (placed && weak_actor.count(entries[i].key))
                rank = actor_rank.size() + 1;
            else
                continue;
            if (rank >= best) continue;
            if (auto name = name_of(entries[i].value)) {
                best = rank;
                actor = i;
                actor_name = std::move(*name);
            }
        }
        if (actor < entries.size()) record(Category::actor, actor_name, entries[actor].text, here);

        for (std::size_t i = 0; i < entries.size(); ++i) {
            if (i == actor) continue;
            const Entry& e = entries[i];
            if (const auto r = resource.find(e.key); r != resource.end()) {
                if (const auto s = e.value.as_string())
                    record(r->second, *s, e.text, here);
                else if (auto h = e.value.is_number() ? name_of(e.value) : std::nullopt)
                    record(r->second, *h, e.text, here);
                else if (e.value.is_container())
                    walk(e.value, depth + 1, here, r->second, e.text);
                continue;
            }
            if (inherited && name_keys.count(e.key)) {
                if (const auto s = e.value.as_string()) {
                    record(*inherited, *s, e.text, here);
                    continue;
                }
            }
            if (const auto s = e.value.as_string()) {
                path_like(*s, e.text, here);
                continue;
            }
            if (e.value.is_container()) walk(e.value, depth + 1, here, std::nullopt, e.text);
        }
    }

    // ------------------------------------------------------------------------------------------ layers
    bool has_map_suffix(std::string_view name) const { return ends_with_any(lower(name), map_suffixes); }

    Status layer(Bytes data, const std::string& src, std::size_t nesting) {
        source = src;
        if (nesting > cfg.max_nesting) {
            diag(Diagnostic::Level::error, "more than max_nesting layers of zstd / SARC");
            return fail(Errc::limit, src + ": too many nested layers");
        }
        if (is_zstd_frame(data)) {
            auto raw = zstd_decompress(data, dicts.get(), ZstdOptions{cfg.max_decompressed});
            if (!raw) {
                diag(Diagnostic::Level::error, raw.error().message);
                return Unexpected(raw.error());
            }
            return layer(*raw, src, nesting + 1);
        }
        if (is_sarc(data)) {
            auto sarc = SarcReader::open(data);
            if (!sarc) {
                diag(Diagnostic::Level::error, sarc.error().message);
                return Unexpected(sarc.error());
            }
            for (const auto& e : *sarc) {
                const bool scan = byml::is_byml(e.data) || is_sarc(e.data) || (is_zstd_frame(e.data) && has_map_suffix(e.name));
                if (!scan) continue;
                const std::string inner =
                    src + ":" + (e.name.empty() ? hex_string(e.name_hash) : std::string(e.name));
                (void)layer(e.data, inner, nesting + 1);   // (a damaged member is a diagnostic; the rest go on)
                source = src;
            }
            return {};
        }
        if (byml::is_byml(data)) {
            auto doc = byml::Document::parse(data);
            if (!doc) {
                diag(Diagnostic::Level::error, doc.error().message);
                return Unexpected(doc.error());
            }
            catalog.add_map(src);
            nodes = 0;
            budget_noted = depth_noted = false;
            path.clear();
            if (const auto root = doc->root()) walk(*root, 0, nullptr, std::nullopt, {});
            return {};
        }
        diag(Diagnostic::Level::info, "not a map: no zstd, SARC or BYML magic");
        return fail(Errc::bad_magic, src + ": not zstd, SARC or BYML");
    }
};

// ---------------------------------------------------------------------------------------------- MapScraper
MapScraper::MapScraper() : MapScraper(ScraperConfig{}) {}
MapScraper::MapScraper(ScraperConfig config) : impl_(std::make_unique<Impl>()) { impl_->cfg = std::move(config); }
MapScraper::~MapScraper() = default;
MapScraper::MapScraper(MapScraper&&) noexcept = default;
MapScraper& MapScraper::operator=(MapScraper&&) noexcept = default;

ScraperConfig& MapScraper::config() noexcept { return impl_->cfg; }
const ScraperConfig& MapScraper::config() const noexcept { return impl_->cfg; }
const Catalog& MapScraper::catalog() const noexcept { return impl_->catalog; }
void MapScraper::clear() { impl_->catalog.clear(); }

void MapScraper::set_dictionaries(std::shared_ptr<const ZstdDictionarySet> d) { impl_->dicts = std::move(d); }
void MapScraper::set_romfs_index(std::shared_ptr<const RomfsIndex> i) { impl_->index = std::move(i); }

Status MapScraper::load_romfs(const std::filesystem::path& root) {
    auto index = RomfsIndex::from_directory(root);
    if (!index) return Unexpected(index.error());
    impl_->index = std::make_shared<RomfsIndex>(std::move(*index));
    const auto zsdic = root / "Pack" / "ZsDic.pack.zs";
    std::error_code ec;
    if (!std::filesystem::exists(zsdic, ec)) {
        impl_->catalog.add_diagnostic({Diagnostic::Level::info, utf8_of(root),
                                       "no Pack/ZsDic.pack.zs: frames that need a dictionary will not open"});
        return {};
    }
    auto data = read_file(zsdic, impl_->cfg.max_file_size);
    if (!data) return Unexpected(data.error());
    auto dicts = ZstdDictionarySet::from_zsdic_pack(*data, ZstdOptions{impl_->cfg.max_decompressed});
    if (!dicts) return Unexpected(dicts.error());
    impl_->dicts = std::make_shared<ZstdDictionarySet>(std::move(*dicts));
    return {};
}

Status MapScraper::scan_buffer(Bytes data, std::string_view source_name) {
    impl_->compile();
    return impl_->layer(data, std::string(source_name), 0);
}

Status MapScraper::scan_file(const std::filesystem::path& file, std::string_view source_name) {
    auto data = read_file(file, impl_->cfg.max_file_size);
    const std::string src = source_name.empty() ? utf8_of(file) : std::string(source_name);
    if (!data) {
        impl_->catalog.add_diagnostic({Diagnostic::Level::error, src, data.error().message});
        return Unexpected(data.error());
    }
    return scan_buffer(*data, src);
}

Status MapScraper::scan_directory(const std::filesystem::path& folder) {
    impl_->compile();
    std::error_code ec;
    std::vector<std::filesystem::path> files;
    const auto opts = std::filesystem::directory_options::skip_permission_denied;
    for (auto it = std::filesystem::recursive_directory_iterator(folder, opts, ec);
         !ec && it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        if (it->is_regular_file(ec) && impl_->has_map_suffix(utf8_of(it->path().filename()))) files.push_back(it->path());
    }
    if (ec) return fail(Errc::io, "listing " + utf8_of(folder) + ": " + ec.message());
    std::sort(files.begin(), files.end());
    if (files.empty())
        impl_->catalog.add_diagnostic({Diagnostic::Level::warning, utf8_of(folder), "no file with a map's name here"});
    for (const auto& f : files) (void)scan_file(f, utf8_of(std::filesystem::relative(f, folder, ec)));
    return {};
}

Status MapScraper::scan_path(const std::filesystem::path& p) {
    std::error_code ec;
    if (std::filesystem::is_directory(p, ec)) return scan_directory(p);
    return scan_file(p);
}

Status MapScraper::scan_index(const RomfsIndex& index, const ReadFn& read) {
    impl_->compile();
    for (const auto& p : index.paths()) {
        if (!impl_->has_map_suffix(p)) continue;
        auto data = read(p);
        if (!data) {
            impl_->catalog.add_diagnostic({Diagnostic::Level::error, p, data.error().message});
            continue;
        }
        (void)impl_->layer(*data, p, 0);
    }
    return {};
}

Status MapScraper::scan_romfs() {
    if (!impl_->index || impl_->index->root().empty())
        return fail(Errc::not_found, "no romfs folder loaded (load_romfs)");
    const auto root = impl_->index->root();
    const std::size_t max = impl_->cfg.max_file_size;
    return scan_index(*impl_->index, [&](std::string_view p) { return read_file(root / path_from_utf8(p), max); });
}

std::size_t MapScraper::resolve() {
    Impl& s = *impl_;
    if (!s.index) {
        s.catalog.add_diagnostic({Diagnostic::Level::warning, {}, "no romfs index: nothing resolved"});
        return 0;
    }
    s.compile();
    const RomfsIndex& index = *s.index;
    std::size_t missing = 0;
    for (AssetRecord& r : s.catalog.mutable_records()) {
        r.resolved_paths.clear();
        auto take = [&](std::string_view candidate) {
            if (const auto c = index.canonical(candidate)) {
                if (std::find(r.resolved_paths.begin(), r.resolved_paths.end(), *c) == r.resolved_paths.end())
                    r.resolved_paths.emplace_back(*c);
            }
        };
        const std::string stem_lower = RomfsIndex::stem_of(r.name);
        // (the stem with its case, for patterns: the romfs is matched in any case, but the path reported keeps its own)
        std::string stem = r.name.substr(r.name.find_last_of('/') == std::string::npos ? 0 : r.name.find_last_of('/') + 1);
        stem = stem.substr(0, stem.find('.'));
        take(r.name);
        take(r.name + ".zs");
        for (const auto& rule : s.cfg.resolve_rules) {
            if (rule.category != r.category) continue;
            std::string p = rule.pattern;
            const std::pair<std::string_view, std::string_view> fills[] = {{"{name}", r.name}, {"{stem}", stem}};
            for (const auto& [ph, val] : fills) {
                for (std::size_t at = p.find(ph); at != std::string::npos; at = p.find(ph, at + val.size()))
                    p.replace(at, ph.size(), val);
            }
            take(p);
        }
        if (r.resolved_paths.empty() && s.cfg.resolve_by_stem && !stem_lower.empty()) {
            for (const auto p : index.by_stem(stem_lower))
                if (s.category_by_extension(p) == r.category) take(p);
        }
        r.resolution = r.resolved_paths.empty() ? Resolution::missing : Resolution::found;
        if (r.resolution == Resolution::missing) ++missing;
    }
    return missing;
}

// ---------------------------------------------------------------------------------------------- JSON
namespace {
void write_vec(JsonWriter& w, const char* key, const std::optional<Vec3>& v) {
    w.key(key);
    if (!v) {
        w.null();
        return;
    }
    w.begin_array().num(v->x).num(v->y).num(v->z).end_array();
}
}  // namespace

std::string MapScraper::to_json(const JsonOptions& o) const {
    const Catalog& c = impl_->catalog;
    JsonWriter w(o.pretty);
    w.begin_object();
    w.key("format").str("longshot-map-scraper");
    w.key("format_version").uint(1);

    w.key("maps_scanned").begin_array();
    for (const auto& m : c.maps_scanned()) w.str(m);
    w.end_array();

    w.key("assets").begin_array();
    for (const AssetRecord* r : c.sorted()) {
        w.begin_object();
        w.key("asset_name_or_path").str(r->name);
        w.key("category").str(category_name(r->category));
        w.key("instance_count").uint(r->instance_count);
        w.key("source_map").str(r->source_map);
        w.key("via_key").str(r->via_key);
        w.key("sample_transform");
        if (r->sample_transform) {
            w.begin_object();
            write_vec(w, "translate", r->sample_transform->translate);
            write_vec(w, "rotate", r->sample_transform->rotate);
            write_vec(w, "scale", r->sample_transform->scale);
            w.end_object();
        } else {
            w.null();
        }
        w.key("resolution").str(resolution_name(r->resolution));
        if (r->resolution != Resolution::not_checked) {
            w.key("resolved_paths").begin_array();
            for (const auto& p : r->resolved_paths) w.str(p);
            w.end_array();
        }
        w.end_object();
    }
    w.end_array();

    if (o.include_summary) {
        w.key("summary").begin_array();
        for (const auto& a : c.aggregate()) {
            w.begin_object();
            w.key("asset_name_or_path").str(a.name);
            w.key("category").str(category_name(a.category));
            w.key("instance_count").uint(a.instance_count);
            w.key("maps").begin_array();
            for (const auto& m : a.maps) w.str(m);
            w.end_array();
            w.key("resolution").str(resolution_name(a.resolution));
            w.end_object();
        }
        w.end_array();
    }

    w.key("unresolved").begin_array();
    for (const AssetRecord* r : c.unresolved()) {
        w.begin_object();
        w.key("asset_name_or_path").str(r->name);
        w.key("category").str(category_name(r->category));
        w.key("source_map").str(r->source_map);
        w.end_object();
    }
    w.end_array();

    w.key("diagnostics").begin_array();
    for (const auto& d : c.diagnostics()) {
        w.begin_object();
        w.key("level").str(level_name(d.level));
        w.key("source").str(d.source);
        w.key("message").str(d.message);
        w.end_object();
    }
    w.end_array();

    if (o.include_census) {
        std::vector<std::pair<std::string_view, const KeyStat*>> keys;
        for (const auto& [k, s] : c.key_census()) keys.emplace_back(k, &s);
        std::stable_sort(keys.begin(), keys.end(), [](const auto& a, const auto& b) { return a.second->count > b.second->count; });
        if (keys.size() > o.census_limit) keys.resize(o.census_limit);
        w.key("key_census").begin_array();
        for (const auto& [k, s] : keys) {
            w.begin_object();
            w.key("key").str(k);
            w.key("count").uint(s->count);
            w.key("strings").uint(s->strings);
            w.key("numbers").uint(s->numbers);
            w.key("containers").uint(s->containers);
            w.key("other").uint(s->other);
            w.key("sample").str(s->sample);
            w.end_object();
        }
        w.end_array();
    }
    w.end_object();
    std::string out = w.take();
    out += '\n';
    return out;
}

}  // namespace lsms
