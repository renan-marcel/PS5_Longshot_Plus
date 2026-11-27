---
name: ps5-live-debug
description: Live runtime debugging of Longshot eboot.bin on a PS5 console using ps5debug-mcp (ports 744/755/3232), with optional Binary Ninja MCP integration. Use when diagnosing PS5 freezes, SIGSEGV crashes, black screens, memory/heap state, or verifying hooks at runtime.
---

# Live PS5 Debugging (`ps5debug-mcp`)

Works **standalone** with `ps5debug-mcp` alone (built-in Zydis disassembler, AOB scan, xrefs, `/dev/klog`, and stack walk). `binary-ninja` MCP is **optional** if you also want static ELF decompilation.

**Never send game dumps, keys, or built binaries (`eboot.bin`, `image.bin`) outside the local PC/LAN.** Logs, addresses, register dumps, and decompiled host runtime summaries are safe.

## 1. Passive Triage First (No Process Pause)

Start with non-intrusive checks before attaching `ptrace`:
1. `ps5_connect(host=...)` (or `PS5_DEBUG_HOST`) and `ps5_klog_start()` to capture `/dev/klog` on TCP 3232.
2. `ps5_foreground_app()` to get the active `pid`, `titleid` (`PPSA99198`), and `app_ver`.
3. `ps5_proc_maps(pid=..., filter_name="eboot.bin")` to locate the live ASLR `ps5_base` and verify guest/host memory regions (`HOS_PS5_GUEST_LO..HI`).
4. `ps5_klog_tail(lines=50)` (and `filter_text="SIG"` / `"fault"`) if the title crashed or froze.
5. Read live globals/counters via `ps5_read_memory`, scan patterns with `ps5_aob_scan`, or inspect patched instructions with `ps5_disasm_region`.

## 2. Address Translation (`ASLR <-> Static ELF / Optional Binary Ninja`)

To map offsets from `llvm-nm`, `llvm-pie.elf`, or (optionally) Binary Ninja:
- **Offset / ELF -> PS5:** `ps5_resolve_address(address=<va>, image_base=<base>, direction="elf_to_ps5")`
- **PS5 -> Offset / ELF:** `ps5_resolve_address(address=<ps5_va>, image_base=<base>, direction="ps5_to_elf")`

## 3. Breakpoints, Watchpoints & Stack Walk

1. Ensure host firewall allows inbound TCP `755` from the PS5.
2. `ps5_debug_attach(pid=<pid>)`
3. Set a software breakpoint (`ps5_debug_set_breakpoint`, slots `0..29`) or hardware watchpoint (`ps5_debug_set_watchpoint`, `DR0..DR3`, `write`/`read/write`/`exec`, `1/2/4/8` bytes).
4. `ps5_debug_wait_stop(timeout=15.0)` to receive the `StopEvent` (`lwpid`, `signame`, `dr6`, GP registers).
5. `ps5_debug_read_stack(pid=<pid>, rbp=<rbp>, rsp=<rsp>, depth=24)` and inspect call sites via `ps5_disasm_region` or `ps5_resolve_address` (and optionally `bn_function_decompile` if Binary Ninja is open).
6. **Always** call `ps5_debug_detach()` when done so the game resumes cleanly.

## 4. Safety Rules for Longshot Runtime

- **Avoid `CMD_PROC_CALL` / thread-hijack injection** while Vulkan/render threads are active; prefer passive `ps5_read_memory`, `ps5_klog_tail`, and short-lived breakpoints/watchpoints.
- Clear breakpoints/watchpoints (`enabled=false`) before detaching if you want the game to continue running unobstructed.
