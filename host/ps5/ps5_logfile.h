/* (longshot, PS5) the title folder's logs/ files: stderr goes to klog only on the console, so what a person is asked to send
   back (logs/nfp.txt, logs/memory.txt, ...) is written to a file of its own here. host/ps5/ps5_logfile.c. */
#ifndef HOS_PS5_LOGFILE_H
#define HOS_PS5_LOGFILE_H

#ifdef __cplusplus
extern "C" {
#endif
/* Appends line and a newline to <title folder>/logs/<name> (logs/ made when missing), on disk at once. One lock for every
   file. A file reaching PS5_LOGFILE_CAP (1 MB) gets one last line saying it is full and no more this run; one already past
   it from an earlier run is started over. No title folder known: nothing is written. */
void hos_ps5_logfile(const char *name, const char *line);
#ifdef __cplusplus
}
#endif
#endif
