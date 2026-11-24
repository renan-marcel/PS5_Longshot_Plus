/* (longshot) PS5: the texture size the title's free memory allows now (vk_texture.cpp; docs/PS5.md "Texture size by free
   memory"). No Vulkan here: tests/test_ps5_tex_tier.py.

   A decoded ASTC texture wider than RX_VK_TEX_MAX_DIM (512 on a PS5 / PS5 Slim) leaves out its top levels: the base
   console's 12,016 MiB do not hold the town at 1024 (docs/PS5.md). With RX_VK_TEX_ROOMY_DIM (1024 in that profile) the
   limit follows the memory instead:
   - roomy: while the title has more than the reserve (HOS_PS5_TEX_RESERVE_MB) + RX_VK_TEX_ROOMY_MB (512) free, new
     textures are made up to RX_VK_TEX_ROOMY_DIM, and the ones made at the low size are made again at the roomy one;
   - not roomy: below that, new ones are made at RX_VK_TEX_MAX_DIM, and the ones made roomy are made again at it, the
     least recently used first;
   - RX_VK_TEX_ROOMY_HYST_MB (128) either side of the line: a scene whose free memory sits on it does not flip each frame.
   Below the reserve itself the older rule still holds: 128 texels, 32 under half of it (ps5_tex_reserve). */
#pragma once

#include <cstdint>

namespace mkwvk::tex_tier {

constexpr uint64_t kMB = 1ull << 20;

enum : uint8_t {
    kNone = 0,   // the limit did not touch it: no larger than RX_VK_TEX_MAX_DIM, or too small to be cut
    kLow = 1,    // made at RX_VK_TEX_MAX_DIM while memory was not roomy: made again larger when it is
    kRoomy = 2,  // made at RX_VK_TEX_ROOMY_DIM while memory was roomy: made again smaller when it is not
};

struct Line {
    uint64_t reserve = 0, margin = 512 * kMB, hysteresis = 128 * kMB;
};

/// Whether memory is roomy now, from whether it was: up above reserve + margin + hysteresis, down below reserve + margin -
/// hysteresis, else as it was
inline bool roomy(bool was, uint64_t free_bytes, const Line& l) {
    const uint64_t line = l.reserve + l.margin;
    if (was) return free_bytes + l.hysteresis >= line;
    return free_bytes > line + l.hysteresis;
}

/// The widest a decoded ASTC texture may stay now
inline uint32_t dim_now(uint32_t low_dim, uint32_t roomy_dim, bool is_roomy) {
    return roomy_dim > low_dim && is_roomy ? roomy_dim : low_dim;
}

/// Which tier a texture of this width (its widest side, before any level is left out) was made in: kNone when the limit
/// did not touch it (cut must be whether it is large enough, in bytes, to be cut at all: RX_VK_TEX_SKIP_MB)
inline uint8_t tier_of(uint32_t widest, bool cut, uint32_t low_dim, uint32_t roomy_dim, bool is_roomy) {
    if (!cut || roomy_dim <= low_dim || widest <= low_dim) return kNone;
    return is_roomy ? kRoomy : kLow;
}

/// Whether a texture of this tier is to be made again now: a low one once memory is roomy, a roomy one once it is not
inline bool remake(uint8_t tier, bool is_roomy) { return (tier == kLow && is_roomy) || (tier == kRoomy && !is_roomy); }

}  // namespace mkwvk::tex_tier
