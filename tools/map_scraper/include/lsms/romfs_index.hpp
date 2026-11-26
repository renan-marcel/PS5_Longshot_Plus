// lsms: the romfs's file list, for resolving the names a map gives to the files that hold them.
//
// Paths are UTF-8, '/'-separated and relative to the romfs root ("Pack/Actor/X.pack.zs"); lookups ignore ASCII case.
// The index is built from a folder, from a text list (one path per line), or path by path (add) from any other lister,
// such as an archive's table of contents.
#pragma once

#include <cstddef>
#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>
#include <vector>

#include "lsms/expected.hpp"

namespace lsms {

/// A UTF-8 string as a filesystem path, and back (never through the Windows ANSI code page)
std::filesystem::path path_from_utf8(std::string_view utf8);
std::string utf8_of(const std::filesystem::path& path);

class RomfsIndex {
public:
    static Expected<RomfsIndex> from_directory(const std::filesystem::path& root);
    static Expected<RomfsIndex> from_list_file(const std::filesystem::path& list);

    void add(std::string_view path);
    bool contains(std::string_view path) const;
    /// The path as stored, for a lookup in any case
    std::optional<std::string_view> canonical(std::string_view path) const;
    /// Every path whose file name, up to its first '.', is this (any case)
    std::vector<std::string_view> by_stem(std::string_view stem) const;

    const std::vector<std::string>& paths() const noexcept { return paths_; }
    std::size_t size() const noexcept { return paths_.size(); }
    /// The folder it was built from; empty for a list
    const std::filesystem::path& root() const noexcept { return root_; }

    /// '\' to '/', no leading "./" or "/"
    static std::string normalize(std::string_view path);
    /// The file name up to its first '.', lower case: "Model/Obj_Chest.bfres.zs" -> "obj_chest"
    static std::string stem_of(std::string_view path);

private:
    std::vector<std::string> paths_;
    std::unordered_map<std::string, std::size_t> by_path_;  // lower-case path -> index
    std::unordered_multimap<std::string, std::size_t> by_stem_;
    std::filesystem::path root_;
};

}  // namespace lsms
