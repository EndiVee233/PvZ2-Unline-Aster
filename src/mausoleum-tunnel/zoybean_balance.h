#pragma once

enum class ZoybeanUnit { basic, cone, bucket, gatling };
enum class ZoybeanHat { none, carrot, watermelon };

static constexpr float zoybeanCycleSeconds = 15.0f / 1.25f;

static constexpr ZoybeanUnit zoybeanUnit(int level, unsigned roll) {
    // Each row is a set of exclusive cumulative cutoffs out of 100.
    constexpr unsigned cutoffs[][3] = {{50, 100, 100}, {25, 75, 100}, {5, 15, 90}, {5, 15, 50}};
    const auto& grade = cutoffs[level < 1 ? 0 : level > 4 ? 3 : level - 1];
    if (roll < grade[0]) return ZoybeanUnit::basic;
    if (roll < grade[1]) return ZoybeanUnit::cone;
    if (roll < grade[2]) return ZoybeanUnit::bucket;
    return ZoybeanUnit::gatling;
}

static constexpr ZoybeanHat zoybeanHat(unsigned roll) {
    if (roll < 5) return ZoybeanHat::none;
    if (roll < 25) return ZoybeanHat::carrot;
    return ZoybeanHat::watermelon;
}
