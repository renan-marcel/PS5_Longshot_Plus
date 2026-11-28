"""The host <-> menu bridge: MkwVkHost 27's amiibo and memory calls at the end, set by rx_backend.c's vk_host (source check)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from srccut import block, between

ROOT = Path(__file__).resolve().parent.parent
api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")


def code(text):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", text, flags=re.S))


def need(ok, msg):
    if not ok:
        raise SystemExit("FAIL: " + msg)


need(re.search(r"#define MKWVK_API_VERSION 27\b", api), "MKWVK_API_VERSION is not 27")
struct = code(between(api, "typedef struct MkwVkHost {", "} MkwVkHost;"))
fields = [re.search(r"\(\*(\w+)\)", d).group(1) for d in struct.split(";") if "(*" in d]
need(fields[-5:-1] == ["amiibo_status", "amiibo_select", "amiibo_touch", "amiibo_config"] and fields[-1] == "memory_usage",
     "the amiibo calls and memory callback are not MkwVkHost's last, in order: %s" % fields[-5:])
need(fields[-6] == "audio_output_state", "the new callbacks do not follow audio_output_state")
need(re.search(r"int \(\*amiibo_status\)\(void\);", struct), "amiibo_status signature")
need(re.search(r"void \(\*amiibo_select\)\(const uint8_t \*id, const char \*name\);", struct), "amiibo_select signature")
need(re.search(r"void \(\*amiibo_touch\)\(int on\);", struct), "amiibo_touch signature")
need(re.search(r"void \(\*amiibo_config\)\(int emulation, int random_uid, int auto_touch\);", struct), "amiibo_config signature")

table = [v.strip() for v in code(between(backend, "static const MkwVkHost vk_host = {", "};")).split(",") if v.strip()]
need(len(table) == len(fields) + 1, "vk_host's initializer and MkwVkHost differ in length")   # (+1: the version)
need(table[-5:] == ["vk_amiibo_status", "vk_amiibo_select", "vk_amiibo_touch", "vk_amiibo_config", "host_memory_usage"],
     "vk_host does not set the amiibo calls and memory callback last, in order")

sel = block(backend, "static void vk_amiibo_select(")
need("amiibo_select(NULL)" in sel and "amiibo_select(&f)" in sel, "vk_amiibo_select: NULL id / figure calls")
need("sizeof f.name - 1" in sel and "f.name[n] = 0" in sel, "vk_amiibo_select does not cut the name to 40 bytes + NUL")
need("amiibo_device_state()" in block(backend, "static int vk_amiibo_status("), "vk_amiibo_status")
touch = block(backend, "static void vk_amiibo_touch(")
need("amiibo_touch()" in touch and "amiibo_remove()" in touch, "vk_amiibo_touch")
need("amiibo_config(emulation, random_uid, auto_touch)" in block(backend, "static void vk_amiibo_config("), "vk_amiibo_config")
need('#include "amiibo_core.h"' in backend, "rx_backend.c does not include amiibo_core.h")
print("PASS: the amiibo bridge")
