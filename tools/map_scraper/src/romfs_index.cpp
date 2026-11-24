// lsms: the romfs file list.
#include "lsms/romfs_index.hpp"

#include <algorithm>
#include <fstream>
#include <system_error>

namespace lsms {

namespace {
std::string lower(std::string_view s) {
    std::string o(s);
    for (char& c : o)
        if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
    return o;
}
}  // namespace

std::filesystem::path path_from_utf8(std::string_view utf8) {
    return std::filesystem::path(std::u8string(utf8.begin(), utf8.end()));
}

std::string utf8_of(const std::filesystem::path& path) {
    const std::u8string u = path.generic_u8string();
    return std::string(u.begin(), u.end());
}

std::string RomfsIndex::normalize(std::string_view path) {
    std::string p(path);
    std::replace(p.begin(), p.end(), '\\', '/');
    std::size_t start = 0;
    while (true) {
        if (p.compare(start, 2, "./") == 0)
            start += 2;
        else if (start < p.size() && p[start] == '/')
            start += 1;
        else
            break;
    }
    return p.substr(start);
}

std::string RomfsIndex::stem_of(std::string_view path) {
    const std::size_t slash = path.find_last_of("/\\");
    std::string_view file = slash == std::string_view::npos ? path : path.substr(slash + 1);
    const std::size_t dot = file.find('.');
    if (dot != std::string_view::npos && dot > 0) file = file.substr(0, dot);
    return lower(file);
}

void RomfsIndex::add(std::string_view path) {
    std::string p = normalize(path);
    if (p.empty()) return;
    std::string key = lower(p);
    if (by_path_.count(key)) return;
    const std::size_t i = paths_.size();
    by_stem_.emplace(stem_of(p), i);
    by_path_.emplace(std::move(key), i);
    paths_.push_back(std::move(p));
}

bool RomfsIndex::contains(std::string_view path) const { return by_path_.count(lower(normalize(path))) != 0; }

std::optional<std::string_view> RomfsIndex::canonical(std::string_view path) const {
    const auto it = by_path_.find(lower(normalize(path)));
    if (it == by_path_.end()) return std::nullopt;
    return std::string_view(paths_[it->second]);
}

std::vector<std::string_view> RomfsIndex::by_stem(std::string_view stem) const {
    std::vector<std::string_view> out;
    const auto range = by_stem_.equal_range(lower(stem));
    for (auto it = range.first; it != range.second; ++it) out.emplace_back(paths_[it->second]);
    std::sort(out.begin(), out.end());
    return out;
}

Expected<RomfsIndex> RomfsIndex::from_directory(const std::filesystem::path& root) {
    std::error_code ec;
    if (!std::filesystem::is_directory(root, ec)) return fail(Errc::not_found, "no folder " + utf8_of(root));
    RomfsIndex index;
    index.root_ = root;
    std::vector<std::string> found;
    const auto opts = std::filesystem::directory_options::skip_permission_denied;
    for (auto it = std::filesystem::recursive_directory_iterator(root, opts, ec);
         !ec && it != std::filesystem::recursive_directory_iterator(); it.increment(ec)) {
        if (!it->is_regular_file(ec)) continue;
        found.push_back(utf8_of(std::filesystem::relative(it->path(), root, ec)));
    }
    if (ec) return fail(Errc::io, "listing " + utf8_of(root) + ": " + ec.message());
    std::sort(found.begin(), found.end());
    for (const auto& p : found) index.add(p);
    return index;
}

Expected<RomfsIndex> RomfsIndex::from_list_file(const std::filesystem::path& list) {
    std::ifstream in(list, std::ios::binary);
    if (!in) return fail(Errc::io, "cannot read " + utf8_of(list));
    RomfsIndex index;
    std::string line;
    while (std::getline(in, line)) {
        while (!line.empty() && (line.back() == '\r' || line.back() == ' ' || line.back() == '\t')) line.pop_back();
        if (line.empty() || line[0] == '#') continue;
        index.add(line);
    }
    return index;
}

}  // namespace lsms
