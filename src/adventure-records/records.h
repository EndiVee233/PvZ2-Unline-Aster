#pragma once

namespace AdventureRecords {
constexpr unsigned schema = 1;
constexpr unsigned maxPlants = 135;
constexpr unsigned maxElapsedMs = 3'600'000;

struct Plant {
    char type[32];
    unsigned char column;
    unsigned char row;
    unsigned char level;
    unsigned char avatar;
};

struct Record {
    unsigned version;
    unsigned owner;
    unsigned day;
    unsigned stars;
    unsigned elapsedMs;
    unsigned count;
    Plant plants[maxPlants];
    unsigned checksum;
};

static_assert(sizeof(Plant) == 36);
static_assert(sizeof(Record) == 4888);

// Use exact aliases. The Egypt endless and tutorial names also start with
// world names in some builds, and have separate progression and rules.
inline unsigned egyptDay(const char* name) {
    if (!name || name[0] != 'e' || name[1] != 'g' || name[2] != 'y' ||
        name[3] != 'p' || name[4] != 't' ||
        (name[5] != '1' && name[5] != '2') || name[6]) return 0;
    return unsigned(name[5] - '0');
}

inline bool validPlantType(const char* type) {
    for (unsigned i = 0; i < sizeof(Plant::type); ++i) {
        const char ch = type[i];
        if (!ch) return i != 0;
        if ((ch < 'a' || ch > 'z') && (ch < '0' || ch > '9') && ch != '_') return false;
    }
    return false;
}

inline unsigned digest(const Record& record) {
    const auto* bytes = reinterpret_cast<const unsigned char*>(&record);
    unsigned hash = 2166136261U;
    for (unsigned i = 0; i < sizeof(Record) - sizeof(unsigned); ++i)
        hash = (hash ^ bytes[i]) * 16777619U;
    return hash;
}

inline bool valid(const Record& record, unsigned owner, unsigned day, unsigned stars) {
    if (owner == ~0U || day < 1 || day > 2 || stars > 3 ||
        record.version != schema || record.owner != owner || record.day != day ||
        record.stars != stars || !record.elapsedMs || record.elapsedMs > maxElapsedMs ||
        record.count > maxPlants || record.checksum != digest(record)) return false;

    volatile unsigned char counts[5][9];
    for (auto& row : counts)
        for (auto& count : row) count = 0;
    for (unsigned i = 0; i < record.count; ++i) {
        const Plant& plant = record.plants[i];
        if (plant.column >= 9 || plant.row >= 5 || plant.level < 1 || plant.level > 4 ||
            plant.avatar > 1 || !validPlantType(plant.type)
            || ++counts[plant.row][plant.column] > 3) return false;
    }
    return true;
}

struct Stopwatch {
    float last;
    float elapsed;
    bool wasRunning;

    void sample(float now, bool running) {
        const float step = now - last;
        // A gap in simulation callbacks can mean suspension or an open modal.
        // Use only consecutive running samples from the native game clock.
        if (wasRunning && running && step >= 0 && step <= 0.25f) elapsed += step;
        last = now;
        wasRunning = running;
    }

    unsigned milliseconds() const {
        return elapsed > 0 && elapsed <= maxElapsedMs / 1000.0f
            ? unsigned(elapsed * 1000.0f + 0.5f) : 0;
    }
};
}
