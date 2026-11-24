// lsms: the C interface (lsms.h) over MapScraper. No exception crosses it.
#define LSMS_BUILDING 1
#include "lsms/lsms.h"

#include <cstdlib>
#include <cstring>
#include <new>
#include <optional>
#include <string>

#include "lsms/map_scraper.hpp"

struct lsms_scraper {
    lsms::MapScraper scraper;
    std::string error;
};

namespace {

template <class F> lsms_result guarded(lsms_scraper* s, F&& f) {
    if (!s) return LSMS_E_INVALID_ARGUMENT;
    try {
        s->error.clear();
        return f();
    } catch (const std::bad_alloc&) {
        s->error = "out of memory";
        return LSMS_E_NO_MEMORY;
    } catch (const std::exception& e) {
        s->error = e.what();
        return LSMS_E_FAILED;
    } catch (...) {
        s->error = "unknown failure";
        return LSMS_E_FAILED;
    }
}

lsms_result from_status(lsms_scraper* s, const lsms::Status& st) {
    if (st) return LSMS_OK;
    s->error = std::string(lsms::errc_name(st.error().code)) + ": " + st.error().message;
    return LSMS_E_FAILED;
}

std::optional<lsms::Category> category(lsms_scraper* s, const char* name) {
    auto c = name ? lsms::category_from_name(name) : std::nullopt;
    if (!c) s->error = std::string("unknown category: ") + (name ? name : "(null)");
    return c;
}

}  // namespace

extern "C" {

int lsms_api_version(void) { return LSMS_C_API_VERSION; }

lsms_scraper* lsms_create(void) {
    try {
        return new lsms_scraper{};
    } catch (...) {
        return nullptr;
    }
}

void lsms_destroy(lsms_scraper* s) { delete s; }

lsms_result lsms_add_actor_key(lsms_scraper* s, const char* key) {
    return guarded(s, [&] {
        if (!key || !*key) return LSMS_E_INVALID_ARGUMENT;
        s->scraper.config().actor_keys.emplace_back(key);
        return LSMS_OK;
    });
}

lsms_result lsms_add_resource_key(lsms_scraper* s, const char* cat, const char* key) {
    return guarded(s, [&] {
        const auto c = category(s, cat);
        if (!c || !key || !*key) return LSMS_E_INVALID_ARGUMENT;
        // (inserted first, so that it wins over a default rule for the same key)
        auto& rules = s->scraper.config().resource_keys;
        rules.insert(rules.begin(), lsms::KeyRule{key, *c});
        return LSMS_OK;
    });
}

lsms_result lsms_add_extension_rule(lsms_scraper* s, const char* cat, const char* suffix) {
    return guarded(s, [&] {
        const auto c = category(s, cat);
        if (!c || !suffix || !*suffix) return LSMS_E_INVALID_ARGUMENT;
        s->scraper.config().extension_rules.push_back(lsms::ExtensionRule{suffix, *c});
        return LSMS_OK;
    });
}

lsms_result lsms_add_resolve_rule(lsms_scraper* s, const char* cat, const char* pattern) {
    return guarded(s, [&] {
        const auto c = category(s, cat);
        if (!c || !pattern || !*pattern) return LSMS_E_INVALID_ARGUMENT;
        s->scraper.config().resolve_rules.push_back(lsms::ResolveRule{*c, pattern});
        return LSMS_OK;
    });
}

lsms_result lsms_set_option(lsms_scraper* s, const char* name, int value) {
    return guarded(s, [&] {
        if (!name) return LSMS_E_INVALID_ARGUMENT;
        auto& cfg = s->scraper.config();
        const std::string n = name;
        if (n == "case_insensitive_keys") cfg.case_insensitive_keys = value != 0;
        else if (n == "scan_path_like_strings") cfg.scan_path_like_strings = value != 0;
        else if (n == "resolve_by_stem") cfg.resolve_by_stem = value != 0;
        else if (n == "key_census") cfg.key_census = value != 0;
        else {
            s->error = "unknown option: " + n;
            return LSMS_E_INVALID_ARGUMENT;
        }
        return LSMS_OK;
    });
}

lsms_result lsms_load_romfs(lsms_scraper* s, const char* dir) {
    return guarded(s, [&] {
        if (!dir) return LSMS_E_INVALID_ARGUMENT;
        return from_status(s, s->scraper.load_romfs(lsms::path_from_utf8(dir)));
    });
}

lsms_result lsms_scan_path(lsms_scraper* s, const char* path) {
    return guarded(s, [&] {
        if (!path) return LSMS_E_INVALID_ARGUMENT;
        return from_status(s, s->scraper.scan_path(lsms::path_from_utf8(path)));
    });
}

lsms_result lsms_scan_buffer(lsms_scraper* s, const void* data, size_t size, const char* source_name) {
    return guarded(s, [&] {
        if (!data && size) return LSMS_E_INVALID_ARGUMENT;
        return from_status(s, s->scraper.scan_buffer(lsms::bytes_of(data, size), source_name ? source_name : "(buffer)"));
    });
}

lsms_result lsms_scan_romfs(lsms_scraper* s) {
    return guarded(s, [&] { return from_status(s, s->scraper.scan_romfs()); });
}

long long lsms_resolve(lsms_scraper* s) {
    long long missing = 0;
    const lsms_result r = guarded(s, [&] {
        missing = static_cast<long long>(s->scraper.resolve());
        return LSMS_OK;
    });
    return r == LSMS_OK ? missing : static_cast<long long>(r);
}

size_t lsms_record_count(const lsms_scraper* s) { return s ? s->scraper.catalog().records().size() : 0; }

char* lsms_to_json(const lsms_scraper* s, int pretty, int include_census) {
    if (!s) return nullptr;
    try {
        lsms::JsonOptions o;
        o.pretty = pretty != 0;
        o.include_census = include_census != 0;
        const std::string json = s->scraper.to_json(o);
        char* out = static_cast<char*>(std::malloc(json.size() + 1));
        if (!out) return nullptr;
        std::memcpy(out, json.c_str(), json.size() + 1);
        return out;
    } catch (...) {
        return nullptr;
    }
}

void lsms_free(void* p) { std::free(p); }

const char* lsms_last_error(const lsms_scraper* s) { return s ? s->error.c_str() : "null handle"; }

}  // extern "C"
