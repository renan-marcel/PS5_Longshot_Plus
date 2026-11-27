---
name: ps5-reversing-patch
description: Reversing and fast incremental PS5 build/deploy workflow for Longshot using scripts/ PS5 toolchain and ps5debug-mcp, with optional binary-ninja MCP static analysis. Use when analyzing lifted game functions (f_*), verifying sead structs, or iterating on PS5 runtime patches.
---

# PS5 Reversing & Incremental Patch Workflow

Works directly from the lifted C (`<build-dir>/longshot-ps5-work/lift/sa/gen/code_*.c`), `llvm-nm`, and `ps5debug-mcp`. `binary-ninja` MCP is **optional** for interactive decompilation.

## 1. Static Analysis (`code_*.c` / `llvm-nm` / Optional Binary Ninja)

- Inspect lifted game functions (`f_<addr>`, e.g. `f_803b44e0`) directly in `<build-dir>/longshot-ps5-work/lift/sa/gen/code_*.c` and `nx2/oot_patches.py`.
- Use `llvm-nm` on `llvm-pie.elf` to resolve runtime symbol offsets, or `ps5_aob_scan` / `ps5_disasm_region` directly on the running PS5.
- *(Optional)* If `binary-ninja` MCP is available, load `llvm-pie.elf` or `eboot.elf.new` for `bn_function_decompile` and `bn_function_xrefs_to`.

## 2. Fast Incremental PS5 Build & Deploy

Iterate in ~1–2 minutes without re-lifting the full `.nup` using the `scripts/` helpers:
1. Generate kit headers if missing: `python -B scripts/gen_kit_headers.py`
2. Cross-compile only modified `host/` or `gpu/vk/` files for `x86_64-sie-ps5`:
   ```bash
   python -B scripts/test_compile_ps5.py host/oot_heap_give_back.c gpu/vk/vk_main.cpp
   ```
   *(If `gpu/vk/vk_api.h` changed `MkwVkHost` or `MkwVkRenderer`, bump `MKWVK_API_VERSION` and **always** recompile both `host/rx_backend.c` and `gpu/vk/vk_main.cpp` together.)*
3. Relink & sign into the existing build directory:
   ```bash
   python -B scripts/update_longshot_build.py --build-dir <BUILD_DIR> [--patch-heap-free]
   ```
4. Deploy `eboot.bin` (and optional `longshot_env.txt` switches) over FTP:
   ```bash
   python -B scripts/upload_to_ps5.py --host <PS5_IP> --file <BUILD_DIR>/PPSA99198/eboot.bin
   ```

## 3. Live Verification

After deploying, use the `ps5-live-debug` skill (`ps5debug-mcp`) to:
- Confirm `eboot.bin` launched without `BOOT_WATCHDOG_ACTIVE` or `klog` faults.
- Verify patched sites via `ps5_resolve_address` + `ps5_disasm_region`.
- Run game-free unit tests (`python3 -I -B tests/run_all.py`) before committing.
