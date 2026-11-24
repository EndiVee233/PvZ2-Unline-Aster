#pragma once

namespace AdventureRecords {
constexpr unsigned schema = 3;
constexpr unsigned maxPlants = 135;
constexpr unsigned maxSlots = 16;
constexpr unsigned maxElapsedMs = 3'600'000;
constexpr unsigned unknownCukeUses = ~0U;
constexpr unsigned maxCukeUses = 3600;

struct Plant {
    char type[32];
    unsigned char column;
    unsigned char row;
    unsigned char level;
    unsigned char avatar;
};

struct Card {
    char type[32];
    unsigned level;
};

struct Loadout {
    unsigned slots;
    Card cards[maxSlots];
};

struct Record {
    unsigned version;
    unsigned owner;
    unsigned day;
    unsigned stars;
    unsigned elapsedMs;
    unsigned count;
    Plant plants[maxPlants];
    // Version 1 ended with its checksum at this offset.
    Loadout loadout;
    unsigned tacticalCukeUses;
    unsigned checksum;
};

static_assert(sizeof(Plant) == 36);
static_assert(sizeof(Card) == 36);
constexpr unsigned legacySize = __builtin_offsetof(Record, loadout) + sizeof(unsigned);
static_assert(legacySize == 4888);
constexpr unsigned loadoutSize = __builtin_offsetof(Record, tacticalCukeUses) + sizeof(unsigned);
static_assert(loadoutSize == 5468);
static_assert(sizeof(Record) == 5472);

#ifdef ASTER_SOCIAL_LEVELS
struct LevelInfo {
    char alias[48];
    unsigned key;
    unsigned char stars;
    bool alwaysAvailable;
    bool formation;
    unsigned char plankRows;
    unsigned title;
    unsigned goals[4];
    char unlocks[2][32];
    unsigned char conflicts;
};

#include "adventure_levels.inc"

inline const LevelInfo* findLevel(const char* alias) {
    if (!alias) return nullptr;
    const auto mapCharacter = [alias](const char* ch) {
        const auto digit = [](char value) { return value >= '0' && value <= '9'; };
        // Numbered branches may also be identified by the resource filename.
        return *ch == '-' && ch != alias && digit(ch[-1]) && digit(ch[1]) ? '_' : *ch;
    };
    unsigned lo = 0, hi = sizeof(levels) / sizeof(levels[0]);
    while (lo < hi) {
        const unsigned mid = lo + (hi - lo) / 2;
        const auto* lhs = alias;
        const auto* rhs = levels[mid].alias;
        while (*lhs && mapCharacter(lhs) == *rhs) { ++lhs; ++rhs; }
        const char actual = mapCharacter(lhs);
        if (actual == *rhs) return &levels[mid];
        if (actual < *rhs) hi = mid;
        else lo = mid + 1;
    }
    return nullptr;
}

inline unsigned levelId(const char* alias) {
    const auto* level = findLevel(alias);
    return level ? level->key : 0;
}

inline bool formationSupported(const char* alias) {
    const auto* level = findLevel(alias);
    return level && level->formation;
}
#else
inline unsigned levelId(const char* name) {
    if (!name || name[0] != 'e' || name[1] != 'g' || name[2] != 'y' ||
        name[3] != 'p' || name[4] != 't' ||
        (name[5] != '1' && name[5] != '2') || name[6]) return 0;
    return unsigned(name[5] - '0');
}

inline bool formationSupported(const char* name) {
    return levelId(name);
}
#endif

inline bool validPlantType(const char* type) {
    for (unsigned i = 0; i < sizeof(Plant::type); ++i) {
        const char ch = type[i];
        if (!ch) return i != 0;
        if ((ch < 'a' || ch > 'z') && (ch < '0' || ch > '9') && ch != '_') return false;
    }
    return false;
}

inline unsigned digest(const Record& record, unsigned size = sizeof(Record)) {
    const auto* bytes = reinterpret_cast<const unsigned char*>(&record);
    unsigned hash = 2166136261U;
    for (unsigned i = 0; i < size - sizeof(unsigned); ++i)
        hash = (hash ^ bytes[i]) * 16777619U;
    return hash;
}

inline bool valid(const Record& record, unsigned owner, unsigned day, unsigned stars,
                  unsigned size = sizeof(Record)) {
    const bool legacy = record.version == 1 && size == legacySize;
    const bool oldLoadout = record.version == 2 && size == loadoutSize;
    if (!legacy && !oldLoadout && (record.version != schema || size != sizeof(Record))) return false;
    const unsigned checksum = legacy ? record.loadout.slots :
        oldLoadout ? record.tacticalCukeUses : record.checksum;
    if (owner == ~0U || (day != 1 && day != 2 && (day >> 30) != 1) || stars > 3 ||
        record.owner != owner || record.day != day ||
        record.stars != stars || !record.elapsedMs || record.elapsedMs > maxElapsedMs ||
        record.count > maxPlants || checksum != digest(record, size)) return false;
    if (record.version == schema && record.tacticalCukeUses != unknownCukeUses &&
        record.tacticalCukeUses > maxCukeUses) return false;

    volatile unsigned char counts[5][9];
    for (auto& row : counts)
        for (auto& count : row) count = 0;
    for (unsigned i = 0; i < record.count; ++i) {
        const Plant& plant = record.plants[i];
        if (plant.column >= 9 || plant.row >= 5 || plant.level < 1 || plant.level > 4 ||
            plant.avatar > 1 || !validPlantType(plant.type)
            || ++counts[plant.row][plant.column] > 3) return false;
    }
    if (!legacy) {
        if (record.loadout.slots > maxSlots) return false;
        for (unsigned i = 0; i < maxSlots; ++i) {
            const Card& card = record.loadout.cards[i];
            if (!card.type[0]) {
                if (card.level) return false;
            } else if (i >= record.loadout.slots || !validPlantType(card.type) ||
                       card.level < 1 || card.level > 4) {
                return false;
            }
        }
    }
    return true;
}

struct Stopwatch {
    float lastFrame;
    float elapsed;

    void advance(float frame, float step, bool playing) {
        // Arena subtracts the engine's frame delta during live battle. Count
        // it up here and use the simulation clock to reject repeat callbacks.
        if (playing && frame > lastFrame && step > 0 && step <= frame) elapsed += step;
        lastFrame = frame;
    }

    unsigned milliseconds() const {
        return elapsed > 0 && elapsed <= maxElapsedMs / 1000.0f
            ? unsigned(elapsed * 1000.0f + 0.5f) : 0;
    }
};
}
