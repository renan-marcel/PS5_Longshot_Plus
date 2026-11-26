// lsms: the map scraper. Walks map and scene files and catalogues the assets they refer to.
//
// Input: a .byml / .bgyml / .bcett.byml, the same zstd-compressed (.zs), a SARC (.sarc, .pack, .pack.zs) holding
// any of them, a folder of those, or a RomfsIndex with a read callback. Layers are taken off by their magic, not by the
// file's name: zstd -> SARC -> BYML, nested as deep as ScraperConfig::max_nesting.
//
// The walk does not assume one schema. What counts as an actor's name, a resource reference or a transform is a set
// of rules in ScraperConfig (keys tried in order, file-name extensions, fallbacks), so a title of the same engine
// family with other key names needs a config, not a new walker. The key census (Catalog::key_census) lists every key
// seen, how often and with what values: the starting point for tuning the rules to a new title.
#pragma once

#include <array>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "lsms/binary_reader.hpp"
#include "lsms/expected.hpp"
#include "lsms/romfs_index.hpp"
#include "lsms/zstd_stream.hpp"

namespace lsms {

enum class Category : std::uint8_t { actor, model, texture, collision, effect, submap, unknown };
inline constexpr std::array<Category, 7> kAllCategories{Category::actor,  Category::model,  Category::texture,
                                                        Category::collision, Category::effect, Category::submap,
                                                        Category::unknown};
std::string_view category_name(Category c) noexcept;
std::optional<Category> category_from_name(std::string_view name) noexcept;

struct Vec3 {
    float x = 0, y = 0, z = 0;
};

struct Transform {
    std::optional<Vec3> translate, rotate, scale;
    bool empty() const noexcept { return !translate && !rotate && !scale; }
};

enum class Resolution : std::uint8_t { not_checked, found, missing };
std::string_view resolution_name(Resolution r) noexcept;

/// One asset as one map refers to it. Records are unique by (source_map, category, name).
struct AssetRecord {
    std::string name;  // asset_name_or_path: an actor's name, a resource's name or a romfs-relative path
    Category category = Category::unknown;
    std::uint64_t instance_count = 0;
    std::string source_map;  // "Banc/Field.bcett.byml.zs", or "Pack/X.pack.zs:Inner/Map.byml" inside an archive
    std::optional<Transform> sample_transform;  // the first placement seen with one
    std::string via_key;  // the key that found it first (".ext" rules give the key the string was under)
    Resolution resolution = Resolution::not_checked;
    std::vector<std::string> resolved_paths;  // romfs paths, after MapScraper::resolve
};

struct KeyRule {
    std::string key;
    Category category;
};
struct ExtensionRule {
    std::string suffix;  // matched at the end of a string, ignoring case and a trailing ".zs"
    Category category;
};
struct ResolveRule {
    Category category;
    std::string pattern;  // romfs path; {name} is the asset's name, {stem} its file name up to the first '.'
};

/// The heuristics. Every list has defaults for the Nintendo EPD BYML family (see README: they are starting points,
/// to be checked against this title's key census); replace or extend any of them.
struct ScraperConfig {
    /// Keys whose string (or hash) names the placed actor, best first. One dictionary holding one of them is one
    /// placement (instance) of that actor.
    std::vector<std::string> actor_keys{"Gyaml", "UnitConfigName", "ActorName", "Actor", "ActorType", "ObjectName",
                                        "ObjName", "PrefabName", "InstanceName"};
    /// Generic keys that name an actor only in a dictionary that also has a transform
    std::vector<std::string> weak_actor_keys{"Name", "Id", "Type"};
    /// Keys whose value (a string, a list of strings, or a dictionary with a name_keys member) is a resource
    std::vector<KeyRule> resource_keys{
        {"ModelName", Category::model},       {"Model", Category::model},           {"ModelPath", Category::model},
        {"Bfres", Category::model},           {"BfresName", Category::model},       {"FmdbName", Category::model},
        {"ModelProjectName", Category::model}, {"Texture", Category::texture},       {"TextureName", Category::texture},
        {"Bntx", Category::texture},          {"TexName", Category::texture},       {"Collision", Category::collision},
        {"CollisionName", Category::collision}, {"Phive", Category::collision},     {"PhiveShape", Category::collision},
        {"ShapeName", Category::collision},   {"Kcl", Category::collision},         {"Effect", Category::effect},
        {"EffectName", Category::effect},     {"Ptcl", Category::effect},           {"EsetName", Category::effect},
        {"SubMap", Category::submap},         {"SubMaps", Category::submap},        {"MapFile", Category::submap},
        {"MapName", Category::submap},        {"Banc", Category::submap},           {"Scene", Category::submap},
        {"Room", Category::submap},           {"ChildMap", Category::submap},       {"LinkedMap", Category::submap},
    };
    /// Inside a dictionary reached through a resource key: the keys whose string is that resource's name
    std::vector<std::string> name_keys{"Name", "Path", "File", "FilePath", "ResourceName", "Resource"};
    std::vector<std::string> translate_keys{"Translate", "Trans", "Translation", "Position", "Pos", "Location"};
    std::vector<std::string> rotate_keys{"Rotate", "Rot", "Rotation"};
    std::vector<std::string> scale_keys{"Scale", "Scl", "Scaling"};
    /// A vector as a dictionary: its components' keys (a vector as an array is [x, y, z])
    std::vector<std::string> x_keys{"X"}, y_keys{"Y"}, z_keys{"Z"};
    /// Strings anywhere that end in these are references of that category (when scan_path_like_strings)
    std::vector<ExtensionRule> extension_rules{
        {".engine__actor__actorparam.bgyml", Category::actor},
        {".pack", Category::actor},
        {".bfres", Category::model},
        {".bfmdl", Category::model},
        {".bntx", Category::texture},
        {".bftex", Category::texture},
        {".bphsh", Category::collision},
        {".bphsc", Category::collision},
        {".bphnm", Category::collision},
        {".bphcl", Category::collision},
        {".kcl", Category::collision},
        {".esetb.byml", Category::effect},
        {".esetb", Category::effect},
        {".ptcl", Category::effect},
        {".bcett.byml", Category::submap},
        {".bgyml", Category::unknown},
        {".byml", Category::unknown},
    };
    /// File names scanned as maps: in a folder walk, in an index, and zstd members of a SARC (BYML and SARC members
    /// are recognized by their magic whatever their names)
    std::vector<std::string> map_suffixes{".bcett.byml.zs", ".bcett.byml", ".byml.zs", ".byml",  ".bgyml.zs",
                                          ".bgyml",         ".pack.zs",    ".pack",     ".sarc.zs", ".sarc"};
    /// Where each category's assets live in the romfs, tried in order; the name itself and name + ".zs" are tried first
    std::vector<ResolveRule> resolve_rules{
        {Category::actor, "Pack/Actor/{stem}.pack.zs"},
        {Category::actor, "Actor/{stem}.engine__actor__ActorParam.bgyml"},
        {Category::model, "Model/{stem}.bfres.zs"},
        {Category::model, "Model/{stem}.bfres"},
        {Category::texture, "Model/{stem}.Tex.bntx.zs"},
        {Category::texture, "Tex/{stem}.bntx.zs"},
        {Category::collision, "Phive/Shape/Dcc/{stem}.bphsh.zs"},
        {Category::collision, "Phive/{stem}.bphsh.zs"},
        {Category::effect, "Effect/{stem}.esetb.byml.zs"},
        {Category::submap, "{name}.bcett.byml.zs"},
        {Category::submap, "Banc/{stem}.bcett.byml.zs"},
    };
    /// Names of hashed keys and hashed actor names (BYML v7 hash maps, uint ids), when a name table is at hand
    std::unordered_map<std::uint64_t, std::string> hash_names;

    bool case_insensitive_keys = true;
    bool scan_path_like_strings = true;
    bool resolve_by_stem = true;  // no rule matched: any romfs file of the same stem and category
    bool key_census = true;

    std::size_t max_depth = 256;       // BYML nesting
    std::size_t max_nesting = 8;       // zstd / SARC layers around a map
    std::size_t max_nodes = 50'000'000;  // per map: a walk budget against hostile files
    std::size_t max_file_size = std::size_t(4) << 30;
    std::size_t max_decompressed = std::size_t(1) << 30;
};

struct Diagnostic {
    enum class Level : std::uint8_t { info, warning, error } level = Level::info;
    std::string source;
    std::string message;
};
std::string_view level_name(Diagnostic::Level l) noexcept;

struct KeyStat {
    std::uint64_t count = 0, strings = 0, numbers = 0, containers = 0, other = 0;
    std::string sample;  // the first string value seen
};

/// One asset across every map that refers to it
struct AggregateRecord {
    std::string name;
    Category category = Category::unknown;
    std::uint64_t instance_count = 0;
    std::vector<std::string> maps;
    Resolution resolution = Resolution::not_checked;
};

class Catalog {
public:
    const std::vector<AssetRecord>& records() const noexcept { return records_; }
    std::vector<AssetRecord>& mutable_records() noexcept { return records_; }
    const AssetRecord* find(std::string_view source_map, Category category, std::string_view name) const;
    /// Finds or makes the record; `created` says which
    AssetRecord& upsert(std::string_view source_map, Category category, std::string_view name, bool& created);

    /// Sorted by category, then name
    std::vector<AggregateRecord> aggregate() const;
    std::vector<const AssetRecord*> unresolved() const;
    /// Sorted by source map, category, name
    std::vector<const AssetRecord*> sorted() const;

    const std::vector<std::string>& maps_scanned() const noexcept { return maps_; }
    void add_map(std::string source) { maps_.push_back(std::move(source)); }
    const std::vector<Diagnostic>& diagnostics() const noexcept { return diagnostics_; }
    void add_diagnostic(Diagnostic d) { diagnostics_.push_back(std::move(d)); }
    const std::map<std::string, KeyStat, std::less<>>& key_census() const noexcept { return census_; }
    KeyStat& census(std::string_view key);

    void clear();

private:
    std::vector<AssetRecord> records_;
    std::unordered_map<std::string, std::size_t> index_;
    std::vector<std::string> maps_;
    std::vector<Diagnostic> diagnostics_;
    std::map<std::string, KeyStat, std::less<>> census_;
};

struct JsonOptions {
    bool pretty = true;
    bool include_summary = true;
    bool include_census = false;
    std::size_t census_limit = 500;  // the most frequent keys
};

class MapScraper {
public:
    MapScraper();
    explicit MapScraper(ScraperConfig config);
    ~MapScraper();
    MapScraper(MapScraper&&) noexcept;
    MapScraper& operator=(MapScraper&&) noexcept;
    MapScraper(const MapScraper&) = delete;
    MapScraper& operator=(const MapScraper&) = delete;

    /// Changes apply from the next scan
    ScraperConfig& config() noexcept;
    const ScraperConfig& config() const noexcept;

    void set_dictionaries(std::shared_ptr<const ZstdDictionarySet> dictionaries);
    void set_romfs_index(std::shared_ptr<const RomfsIndex> index);
    /// The romfs folder's index, and its zstd dictionaries from Pack/ZsDic.pack.zs when present
    Status load_romfs(const std::filesystem::path& romfs_root);

    Status scan_path(const std::filesystem::path& file_or_folder);
    Status scan_file(const std::filesystem::path& file, std::string_view source_name = {});
    /// Every file under the folder whose name ends in one of config().map_suffixes; sources are relative to it
    Status scan_directory(const std::filesystem::path& folder);
    Status scan_buffer(Bytes data, std::string_view source_name);

    using ReadFn = std::function<Expected<std::vector<std::byte>>(std::string_view romfs_path)>;
    /// Every map the index lists, read through the callback (an archive, a network share, a test's memory)
    Status scan_index(const RomfsIndex& index, const ReadFn& read);
    /// The romfs index set or loaded (load_romfs): reads the files from its folder
    Status scan_romfs();

    /// Resolves every record against the romfs index; answers how many stay missing
    std::size_t resolve();

    const Catalog& catalog() const noexcept;
    void clear();
    std::string to_json(const JsonOptions& options = {}) const;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace lsms
