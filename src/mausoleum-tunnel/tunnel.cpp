#include "qin_routes.inc"
#include "zoybean_balance.h"

using Word = unsigned;
using Object = unsigned char*;

extern "C" void __aeabi_memclr8(void* memory, Word size) {
    // The injected module is linked without the Android C runtime.
    auto bytes = static_cast<volatile unsigned char*>(memory);
    for (Word i = 0; i < size; ++i) bytes[i] = 0;
}

template<class T> static T field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R native(Word base, Word offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

static Object currentApp(Word base) {
    const auto holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return holder ? field<Object>(holder, 0) : nullptr;
}

static Object currentBoard(Word base) {
    const auto app = currentApp(base);
    return app ? field<Object>(app, 0x6bc) : nullptr;
}

static int compare(const char* first, const char* second) {
    while (*first && *first == *second) {
        ++first;
        ++second;
    }
    return static_cast<unsigned char>(*first) - static_cast<unsigned char>(*second);
}

static bool equal(const char* actual, const char* expected) {
    return actual && compare(actual, expected) == 0;
}

struct Route {
    const Cell* cells;
    unsigned count;
};

static Route routeFor(Object board) {
    if (!board) return {};
    const auto alias = field<const char*>(board, 0xc4);
    if (equal(alias, "mausoleum1")) return {qinRoad2, sizeof(qinRoad2) / sizeof(Cell)};
    return {};
}

static bool qinMusicPlaying;
static bool qinMusicLoaded;
static bool motonAudioLoaded;
static bool motonAudioAttempted;
static bool teaAudioLoaded;
static bool teaAudioAttempted;
static bool zoybeanAudioLoaded;
static bool zoybeanAudioAttempted;

static bool startsWith(const char* actual, const char* prefix);

static const char* motonAudioFallback(const char* name) {
    if (equal(name, "Play_Plant_Moton_Fire")) return "Play_Throw";
    if (equal(name, "Play_Plant_Moton_Fire_Hit")) return "Play_Splat";
    if (equal(name, "Play_Plant_Moton_PF")) return "Plant_Citron_Nitro";
    if (equal(name, "Play_Plant_Moton_PF_Hit")) return "Play_Plant_Future_Citron_Impact";
    return nullptr;
}

extern "C" Word asterMotonAudioEvent(const char* name) {
    return motonAudioFallback(name) != nullptr || startsWith(name, "Play_Plant_ElectriciTea_") ||
           startsWith(name, "Play_Plant_Zoybean_");
}

extern "C" Word asterQinMusicEvent(Word base, Object sound, const char* name, Word emitter,
                                  Word original, const void* bank, Word bankSize,
                                  const void* motonBank, Word motonBankSize,
                                  const void* teaBank, Word teaBankSize,
                                  const void* zoybeanBank, Word zoybeanBankSize) {
    if (zoybeanBankSize && startsWith(name, "Play_Plant_Zoybean_")) {
        if (!zoybeanAudioAttempted) {
            Word bankId = 0;
            zoybeanAudioLoaded = native<int>(base, 0x1528b60, zoybeanBank, zoybeanBankSize, &bankId) == 1;
            zoybeanAudioAttempted = true;
        }
        return zoybeanAudioLoaded ? native<Word>(base, original, sound, name, emitter) : 0;
    }
    if (teaBankSize && startsWith(name, "Play_Plant_ElectriciTea_")) {
        if (!teaAudioAttempted) {
            Word bankId = 0;
            teaAudioLoaded = native<int>(base, 0x1528b60, teaBank, teaBankSize, &bankId) == 1;
            teaAudioAttempted = true;
        }
        return teaAudioLoaded ? native<Word>(base, original, sound, name, emitter) : 0;
    }
    const char* fallback = motonAudioFallback(name);
    const bool qinBattleMusic = equal(name, "Play_Music_World") && routeFor(currentBoard(base)).cells;
    if (!motonAudioAttempted && motonBankSize && (fallback || qinBattleMusic)) {
        Word bankId = 0;
        const int status = native<int>(base, 0x1528b60, motonBank, motonBankSize, &bankId);
        motonAudioLoaded = status == 1;
        motonAudioAttempted = true;
        native<int>(base, 0x147adc, 4, "AsterQinAudio", "Moton bank load status=%d id=%u", status, bankId);
    }
    if (fallback) {
        const auto playing = motonAudioLoaded ? native<Word>(base, original, sound, name, emitter) : 0;
        return playing ? playing : native<Word>(base, original, sound, fallback, emitter);
    }
    const auto result = native<Word>(base, original, sound, name, emitter);
    if (qinMusicPlaying && equal(name, "Stop_Music_World")) {
        native<Word>(base, original, sound, "Stop_Aster_Qin_Chapter_One", emitter);
        qinMusicPlaying = false;
    } else if (!qinMusicPlaying && qinBattleMusic) {
        if (!qinMusicLoaded) {
            Word bankId = 0;
            const int status = native<int>(base, 0x1528b60, bank, bankSize, &bankId);
            native<int>(base, 0x147adc, 4, "AsterQinAudio", "Wwise bank load status=%d id=%u", status, bankId);
            if (status != 1) return result;
            qinMusicLoaded = true;
        }
        const auto playing = native<Word>(base, original, sound, "Play_Aster_Qin_Chapter_One", emitter);
        qinMusicPlaying = playing != 0;
        native<int>(base, 0x147adc, 4, "AsterQinAudio", "Wwise chapter music playing ID %u", playing);
    }
    return result;
}

static bool active(Object board) {
    return field<Word>(board, 0xc0) == 5 && !field<Word>(board, 0x7f4)
        && !field<unsigned char>(board, 0x8d5) && !field<unsigned char>(board, 0x7fd);
}

struct Point { float x; float y; };
static constexpr float firstLaneY = 222.0f;
static constexpr float laneHeight = 76.0f;
static constexpr float archerAttackX = 744.0f;
static constexpr char archerAlias[] = "mausoleum_archer";
static constexpr char drunkardAlias[] = "mausoleum_drunkard";
static constexpr char assassinAlias[] = "qin_jingke";
static constexpr char taoistAlias[] = "qin_taoist";
static constexpr char terracottaSmall[] = "qin_terracotta_small";
static constexpr char terracottaGeneral[] = "qin_terracotta_mid";
static constexpr char terracottaRuin[] = "terracottaArmy";

static bool startsWith(const char* actual, const char* prefix) {
    if (!actual) return false;
    while (*prefix) if (*actual++ != *prefix++) return false;
    return true;
}

static bool qinBattlefield(Object board) {
    return board && startsWith(field<const char*>(board, 0xc4), "mausoleum");
}

static bool isZoybeanAlly(const char* alias) {
    return startsWith(alias, "zoybeanpod_") || equal(alias, "zombie_zoybeanpodgatlingpea");
}

extern "C" Word asterQinSkipLegacyZombieGoal(const char* alias) {
#ifdef ASTER_ZOYBEAN_SHOWCASE
    if (equal(alias, "zoybean_showcase_target")) return 1;
#endif
    return startsWith(alias, "mausoleum_") || startsWith(alias, "qin_shield_")
        || isZoybeanAlly(alias) || equal(alias, assassinAlias) || equal(alias, taoistAlias)
        || equal(alias, terracottaSmall) || equal(alias, terracottaGeneral);
}

static float absolute(float value) { return value < 0 ? -value : value; }
static float clamp(float value, float upper) { return value < 0 ? 0 : value > upper ? upper : value; }

static Point routePoint(Route route, unsigned index) {
    const Cell& cell = route.cells[index == 0 ? 0 : index > route.count ? route.count - 1 : index - 1];
    return {
        index == 0 ? 776.0f : index > route.count ? 200.0f : 232.0f + 64.0f * cell.col,
        firstLaneY + laneHeight * cell.row
    };
}

// Locate an actor on the horizontal/vertical centerline. The tolerance is
// narrower than half a tile, so a zombie in a neighbouring lane cannot snap in.
static float project(Route route, Point position) {
    if (position.x <= 200 || position.x > 776) return -1;
    float best = 26.0f;
    float progress = -1;
    float total = 0;
    Point start = routePoint(route, 0);
    for (unsigned i = 1; i <= route.count + 1; ++i) {
        const Point end = routePoint(route, i);
        const float dx = end.x - start.x;
        const float dy = end.y - start.y;
        const float length = absolute(dx) + absolute(dy);
        const float advance = dx ? (position.x - start.x) * (dx < 0 ? -1 : 1)
                                 : (position.y - start.y) * (dy < 0 ? -1 : 1);
        const float distance = clamp(advance, length);
        const float off = (dx ? absolute(position.y - start.y) : absolute(position.x - start.x))
                        + absolute(advance - distance);
        if (off <= best) {
            best = off;
            progress = total + distance;
        }
        total += length;
        start = end;
    }
    return progress;
}

static Point follow(Route route, float distance) {
    Point start = routePoint(route, 0);
    for (unsigned i = 1; i <= route.count + 1; ++i) {
        const Point end = routePoint(route, i);
        const float dx = end.x - start.x;
        const float dy = end.y - start.y;
        const float length = absolute(dx) + absolute(dy);
        if (distance < length) {
            if (dx) start.x += dx < 0 ? -distance : distance;
            else start.y += dy < 0 ? -distance : distance;
            return start;
        }
        distance -= length;
        start = end;
    }
    return start;
}

static void setPosition(Object zombie, Point p) {
    const float position[] = {p.x, p.y, field<float>(zombie, 0x18)};
    const auto table = field<Word*>(zombie, 0);
    reinterpret_cast<void(*)(Object, const float*)>(table[0x3c / 4])(zombie, position);
}

static int rowAt(float y) { return static_cast<int>((y - firstLaneY) / laneHeight + 0.5f); }

static Object archerTarget(Word base, Object board, Object zombie) {
    const float x = field<float>(zombie, 0x10);
    const int row = rowAt(field<float>(zombie, 0x14));
    if (!board || x > archerAttackX || row < 0 || row >= 5) return nullptr;
    static constexpr struct { Word size, capacity, references; char value[4]; } empty{};
    const char* type = empty.value;
    for (int col = 8; col >= 0; --col) {
        if (232.0f + 64.0f * col >= x) continue;
        const auto plant = native<Object>(base, 0x203990, board, col, row, &type);
        if (plant && !native<Word>(base, 0x348944, plant)) return plant;
    }
    return nullptr;
}

static const char* zombieAlias(Word base, Object zombie) {
    if (!zombie) return nullptr;
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto type = registry ? native<Object>(base, 0x1da034, registry, zombie + 0xc8) : nullptr;
    return type ? field<const char*>(type, 4) : nullptr;
}

static bool isQinTerracotta(const char* alias) {
    return equal(alias, terracottaSmall) || equal(alias, terracottaGeneral);
}

extern "C" Word asterQinImmuneToHypnosis(Word base, Object zombie) {
    const auto alias = zombieAlias(base, zombie);
    return isQinTerracotta(alias) || isZoybeanAlly(alias);
}

extern "C" float asterZoybeanGroundStep(Word base, Object zombie, float authoredStep) {
    // The legacy movement code applies the right-facing sign after this
    // lookup. The CN summons already encode the opposite sign in the PAM.
    return authoredStep < 0 && isZoybeanAlly(zombieAlias(base, zombie)) ? -authoredStep : authoredStep;
}

extern "C" Word asterQinRejectCondition(Word base, Object zombie, Word condition) {
    switch (condition) {
    case 22: // hypnotized
        return asterQinImmuneToHypnosis(base, zombie);
    case 0:  // chill
    case 1:  // freeze
    case 2:  // stun
    case 3:  // butter
    case 21: // stucked
    case 23: // sunbeaned
    case 29: // haunted
    case 30: // icecubed
    case 33: // sapped
    case 37: // present_boxed
    case 39: // poison
    case 53: // shrinking
    case 54: // shrunken
        return isQinTerracotta(zombieAlias(base, zombie));
    default:
        return 0;
    }
}

static bool isArcher(Word base, Object zombie) {
    return equal(zombieAlias(base, zombie), archerAlias);
}

struct alignas(8) DamageInfo {
    Word kind;
    float amount;
    Word flags[2];
    int sourceType;
    int sourceLevel;
    Word modifiers[6];
};

static constexpr Word bypassHelmDamage = 1U << 3;
static constexpr Word lightningDamage = 1U << 6;
static constexpr Word lobbedDamage = 1U << 10;
static constexpr Word catapultDamage = 1U << 22;
static constexpr Word bodyHealthOffset = 0x138;
static constexpr Word scrollHealthOffset = 0x150;
static constexpr Word armorKindOffset = 0x80;
static constexpr Word facingOffset = 0x134;

static void clearAssassinScroll(Object zombie) {
    *reinterpret_cast<float*>(zombie + scrollHealthOffset) = 0.0f;
    *reinterpret_cast<Word*>(zombie + armorKindOffset) = 0;
}

static Object damagingProjectile;
static Object projectileVictim;
static void terracottaDefeated(Word base, Object zombie, const DamageInfo& hit);

static constexpr Word missingPlantId = ~0U;
static constexpr Word motonPlantId = 0x100;
static constexpr Word zoybeanId = 0x102;
static constexpr char zoybeanAlias[] = "zoybeanpod";

static Word legacyPlantId(Object map, const char* name) {
    for (Object node = field<Object>(map, 0xc); node;) {
        const int order = compare(name, field<const char*>(node, 0x10));
        if (!order) return field<Word>(node, 0x14);
        node = field<Object>(node, order < 0 ? 8 : 12);
    }
    return missingPlantId;
}

static bool exploitsTerracottaWeakness(Word base, int sourceType) {
    if (sourceType < 0) return false;
    const auto plantIds = reinterpret_cast<Object>(base + 0x1830470);
    return static_cast<Word>(sourceType) == legacyPlantId(plantIds, "moton")
        || static_cast<Word>(sourceType) == legacyPlantId(plantIds, "agave")
        || static_cast<Word>(sourceType) == legacyPlantId(plantIds, "lemon");
}

static const char* plantAlias(Word base, Object plant) {
    if (!plant) return nullptr;
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto type = registry ? native<Object>(base, 0x1da034, registry, plant + 0xf8) : nullptr;
    return type ? field<const char*>(type, 4) : nullptr;
}

extern "C" Word asterMotonCanUsePlantFood(Word base, Object framework) {
    // The generic framework shares its activation code with stock plants,
    // but defaults to disabled. The caller has already checked plant state.
    const auto alias = plantAlias(base, field<Object>(framework, 8));
    return equal(alias, "moton") || equal(alias, "electricitea") || equal(alias, zoybeanAlias);
}

static void electriciteaAction(Word base, Object plant, bool plantFood);
static void updateZoybeanPlant(Word base, Object plant, Object board);

static Cell electriciteaCell(Object plant) {
    // Aster stores Plant::mRow before Plant::mColumn.
    return {field<int>(plant, 0xb0), field<int>(plant, 0xac)};
}

static bool electriciteaValidCell(Cell cell) {
    return cell.col >= 0 && cell.col < 9 && cell.row >= 0 && cell.row < 5;
}

extern "C" Word asterMotonAction(Word base, Object plant, int projectileAction) {
    const auto alias = plantAlias(base, plant);
    if (equal(alias, "electricitea")) {
        if (electriciteaValidCell(electriciteaCell(plant)))
            electriciteaAction(base, plant, projectileAction == 1);
        return 1;
    }
    if (equal(alias, zoybeanAlias)) return 1;
    if (!equal(alias, "moton")) return 0;
    if (field<int>(plant, 0xac) < 0 || field<int>(plant, 0xb0) < 0) return 1;
    // Each Moton animation command fires its own projectile, independently
    // of the legacy framework's current action index.
    auto& action = *reinterpret_cast<int*>(plant + 0xe8);
    const int previousAction = action;
    action = projectileAction;
    native<Object>(base, 0x4b3c5c, plant);
    action = previousAction;
    return 1;
}

static bool isMotonProjectile(Object projectile) {
    const auto props = field<Object>(projectile, 0x40);
    return props && equal(field<const char*>(props, 0x98), "POPANIM_EFFECTS_MOTON_EFFECT");
}

#ifdef ASTER_ZOYBEAN_SHOWCASE
static bool zoybeanShowcaseGatlingHit(Object projectile);
#endif

static void releaseText(Word base, const char* value);

extern "C" Word asterMotonImpact(Word base, Object projectile) {
    if (!isMotonProjectile(projectile)) return 0;
    const auto props = field<Object>(projectile, 0x40);
    const bool powered = equal(field<const char*>(props, 0xa8), "plantfood");
    const char* cue = powered ? "Play_Plant_Moton_PF_Hit" : "Play_Plant_Moton_Fire_Hit";
    const char* name;
    char allocator = 0;
    native<void>(base, 0x14ed0e1, &name, cue, &allocator);
    native<void>(base, 0x23f268, projectile, &name, 0U);
    releaseText(base, name);
    return 1;
}

extern "C" void asterQinProjectileHit(Object target, const DamageInfo* hit, Object projectile, Word original) {
    // The damage itself runs synchronously through the target's virtual handler.
    const auto previousProjectile = damagingProjectile;
    const auto previousVictim = projectileVictim;
    damagingProjectile = projectile;
    projectileVictim = target;
    reinterpret_cast<void(*)(Object, const DamageInfo*)>(original)(target, hit);
    damagingProjectile = previousProjectile;
    projectileVictim = previousVictim;
}

extern "C" void asterQinTakeDamage(Word base, Object zombie, const DamageInfo* hit, Word original) {
    const auto apply = reinterpret_cast<void(*)(Object, const DamageInfo*)>(original);
    const auto alias = zombieAlias(base, zombie);
    DamageInfo pigHit;
    if ((hit->flags[0] & lightningDamage) && equal(alias, "mausoleum_piggy")) {
        // The legacy ZombieBasic electrocution clip contains a humanoid skeleton.
        pigHit = *hit;
        pigHit.flags[0] &= ~lightningDamage;
        hit = &pigHit;
    }
    DamageInfo motonHit;
    if (hit->amount > 0 && projectileVictim == zombie && damagingProjectile && isMotonProjectile(damagingProjectile)) {
        motonHit = *hit;
        motonHit.sourceType = motonPlantId;
        if (field<Word>(zombie, armorKindOffset) || equal(alias, "qin_taoist"))
            motonHit.amount *= 2.0f;
        hit = &motonHit;
    }
    const bool general = equal(alias, terracottaGeneral);
    if (general || equal(alias, terracottaSmall)) {
        const auto health = field<float>(zombie, bodyHealthOffset);
        if (hit->amount > 0 && exploitsTerracottaWeakness(base, hit->sourceType)) {
            DamageInfo weakness = *hit;
            // CN applies the source multiplier as 1 + AttackUpRate (2.0).
            weakness.amount *= 3.0f;
            apply(zombie, &weakness);
        } else {
            apply(zombie, hit);
        }
        if (general && health > 0 && field<float>(zombie, bodyHealthOffset) <= 0)
            terracottaDefeated(base, zombie, *hit);
        return;
    }
    if (field<float>(zombie, scrollHealthOffset) <= 0.0f || !equal(alias, assassinAlias)) {
#ifdef ASTER_ZOYBEAN_SHOWCASE
        if (equal(alias, "zoybean_showcase_target") && projectileVictim == zombie &&
            damagingProjectile && zoybeanShowcaseGatlingHit(damagingProjectile)) {
            const auto health = field<float>(zombie, bodyHealthOffset);
            apply(zombie, hit);
            native<int>(base, 0x147adc, 4, "AsterZoybeanTest",
                        "gatling hit row=%d vx=%d damage=%d body=%d->%d",
                        rowAt(field<float>(zombie, 0x14)) + 1, int(field<float>(damagingProjectile, 0x6c)),
                        int(hit->amount), int(health), int(field<float>(zombie, bodyHealthOffset)));
            return;
        }
#endif
        apply(zombie, hit);
        return;
    }

    const Word state = field<Word>(zombie, 0xd8);
    if (field<float>(zombie, bodyHealthOffset) <= 0 || (state >= 5 && state <= 9)) {
        clearAssassinScroll(zombie);
        apply(zombie, hit);
        return;
    }
    const bool protectedFromHit = !(field<Word>(zombie, 0x8c) & 0x4000);
    const Word bypassFlags = bypassHelmDamage | lobbedDamage | catapultDamage;
    if (projectileVictim == zombie && damagingProjectile && protectedFromHit
        && hit->amount > 0.0f && !(hit->flags[0] & bypassFlags)) {
        const float speedX = field<float>(damagingProjectile, 0x6c);
        const bool mirrored = field<unsigned char>(damagingProjectile, 0xc0) != 0;
        const float velocityX = mirrored ? -speedX : speedX;
        const bool fromFront = field<Word>(zombie, facingOffset) == 1 ? velocityX < 0.0f : velocityX > 0.0f;
        if (fromFront) {
            auto& scroll = *reinterpret_cast<float*>(zombie + scrollHealthOffset);
            scroll -= hit->amount;
            if (scroll <= 0.0f) clearAssassinScroll(zombie);
            return;
        }
    }

    DamageInfo body = *hit;
    body.flags[0] |= bypassHelmDamage;
    apply(zombie, &body);
    if (field<float>(zombie, bodyHealthOffset) <= 0.0f) clearAssassinScroll(zombie);
}

extern "C" Object asterQinDropHeadgear(Word base, Object zombie, Word kind, int health, Word original) {
    // The scroll uses the stock health slot but its PAM has no cone drop part.
    if (equal(zombieAlias(base, zombie), assassinAlias)) return nullptr;
    return reinterpret_cast<Object(*)(Object, Word, int)>(original)(zombie, kind, health);
}

static constexpr char shieldSegment[] = "qin_shield_segment";
static constexpr char shieldPair[] = "qin_shield_pair";
static constexpr char shieldTriad[] = "qin_shield_triad";

static bool isShield(const char* alias) {
    return equal(alias, shieldSegment) || equal(alias, shieldPair)
        || equal(alias, shieldTriad) || equal(alias, "qin_shield_almanac");
}

extern "C" Word asterQinShieldFollowers(const char* const* alias) {
    if (equal(*alias, shieldPair)) return 1;
    if (equal(*alias, shieldTriad)) return 2;
    return 0;
}

extern "C" Object asterQinShieldSegment(Word base, Object output, Object leader, Word original) {
    if (!isShield(zombieAlias(base, leader)))
        return reinterpret_cast<Object(*)(Object, Object)>(original)(output, leader);

    // The Camel formation asks its leader for the type of each following unit.
    const auto types = field<Object>(reinterpret_cast<Object>(base), 0x1830498);
    static constexpr struct { Word length, capacity, references; char value[sizeof(shieldSegment)]; }
        alias{sizeof(shieldSegment) - 1, sizeof(shieldSegment) - 1, 0, "qin_shield_segment"};
    const char* name = alias.value;
    return native<Object>(base, 0x1df078, output, types, &name);
}

extern "C" void asterQinCamelSign(Word base, Object zombie, Word kind, float health) {
    if (!isShield(zombieAlias(base, zombie))) native<void>(base, 0xa4367c, zombie, kind, health);
}

extern "C" Word asterQinArcherCanShoot(Word base, Object zombie) {
    if (!isArcher(base, zombie)) return native<Word>(base, 0xc1ec30, zombie);
    return !!archerTarget(base, currentBoard(base), zombie);
}

extern "C" void asterQinAimArrow(Word base, Object projectile, Object zombie) {
    if (!projectile || !isArcher(base, zombie)) return;
    const auto plant = archerTarget(base, currentBoard(base), zombie);
    const float target[] = {
        plant ? field<float>(plant, 0x10) : 200.0f,
        plant ? field<float>(plant, 0x14) : field<float>(zombie, 0x14),
        plant ? field<float>(plant, 0x18) : 0.0f,
    };
    native<void>(base, 0x7b520c, projectile, target, 350.0f, 1.0f);
}

struct ZombieList { Object* first; Object* end; };

static ZombieList liveZombies(Word base, Object board) {
    const auto list = native<Object>(base, 0x20a1c0, board);
    if (!list) return {};
    const auto first = field<Object*>(list, 0);
    const auto end = field<Object*>(list, 4);
    if (!first || end < first || end - first > 4096) return {};
    return {first, end};
}

struct Identity {
    Word low;
    Word high;
    bool operator==(const Identity& other) const { return low == other.low && high == other.high; }
};

static Identity identity(Object actor) { return {field<Word>(actor, 8), field<Word>(actor, 12)}; }

struct Rider {
    Object zombie;
    Identity id;
    float x;
    float distance;
    float scale;
    bool vendor;
};

// Negative values mark actors that use this update without following the tunnel.
static constexpr float archerUpdate = -1.0f;
static constexpr float drunkardUpdate = -2.0f;
static constexpr float assassinUpdate = -3.0f;
static constexpr float taoistUpdate = -4.0f;
static constexpr float terracottaUpdate = -5.0f;

struct VendorClock { Identity id; float due; Word round; };

static VendorClock cartClocks[96];
static Word battleRound;
static Object lastBoard;
static float lastBattleStart;

enum class DrunkardAction { walking, drinking, changingRow, spraying };

struct Drunkard {
    Identity id;
    Word round;
    DrunkardAction action;
    float startX;
    float startedAt;
    int row;
    int destination;
    bool sprayed;
};

static Drunkard drunkards[64];
enum class ArcherPose { walking, crouching, aiming, firing, standing };
struct Archer { Identity id; Word round; ArcherPose pose; };
static Archer archers[64];

enum class AssassinPhase { approach, reveal, vanish, land, hunt, strike };
struct Assassin {
    Identity id;
    Word round;
    AssassinPhase phase;
    float position;
    int targetColumn;
    bool struck;
};
static Assassin assassins[64];

enum class QinAction { walk, convert, raise, channel, finish, emerge, smash };
struct QinActor {
    Identity id;
    Word round;
    QinAction action;
    float position;
    float due;
    Identity target;
    Cell cell;
    bool applied;
};
static QinActor terracottaActors[128];

static QinActor& qinActor(Object zombie) {
    const auto id = identity(zombie);
    auto& actor = terracottaActors[id.low % 128];
    if (actor.round != battleRound || !(actor.id == id)) {
        actor.id = id;
        actor.round = battleRound;
        actor.action = QinAction::walk;
        actor.due = 0;
    }
    return actor;
}

static bool zoybeanGiant(const char* alias);

extern "C" void asterQinBeginBite(Word base, Object zombie, Word state, Word transition) {
    if ((field<Word>(zombie, 0x1c) & 1U) && zoybeanGiant(zombieAlias(base, zombie))) return;
    const auto id = identity(zombie);
    const auto& actor = assassins[id.low % 64];
    // Once the scroll breaks, this zombie only deals dagger damage.
    if (actor.round == battleRound && actor.id == id && actor.phase != AssassinPhase::approach
        && currentBoard(base) == lastBoard && routeFor(lastBoard).cells) return;
    const auto& qin = terracottaActors[id.low % 128];
    if (currentBoard(base) == lastBoard && qinBattlefield(lastBoard)
        && ((qin.round == battleRound && qin.id == id && qin.action != QinAction::walk)
            || equal(zombieAlias(base, zombie), terracottaGeneral))) return;
    native<void>(base, 0xa558f0, zombie, state, transition);
}

struct SprayStun { Identity id; Word round; float until; };
static SprayStun sprayStuns[128];

extern "C" Word asterQinPlantSprayStunned(Word base, Object plant) {
    const Identity id = identity(plant);
    const auto& stun = sprayStuns[id.low % 128];
    if (stun.round != battleRound || !(stun.id == id) || !stun.until) return 0;
    const auto board = currentBoard(base);
    if (board != lastBoard || !routeFor(board).cells) return 0;
    const auto clock = native<Object>(base, 0x1f7380);
    return clock && field<float>(clock, 0x24) < stun.until;
}

static void releaseText(Word base, const char* value) {
    char allocator = 0;
    native<void>(base, 0x14ebf59, value - 12, &allocator);
}

static Word shieldWear(float health, float maximum) {
    return health > maximum * 0.667f ? 0 : health > maximum * 0.333f ? 1 : 2;
}

extern "C" void asterQinShieldArt(Word base, Object zombie) {
    if (!isShield(zombieAlias(base, zombie))) return;
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    const auto animation = rig ? field<Object>(rig, 0x14) : nullptr;
    if (!animation || !field<Object>(animation, 0x40)) return;

    // In the donor the shield artwork tracks body health, with two wear stages.
    const Word damage = shieldWear(field<float>(zombie, 0x138), field<float>(zombie, 0x13c));
    static constexpr char layers[][sizeof("zombie_qin_shield_damage_01")] = {
        "zombie_qin_shield_norm", "zombie_qin_shield_damage_01", "zombie_qin_shield_damage_02",
    };
    for (Word i = 0; i < 3; ++i) {
        char allocator = 0;
        const char* name;
        native<void>(base, 0x14ed0e1, &name, layers[i], &allocator);
        native<Word>(base, 0x774f70, rig, &name, Word(i == damage));
        releaseText(base, name);
    }
}

extern "C" void asterQinShieldBodyHit(Word base, Object zombie, float hitpoints) {
    auto& current = *reinterpret_cast<float*>(zombie + 0x138);
    const float previous = current;
    const float maximum = field<float>(zombie, 0x13c);
    current = hitpoints;
    if (hitpoints <= 0.0f && field<float>(zombie, scrollHealthOffset) > 0.0f
        && equal(zombieAlias(base, zombie), assassinAlias)) clearAssassinScroll(zombie);
    if (shieldWear(previous, maximum) != shieldWear(hitpoints, maximum)) asterQinShieldArt(base, zombie);
}

static void playZombieClip(Word base, Object rig, const char* label, bool loop) {
    if (!rig) return;
    char allocator = 0;
    const char* clip;
    native<void>(base, 0x14ed0e1, &clip, label, &allocator);
    Word tracks[3]{};
    const auto play = field<Word*>(rig, 0)[0x3c / 4];
    reinterpret_cast<int(*)(Object, const char**, Word, float, Word*)>(play)(rig, &clip, loop, 0.0f, tracks);
    if (tracks[0]) native<void>(base, 0x14c2e95, tracks[0]);
    releaseText(base, clip);
}

static bool clipPlaying(Word base, Object rig) {
    return rig && native<Word>(base, 0x7762e4, rig);
}

static float zombieClipFrame(Object rig) {
    const auto anim = rig ? field<Object>(rig, 0x14) : nullptr;
    const auto playback = anim ? field<Object>(anim, 0x40) : nullptr;
    return playback ? field<float>(playback, 0xc) : -1.0f;
}

static Object plantAt(Word base, Object board, int col, int row) {
    static constexpr struct { Word size, capacity, references; char value[4]; } empty{};
    const char* type = empty.value;
    const auto plant = native<Object>(base, 0x203990, board, col, row, &type);
    return plant && !native<Word>(base, 0x348944, plant) ? plant : nullptr;
}

static constexpr float plantCenter(int col) { return 232.0f + 64.0f * col; }

static constexpr float lawnRight = 776.0f;
static float battleTime(Word base) {
    const auto clock = native<Object>(base, 0x1f7380);
    return clock ? field<float>(clock, 0x24) : 0;
}

static bool onLawn(Point position) {
    return position.x >= 200.0f && position.x <= lawnRight && rowAt(position.y) >= 0 && rowAt(position.y) < 5;
}

static constexpr Word electriciteaId = 0x101;

static Point groundPosition(Object entity) {
    return {field<float>(entity, 0x10), field<float>(entity, 0x14)};
}

static bool lightningTarget(Word base, Object zombie) {
    return zombie && !native<Word>(base, 0x348944, zombie) &&
           field<float>(zombie, bodyHealthOffset) > 0 &&
           !(field<Word>(zombie, 0x240) & (1U << 22));
}

struct ElectriciteaRect { int x, y, width, height; };

static ElectriciteaRect electriciteaHitRect(Object zombie) {
    const auto getRect = field<Word*>(zombie, 0)[0x90 / 4];
    return *reinterpret_cast<const ElectriciteaRect* (*)(Object)>(getRect)(zombie);
}

static bool electriciteaInReach(Cell cell, Object zombie) {
    const auto position = groundPosition(zombie);
    const float top = firstLaneY - laneHeight * 0.5f;
    if (position.x < 200.0f || position.x >= lawnRight ||
        position.y < top || position.y >= top + 5 * laneHeight) return false;
    const int zombieColumn = static_cast<int>((position.x - 200.0f) / 64.0f);
    const int zombieRow = rowAt(position.y);
    return zombieColumn >= cell.col - 1 && zombieColumn <= cell.col + 1 &&
           zombieRow >= cell.row - 1 && zombieRow <= cell.row + 1;
}

static unsigned electriciteaTargets(Word base, Object board, Cell cell, Object* targets) {
    unsigned count = 0;
    const auto zombies = liveZombies(base, board);
    for (auto slot = zombies.first; slot != zombies.end; ++slot) {
        auto zombie = *slot;
        if (!lightningTarget(base, zombie) || !electriciteaInReach(cell, zombie)) continue;
        // Reservoir sampling gives each eligible zombie a chance when more than three overlap.
        if (count < 3) targets[count] = zombie;
        else {
            const unsigned index = native<unsigned>(base, 0x11317a8, count + 1);
            if (index < 3) targets[index] = zombie;
        }
        ++count;
    }
    return count < 3 ? count : 3;
}

static void playElectriciteaSound(Word base, Object plant, const char* cue) {
    char allocator = 0;
    const char* sound;
    native<void>(base, 0x14ed0e1, &sound, cue, &allocator);
    native<void>(base, 0x23f268, plant, &sound, 0U);
    releaseText(base, sound);
}

// These visuals use the board's native PopAnim entity factory, as does the stock Lightning Reed.
static Object electriciteaVisual(Word base, Object board, const char* resource, const char* clip,
                                Point point, float height) {
    char allocator = 0;
    const char* value;
    native<void>(base, 0x14ed0e1, &value, resource, &allocator);
    alignas(8) Word handle[2]{};
    native<void>(base, 0xe45d08, handle, &value);
    releaseText(base, value);
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto animation = registry ? native<Object>(base, 0x1da034, registry, handle) : nullptr;
    Object visual = nullptr;
    if (animation) {
        const auto type = native<Object>(base, 0x2f7750);
        visual = native<Object>(base, 0x202274, board, type);
        if (visual) {
            native<void>(base, 0x2f8834, visual, animation, 0U);
            native<void>(base, 0x14ed0e1, &value, clip, &allocator);
            native<void>(base, 0x2fa844, visual, &value, 2U);
            releaseText(base, value);
            const float position[] = {point.x, point.y, height};
            native<void>(base, 0x8fbd94, visual, position, -1);
            native<void>(base, 0x8fbcf0, visual, 1U);
            native<void>(base, 0x2f8a50, visual, 0.5f, 0.5f);
        }
    }
    native<void>(base, 0x1d9bb4, handle, 0U, 0U);
    return visual;
}

struct ElectriciteaPoint {
    Point ground;
    float height;
};

static ElectriciteaPoint electriciteaContact(Object target) {
    // The CN attack targets the center of the hit box horizontally and one third of the way down.
    const auto bounds = electriciteaHitRect(target);
    return {{bounds.x + bounds.width * 0.5f, groundPosition(target).y},
            groundPosition(target).y - (bounds.y + bounds.height / 3.0f)};
}

static void electriciteaBolt(Word base, Object board, ElectriciteaPoint from, ElectriciteaPoint to,
                            bool plantFood) {
    const Point direction{to.ground.x - from.ground.x,
                          (to.ground.y - to.height) - (from.ground.y - from.height)};
    const float lengthSquared = direction.x * direction.x + direction.y * direction.y;
    if (lengthSquared < 1.0f) return;
    const auto visual = electriciteaVisual(base, board,
        "POPANIM_EFFECTS_ELECTRICI_TEA_BOLT",
        plantFood ? "animation2" : "animation", from.ground, from.height);
    if (!visual) return;
    // The CN effect is authored around the canvas center for the segmented bolt renderer.
    // Each clip has a different projected source image on the 390-unit canvas.
    const float startX = plantFood ? 121.0f : 124.0f;
    const float centerY = plantFood ? 176.0f : 151.0f;
    const float width = plantFood ? 149.0f : 143.0f;
    native<void>(base, 0x2f8a50, visual, startX / 390.0f, centerY / 390.0f);
    const auto app = currentApp(base);
    const float projection = app ? field<float>(app, 0x690) : 1.0f;
    native<void>(base, 0x2f8a88, visual, native<float>(base, 0x147800, lengthSquared) * projection / width, 1.0f);
    native<void>(base, 0x2f8abc, visual, &direction);
}

static void electriciteaDamage(Word base, Object board, Object target, float amount, int level, bool red = false,
                               bool counter = false) {
    const auto contact = electriciteaContact(target);
    electriciteaVisual(base, board,
        red ? "POPANIM_EFFECTS_ASTERTEAHITFX_HIT_RED" : "POPANIM_EFFECTS_ASTERTEAHITFX_HIT",
        "idle", contact.ground, contact.height);
    const Word flags = counter ? lightningDamage | bypassHelmDamage | 2U : lightningDamage;
    DamageInfo hit{0, amount, {flags, 0}, electriciteaId, level, {}};
    const auto damage = field<Word*>(target, 0)[0x74 / 4];
    // The counter already owns its eater and can finish even when ordinary shots cannot hit it.
    auto& zombieFlags = *reinterpret_cast<Word*>(target + 0x8c);
    const Word protection = counter ? zombieFlags & 0x4000U : 0;
    zombieFlags &= ~protection;
    reinterpret_cast<void(*)(Object, const DamageInfo*)>(damage)(target, &hit);
    if (protection && field<float>(target, bodyHealthOffset) > 0) zombieFlags |= protection;
    if (red && lightningTarget(base, target)) native<void>(base, 0xa4adcc, target, 3.0f);
}

struct ElectriciteaChain {
    Object board;
    ElectriciteaPoint from;
    Identity hit[3];
    float amount;
    float due;
    float expires;
    int level;
    unsigned count;
    bool burst;
};

static ElectriciteaChain teaChains[90];

static void startElectriciteaChain(Word base, Object board, Object first, ElectriciteaPoint from,
                                  int level, float amount, bool burst) {
    const auto now = battleTime(base);
    for (auto& chain : teaChains) {
        if (chain.board == board && chain.count && chain.expires >= now) continue;
        chain = {board, from, {identity(first)}, amount, now + 0.15f, now + 0.45f, level, 1, burst};
        return;
    }
}

static Object electriciteaChainTarget(Word base, const ElectriciteaChain& chain) {
    Object closest = nullptr;
    float nearest = 128.0f * 128.0f;
    const auto zombies = liveZombies(base, chain.board);
    for (auto slot = zombies.first; slot != zombies.end; ++slot) {
        const auto zombie = *slot;
        if (!lightningTarget(base, zombie)) continue;
        const auto id = identity(zombie);
        bool seen = false;
        for (unsigned i = 0; i < chain.count; ++i) seen |= id == chain.hit[i];
        if (seen) continue;
        const auto point = groundPosition(zombie);
        const float dx = point.x - chain.from.ground.x;
        const float dy = point.y - chain.from.ground.y;
        const float distance = dx * dx + dy * dy;
        if (distance <= nearest) {
            closest = zombie;
            nearest = distance;
        }
    }
    return closest;
}

static void updateElectriciteaChains(Word base, Object board, float now) {
    for (auto& chain : teaChains) {
        if (!chain.count) continue;
        if (chain.board != board || chain.expires < now) {
            chain.count = 0;
            continue;
        }
        if (chain.due > now) continue;
        const auto target = electriciteaChainTarget(base, chain);
        if (!target) continue;
        const auto contact = electriciteaContact(target);
        electriciteaBolt(base, board, chain.from, contact, false);
        electriciteaDamage(base, board, target, chain.amount, chain.level);
        chain.hit[chain.count++] = identity(target);
        if (chain.count == 3) {
            chain.count = 0;
        } else {
            chain.from = contact;
            chain.due = now + 0.15f;
            chain.amount *= chain.burst ? 0.35f : 0.5f;
        }
    }
}

struct ElectriciteaAttack {
    Object board;
    Identity plant;
    float next;
    float strike;
    bool red;
};

static ElectriciteaAttack teaAttacks[45];

static ElectriciteaAttack* electriciteaAttack(Object plant, Object board) {
    const Cell cell = electriciteaCell(plant);
    if (!electriciteaValidCell(cell)) return nullptr;
    auto& state = teaAttacks[cell.row * 9 + cell.col];
    const auto id = identity(plant);
    if (state.board != board || !(state.plant == id)) state = {board, id, 0, 0, false};
    return &state;
}

static void electriciteaAction(Word base, Object plant, bool plantFood) {
    const auto board = currentBoard(base);
    if (!board || !active(board) || field<float>(plant, 0x9c) <= 0) return;
    const int level = field<int>(plant, 0x38);
    const auto source = groundPosition(plant);
    if (plantFood) {
        if (field<Word>(plant, 0x90) != 6) return;
        Object target = nullptr;
        unsigned count = 0;
        const auto zombies = liveZombies(base, board);
        for (auto slot = zombies.first; slot != zombies.end; ++slot) {
            if (lightningTarget(base, *slot) && onLawn(groundPosition(*slot)) &&
                native<unsigned>(base, 0x11317a8, ++count) == 0)
                target = *slot;
        }
        if (target) {
            electriciteaBolt(base, board, {source, 28.0f}, electriciteaContact(target), true);
            electriciteaDamage(base, board, target, 570.0f, level);
        }
        return;
    }

    const auto attack = electriciteaAttack(plant, board);
    if (!attack || !attack->strike) return;
    const bool red = attack->red;
    attack->strike = 0;
    Object targets[3];
    const Cell cell = electriciteaCell(plant);
    const auto count = electriciteaTargets(base, board, cell, targets);
    const float amount = 60.0f + (level >= 1 && level <= 5 ? (level - 1) * 20.0f : 0.0f);
    const unsigned chainChance = level == 2 ? 45 : level >= 3 ? 60 : 0;
    for (unsigned i = 0; i < count; ++i) {
        const auto target = targets[i];
        if (!lightningTarget(base, target) || !electriciteaInReach(cell, target)) continue;
        const auto contact = electriciteaContact(target);
        if (chainChance && native<unsigned>(base, 0x11317a8, 100U) < chainChance)
            startElectriciteaChain(base, board, target, contact, level, 150.0f, false);
        electriciteaDamage(base, board, target, amount, level, red);
    }
}

extern "C" void asterElectriciteaTick(Word base, Object plant, Word original) {
    reinterpret_cast<void(*)(Object)>(original)(plant);
    if (!field<unsigned char>(plant, 0xb4) || field<unsigned char>(plant, 0x1b8) ||
        (field<Word>(plant, 0x20) & 4U) ||
        field<float>(plant, 0x9c) <= 0) return;
    const auto alias = plantAlias(base, plant);
    if (!equal(alias, "electricitea") && !equal(alias, zoybeanAlias)) return;
    const auto board = currentBoard(base);
    if (!board || !active(board)) return;
    if (equal(alias, zoybeanAlias)) {
        updateZoybeanPlant(base, plant, board);
        return;
    }
    if (field<Word>(plant, 0x1f8) & 0x400U) return;
    const auto attack = electriciteaAttack(plant, board);
    if (!attack) return;
    const auto state = field<Word>(plant, 0x90);
    if (state == 3 || state == 6) {
        attack->strike = 0;
        return;
    }
    const float now = battleTime(base);
    if (attack->strike && now >= attack->strike) electriciteaAction(base, plant, false);
    if (now < attack->next) return;
    Object targets[3];
    if (!electriciteaTargets(base, board, electriciteaCell(plant), targets)) return;
    const auto rig = field<Object>(plant, 0x194);
    if (!rig) return;
    attack->next = now + 1.4f;
    attack->strike = now + 22.0f / 30.0f;
    attack->red = field<int>(plant, 0x38) >= 5 && native<unsigned>(base, 0x11317a8, 100U) < 20;
    playZombieClip(base, rig, attack->red ? "attack5" : "attack", false);
    playElectriciteaSound(base, plant, "Play_Plant_ElectriciTea_Attack");
    const Point origin = groundPosition(plant);
    electriciteaVisual(base, board, attack->red ? "POPANIM_EFFECTS_ELECTRICI_TEA_SUPER_BOTTOM_EFFECTS"
                                               : "POPANIM_EFFECTS_ELECTRICI_TEA_ATTACK_BOTTOM_EFFECTS",
                       "attack", origin, 0.0f);
    electriciteaVisual(base, board, attack->red ? "POPANIM_EFFECTS_ELECTRICI_TEA_SUPER_TOP_EFFECTS"
                                               : "POPANIM_EFFECTS_ELECTRICI_TEA_ATTACK_TOP_EFFECTS",
                       "attack", origin, 0.0f);
}

struct ElectriciteaBite {
    Object board;
    Identity plant;
    Identity eater;
    Point origin;
    float battleStart;
    float finish;
    int level;
    bool cloudPlayed;
};

static ElectriciteaBite teaBites[45];
static Object electriciteaBitingZombie;

static int electriciteaBiteCell(Word base, Object plant) {
    if (!equal(plantAlias(base, plant), "electricitea") || field<float>(plant, 0x9c) <= 0) return -1;
    const Cell cell = electriciteaCell(plant);
    return electriciteaValidCell(cell) ? cell.row * 9 + cell.col : -1;
}

static Object electriciteaEater(Word base, Identity eater) {
    if (!eater.low && !eater.high) return nullptr;
    const auto registry = native<Object>(base, 0x11d74b4);
    if (!registry) return nullptr;
    alignas(8) const Identity weak = eater;
    const auto zombie = native<Object>(base, 0x1da034, registry, &weak);
    return zombie && identity(zombie) == eater && !native<Word>(base, 0x348944, zombie) &&
           field<float>(zombie, bodyHealthOffset) > 0 ? zombie : nullptr;
}

static void queueElectriciteaBurst(Word base, Object plant, int cell, Identity plantId, Identity eater,
                                   Point origin, int level) {
    if (cell < 0 || (!eater.low && !eater.high) ||
        (field<float>(plant, 0x9c) > 0 && field<Word>(plant, 0x90) != 3 &&
         !native<Word>(base, 0x348944, plant))) return;
    const auto board = currentBoard(base);
    if (!board || !active(board)) return;
    const float battleStart = field<float>(board, 0xcc);
    auto& bite = teaBites[cell];
    if (bite.board == board && bite.battleStart == battleStart && bite.plant == plantId) return;
    bite = {board, plantId, eater, origin, battleStart, battleTime(base) + 0.5f, level, false};
    if (const auto zombie = electriciteaEater(base, eater))
        native<void>(base, 0xa4adcc, zombie, 0.55f);
}

static void observeElectriciteaBite(Word base, Object plant, const DamageInfo* hit, Object eater, Word original) {
    const int cell = electriciteaBiteCell(base, plant);
    if (cell >= 0 && !eater && hit->kind && hit->amount > 0) {
        const auto board = currentBoard(base);
        const auto live = board && active(board) ? liveZombies(base, board) : ZombieList{};
        for (auto slot = live.first; slot != live.end; ++slot) {
            if (*slot == reinterpret_cast<Object>(hit->kind)) {
                eater = *slot;
                break;
            }
        }
    }
    const bool watched = cell >= 0 && eater && hit->amount > 0;
    const auto id = watched ? identity(eater) : Identity{};
    const auto origin = watched ? groundPosition(eater) : Point{};
    const auto plantId = watched ? identity(plant) : Identity{};
    const int level = watched ? field<int>(plant, 0x38) : 0;
    reinterpret_cast<void(*)(Object, const DamageInfo*)>(original)(plant, hit);
    if (watched) queueElectriciteaBurst(base, plant, cell, plantId, id, origin, level);
}

extern "C" void asterElectriciteaBite(Word base, Object plant, const DamageInfo* hit, Word original) {
    observeElectriciteaBite(base, plant, hit, electriciteaBitingZombie, original);
}

extern "C" void asterElectriciteaZombieBite(Word base, Object plant, const DamageInfo* hit, Object eater, Word original) {
    // Some zombie types use their own virtual damage route. Retain the actor
    // from the bite callback while it synchronously applies damage to the plant.
    const auto previous = electriciteaBitingZombie;
    electriciteaBitingZombie = eater;
    observeElectriciteaBite(base, plant, hit, eater, original);
    electriciteaBitingZombie = previous;
}

extern "C" void asterElectriciteaSwallowed(Word base, Object plant, const Word* eater, Word original) {
    const int cell = electriciteaBiteCell(base, plant);
    const int level = cell >= 0 ? field<int>(plant, 0x38) : 0;
    const auto id = cell >= 0 ? Identity{eater[0], eater[1]} : Identity{};
    const auto zombie = electriciteaEater(base, id);
    const auto origin = zombie ? groundPosition(zombie) : cell >= 0 ? groundPosition(plant) : Point{};
    const auto plantId = cell >= 0 ? identity(plant) : Identity{};
    reinterpret_cast<void(*)(Object, const Word*)>(original)(plant, eater);
    queueElectriciteaBurst(base, plant, cell, plantId, id, origin, level);
}

static bool electriciteaHolding(Object board, Object zombie) {
    const auto id = identity(zombie);
    for (const auto& bite : teaBites)
        if (bite.board == board && bite.battleStart == field<float>(board, 0xcc) && bite.eater == id)
            return true;
    return false;
}

static void updateElectriciteaBursts(Word base, Object board, float now) {
    for (auto& bite : teaBites) {
        if (!bite.board) continue;
        if (bite.board != board || bite.battleStart != field<float>(board, 0xcc)) {
            bite.board = nullptr;
            continue;
        }
        if (!bite.cloudPlayed) {
            electriciteaVisual(base, board, "POPANIM_EFFECTS_ELECTRICI_TEA_CLOUD_ATTACK", "animation",
                               {bite.origin.x, bite.origin.y - 50.0f}, 0.0f);
            bite.cloudPlayed = true;
        }
        const auto eater = electriciteaEater(base, bite.eater);
        if (eater) {
            const auto position = groundPosition(eater);
            if (position.x != bite.origin.x || position.y != bite.origin.y)
                setPosition(eater, bite.origin);
        }
        if (now < bite.finish) continue;
        if (eater) {
            startElectriciteaChain(base, board, eater, electriciteaContact(eater), bite.level, 332.5f, true);
            electriciteaDamage(base, board, eater, field<float>(eater, bodyHealthOffset) + 950.0f,
                               bite.level, false, true);
        }
        bite.board = nullptr;
    }
    updateElectriciteaChains(base, board, now);
}

static void retireEntity(Object entity) {
    const auto remove = field<Word*>(entity, 0)[0x24 / 4];
    reinterpret_cast<void(*)(Object)>(remove)(entity);
}

static int nextPlantColumn(Word base, Object board, int row, float start, float end) {
    for (int col = 0; col < 9; ++col) {
        const float center = plantCenter(col);
        if (center >= start && center <= end && plantAt(base, board, col, row)) return col;
    }
    return -1;
}

static void assassinStrike(Object plant) {
    // The donor's AssassinateDamage and kill_plant marker bypass the bite handler.
    static constexpr DamageInfo hit{0, 300.0f, {}, -1, -1, {}};
    const auto damage = field<Word*>(plant, 0)[0x74 / 4];
    reinterpret_cast<void(*)(Object, const DamageInfo*)>(damage)(plant, &hit);
}

static void updateAssassin(Word base, Object board, Object registry, Object zombie) {
    const Word state = field<Word>(zombie, 0xd8);
    if (field<float>(zombie, bodyHealthOffset) <= 0 || (state >= 5 && state <= 9)) {
        if (field<float>(zombie, scrollHealthOffset) > 0) clearAssassinScroll(zombie);
        return;
    }
    const Identity id = identity(zombie);
    auto& actor = assassins[id.low % 64];
    if (actor.round != battleRound || !(actor.id == id))
        actor = {id, battleRound, AssassinPhase::approach, 0, -1, false};

    const float x = field<float>(zombie, 0x10);
    const float y = field<float>(zombie, 0x14);
    const int row = rowAt(y);
    if (row < 0 || row >= 5) return;
    if (actor.phase == AssassinPhase::approach
        && (state < 1 || state > 3 || x > 776.0f || field<float>(zombie, scrollHealthOffset) > 0)) return;
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    if (!rig) return;

    if (actor.phase == AssassinPhase::approach) {
        actor.phase = AssassinPhase::reveal;
        actor.position = x;
        if (state != 1) native<void>(base, 0xa558f0, zombie, 1, 0);
        playZombieClip(base, rig, "pohuai", false);
        return;
    }
    if (actor.phase == AssassinPhase::hunt) {
        if (state != 1) return;
        const float frame = zombieClipFrame(rig);
        if (frame >= 0 && frame < 417.0f) playZombieClip(base, rig, "walk02", true);
        const int col = nextPlantColumn(base, board, row, x, x + 26.0f);
        if (col >= 0) {
            actor.phase = AssassinPhase::strike;
            actor.position = x;
            actor.targetColumn = col;
            actor.struck = false;
            playZombieClip(base, rig, "attack", false);
        }
        return;
    }

    if (x != actor.position) setPosition(zombie, {actor.position, y});
    const bool playing = clipPlaying(base, rig);
    if (actor.phase == AssassinPhase::strike && !actor.struck && (zombieClipFrame(rig) >= 670.0f || !playing)) {
        actor.struck = true;
        if (const auto plant = plantAt(base, board, actor.targetColumn, row)) assassinStrike(plant);
    }
    if (playing) return;
    switch (actor.phase) {
    case AssassinPhase::reveal:
        actor.phase = AssassinPhase::vanish;
        playZombieClip(base, rig, "sprint_start", false);
        break;
    case AssassinPhase::vanish: {
        const int col = nextPlantColumn(base, board, row, plantCenter(0), plantCenter(8));
        actor.phase = AssassinPhase::land;
        // The first cell has no empty ground behind it. Stay inside the
        // playable strip and within dagger reach of its plant.
        actor.position = col <= 0 ? plantCenter(0) - 16.0f : plantCenter(col) - 34.0f;
        // The stock facing setter reverses the ground track and mirrors the rig.
        native<void>(base, 0xa41cb8, zombie, 1);
        setPosition(zombie, {actor.position, y});
        playZombieClip(base, rig, "sprint_end", false);
        break;
    }
    case AssassinPhase::land:
    case AssassinPhase::strike:
        actor.phase = AssassinPhase::hunt;
        playZombieClip(base, rig, "walk02", true);
        break;
    default:
        break;
    }
}

static void updateArcher(Word base, Object board, Object registry, Object zombie, float previousX) {
    const Identity id = identity(zombie);
    auto& archer = archers[id.low % 64];
    if (archer.round != battleRound || !(archer.id == id))
        archer = {id, battleRound, ArcherPose::walking};

    const Word state = field<Word>(zombie, 0xd8);
    const bool firing = state == 20 || state == 21;
    if (state != 1 && !firing) {
        archer.pose = ArcherPose::walking;
        return;
    }
    const bool target = archerTarget(base, board, zombie) != nullptr;
    if (!target && archer.pose == ArcherPose::walking && state == 1) return;
    const float y = field<float>(zombie, 0x14);
    const float step = previousX - field<float>(zombie, 0x10);
    if (step > 0 && step <= 4.0f) {
        // Wait for the center of the last square before fixing the attack
        // position. The stock projectile action accepts columns 0 through 8.
        const float stoppedX = target && previousX > archerAttackX ? archerAttackX : previousX;
        setPosition(zombie, {stoppedX, y});
    }

    // The hunter owns the release clip and its use_action projectile event.
    // Restore the crouched idle in the same update that it leaves that state.
    if (firing) {
        archer.pose = ArcherPose::firing;
        return;
    }
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    if (target) {
        if (archer.pose == ArcherPose::walking || archer.pose == ArcherPose::standing) {
            archer.pose = ArcherPose::crouching;
            playZombieClip(base, rig, "startshoot", false);
        } else if (archer.pose == ArcherPose::firing
                   || (archer.pose == ArcherPose::crouching && !clipPlaying(base, rig))) {
            archer.pose = ArcherPose::aiming;
            playZombieClip(base, rig, "waitshoot", true);
        }
    } else if (archer.pose != ArcherPose::standing) {
        archer.pose = ArcherPose::standing;
        playZombieClip(base, rig, "endshoot", false);
    } else if (!clipPlaying(base, rig)) {
        archer.pose = ArcherPose::walking;
        playZombieClip(base, rig, "walk", true);
    }
}

static void showAlcohol(Word base, Object registry, Object plant) {
    char allocator = 0;
    const char* resourceId;
    native<void>(base, 0x14ed0e1, &resourceId, "POPANIM_EFFECTS_ZOMBIE_MAUSOLEUM_DRUNK_EFFECT", &allocator);
    alignas(8) Word handle[2]{};
    native<void>(base, 0xe45d08, handle, &resourceId);
    const auto animation = native<Object>(base, 0x1da034, registry, handle);
    if (animation) {
        const char* name;
        native<void>(base, 0x14ed0e1, &name, "qin_alcohol", &allocator);
        const auto effect = native<Object>(base, 0x2e17b4, plant + 0x250, &name);
        releaseText(base, name);
        native<void>(base, 0x2e1328, effect, animation);
        const char* clip;
        native<void>(base, 0x14ed0e1, &clip, "alcohol", &allocator);
        native<void>(base, 0x2e1568, effect, &clip);
        releaseText(base, clip);
        const float offset[] = {0, 0, 18};
        const auto attach = field<Word*>(effect, 0)[0xc / 4];
        reinterpret_cast<void(*)(Object, Object, const float*, Word)>(attach)(effect, plant, offset, 1);
    }
    native<void>(base, 0x1d9bb4, handle, 0U, 0U, 0U);
    releaseText(base, resourceId);
}

static void sprayPlants(Word base, Object board, Object registry, Object zombie, int row, float now) {
    static constexpr struct { Word size, capacity, references; char value[4]; } empty{};
    const char* type = empty.value;
    const float x = field<float>(zombie, 0x10);
    const int front = static_cast<int>((x - 200.0f) / 64.0f);
    for (int col = front; col >= 0 && col >= front - 2; --col) {
        if (col > 8 || 232.0f + 64.0f * col >= x) continue;
        const auto plant = native<Object>(base, 0x203990, board, col, row, &type);
        if (!plant || native<Word>(base, 0x348944, plant)) continue;
        const auto id = identity(plant);
        sprayStuns[id.low % 128] = {id, battleRound, now + 3.0f};
        showAlcohol(base, registry, plant);
    }
}

static void updateDrunkard(Word base, Object board, Object registry, Object zombie, float previousX, float now) {
    const Identity id = identity(zombie);
    auto& actor = drunkards[id.low % 64];
    const float x = field<float>(zombie, 0x10);
    const float y = field<float>(zombie, 0x14);
    if (actor.round != battleRound || !(actor.id == id))
        actor = {id, battleRound, DrunkardAction::walking, x < 776.0f ? x : 776.0f, now, 0, 0, false};
    if (field<Word>(zombie, 0xd8) != 1) {
        actor.action = DrunkardAction::walking;
        return;
    }

    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    const float elapsed = now - actor.startedAt;
    switch (actor.action) {
    case DrunkardAction::walking: {
        if (actor.startX - x < 128.0f || x < 264.0f || x >= previousX) return;
        const int row = rowAt(y);
        if (row < 0 || row > 4) return;
        const bool down = ((id.low + static_cast<Word>(x / 64.0f)) & 1) != 0;
        const int destination = row == 0 ? 1 : row == 4 ? 3 : row + (down ? 1 : -1);
        actor = {id, battleRound, DrunkardAction::drinking, x, now, row, destination, false};
        playZombieClip(base, rig, "drink", false);
        break;
    }
    case DrunkardAction::drinking:
        setPosition(zombie, {actor.startX, y});
        if (!clipPlaying(base, rig)) {
            actor.action = DrunkardAction::changingRow;
            actor.startedAt = now;
            playZombieClip(base, rig, "walk", true);
        }
        break;
    case DrunkardAction::changingRow: {
        const float advance = clamp(elapsed / 1.5f, 1.0f);
        const float row = actor.row + (actor.destination - actor.row) * advance;
        setPosition(zombie, {actor.startX, firstLaneY + laneHeight * row});
        if (advance == 1.0f) {
            actor.action = DrunkardAction::spraying;
            actor.startedAt = now;
            playZombieClip(base, rig, "spray", false);
        }
        break;
    }
    case DrunkardAction::spraying: {
        setPosition(zombie, {actor.startX, y});
        const bool finished = !clipPlaying(base, rig);
        // Frame 216 is the donor PAM's spray event. Use its playback frame
        // so the hit stays synchronized with slowdowns and fast-forward.
        if (!actor.sprayed && (zombieClipFrame(rig) >= 216.0f || finished)) {
            actor.sprayed = true;
            sprayPlants(base, board, registry, zombie, actor.destination, now);
        }
        if (finished) {
            actor.action = DrunkardAction::walking;
            playZombieClip(base, rig, "walk", true);
        }
        break;
    }
    }
}

static bool vendorDue(Identity key, float now) {
    auto& slot = cartClocks[key.low % 96];
    if (slot.round != battleRound || !(slot.id == key)) {
        slot = {key, now + 6.0f, battleRound};
        return false;
    }
    if (now < slot.due) return false;
    slot.due = now + 6.0f;
    return true;
}

static Object spawnQinZombie(Word base, Object board, const char* alias, Point p, int level = 1) {
    const auto names = field<Object>(reinterpret_cast<Object>(base), 0x1830498);
    if (!names) return nullptr;
    Object node = field<Object>(names, 0xc);
    while (node) {
        const int order = compare(alias, field<const char*>(node, 0x10));
        if (!order) break;
        node = field<Object>(node, order < 0 ? 8 : 12);
    }
    if (!node) return nullptr;
    alignas(8) Word handle[2];
    handle[0] = 0;
    handle[1] = 0;
    native<void>(base, 0x1d9bb4, handle, 0U, field<Word>(node, 0x18), field<Word>(node, 0x1c));
    const auto registry = native<Object>(base, 0x11d74b4);
    Object zombie = nullptr;
    if (registry && native<Object>(base, 0x1da034, registry, handle)) {
        // Spawn in a real row, relocate to the cart, and enter the stock walking state.
        // The wave manager starts that state for wave spawns only.
        const int row = rowAt(p.y);
        zombie = native<Object>(base, 0x216738, board, handle, row, level, 0U, 0U);
        if (zombie) {
            setPosition(zombie, p);
            native<void>(base, 0xa558f0, zombie, 1, 0);
        }
    }
    native<void>(base, 0x1d9bb4, handle, 0U, 0U, 0U);
    return zombie;
}

static Object gridItemAt(Word base, Object registry, const Cell& cell, const char* alias);
static Object placeTerracottaRuin(Word base, Object board, Cell cell) {
    char allocator = 0;
    const char* name;
    native<void>(base, 0x14ed0e1, &name, terracottaRuin, &allocator);
    const auto item = native<Object>(base, 0x20be10, board, &name, cell.col, cell.row, 1);
    releaseText(base, name);
    return item;
}

struct PendingRuin { Word round; float due; };
static PendingRuin pendingRuins[5][9];

static void terracottaDefeated(Word base, Object zombie, const DamageInfo& hit) {
    const auto board = currentBoard(base);
    const Point p{field<float>(zombie, 0x10), field<float>(zombie, 0x14)};
    if (board != lastBoard || !active(board) || !onLawn(p) || (hit.flags[0] & 2U)) return;
    const int col = static_cast<int>((p.x - 200.0f) / 64.0f);
    if (col < 0 || col >= 9) return;
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto rig = registry ? native<Object>(base, 0x1da034, registry, zombie + 0xd0) : nullptr;
    playZombieClip(base, rig, "die2", false);
    pendingRuins[rowAt(p.y)][col] = {battleRound, battleTime(base) + (427.0f - 374.0f) / 30.0f};
}

static void placePendingRuins(Word base, Object board, Object registry, float now) {
    for (int row = 0; row < 5; ++row) {
        for (int col = 0; col < 9; ++col) {
            auto& ruin = pendingRuins[row][col];
            if (ruin.round != battleRound || ruin.due <= 0 || now < ruin.due) continue;
            ruin.due = 0;
            if (!plantAt(base, board, col, row) && !gridItemAt(base, registry, {col, row}, "uncharted_haystack_grid")
                && !gridItemAt(base, registry, {col, row}, terracottaRuin))
                placeTerracottaRuin(base, board, {col, row});
        }
    }
}

static bool canConvert(const char* alias) {
    return equal(alias, "mausoleum_basic") || equal(alias, "mausoleum_armor1")
        || equal(alias, "mausoleum_armor2") || equal(alias, "mausoleum_flag");
}

static Object findInfantry(Word base, Object board, Point caster, const Identity* target = nullptr) {
    const auto live = liveZombies(base, board);
    Object chosen = nullptr;
    float best = 10000;
    for (auto slot = live.first; slot != live.end; ++slot) {
        const auto zombie = *slot;
        if (!zombie || native<Word>(base, 0x348944, zombie) || field<float>(zombie, bodyHealthOffset) <= 0
            || !canConvert(zombieAlias(base, zombie)) || (target && !(identity(zombie) == *target))) continue;
        const Point p{field<float>(zombie, 0x10), field<float>(zombie, 0x14)};
        if (!onLawn(p) || field<Word>(zombie, facingOffset) != 0) continue;
        const float distance = absolute(p.x - caster.x) + absolute(p.y - caster.y);
        if (distance < best) {
            chosen = zombie;
            best = distance;
        }
    }
    return chosen;
}

static Cell findRuin(Word base, Object registry, Point caster) {
    Cell chosen{-1, -1};
    float best = 10000;
    for (int row = 0; row < 5; ++row) {
        for (int col = 0; col < 9; ++col) {
            const float distance = absolute(plantCenter(col) - caster.x)
                + absolute(firstLaneY + row * laneHeight - caster.y);
            if (distance >= best || !gridItemAt(base, registry, {col, row}, terracottaRuin)) continue;
            chosen = {col, row};
            best = distance;
        }
    }
    return chosen;
}

struct Summon { QinAction kind; Identity target; Cell cell; Point caster; };

static bool updateTaoist(Word base, Object board, Object registry, Object zombie, float now, Summon& summon) {
    auto& actor = qinActor(zombie);
    const Word state = field<Word>(zombie, 0xd8);
    if (field<float>(zombie, bodyHealthOffset) <= 0 || state < 1 || state > 3) return false;
    const Point p{field<float>(zombie, 0x10), field<float>(zombie, 0x14)};
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    if (!rig) return false;
    if (actor.action == QinAction::walk) {
        // The source starts checking for targets at column 7.
        if (!onLawn(p) || p.x > plantCenter(7) + 32 || now < actor.due || state != 1) return false;
        actor.cell = findRuin(base, registry, p);
        if (actor.cell.col >= 0) {
            actor.action = QinAction::raise;
            playZombieClip(base, rig, "attack", false);
        } else if (const auto infantry = findInfantry(base, board, p)) {
            actor.action = QinAction::convert;
            actor.target = identity(infantry);
            playZombieClip(base, rig, "power_up", false);
        }
        actor.due = now + (actor.action == QinAction::walk ? 0.5f : 10.0f);
        actor.position = p.x;
        actor.applied = false;
        return false;
    }

    setPosition(zombie, {actor.position, p.y});
    const bool playing = clipPlaying(base, rig);
    const Point caster{actor.position, p.y};
    if (actor.action == QinAction::raise && !actor.applied && (zombieClipFrame(rig) >= 217 || !playing)) {
        actor.applied = true;
        summon = {QinAction::raise, {0, 0}, actor.cell, caster};
        return true;
    }
    if (playing) return false;
    if (actor.action == QinAction::convert) {
        actor.action = QinAction::channel;
        playZombieClip(base, rig, "power", false);
        summon = {QinAction::convert, actor.target, {-1, -1}, caster};
        return true;
    }
    if (actor.action == QinAction::channel) {
        actor.action = QinAction::finish;
        playZombieClip(base, rig, "power_down", false);
    } else {
        actor.action = QinAction::walk;
        playZombieClip(base, rig, "walk", true);
    }
    return false;
}

static void aimTaoistBeam(Word base, Object effect, Point caster, Point target) {
    const auto visual = native<Object>(base, 0x2e1428, effect);
    if (!visual) return;
    const float staff[] = {caster.x - 22.0f, caster.y, 48.0f};
    const Point direction{target.x - staff[0], target.y - caster.y + 6.0f};
    const float length = native<float>(base, 0x147800, direction.x * direction.x + direction.y * direction.y);
    // The donor's trail spans x=0 to x=131, centered at y=13 on a 390-unit canvas.
    native<void>(base, 0x8fbd94, visual, staff, -1);
    native<void>(base, 0x2f8a50, visual, 0.0f, 13.0f / 390.0f);
    native<void>(base, 0x2f8a88, visual, length / 131.0f, 1.0f);
    native<void>(base, 0x2f8abc, visual, &direction);
}

static void qinSummonEffect(Word base, Object registry, Object zombie, bool revive, Point caster, Point target) {
    const char* resource = revive ? "POPANIM_EFFECTS_ZOMBIE_QIN_TAOIST_SOULFIRE"
                                  : "POPANIM_EFFECTS_ZOMBIE_QIN_TAOIST_SKILL";
    const char* label = revive ? "attack" : "animation3";
    char allocator = 0;
    const char* resourceId;
    native<void>(base, 0x14ed0e1, &resourceId, resource, &allocator);
    alignas(8) Word handle[2]{};
    native<void>(base, 0xe45d08, handle, &resourceId);
    if (const auto anim = native<Object>(base, 0x1da034, registry, handle)) {
        const char* name;
        native<void>(base, 0x14ed0e1, &name, "qin_taoist_summon", &allocator);
        const auto effect = native<Object>(base, 0x2e17b4, zombie + 0x298, &name);
        releaseText(base, name);
        native<void>(base, 0x2e1328, effect, anim);
        const char* clip;
        native<void>(base, 0x14ed0e1, &clip, label, &allocator);
        native<void>(base, 0x2e15ac, effect, &clip, 0U);
        releaseText(base, clip);
        if (revive) {
            const float offset[] = {64.0f, 28.0f, 0};
            const auto attach = field<Word*>(effect, 0)[0xc / 4];
            reinterpret_cast<void(*)(Object, Object, const float*, Word)>(attach)(effect, zombie, offset, 1);
        } else {
            aimTaoistBeam(base, effect, caster, target);
        }
    }
    native<void>(base, 0x1d9bb4, handle, 0U, 0U, 0U);
    releaseText(base, resourceId);
}

static void summonTerracotta(Word base, Object board, Object registry, const Summon& summon) {
    const bool revive = summon.kind == QinAction::raise;
    const auto source = revive ? gridItemAt(base, registry, summon.cell, terracottaRuin)
        : findInfantry(base, board, {}, &summon.target);
    if (!source) return;
    const Point position = revive ? Point{plantCenter(summon.cell.col), firstLaneY + summon.cell.row * laneHeight}
        : Point{field<float>(source, 0x10), field<float>(source, 0x14)};
    const auto zombie = spawnQinZombie(base, board, revive ? terracottaGeneral : terracottaSmall, position);
    if (!zombie) return;
    retireEntity(source);
    auto& actor = qinActor(zombie);
    actor.action = QinAction::emerge;
    actor.position = position.x;
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    playZombieClip(base, rig, revive ? "resurrection" : "into", false);
    qinSummonEffect(base, registry, zombie, revive, summon.caster, position);
}

static void updateTerracotta(Word base, Object board, Object registry, Object zombie, bool general) {
    if (field<float>(zombie, bodyHealthOffset) <= 0 || field<Word>(zombie, 0xd8) != 1) return;
    auto& actor = qinActor(zombie);
    const auto rig = native<Object>(base, 0x1da034, registry, zombie + 0xd0);
    if (!rig) return;
    const Point p{field<float>(zombie, 0x10), field<float>(zombie, 0x14)};
    if (actor.action == QinAction::walk) {
        if (!general || !onLawn(p)) return;
        const int col = nextPlantColumn(base, board, rowAt(p.y), p.x - 40.0f, p.x + 3.0f);
        if (col < 0) return;
        actor.action = QinAction::smash;
        actor.position = p.x;
        actor.cell = {col, rowAt(p.y)};
        actor.target = identity(plantAt(base, board, col, actor.cell.row));
        actor.applied = false;
        playZombieClip(base, rig, "eat", false);
        return;
    }
    setPosition(zombie, {actor.position, p.y});
    const bool playing = clipPlaying(base, rig);
    if (actor.action == QinAction::smash && !actor.applied && (zombieClipFrame(rig) >= 269 || !playing)) {
        actor.applied = true;
        const auto plant = plantAt(base, board, actor.cell.col, actor.cell.row);
        if (plant && identity(plant) == actor.target) {
            static constexpr DamageInfo hit{0, 100000.0f, {}, -1, -1, {}};
            const auto damage = field<Word*>(plant, 0)[0x74 / 4];
            reinterpret_cast<void(*)(Object, const DamageInfo*)>(damage)(plant, &hit);
        }
    }
    if (!playing) {
        actor.action = QinAction::walk;
        playZombieClip(base, rig, "walk", true);
    }
}

#include "zoybean.inc"

extern "C" Word asterQinTunnelStep(Word base, Object board, Word original) {
    auto update = reinterpret_cast<Word(*)(Object)>(original);
    const Route route = routeFor(board);
    if (currentBoard(base) != board || !active(board)) return update(board);
    if (!qinBattlefield(board)) {
        const Word result = update(board);
        if (currentBoard(base) == board && active(board)) {
            const auto now = battleTime(base);
            updateElectriciteaBursts(base, board, now);
            updateZoybeanAllies(base, board, now);
        }
        return result;
    }

    const float battleStart = field<float>(board, 0xcc);
    if (board != lastBoard || battleStart != lastBattleStart) {
        lastBoard = board;
        lastBattleStart = battleStart;
        ++battleRound;
    }
    Rider riders[64];
    unsigned count = 0;
    const auto registry = native<Object>(base, 0x11d74b4);
    if (registry) {
        const auto live = liveZombies(base, board);
        for (auto slot = live.first; slot != live.end && count < 64; ++slot) {
            const auto zombie = *slot;
            if (!zombie || native<Word>(base, 0x348944, zombie)) continue;
            const float x = field<float>(zombie, 0x10);
            const auto type = native<Object>(base, 0x1da034, registry, zombie + 0xc8);
            const auto alias = type ? field<const char*>(type, 4) : nullptr;
            if (equal(alias, assassinAlias)) {
                riders[count++] = {zombie, identity(zombie), x, assassinUpdate, 0, false};
                continue;
            }
            if (equal(alias, drunkardAlias)) {
                riders[count++] = {zombie, identity(zombie), x, drunkardUpdate, 0, false};
                continue;
            }
            if (equal(alias, archerAlias)) {
                riders[count++] = {zombie, identity(zombie), x, archerUpdate, 0, false};
                continue;
            }
            if (equal(alias, taoistAlias)) {
                riders[count++] = {zombie, identity(zombie), x, taoistUpdate, 0, false};
                continue;
            }
            if (equal(alias, terracottaGeneral) || equal(alias, terracottaSmall)) {
                riders[count++] = {zombie, identity(zombie), x, terracottaUpdate, 0, equal(alias, terracottaGeneral)};
                continue;
            }
            const bool vendor = equal(alias, "mausoleum_vendor");
            const float scale = vendor ? 0.25f / 0.19f : equal(alias, "mausoleum_cavalry")
                ? 0.45f / 0.185f : equal(alias, "mausoleum_piggy") ? 2.0f : 0;
            if (scale <= 0) continue;
            const float distance = route.cells ? project(route, {x, field<float>(zombie, 0x14)}) : -1;
            if (distance >= 0) riders[count++] = {zombie, identity(zombie), x, distance, scale, vendor};
        }
    }

    const Word result = update(board);
    if (currentBoard(base) != board || !active(board) || !registry) return result;
    const float now = battleTime(base);
    updateElectriciteaBursts(base, board, now);
    updateZoybeanAllies(base, board, now);
    placePendingRuins(base, board, registry, now);
    if (count == 0) return result;
    Point births[16];
    unsigned birthCount = 0;
    Summon summons[16];
    unsigned summonCount = 0;
    const auto live = liveZombies(base, board);
    for (auto slot = live.first; slot != live.end; ++slot) {
        const auto zombie = *slot;
        for (unsigned i = 0; i < count; ++i) {
            const Rider& rider = riders[i];
            if (zombie != rider.zombie || !(identity(zombie) == rider.id)) continue;
            if (native<Word>(base, 0x348944, zombie) || electriciteaHolding(board, zombie)) break;
            if (rider.distance == assassinUpdate) {
                updateAssassin(base, board, registry, zombie);
                break;
            }
            if (rider.distance == drunkardUpdate) {
                if (now > 0) updateDrunkard(base, board, registry, zombie, rider.x, now);
                break;
            }
            if (rider.distance == archerUpdate) {
                updateArcher(base, board, registry, zombie, rider.x);
                break;
            }
            if (rider.distance == taoistUpdate) {
                Summon summon;
                if (updateTaoist(base, board, registry, zombie, now, summon) && summonCount < 16)
                    summons[summonCount++] = summon;
                break;
            }
            if (rider.distance == terracottaUpdate) {
                updateTerracotta(base, board, registry, zombie, rider.vendor);
                break;
            }
            const float step = rider.x - field<float>(zombie, 0x10);
            // Use actual movement, preserving plant collision and status effects.
            if (step > 0 && step <= 4.0f) {
                setPosition(zombie, follow(route, rider.distance + step * rider.scale));
            }
            if (rider.vendor && now > 0 && vendorDue(rider.id, now) && birthCount < 16) {
                births[birthCount++] = follow(route, rider.distance > 12 ? rider.distance - 12 : 0);
            }
            break;
        }
    }
    for (unsigned i = 0; i < birthCount; ++i) spawnQinZombie(base, board, "mausoleum_piggy", births[i]);
    for (unsigned i = 0; i < summonCount; ++i) summonTerracotta(base, board, registry, summons[i]);
    return result;
}

static constexpr char haystackGrid[] = "uncharted_haystack_grid";
static constexpr char haystackPlant[] = "uncharted_haystack";

extern "C" Word asterQinHaystackLegacyId(Word base, Object map, const char* const* name) {
    // Older plant lookups use a numeric ID. Keep the haystack's type and
    // artwork distinct while routing those lookups through the lily pad ID.
    if (map != reinterpret_cast<Object>(base + 0x1830470) || !name)
        return missingPlantId;
    const auto alias = *name;
    const Word customId = equal(alias, "moton") ? motonPlantId
                         : equal(alias, "electricitea") ? electriciteaId
                         : equal(alias, zoybeanAlias) ? zoybeanId : missingPlantId;
    if (customId != missingPlantId) {
        // Aster's runtime initializes this map through its own constructor.
        // Register on the first lookup, after that constructor has run.
        if (legacyPlantId(map, alias) == missingPlantId) {
            const char* value = nullptr;
            char allocator = 0;
            native<void>(base, 0x14ed0e1, &value, alias, &allocator);
            *native<Word*>(base, 0x498158, map + 4, &value) = customId;
            releaseText(base, value);
        }
        return customId;
    }
    if (!equal(*name, haystackPlant)) return missingPlantId;
    return legacyPlantId(map, "lilypad");
}

extern "C" const char* asterQinGroundAlias(Word base, const char* fallback) {
    return routeFor(currentBoard(base)).cells ? haystackGrid : fallback;
}

static const char* gridItemAlias(Word base, Object registry, Object item) {
    if (!item || !registry || native<Word>(base, 0x348944, item)) return nullptr;
    const auto type = native<Object>(base, 0x1da034, registry, item + 0xc8);
    return type ? field<const char*>(type, 4) : nullptr;
}

extern "C" Word asterQinChewable(Word base, Object item, Object context, Word original) {
    const auto stock = reinterpret_cast<Word(*)(Object, Object)>(original);
    const auto board = currentBoard(base);
    if (!qinBattlefield(board)) return stock(item, context);
    const auto alias = gridItemAlias(base, native<Object>(base, 0x11d74b4), item);
    if (equal(alias, terracottaRuin)) return 0;
    if (!equal(alias, haystackGrid)) return stock(item, context);

    // Attack the plant on top first. The surrounding stock code already
    // checks the zombie's hit rectangle and applies its normal bite damage.
    static constexpr struct { Word size, capacity, references; char value[4]; } empty{};
    const char* type = empty.value;
    return !native<Object>(base, 0x203990, board, field<int>(item, 0xd8), field<int>(item, 0xdc), &type);
}

static Object gridItemAt(Word base, Object registry, const Cell& cell, const char* alias) {
    struct { Object* first; Object* end; Object* capacity; } items{};
    native<void>(base, 0xbf5290, &items, 4U, cell.col, cell.row);
    Object found = nullptr;
    for (auto it = items.first; it != items.end; ++it) {
        if (equal(gridItemAlias(base, registry, *it), alias)) {
            found = *it;
            break;
        }
    }
    if (items.first) native<void>(base, 0x14c2e95, items.first);
    return found;
}

extern "C" Word asterQinCanPlant(Word base, Object board, const Cell* cell, Object weak, Word original) {
    const auto stock = reinterpret_cast<Word(*)(Object, const Cell*, Object)>(original);
    const Route route = routeFor(board);
    if (!qinBattlefield(board) || !cell || !weak) return stock(board, cell, weak);
    const auto registry = native<Object>(base, 0x11d74b4);
    constexpr Word blocked = 2;
    if (registry && gridItemAt(base, registry, *cell, terracottaRuin)) return blocked;
    if (!route.cells) return stock(board, cell, weak);
    const auto type = registry ? native<Object>(base, 0x1da034, registry, weak) : nullptr;
    const auto alias = type ? field<const char*>(type, 4) : nullptr;

    bool tunnel = false;
    for (unsigned i = 0; i < route.count; ++i) {
        const Cell& p = route.cells[i];
        if (p.col == cell->col && p.row == cell->row) {
            tunnel = true;
            break;
        }
    }
    const bool haystack = equal(alias, haystackPlant);
    if (!tunnel) return haystack ? blocked : stock(board, cell, weak);
    const bool supported = alias && gridItemAt(base, registry, *cell, haystackGrid);
    if (haystack) return supported ? blocked : 0;
    if (alias && !supported) return blocked;
    return stock(board, cell, weak);
}
