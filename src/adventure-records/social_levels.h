#pragma once

namespace {
constexpr char dialogFile[] = "/data/data/com.pvz2unline.aster/cache/aster-social-level";
constexpr char dialogTemp[] = "/data/data/com.pvz2unline.aster/cache/aster-social-level.tmp";
constexpr char replyFile[] = "/data/data/com.pvz2unline.aster/cache/aster-social-reply";

enum class SocialPhase : Word { Idle, Choosing, Loading, Viewing, Returning };
enum class SocialEvent : Word { Select = 1, Closed = 3, Unavailable = 4 };
enum class SocialCommand : Word { Watch = 2, Back = 3, Scores = 4 };

struct SocialMessage {
    Word token, owner, day, kind;
};

struct SocialSession {
    Object scene;
    Object board;
    Word previousScene, seed, transition, flags;
    SocialMessage id;
    Word expires, lastPoll;
    SocialPhase phase;
    bool failed;
    bool backRequested;
    Object viewBack;
    char32_t viewTitle[64];
    char stage[64];
};

static SocialSession social;
static Record friendRecord;
static Word sequence;

struct ChallengeChoice {
    Word owner, day, stars, expires;
    bool applied;
};
static ChallengeChoice selectedChallenge;

static Word wallTime(Word base) {
    Word time[2];
    return native<int>(base, 0x147974, time, nullptr) == 0
        ? time[0] * 100U + time[1] / 10000U : 0;
}

static bool publish(Word base, Word kind) {
    SocialMessage event{social.id.token, social.id.owner, social.id.day, kind};
    return writeBytes(base, &event, sizeof(event), dialogFile, dialogTemp);
}

static void releaseString(Word base, const char* value) {
    char allocator = 0;
    native<void>(base, 0x14ebf59, value - 12, &allocator);
}

}

#include "level_menu.h"
#include "formation_view.h"

namespace {
static void startStockLevel(Word base) {
    char allocator = 0;
    const char* stage = nullptr;
    const char* alias = nullptr;
    native<void>(base, 0x14ed0e1, &stage, social.stage, &allocator);
    native<void>(base, 0x14ed0e1, &alias, social.id.day == 1 ? "egypt1" : "egypt2", &allocator);
    native<void>(base, 0x354360, social.scene, &stage, &alias, social.seed, social.transition, social.flags);
    releaseString(base, alias);
    releaseString(base, stage);
}

static void returnToMap(Word base, bool failed) {
    social.phase = SocialPhase::Returning;
    social.failed = failed;
    Object board = gameBoard(base);
    if (board && board == social.board) {
        // The stock quit flow ends the Board before the map drops the entity
        // registry. Its plant listeners otherwise outlive their Board.
        field<Word>(board, 0x7f4) = 7;
        native<void>(base, 0x226770, board);
    }
    social.viewBack = nullptr;
    social.backRequested = false;
    social.viewTitle[0] = 0;
    native<void>(base, 0x352498, social.scene, social.previousScene, 0U, 1U);
}

static bool readExact(Word base, int fd, void* target, Word length) {
    auto* bytes = reinterpret_cast<Object>(target);
    Word pos = 0;
    while (pos < length) {
        int amount = native<int>(base, 0x148460, fd, bytes + pos, length - pos);
        if (amount <= 0) return false;
        pos += Word(amount);
    }
    return true;
}

static bool readReply(Word base, SocialMessage& reply) {
    int fd = native<int>(base, 0x148448, replyFile, 0, 0);
    if (fd < 0) return false;
    bool valid = readExact(base, fd, &reply, sizeof(reply)) && reply.token == social.id.token &&
        reply.owner == social.id.owner && reply.day == social.id.day;
    Word count = 0;
    if (valid && reply.kind == Word(SocialCommand::Watch)) {
        const auto& score = menu.scores[menu.watch ? menu.watch - chooseFriend : 0];
        valid = social.phase == SocialPhase::Choosing && menu.watch &&
            readExact(base, fd, &friendRecord, sizeof(friendRecord)) &&
            AdventureRecords::valid(friendRecord, friendRecord.owner, social.id.day, menu.stars) &&
            friendRecord.elapsedMs == score.elapsedMs;
    } else if (valid && reply.kind == Word(SocialCommand::Scores)) {
        valid = social.phase == SocialPhase::Choosing && !menu.scoreCount &&
            readExact(base, fd, &count, sizeof(count)) && count <= maxFriendScores &&
            readExact(base, fd, menu.scores, count * sizeof(FriendScore));
        for (Word i = 0; valid && i < count; ++i) {
            const auto& row = menu.scores[i];
            valid = row.stars < 4 && row.elapsedMs > 0 && row.elapsedMs <= 3600000 &&
                row.name[0] && !row.name[39];
        }
    } else {
        valid = valid && reply.kind == Word(SocialCommand::Back);
    }
    char extra;
    valid = valid && native<int>(base, 0x148460, fd, &extra, 1) == 0;
    if (valid && reply.kind == Word(SocialCommand::Scores)) menu.scoreCount = count;
    native<int>(base, 0x147b90, fd);
    native<int>(base, 0x148424, replyFile);
    return valid;
}
}

extern "C" void asterAdventureChoose(Word base, Object scene, const char* const* stage,
                                     const char* const* alias, Word seed, Word transition, Word flags) {
    // The map's level nodes also receive touches through the scene dispatcher.
    if (social.phase == SocialPhase::Choosing && scene == social.scene &&
        field<Word>(scene, 0x984) == social.previousScene) return;
    const Word day = alias ? AdventureRecords::egyptDay(*alias) : 0;
    const Word player = owner(ownerStore(base));
    const Word previous = field<Word>(scene, 0x984);
    const char* name = stage ? *stage : nullptr;
    Object app = gameApp(base);
    if (day && app && !field<Object>(app, 0x1370) && !field<Word>(app, 0x1374) && player != ~0U && previous && previous != 6 && previous < 128 && name &&
        social.phase == SocialPhase::Idle) {
        Word size = 0;
        while (size < sizeof(social.stage) && name[size]) ++size;
        if (size < sizeof(social.stage)) {
            const Word clock = wallTime(base);
            SocialMessage id{clock + ++sequence, player, day, 0};
            social.scene = scene;
            social.board = nullptr;
            social.previousScene = previous;
            social.seed = seed;
            social.transition = transition;
            social.flags = flags;
            social.id = id;
            social.expires = clock + 60000U;
            social.lastPoll = clock - 10U;
            social.phase = SocialPhase::Choosing;
            social.failed = false;
            selectedChallenge.day = 0;
            menu.action = menu.stars = menu.page = menu.watch = menu.scoreCount = menu.chosenFriend = 0;
            for (Word i = 0; i <= size; ++i) social.stage[i] = name[i];
            native<int>(base, 0x148424, replyFile);
            publish(base, Word(SocialEvent::Select));
            return;
        }
    }
    native<void>(base, 0x354360, scene, stage, alias, seed, transition, flags);
}

namespace {
static void endMenu(Word base, Word event = 0) {
    closeMenu(base);
    if (menu.watch && event) publish(base, event);
    menu.watch = 0;
    social.phase = SocialPhase::Idle;
}

// Process input on the renderer outside the widget's mouse-up callback.
static void updateMenu(Word base, Word clock) {
    if (!menu.dialog) {
        menu.unlocked = starChallengesUnlocked(base, social.id.day, &menu.earnedStars);
        for (Word i = 0; i < 4; ++i) {
            menu.bestTimes[i] = asterAdventureBest(base, social.id.day, i, &menuBest)
                ? menuBest.elapsedMs : 0;
        }
        if (!showMenu(base, social.id.day)) endMenu(base);
        return;
    }
    Object app = gameApp(base);
    if (!menuMounted(app)) {
        endMenu(base, Word(SocialEvent::Closed));
        return;
    }
    Word action = menu.action;
    menu.action = 0;
    if (!action) return;
    native<int>(base, 0x147adc, 4, "AsterSocial", "menu day=%u action=%u", social.id.day, action);
    if (action == Dismiss) {
        endMenu(base);
        return;
    }
    if (action == Enter) {
        if (menu.stars && !starChallengesUnlocked(base, social.id.day)) {
            menu.unlocked = false;
            if (!showMenu(base, social.id.day)) endMenu(base);
            return;
        }
        endMenu(base);
        selectedChallenge = {social.id.owner, social.id.day, menu.stars, clock + 2000U, false};
        startStockLevel(base);
        return;
    }
    if (action == WatchFriend) {
        if (menu.chosenFriend && publish(base, menu.chosenFriend)) {
            menu.watch = menu.chosenFriend;
            social.expires = clock + 1000U;
        }
        return;
    }
    if (action >= chooseFriend && action - chooseFriend < menu.scoreCount) {
        menu.chosenFriend = action;
    } else if (action >= SelectStars && action < SelectStars + 4) {
        menu.stars = action - SelectStars;
        menu.page = menu.chosenFriend = 0;
    } else if (action == PrevPage && menu.page) {
        --menu.page;
        menu.chosenFriend = 0;
    } else if (action == NextPage) {
        ++menu.page;
        menu.chosenFriend = 0;
    }
    if (!showMenu(base, social.id.day)) endMenu(base);
}
}

extern "C" void asterAdventureSocialFrame(Word base) {
    // Restart can create a new Board in the same scene. Keep the selected
    // tier through that transition, and retire it on leaving the battle.
    if (selectedChallenge.day && selectedChallenge.applied &&
        (field<Word>(social.scene, 0x984) != 6 ||
         owner(ownerStore(base)) != selectedChallenge.owner)) {
        selectedChallenge.day = 0;
    }
    if (social.phase == SocialPhase::Idle) return;
    Object board = gameBoard(base);
    Word scene = field<Word>(social.scene, 0x984);
    if (social.phase == SocialPhase::Returning) {
        if (board == social.board && scene == 6) return;
        publish(base, Word(social.failed ? SocialEvent::Unavailable : SocialEvent::Closed));
        social.phase = SocialPhase::Idle;
        social.board = nullptr;
        return;
    }
    if (social.failed) {
        returnToMap(base, true);
        return;
    }
    if (owner(ownerStore(base)) != social.id.owner ||
        (social.phase == SocialPhase::Choosing && scene != social.previousScene)) {
        if (social.phase == SocialPhase::Choosing) endMenu(base, Word(SocialEvent::Closed));
        else returnToMap(base, true);
        return;
    }
    if (social.phase == SocialPhase::Viewing && social.backRequested) {
        returnToMap(base, false);
        return;
    }
    Word clock = wallTime(base);
    if (static_cast<int>(clock - social.expires) >= 0) {
        if (social.phase == SocialPhase::Choosing) {
            if (menu.watch) {
                publish(base, Word(SocialEvent::Unavailable));
                menu.watch = 0;
                social.expires = clock + 60000U;
            } else {
                endMenu(base);
                return;
            }
        } else {
            returnToMap(base, true);
            return;
        }
    }
    if (social.phase == SocialPhase::Choosing) {
        updateMenu(base, clock);
        if (social.phase == SocialPhase::Idle) return;
    }
    if (clock - social.lastPoll < 10U) return;
    social.lastPoll = clock;
    SocialMessage reply;
    if (!readReply(base, reply)) return;
    auto command = static_cast<SocialCommand>(reply.kind);
    if (social.phase == SocialPhase::Choosing) {
        if (command == SocialCommand::Scores) {
            if (!menu.watch && menu.scoreCount && !showMenu(base, social.id.day)) endMenu(base);
        } else if (command == SocialCommand::Watch) {
            prepareFormationTitle(menu.scores[menu.watch - chooseFriend].name, friendRecord.elapsedMs);
            closeMenu(base);
            menu.watch = 0;
            social.phase = SocialPhase::Loading;
            social.expires = clock + 2000U;
            startStockLevel(base);
        } else if (command == SocialCommand::Back && menu.watch) {
            menu.watch = 0;
            social.expires = clock + 60000U;
        }
    } else if (command == SocialCommand::Back) {
        returnToMap(base, false);
    }
}

extern "C" void asterAdventureViewLoaded(Word base, Object board) {
    if (social.phase != SocialPhase::Loading || !board || board != gameBoard(base)) return;
    if (AdventureRecords::egyptDay(field<const char*>(board, 0xc4)) != social.id.day) return;
    // These are transient Board fields. Normal play keeps its selected
    // challenge and the owning player's unlock and reward records.
    field<int>(board, 0x7f0) = -1;
    field<unsigned char>(board, 0x8a0) = 0;
    social.board = board;
}

extern "C" bool asterAdventureSelectChallenge(Word base, Object board, Object properties) {
    if (!board || board != gameBoard(base)) return false;
    Word day = AdventureRecords::egyptDay(field<const char*>(board, 0xc4));
    if (!day) return false;
    int index = -1;
    if (social.phase != SocialPhase::Loading || day != social.id.day) {
        const auto choice = selectedChallenge;
        if (!properties || day != choice.day || choice.owner != owner(ownerStore(base)) ||
            (!choice.applied && static_cast<int>(wallTime(base) - choice.expires) >= 0)) return false;
        if (choice.stars) {
            const Word first = field<Word>(properties, 0x1c);
            const Word last = field<Word>(properties, 0x20);
            if (!first || last < first || last - first < choice.stars * 12) return false;
            index = int(choice.stars) - 1;
        }
        selectedChallenge.applied = true;
        native<int>(base, 0x147adc, 4, "AsterSocial", "play day=%u stars=%u", day, choice.stars);
    }
    if (index < 0) field<unsigned char>(board, 0x8a0) = 0;
    field<int>(board, 0x7f0) = index;
    return true;
}

extern "C" bool asterAdventureSelectedStarModule(Word base) {
    const auto choice = selectedChallenge;
    if (!choice.applied || !choice.day || !choice.stars || choice.stars > 3 ||
        choice.owner != owner(ownerStore(base))) return false;
    Object board = gameBoard(base);
    return board && AdventureRecords::egyptDay(field<const char*>(board, 0xc4)) == choice.day &&
        field<int>(board, 0x7f0) == int(choice.stars) - 1;
}

static int challengeDialogStars(Word base, Word count, Word index, Word mode) {
    if (count != 3 || index >= 3 || mode < 1 || mode > 3) return -1;
    Object board = gameBoard(base);
    if (!board || field<Word>(board, 0x7f0) != index) return -1;
    const auto* alias = &field<const char*>(board, 0xc4);
    if (!AdventureRecords::egyptDay(*alias)) return -1;
    Object store = ownerStore(base);
    Object profile = store ? native<Object>(base, 0x7a98dc, store) : nullptr;
    return profile ? int(earnedStars(base, profile, alias)) : -1;
}

extern "C" bool asterAdventureAllStarsTitle(Word base, Object page) {
    const Word index = field<Word>(page, 0x48);
    const int mask = challengeDialogStars(base, field<Word>(page, 0x44), index,
                                        field<Word>(page, 0x4c));
    return mask < 0 ? index == 2 : (Word(mask) | (1U << index)) == 7;
}

extern "C" int asterAdventureOtherStarArt(Word base, Object widget, Word slot) {
    const Word index = field<Word>(widget, 0xa4);
    // Keep the selected star's stock outline and reward animation.
    if (slot == index || slot >= 3) return -1;
    const int mask = challengeDialogStars(base, field<Word>(widget, 0xa0), index,
                                        field<Word>(widget, 0xa8));
    return mask < 0 ? -1 : int((Word(mask) >> slot) & 1);
}

// The native phase-1 update has finished loading the level resources and is
// about to open its intro. Run the native transition that reveals the Board,
// then switch to the defense editor's animation pass. The begin-battle entry is blocked
// in case an intro module tries to start gameplay during SetPhase.
extern "C" bool asterAdventureEnterView(Word base, Object board, Word nextPhase) {
    if (nextPhase != 3 || social.phase != SocialPhase::Loading || !board || board != social.board) {
        return false;
    }
    social.phase = SocialPhase::Viewing;
    native<void>(base, 0x224554, board, nextPhase);
    Object registry = native<Object>(base, 0x11d74b4);
    Object names = field<Object>(reinterpret_cast<Object>(base), 0x183049c);
    if (!registry || !names || field<Word>(board, 0xb4) != 9 || field<Word>(board, 0xb8) != 5) {
        social.failed = true;
        return true;
    }
    for (Word i = 0; i < friendRecord.count; ++i) {
        const Plant& item = friendRecord.plants[i];
        const char* alias = nullptr;
        char allocator = 0;
        WeakRef type;
        native<void>(base, 0x14ed0e1, &alias, item.type, &allocator);
        native<void>(base, 0x20cea8, &type, names, &alias);
        releaseString(base, alias);
        Object found = native<Object>(base, 0x1da034, registry, &type);
        // A record does not name the exact outfit. Use the base appearance
        // without inheriting the viewer's currently equipped costume.
        Object plant = found ? native<Object>(base, 0x21ab00, board, Word(item.column), Word(item.row),
            &type, 0U, 1U, int(item.level), 0U, 1U, 1U) : nullptr;
        native<void>(base, 0x1d9bb4, &type, 0U, 0U, 0U);
        if (!plant) {
            social.failed = true;
            return true;
        }
    }
    // Phase 4 allows the normal HUD hit test. This preview skips the
    // chooser and keeps the battle entry guarded for its entire lifetime.
    native<void>(base, 0x224554, board, 4U);
    native<int>(base, 0x147adc, 4, "AsterSocial", "view day=%u plants=%u", social.id.day, friendRecord.count);
    social.expires = wallTime(base) + 360000U;
    social.failed = !showFormationHud(base, board);
    return true;
}

extern "C" bool asterAdventureViewFrozen(Word, Object board) {
    return isFormationBoard(board);
}
