/* lsms: the stable C interface, for other languages (Python ctypes/cffi, C#, Rust, Lua...).
 *
 * Strings in and out are UTF-8. A scraper handle is used by one thread at a time. Strings the library returns
 * (lsms_to_json) are freed with lsms_free; lsms_last_error's string belongs to the handle and lives until the next call.
 * The interface only grows: a change to an existing function bumps LSMS_C_API_VERSION.
 */
#ifndef LSMS_H
#define LSMS_H

#include <stddef.h>

#if defined(LSMS_SHARED)
#  if defined(_WIN32)
#    if defined(LSMS_BUILDING)
#      define LSMS_API __declspec(dllexport)
#    else
#      define LSMS_API __declspec(dllimport)
#    endif
#  elif defined(__GNUC__)
#    define LSMS_API __attribute__((visibility("default")))
#  endif
#endif
#ifndef LSMS_API
#  define LSMS_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

#define LSMS_C_API_VERSION 1

typedef struct lsms_scraper lsms_scraper;

typedef enum lsms_result {
    LSMS_OK = 0,
    LSMS_E_INVALID_ARGUMENT = -1,
    LSMS_E_FAILED = -2, /* lsms_last_error says why */
    LSMS_E_NO_MEMORY = -3
} lsms_result;

LSMS_API int lsms_api_version(void);

LSMS_API lsms_scraper* lsms_create(void);
LSMS_API void lsms_destroy(lsms_scraper* s);

/* Rules, on top of the defaults. category: "actor", "model", "texture", "collision", "effect", "submap", "unknown" */
LSMS_API lsms_result lsms_add_actor_key(lsms_scraper* s, const char* key);
LSMS_API lsms_result lsms_add_resource_key(lsms_scraper* s, const char* category, const char* key);
LSMS_API lsms_result lsms_add_extension_rule(lsms_scraper* s, const char* category, const char* suffix);
LSMS_API lsms_result lsms_add_resolve_rule(lsms_scraper* s, const char* category, const char* pattern);
/* name: "case_insensitive_keys", "scan_path_like_strings", "resolve_by_stem", "key_census" (0 or 1) */
LSMS_API lsms_result lsms_set_option(lsms_scraper* s, const char* name, int value);

LSMS_API lsms_result lsms_load_romfs(lsms_scraper* s, const char* romfs_dir);
LSMS_API lsms_result lsms_scan_path(lsms_scraper* s, const char* file_or_dir);
LSMS_API lsms_result lsms_scan_buffer(lsms_scraper* s, const void* data, size_t size, const char* source_name);
LSMS_API lsms_result lsms_scan_romfs(lsms_scraper* s);
/* The number of records left missing, or a negative lsms_result */
LSMS_API long long lsms_resolve(lsms_scraper* s);

LSMS_API size_t lsms_record_count(const lsms_scraper* s);
/* The catalogue as JSON (see README for its shape), or NULL; free with lsms_free */
LSMS_API char* lsms_to_json(const lsms_scraper* s, int pretty, int include_census);
LSMS_API void lsms_free(void* p);
LSMS_API const char* lsms_last_error(const lsms_scraper* s);

#ifdef __cplusplus
}
#endif

#endif /* LSMS_H */
