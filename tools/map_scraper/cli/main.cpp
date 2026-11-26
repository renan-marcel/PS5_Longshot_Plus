// lsms-scan: the map scraper from the command line.
//
//   lsms-scan [options] <map file or folder>...
//     --romfs DIR            the romfs folder: its file index (resolution) and Pack/ZsDic.pack.zs (dictionaries)
//     --all                  scan every map in --romfs (no inputs needed)
//     --index FILE           a list of romfs paths, one per line, to resolve against (instead of --romfs's own)
//     --out FILE             the JSON goes here (default: standard output)
//     --census               add the key census (every key seen, how often, with what values)
//     --actor-key KEY        another actor key, tried first (repeatable)
//     --resource-key CAT=KEY another resource key (repeatable); CAT: actor model texture collision effect submap unknown
//     --no-path-scan         do not catalogue strings by their file extension
//     --no-resolve           do not resolve against the romfs
//     --compact              JSON on one line
// Exit status: 0 done, 1 a scan failed, 2 bad arguments.
#include <cstdio>
#include <cstring>
#include <fstream>
#include <string>
#include <vector>

#include "lsms/map_scraper.hpp"

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#endif

namespace {

/// The arguments as UTF-8 (on Windows, from the wide command line: never through the ANSI code page)
std::vector<std::string> utf8_args(int argc, char** argv) {
    std::vector<std::string> out;
#ifdef _WIN32
    (void)argv;
    int n = 0;
    wchar_t** w = CommandLineToArgvW(GetCommandLineW(), &n);
    for (int i = 0; w && i < n; ++i) {
        const int len = WideCharToMultiByte(CP_UTF8, 0, w[i], -1, nullptr, 0, nullptr, nullptr);
        std::string s(len > 0 ? len - 1 : 0, '\0');
        if (len > 1) WideCharToMultiByte(CP_UTF8, 0, w[i], -1, s.data(), len, nullptr, nullptr);
        out.push_back(std::move(s));
    }
    if (w) LocalFree(w);
    (void)argc;
#else
    for (int i = 0; i < argc; ++i) out.emplace_back(argv[i]);
#endif
    return out;
}

int usage() {
    std::fputs("usage: lsms-scan [--romfs DIR] [--all] [--index FILE] [--out FILE] [--census] [--actor-key KEY]...\n"
               "                 [--resource-key CAT=KEY]... [--no-path-scan] [--no-resolve] [--compact] [INPUT]...\n",
               stderr);
    return 2;
}

}  // namespace

int main(int argc, char** argv) {
    const std::vector<std::string> args = utf8_args(argc, argv);
    std::string romfs, index_file, out_file;
    std::vector<std::string> inputs;
    bool all = false, census = false, resolve = true, compact = false;
    lsms::MapScraper scraper;
    auto& cfg = scraper.config();

    for (std::size_t i = 1; i < args.size(); ++i) {
        const std::string& a = args[i];
        auto next = [&]() -> const std::string* { return i + 1 < args.size() ? &args[++i] : nullptr; };
        if (a == "--romfs" || a == "--index" || a == "--out" || a == "--actor-key" || a == "--resource-key") {
            const std::string* v = next();
            if (!v) return usage();
            if (a == "--romfs") romfs = *v;
            else if (a == "--index") index_file = *v;
            else if (a == "--out") out_file = *v;
            else if (a == "--actor-key") cfg.actor_keys.insert(cfg.actor_keys.begin(), *v);
            else {
                const auto eq = v->find('=');
                const auto cat = eq == std::string::npos ? std::nullopt : lsms::category_from_name(v->substr(0, eq));
                if (!cat) {
                    std::fprintf(stderr, "lsms-scan: --resource-key wants CATEGORY=KEY, not %s\n", v->c_str());
                    return 2;
                }
                cfg.resource_keys.insert(cfg.resource_keys.begin(), lsms::KeyRule{v->substr(eq + 1), *cat});
            }
        } else if (a == "--all") all = true;
        else if (a == "--census") census = true;
        else if (a == "--no-path-scan") cfg.scan_path_like_strings = false;
        else if (a == "--no-resolve") resolve = false;
        else if (a == "--compact") compact = true;
        else if (a == "-h" || a == "--help") {
            usage();
            return 0;
        }
        else if (a.rfind("--", 0) == 0) return usage();
        else inputs.push_back(a);
    }
    if (inputs.empty() && !(all && !romfs.empty())) return usage();

    int status = 0;
    if (!romfs.empty()) {
        if (auto st = scraper.load_romfs(lsms::path_from_utf8(romfs)); !st) {
            std::fprintf(stderr, "lsms-scan: %s\n", st.error().message.c_str());
            return 1;
        }
    }
    if (!index_file.empty()) {
        auto index = lsms::RomfsIndex::from_list_file(lsms::path_from_utf8(index_file));
        if (!index) {
            std::fprintf(stderr, "lsms-scan: %s\n", index.error().message.c_str());
            return 1;
        }
        scraper.set_romfs_index(std::make_shared<lsms::RomfsIndex>(std::move(*index)));
    }
    if (all) {
        if (auto st = scraper.scan_romfs(); !st) {
            std::fprintf(stderr, "lsms-scan: %s\n", st.error().message.c_str());
            status = 1;
        }
    }
    for (const auto& in : inputs) {
        auto p = lsms::path_from_utf8(in);
        std::error_code ec;
        if (!std::filesystem::exists(p, ec) && !romfs.empty()) p = lsms::path_from_utf8(romfs) / p;   // (a romfs path)
        if (auto st = scraper.scan_path(p); !st) {
            std::fprintf(stderr, "lsms-scan: %s: %s\n", in.c_str(), st.error().message.c_str());
            status = 1;
        }
    }
    if (resolve && (!romfs.empty() || !index_file.empty())) {
        const std::size_t missing = scraper.resolve();
        std::fprintf(stderr, "lsms-scan: %zu references not found in the romfs\n", missing);
    }

    lsms::JsonOptions o;
    o.pretty = !compact;
    o.include_census = census;
    const std::string json = scraper.to_json(o);
    if (out_file.empty()) {
        std::fwrite(json.data(), 1, json.size(), stdout);
    } else {
        std::ofstream out(lsms::path_from_utf8(out_file), std::ios::binary);
        if (!out.write(json.data(), static_cast<std::streamsize>(json.size()))) {
            std::fprintf(stderr, "lsms-scan: cannot write %s\n", out_file.c_str());
            return 1;
        }
    }
    const auto& c = scraper.catalog();
    std::fprintf(stderr, "lsms-scan: %zu maps, %zu asset records, %zu diagnostics\n", c.maps_scanned().size(),
                 c.records().size(), c.diagnostics().size());
    return status;
}
