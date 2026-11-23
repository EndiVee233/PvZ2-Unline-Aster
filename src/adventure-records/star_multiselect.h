#pragma once

namespace {
struct MultiStarCondition {
    WeakRef properties;
    Object condition;
    Word tiers;
};
struct MultiStarRun {
    Object board, module;
    Word mask, count, failed, passed, newStars;
    bool checked, awarded;
    WeakRef rewardImage;
    MultiStarCondition conditions[12];
};
static MultiStarRun multiStar;

static bool activeMultiStar(Object board) {
    return board && multiStar.board == board && multiStar.mask;
}

static Word evaluateMultiStar(Object board) {
    if (!activeMultiStar(board)) return 0;
    if (!multiStar.checked) {
        Word passed = multiStar.mask & ~multiStar.failed;
        for (Word i = 0; i < multiStar.count; ++i) {
            const auto& goal = multiStar.conditions[i];
            if (!goal.condition) continue;
            const Word isSatisfied = field<Word>(field<Object>(goal.condition, 0), 0x5c);
            if (!reinterpret_cast<bool(*)(Object)>(isSatisfied)(goal.condition)) passed &= ~goal.tiers;
        }
        multiStar.passed = passed;
        multiStar.checked = true;
    }
    return multiStar.passed;
}
}

namespace {
static bool collectMultiStarGoals(Object properties, Word mask) {
    const Word first = field<Word>(properties, 0x1c), end = field<Word>(properties, 0x20);
    if (!first || end < first || end - first != 36) return false;
    multiStar.count = 0;
    for (Word tier = 1; tier <= 3; ++tier) {
        const Word bit = starBit(tier);
        if (!(mask & bit)) continue;
        Object entry = reinterpret_cast<Object>(first + (tier - 1) * 12);
        Word begin = field<Word>(entry, 0), limit = field<Word>(entry, 4);
        if (!begin || limit < begin || (limit - begin) % sizeof(WeakRef) ||
            limit - begin > 4 * sizeof(WeakRef) || limit == begin) return false;
        for (; begin < limit; begin += sizeof(WeakRef)) {
            const auto& ref = *reinterpret_cast<const WeakRef*>(begin);
            Word i = 0;
            for (; i < multiStar.count; ++i) {
                auto& existing = multiStar.conditions[i];
                if (existing.properties.id == ref.id && existing.properties.serial == ref.serial) {
                    existing.tiers |= bit;
                    break;
                }
            }
            if (i == multiStar.count) {
                if (i == sizeof(multiStar.conditions) / sizeof(*multiStar.conditions)) return false;
                multiStar.conditions[i] = {ref, nullptr, bit};
                ++multiStar.count;
            }
        }
    }
    return true;
}

static Object lastMultiRecoveryBoard;
static float lastMultiRecoveryStart;
static void recoverMultiStar(Word base, Object board) {
    if (!board || activeMultiStar(board) || !playing(board) ||
        !field<unsigned char>(board, 0x8a0) || !socialContentEnabled(base)) return;
    const float start = field<float>(board, 0xcc);
    if (lastMultiRecoveryBoard == board && lastMultiRecoveryStart == start) return;
    lastMultiRecoveryBoard = board;
    lastMultiRecoveryStart = start;
    const auto* level = AdventureRecords::findLevel(field<const char*>(board, 0xc4));
    const Word primary = field<Word>(board, 0x7f0);
    Object manager = field<Object>(board, 0x938);
    if (!level || level->stars != 3 || primary >= 3 || !manager) return;
    // Native save restores the instantiated objectives. Every tier in the
    // catalog has at least one distinct objective beyond those of the others.
    const auto module = native<Object>(base, 0x43af38, manager, native<Object>(base, 0x902464));
    if (!module || field<unsigned char>(module, 0x19)) return;
    Object registry = native<Object>(base, 0x11d74b4);
    Object properties = native<Object>(base, 0x1da034, registry, module + 0x10);
    if (!properties || !collectMultiStarGoals(properties, 7)) return;
    const Word begin = field<Word>(manager, 0x1c), end = field<Word>(manager, 0x20);
    if (!begin || end <= begin || (end - begin) % 4 || end - begin > 4 * 128) return;
    Word mask = 7;
    for (Word i = 0; i < multiStar.count; ++i) {
        auto& goal = multiStar.conditions[i];
        auto props = native<Object>(base, 0x1da034, registry, &goal.properties);
        if (props) {
            for (Word at = begin; at < end; at += 4) {
                Object condition = *reinterpret_cast<Object*>(at);
                if (condition && props == native<Object>(base, 0x1da034, registry, condition + 0x10)) {
                    goal.condition = condition;
                    break;
                }
            }
        }
        if (!goal.condition) mask &= ~goal.tiers;
    }
    if (!severalStars(mask) || !(mask & (1U << primary)) || conflictingStars(*level, mask)) return;
    const Word player = owner(ownerStore(base));
    if (player == ~0U) return;
    Word used = 0;
    for (Word i = 0; i < multiStar.count; ++i)
        if (multiStar.conditions[i].tiers & mask) multiStar.conditions[used++] = multiStar.conditions[i];
    multiStar.count = used;
    multiStar.board = board;
    multiStar.module = module;
    multiStar.mask = mask;
    multiStar.failed = multiStar.passed = multiStar.newStars = 0;
    multiStar.checked = multiStar.awarded = false;
    multiStar.rewardImage = {};
    selectedChallenge = {player, level->key, primary + 1, 0, true, mask};
    native<int>(base, 0x147adc, 4, "AsterSocial", "restored multi star day=%u mask=%u", level->key, mask);
}
}

extern "C" bool asterAdventureLoadMultiStar(Word base, Object module, Object properties) {
    Object board = gameBoard(base);
    const auto& choice = selectedChallenge;
    if (!board || !properties || !choice.applied || !severalStars(choice.mask) ||
        AdventureRecords::levelId(field<const char*>(board, 0xc4)) != choice.day ||
        owner(ownerStore(base)) != choice.owner) return false;

    if (!collectMultiStarGoals(properties, choice.mask)) {
        selectedChallenge.mask = 0;
        return false;
    }
    Object manager = native<Object>(base, 0x43a0e0, module);
    if (!manager) {
        selectedChallenge.mask = 0;
        return false;
    }
    for (Word i = 0; i < multiStar.count; ++i) {
        auto& goal = multiStar.conditions[i];
        goal.condition = native<Object>(base, 0x43be34, manager, &goal.properties);
    }
    // A missing instance invalidates its tiers, while other registered goals
    // continue to use their native progress and win callbacks.
    for (Word i = 0; i < multiStar.count; ++i)
        if (!multiStar.conditions[i].condition) multiStar.failed |= multiStar.conditions[i].tiers;
    multiStar.board = board;
    multiStar.module = module;
    multiStar.mask = choice.mask;
    return true;
}

extern "C" bool asterAdventureMultiStarFailure(Word base, Object board, Object condition) {
    if (!activeMultiStar(board) || board != gameBoard(base)) return false;
    for (Word i = 0; i < multiStar.count; ++i) {
        if (multiStar.conditions[i].condition != condition) continue;
        multiStar.failed |= multiStar.conditions[i].tiers;
        return true;
    }
    return false;
}

extern "C" void asterAdventureAwardMultiStar(Word base, Object module) {
    Object board = gameBoard(base);
    if (!activeMultiStar(board) || multiStar.module != module) {
        native<void>(base, 0x902ea8, module);
        return;
    }
    if (multiStar.awarded) return;
    Word earned = evaluateMultiStar(board);
    Object store = ownerStore(base);
    Object profile = store ? native<Object>(base, 0x7a98dc, store) : nullptr;
    if (!profile || owner(store) != selectedChallenge.owner) earned = 0;
    const auto* alias = &field<const char*>(board, 0xc4);
    const Word existing = earned ? earnedStars(base, profile, alias, 3) : 0;
    multiStar.newStars = earned & ~existing;
    for (Word tier = 1; tier <= 3; ++tier) {
        if (!(multiStar.newStars & starBit(tier))) continue;
        native<void>(base, 0x7482e4, profile, alias, tier - 1, 1U);
    }
    const Word displayTier = firstStar(multiStar.newStars ? multiStar.newStars : earned);
    if (displayTier) {
        field<Word>(board, 0x7f0) = displayTier - 1;
        selectedChallenge.stars = displayTier;
    }
    field<unsigned char>(module, 0x19) = 1; // Already checked.
    field<unsigned char>(module, 0x1a) = multiStar.newStars != 0;
    field<unsigned char>(module, 0x1b) = earned != 0;
    field<unsigned char>(board, 0x7fe) = earned == 0;
    multiStar.awarded = true;
    if (pendingMultiRecord == board) {
        pendingMultiRecord = nullptr;
        // A combined clear supplies one formation to all passed tiers.
        const bool synchronize = severalStars(earned);
        for (Word tier = 1; tier <= 3; ++tier)
            if (earned & starBit(tier)) saveAdventureRecord(base, board, tier, pendingRecordAssisted, synchronize);
    }
    native<int>(base, 0x147adc, 4, "AsterSocial", "multi star selected=%u passed=%u awarded=%u",
                multiStar.mask, earned, multiStar.newStars);
}

extern "C" bool asterAdventureMultiStarTitle(Word base, Object page) {
    if (!activeMultiStar(gameBoard(base)) || !multiStar.awarded || field<Word>(page, 0x44) != 3) return false;
    Word mode = field<Word>(page, 0x4c);
    if (mode != 1 && mode != 2) return false;
    const Word newlyEarned = multiStar.newStars;
    if (!severalStars(newlyEarned)) return false;
    const char32_t* title = nullptr;
    makeText(base, title, newlyEarned == 7 ? U"你获得了三颗星！" : U"你获得了两颗星！");
    native<void>(base, 0x14e9b0d, page + 4, &title);
    freeText(base, title);
    return true;
}
extern "C" void asterAdventureMergeMultiStarGoals(Word base, Object descriptions) {
    Object board = gameBoard(base);
    if (!descriptions || !activeMultiStar(board)) return;
    const Word primary = field<Word>(board, 0x7f0);
    Object start = field<Object>(descriptions, 0), end = field<Object>(descriptions, 4);
    if (!start || end != start + 3 * 36 || primary >= 3) return;
    const char32_t* lines[12];
    Word count = 0, failed = 0;
    for (Word tier = 1; tier <= 3; ++tier) {
        if (!(multiStar.mask & starBit(tier))) continue;
        Object row = start + (tier - 1) * 36;
        const auto* first = field<const char32_t**>(row, 0);
        const auto* last = field<const char32_t**>(row, 4);
        if (!first || last < first || last - first > 4) return;
        auto* marks = field<Word*>(row, 12);
        Word marked = marks && field<Word>(row, 24) ? *marks : 0;
        for (Word i = 0; first + i != last; ++i) {
            Word line = 0;
            for (; line < count; ++line) {
                const auto* a = first[i];
                const auto* b = lines[line];
                while (*a && *a == *b) { ++a; ++b; }
                if (*a == *b) break;
            }
            if (line == count) lines[count++] = first[i];
            if (marked & (1U << i)) failed |= 1U << line;
        }
    }
    if (!count) return;
    Object target = start + primary * 36;
    auto*& marks = field<Word*>(target, 12);
    if (!marks) {
        marks = native<Word*>(base, 0x14c1a7d, sizeof(Word));
        field<Word*>(target, 28) = marks + 1;
    }
    *marks = failed;
    field<Word>(target, 16) = 0;
    field<Word*>(target, 20) = marks;
    field<Word>(target, 24) = count;
    const char32_t* retained[12];
    for (Word i = 0; i < count; ++i)
        native<void>(base, 0x14eae39, &retained[i], &lines[i]);
    const char32_t** values[] = {retained, retained + count, retained + count};
    native<void>(base, 0x7e509c, target, values);
    for (Word i = 0; i < count; ++i) freeText(base, retained[i]);
}

extern "C" int asterAdventureMultiStarDescription(Word base, Object board, Word index) {
    if (!activeMultiStar(board) || board != gameBoard(base) || index >= 3) return -1;
    return (multiStar.mask & (1U << index)) != 0;
}

extern "C" Object asterAdventureSpawnStarReward(Word base, Object board, const char** kind) {
    Object reward = native<Object>(base, 0x21f2ec, board, kind);
    if (reward && activeMultiStar(board))
        multiStar.rewardImage = field<WeakRef>(reward, 0x80);
    return reward;
}

extern "C" void asterAdventureDrawStarReward(Word base, Object graphics, Object image,
                                              const float* matrix, Object sprite) {
    const auto draw = [&](const float* transform) {
        native<void>(base, 0x116a498, graphics, image, transform, 0.0f, 0.0f);
    };
    if (!severalStars(multiStar.newStars) || !activeMultiStar(gameBoard(base)) ||
        !(multiStar.rewardImage.id | multiStar.rewardImage.serial) ||
        field<Word>(sprite, 8) != multiStar.rewardImage.id ||
        field<Word>(sprite, 12) != multiStar.rewardImage.serial) {
        draw(matrix);
        return;
    }
    struct StarLayer { float size, x, y; };
    static constexpr StarLayer two[] = {{0.75f, 0.18f, -0.055f}, {0.79f, -0.17f, 0.055f}};
    static constexpr StarLayer three[] = {
        {0.62f, -0.19f, -0.24f}, {0.76f, 0.23f, -0.08f}, {0.79f, -0.10f, 0.15f},
    };
    const bool allThree = multiStar.newStars == 7;
    const auto* layers = allThree ? three : two;
    const int width = field<int>(image, 0x28);
    const int height = field<int>(image, 0x2c);
    // Apply the local arrangement before the native animation's transform.
    // The original reward still owns its glow, motion, and hit target.
    for (int i = 0; i < (allThree ? 3 : 2); ++i) {
        const auto& layer = layers[i];
        const float x = width * ((1.0f - layer.size) * 0.5f + layer.x);
        const float y = height * ((1.0f - layer.size) * 0.5f + layer.y);
        const float posed[] = {
            matrix[0] * layer.size, matrix[1] * layer.size, matrix[2] + matrix[0] * x + matrix[1] * y,
            matrix[3] * layer.size, matrix[4] * layer.size, matrix[5] + matrix[3] * x + matrix[4] * y,
            matrix[6] * layer.size, matrix[7] * layer.size, matrix[8] + matrix[6] * x + matrix[7] * y,
        };
        draw(posed);
    }
}

extern "C" int asterAdventureGoalListY(Word base, Object widget, int y) {
    if (!activeMultiStar(gameBoard(base))) return y;
    const Word begin = field<Word>(widget, 0xb0), end = field<Word>(widget, 0xb4);
    if (end < begin || end - begin < 5 * sizeof(Word)) return y;
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = holder ? field<Object>(holder, 0) : nullptr;
    return app ? y + int(18.0f * field<float>(app, 0x698)) : y;
}
