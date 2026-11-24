/* PS5: the report a break leaves in bug-reports/ (host/ps5/ps5_bug_report.c). */
#ifndef HOS_PS5_BUG_REPORT_H
#define HOS_PS5_BUG_REPORT_H
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
/* The log's text as it is written (host/hos_thread.c): the last 64 KB are kept for a report. */
void hos_ps5_log_keep(const char *s, size_t n);
/* A report folder under title_dir/bug-reports: kind "crash" or "freeze", the reason (a fixed label), a detail (or NULL), and
   the facts the caller gathered ("Name: value" lines). 1 when written; made gets its folder. */
int hos_ps5_bug_report_write(const char *title_dir, const char *kind, const char *reason, const char *detail,
                             const char *facts, char *made, size_t made_cap);
/* (host/ps5/win32_ps5.c) The same with the facts the title has: once per run and kind. */
void hos_ps5_bug_report(const char *kind, const char *reason, const char *detail);
#ifdef __cplusplus
}
#endif
#endif
