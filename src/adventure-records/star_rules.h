#pragma once

enum class StarDifficulty : Word { Easy, Normal, Hard };

static constexpr Word starBit(Word tier) { return tier ? 1U << (tier - 1) : 0; }
static constexpr bool severalStars(Word mask) { return (mask & (mask - 1)) != 0; }

static Word firstStar(Word mask) {
    for (Word tier = 1; tier <= 3; ++tier)
        if (mask & starBit(tier)) return tier;
    return 0;
}
