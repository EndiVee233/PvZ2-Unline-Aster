#pragma once

struct ChallengeChoice {
    Word owner, day, stars, expires;
    bool applied;
    Word mask = 0;
};

// A negative result either keeps the stock flow or finishes this level.
static constexpr int stockStarFlow = -2;
static constexpr int allStarsEarned = -1;

static Object currentStarResult(Object dialog) {
    const Word begin = field<Word>(dialog, 0xe0);
    const Word end = field<Word>(dialog, 0xe4);
    const Word index = field<Word>(dialog, 0xec);
    constexpr Word pageSize = 0x88;
    if (!begin || end < begin || (end - begin) % pageSize || index >= (end - begin) / pageSize) {
        return nullptr;
    }
    return reinterpret_cast<Object>(begin + index * pageSize);
}

template<class StarMask, class LevelId, class Clock>
static int advanceAdventureStar(Word base, Object page, Object board, Word player,
                                ChallengeChoice& choice, bool apply, StarMask starMask,
                                LevelId levelId, Clock wallTime) {
    if (!page || !board || !choice.applied || !choice.day || player != choice.owner ||
        field<Word>(page, 0) != 4) return stockStarFlow;
    const Word count = field<Word>(page, 0x44), index = field<Word>(page, 0x48);
    const Word mode = field<Word>(page, 0x4c);
    // Mode 3 is the pre-battle conditions page. A failed challenge uses mode 0.
    if (count != 3 || index >= count || mode < 1 || mode > 2 || (choice.mask ? !(choice.mask & (1U << index)) : choice.stars != index + 1) ||
        levelId(field<const char*>(board, 0xc4)) != choice.day) return stockStarFlow;
    const int saved = starMask(base, count, index, mode);
    if (saved < 0) return stockStarFlow;
    const Word earned = Word(saved) | (1U << index);
    for (Word next = 0; next < count; ++next) {
        if (earned & (1U << next)) continue;
        if (apply) {
            choice = {player, choice.day, next + 1, wallTime(base) + 2000U, false};
            native<int>(base, 0x147adc, 4, "AsterSocial", "next star day=%u stars=%u", choice.day, choice.stars);
        }
        return int(next);
    }
    return allStarsEarned;
}

static Word starAdvanceTime(Word base) {
    Word time[2];
    return native<int>(base, 0x147974, time, nullptr) == 0
        ? time[0] * 100U + time[1] / 10000U : 0;
}
