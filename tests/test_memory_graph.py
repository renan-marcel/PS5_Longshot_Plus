"""The optional game's-memory overlay: bounded sampling, min/max, Gameplay toggle, and renderer/host API wiring.

    python -I -B tests/test_memory_graph.py [--cxx clang++]
"""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]


def need(condition, message):
    if not condition:
        raise SystemExit("FAIL: " + message)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--cxx", default="clang++")
    args = p.parse_args()

    api = (ROOT / "gpu/vk/vk_api.h").read_text(encoding="utf-8")
    backend = (ROOT / "host/rx_backend.c").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    fps = (ROOT / "gpu/vk/vk_fps.cpp").read_text(encoding="utf-8")
    options = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")

    need(re.search(r"#define MKWVK_API_VERSION 27\b", api), "the memory callback needs API version 27")
    need(re.search(r"int \(\*memory_usage\)\(uint64_t \*used, uint64_t \*total\);", api),
         "MkwVkHost does not expose used and total game memory")
    need("*used = hos_used_memory(hos_program_size);" in backend and "*total = hos_total_memory;" in backend,
         "the host callback does not report the emulated game's used/total memory")
    need("host_memory_usage" in backend.split("static const MkwVkHost vk_host = {", 1)[1],
         "vk_host does not install the memory callback")

    need("int show_memory_graph = 0;" in options, "the new option is not off by default")
    row = re.search(r'\{TAB_GAMEPLAY, "Memory Graphy", &opts\.show_memory_graph, 0, 1, 1, tx_onoff,', menu)
    fps_row = menu.index('{TAB_GAMEPLAY, "FPS counter", &opts.show_fps')
    graph_row = menu.index('{TAB_GAMEPLAY, "Memory Graphy", &opts.show_memory_graph')
    need(row and graph_row > fps_row, "Memory Graphy is not a Gameplay On/Off row directly after FPS counter")
    need("memory_graphy" in options, "the persisted option key is not documented in Options")
    need("fps_memory_graph_now.store(opts.show_memory_graph != 0" in menu,
         "menu initialization or updates do not gate sampling with the option")
    need("if (fps || memory) draw_fps(c, open);" in menu,
         "the memory graph is not drawn when the FPS counter is disabled")
    need("summary.min_used" in menu and "summary.max_used" in menu and '"Used"' in menu and '"Free"' in menu,
         "the overlay does not draw used/free values and minimum/maximum used memory")
    need("fps_memory_graph_now.load" in fps and "memory_stats::kSampleNs" in fps,
         "memory samples are not gated or time-limited")

    with tempfile.TemporaryDirectory(prefix="memory-graph-") as tmp:
        exe = Path(tmp) / "memory-graph"
        subprocess.run([args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror",
                        str(ROOT / "tests/test_memory_graph.cpp"), "-o", str(exe)], check=True)
        subprocess.run([str(exe)], check=True)
    print("PASS: bounded memory history, minimum/maximum, and overlay wiring")


if __name__ == "__main__":
    main()
