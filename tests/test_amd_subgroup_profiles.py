"""Check 32- and 64-lane shader profiles, AMD's fragment shuffle path and RADV's mesh NumWorkgroups workaround (#2338)
without a GPU."""

import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]
VK = ROOT / "gpu/vk"

FIXTURE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdlib>
#include "shader_recompiler/profile.h"
#include "shader_recompiler/stage.h"

enum VkShaderStageFlagBits : uint32_t {
    VK_SHADER_STAGE_VERTEX_BIT = 1,
    VK_SHADER_STAGE_FRAGMENT_BIT = 16,
    VK_SHADER_STAGE_COMPUTE_BIT = 32,
    VK_SHADER_STAGE_TASK_BIT_EXT = 64,
    VK_SHADER_STAGE_MESH_BIT_EXT = 128,
    VK_SHADER_STAGE_ALL_GRAPHICS = 31,
    VK_SHADER_STAGE_ALL = 0x7fffffff,
};
using VkShaderStageFlags = uint32_t;
constexpr uint32_t VK_DRIVER_ID_AMD_PROPRIETARY = 1;
constexpr uint32_t VK_DRIVER_ID_MESA_RADV = 3;   // (vulkan_core.h's values)
#define VK_MAKE_VERSION(major, minor, patch) \
    ((((uint32_t)(major)) << 22U) | (((uint32_t)(minor)) << 12U) | ((uint32_t)(patch)))
struct {
    uint32_t sg32_stages = 0, subgroup_size = 32, subgroup_max = 32, driver_id = 0;
    struct {
        bool shaderFloat16 = true;   // (k10: f16 lowered where the GPU has none; here it has)
        // (make_profile: storage image and texel buffer arrays indexed nonuniformly where the GPU can)
        bool shaderStorageImageArrayNonUniformIndexing = true, shaderUniformTexelBufferArrayNonUniformIndexing = true,
             shaderStorageTexelBufferArrayNonUniformIndexing = true;
    } vk12;
    bool float_atomic_add = false;
    // (make_profile: RADV's version for the mesh NumWorkgroups workaround, #2338)
    struct { struct { uint64_t minStorageBufferOffsetAlignment = 16; } limits; uint32_t driverVersion = 0; } props;
    struct { bool gather_offset = false; } fixes;   // (vk_vendor.h: make_profile reads the gather offset from it)
} dev;

using Shader::Stage;
using Id = uint32_t;
struct EmitContext {
    const Shader::Profile& profile;
    Stage stage;
    Id lane;
    Id U32[2]{};
    Id Const(Id value) { return value; }
    Id OpShiftRightLogical(Id, Id a, Id b) { return a >> b; }
    Id OpShiftLeftLogical(Id, Id a, Id b) { return a << b; }
    Id OpIAdd(Id, Id a, Id b) { return a + b; }
};
Id GetThreadId(const EmitContext& ctx) { return ctx.lane; }
'''

CASES = r'''
void check(const Shader::Profile& p, uint32_t size) {
    assert(p.max_subgroup_size == size);
    assert(p.warp_size_potentially_larger_than_guest == (size > 32));
}

int main(int argc, char** argv) {
    assert(argc == 12);
    const auto number = [&](int i) { return uint32_t(std::strtoul(argv[i], nullptr, 10)); };
    dev.subgroup_size = number(1);
    dev.subgroup_max = number(2);
    dev.sg32_stages = number(3);
    dev.driver_id = number(4);
    // (#2338: the driver's version, VK_MAKE_VERSION as Mesa encodes it; unset: 0, unknown)
    if (const char* v = getenv("FIXTURE_DRIVER_VERSION")) dev.props.driverVersion = uint32_t(std::strtoul(v, nullptr, 0));
    // (storage buffers bound and translated at 16 bytes at least: AMD's 4 made the 8- and 16-byte vector views inexact)
    for (const uint64_t device : {uint64_t{4}, uint64_t{16}, uint64_t{64}}) {
        dev.props.limits.minStorageBufferOffsetAlignment = device;
        assert(storage_binding_align() == std::max<uint64_t>(device, 16));
    }
    dev.props.limits.minStorageBufferOffsetAlignment = 4;
    check(profile(), number(5));
    assert(profile().min_ssbo_alignment == 16);
    // (#2338: native mesh shaders keep NumWorkgroups live on RADV before 26.2.5, and where its version is unknown)
    const char* mesh = getenv("FIXTURE_MESH_NUM_WORKGROUPS");
    assert(profile().need_mesh_num_workgroups == (mesh && mesh[0] == '1'));
    check(profile_graphics(VK_SHADER_STAGE_VERTEX_BIT), number(6));
    check(profile_graphics(VK_SHADER_STAGE_FRAGMENT_BIT), number(7));
    check(profile_pinned(), number(8));
    check(profile_graphics(VK_SHADER_STAGE_TASK_BIT_EXT), number(9));
    check(profile_graphics(VK_SHADER_STAGE_MESH_BIT_EXT), number(10));
    const bool workaround = number(11) != 0;
    check_stamp(number(5), number(3), workaround, getenv("RX_VK_WARP64") != nullptr);
    const auto& fragment = profile_graphics(VK_SHADER_STAGE_FRAGMENT_BIT);
    const auto& compute = profile_pinned();
    EmitContext lo{fragment, Stage::Fragment, 31};
    EmitContext hi{fragment, Stage::Fragment, 32};
    EmitContext cs{compute, Stage::Compute, 31};
    assert(UseShuffleFallback(lo) == workaround && UseShuffleFallback(hi) == workaround);
    assert(!UseShuffleFallback(cs));
    assert(HostThreadId(lo, 7) == 7 && HostThreadId(cs, 7) == 7);
    assert(HostThreadId(hi, 7) == (number(7) > 32 ? 39 : 7));
}
'''


def section(source, start, end):
    first = source.index(start)
    return source[first:source.index(end, first)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="clang++")
    args = parser.parse_args()
    shader = (VK / "vk_shader.cpp").read_text(encoding="utf-8")
    warp = (VK / "eden/shader_recompiler/backend/spirv/emit_spirv_warp.cpp").read_text(encoding="utf-8")
    stamp = section(shader, "    const uint32_t lanes[]", "    // (the records keep Shader::Info")
    check_stamp = r'''
void check_stamp(uint32_t size, uint32_t pinned, bool workaround, bool forced) {
    bool added = false;
    const auto add = [&](const uint32_t* values, size_t bytes) {
        assert(bytes == 6 * sizeof(uint32_t));
        assert(values[0] == uint32_t(size > 32) && values[1] == size);
        assert(values[2] == uint32_t(workaround) && values[3] == pinned && values[4] == uint32_t(forced));
        // (the storage binding alignment the translation is built with: a cache of a 16-aligned GPU is no use on a 64-aligned one)
        assert(values[5] == uint32_t(storage_binding_align()));
        added = true;
    };
''' + stamp + r'''
    assert(added);
}
'''
    internal = (VK / "vk_internal.h").read_text(encoding="utf-8")
    fixture = (FIXTURE + section(internal, "inline uint64_t storage_binding_align()", "/// A range of guest memory")
               + section(shader, "Shader::Profile make_profile(", "Shader::HostTranslateInfo host_info()")
               + section(shader, "const Shader::Profile& profile()", "const std::vector<Code>& codes_of(")
               + section(warp, "Id HostThreadId(", "Id GuestLane(")
               + section(warp, "bool UseShuffleFallback(", "Id ShuffleAbsolute(") + check_stamp + CASES)
    with tempfile.TemporaryDirectory(prefix="longshot-subgroup-profile-") as tmp:
        cpp, exe = Path(tmp) / "fixture.cpp", Path(tmp) / "fixture.exe"
        cpp.write_text(fixture, encoding="utf-8")
        subprocess.run([args.cxx, "-std=c++20", "-I", str(VK / "eden"), "-I", str(ROOT / "gpu/third_party/suyu"),
                        str(cpp), "-o", str(exe)], check=True, timeout=60)
        # A fresh process per device: the real profiles are cached once for the selected GPU.
        # Inputs: default lanes, maximum lanes, pinned-stage mask, proprietary AMD driver.
        # Expected widths: base, vertex, fragment, compute, task, mesh; then fragment workaround.
        cases = [
            ((32, 32, 0, 0), (32, 32, 32, 32, 32, 32, 0), {}),
            ((64, 64, 32, 1), (64, 64, 64, 32, 64, 64, 1), {}),
            ((32, 64, 32, 1), (64, 64, 64, 32, 64, 64, 1), {}),
            ((32, 64, 0, 0), (64, 64, 64, 64, 64, 64, 0), {}),
            ((32, 64, 31, 1), (64, 32, 32, 64, 64, 64, 1), {}),
            ((64, 64, 240, 1), (64, 64, 32, 32, 32, 32, 1), {}),
            ((64, 64, 0, 0), (64, 64, 64, 64, 64, 64, 0), {}),
            ((64, 64, 32, 1), (32, 32, 32, 32, 32, 32, 1), {"RX_VK_WARP64": "0"}),
            ((64, 64, 240, 1), (64, 64, 64, 32, 64, 64, 1), {"RX_VK_WARP64": "1"}),
            ((64, 64, 32, 1), (64, 64, 64, 32, 64, 64, 0), {"RX_VK_FRAG_SHUFFLE_FALLBACK": "0"}),
            ((64, 64, 32, 0), (64, 64, 64, 32, 64, 64, 1), {"RX_VK_FRAG_SHUFFLE_FALLBACK": "1"}),
        ]
        # RADV (driver 3) with Mesa's version encoded as VK_MAKE_VERSION: the mesh NumWorkgroups workaround before 26.2.5 and
        # where the version is unknown (0), not from 26.2.5 nor on another driver (#2338)
        radv = lambda major, minor, patch: str(major << 22 | minor << 12 | patch)   # noqa: E731
        cases += [
            ((32, 32, 0, 3), (32, 32, 32, 32, 32, 32, 0), {"FIXTURE_DRIVER_VERSION": radv(26, 2, 4), "FIXTURE_MESH_NUM_WORKGROUPS": "1"}),
            ((32, 32, 0, 3), (32, 32, 32, 32, 32, 32, 0), {"FIXTURE_DRIVER_VERSION": radv(26, 2, 5)}),
            ((32, 32, 0, 3), (32, 32, 32, 32, 32, 32, 0), {"FIXTURE_MESH_NUM_WORKGROUPS": "1"}),
            ((64, 64, 32, 1), (64, 64, 64, 32, 64, 64, 1), {"FIXTURE_DRIVER_VERSION": radv(25, 0, 0)}),
        ]
        env = {k: v for k, v in os.environ.items()
               if k not in ("RX_VK_WARP64", "RX_VK_FRAG_SHUFFLE_FALLBACK", "FIXTURE_DRIVER_VERSION", "FIXTURE_MESH_NUM_WORKGROUPS")}
        for device, expected, overrides in cases:
            subprocess.run([str(exe), *map(str, device + expected)], env=env | overrides, check=True, timeout=10)
    assert "EmitSPIRV(profile_pinned(), rt, t->program, bindings)" in shader
    for stage in ("TASK", "MESH"):
        assert f"fallback ? profile_pinned() : profile_graphics(VK_SHADER_STAGE_{stage}_BIT_EXT)" in shader
    for start, end in (("Id ShuffleRelative(", "Id BroadcastLane("), ("Id EmitShuffleIndex(", "Id EmitShuffleUp("),
                       ("Id EmitShuffleButterfly(", "Id EmitQuadBroadcast(")):
        assert "UseShuffleFallback(ctx)" in section(warp, start, end)
    quad = section(warp, "Id EmitQuadBroadcast(", "Id EmitQuadSwap(")
    assert "ctx.profile.has_broken_spirv_subgroup_shuffle" in quad and "UseShuffleFallback" not in quad
    print("stage subgroup widths, 32-lane partitions, AMD fragment shuffles, and cache identity ok")


if __name__ == "__main__":
    main()
