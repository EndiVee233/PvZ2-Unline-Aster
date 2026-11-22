#include "records.h"

using Word = unsigned;
using Object = unsigned char*;
using AdventureRecords::Plant;
using AdventureRecords::Record;
using AdventureRecords::Stopwatch;

struct WeakRef {
    Word id;
    Word serial;
};

template<class T> static T& field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R native(Word base, Word offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

struct Run {
    Object board;
    Object profile;
    Word owner;
    Word day;
    Word stars;
    float startedAt;
    Stopwatch clock;
#ifdef ASTER_SOCIAL_LEVELS
    bool friendSunUsed;
    Word tacticalCukeUses;
    AdventureRecords::Card borrowedCard;
    WeakRef borrowedDrop;
    Object borrowedCursor;
    float borrowedDropTime;
#endif
#ifdef ASTER_WSA_BATTLE_TOOLS
    float commandPollAt;
    float clearAt;
    bool sweeping;
    bool assisted;
#endif
};

static Run current;
static Record completed;
static Record prior;
static bool hasCompleted;

#ifdef ASTER_SOCIAL_LEVELS
static bool socialContentEnabled(Word base);
static void bindBorrowedCard(Object board);
static void dropBorrowedCard(Word base, Object board);
#include "loadout.h"
#endif

static Object gameApp(Word base) {
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return holder ? field<Object>(holder, 0) : nullptr;
}

static Object gameBoard(Word base) {
    const auto app = gameApp(base);
    return app ? field<Object>(app, 0x6bc) : nullptr;
}

static Object ownerStore(Word base) {
    return field<Object>(reinterpret_cast<Object>(base), 0x18300a4);
}

static Word owner(Object store) {
    return store ? field<Word>(store, 0x74) : ~0U;
}

static Object gameClock(Word base) {
    return field<Object>(reinterpret_cast<Object>(base), 0x1830528);
}

static float now(Word base) {
    const auto clock = gameClock(base);
    return clock ? field<float>(clock, 0x24) : 0;
}

static bool playing(Object board) {
    return field<Word>(board, 0xc0) == 5 && !field<Word>(board, 0x7f4)
        && !field<unsigned char>(board, 0x8d5) && !field<unsigned char>(board, 0x7fd);
}

static Object observedBattleBoard;
static float observedBattleStart;
static constexpr Word plantActionsEnabled = 0x7fb;

static void restoreEgyptEndlessPlantUpdates(Word base, Object board) {
    if (!board || !playing(board)) return;
    const float start = field<float>(board, 0xcc);
    if (observedBattleBoard == board && observedBattleStart == start) return;
    if (gameBoard(base) != board) return;
    observedBattleBoard = board;
    observedBattleStart = start;

    constexpr char level[] = "egypt_dangerroom";
    const char* alias = field<const char*>(board, 0xc4);
    if (!alias) return;
    for (char ch : level) {
        if (*alias++ != ch) return;
    }
    // The legacy floor intro suspends plant actions. Its restored seed chooser
    // enters battle without re-enabling the plant action state machine.
    field<unsigned char>(board, plantActionsEnabled) = 1;
}

static bool sameRun(Word base, Object board) {
    return board && current.board == board && gameBoard(base) == board &&
        owner(ownerStore(base)) == current.owner &&
        field<float>(board, 0xcc) == current.startedAt &&
        AdventureRecords::levelId(field<const char*>(board, 0xc4)) == current.day;
}

#ifdef ASTER_SOCIAL_LEVELS
extern "C" void asterAdventureTacticalCuke(Word base, Object board, Word event, Word mode, Word data) {
    if (sameRun(base, board) && field<Word>(board, 0xc0) == 5 && !field<Word>(board, 0x7f4) &&
        current.tacticalCukeUses < AdventureRecords::maxCukeUses) {
        ++current.tacticalCukeUses;
    }
    native<void>(base, 0x207d90, board, event, mode, data);
}
#endif

#ifdef ASTER_WSA_BATTLE_TOOLS
static constexpr char commandPath[] = "/data/data/com.pvz2unline.aster/cache/aster-battle-tools.cmd";
static constexpr char claimedPath[] = "/data/data/com.pvz2unline.aster/cache/aster-battle-tools.claimed";

static char takeBattleCommand(Word base) {
    if (native<int>(base, 0x147e6c, commandPath, claimedPath) != 0) return 0;
    // O_NONBLOCK and O_NOFOLLOW from the Android ARM fcntl ABI.
    int fd = native<int>(base, 0x148448, claimedPath, 0x8800, 0);
    char input[2];
    int size = -1;
    if (fd >= 0) {
        size = native<int>(base, 0x148460, fd, input, sizeof(input));
        native<int>(base, 0x147b90, fd);
    }
    native<int>(base, 0x148424, claimedPath);
    return size == 1 ? input[0] : 0;
}

static void checkBattleTools(Word base, float time) {
    char command = 0;
    if (time >= current.commandPollAt) {
        current.commandPollAt = time + 0.5f;
        command = takeBattleCommand(base);
        if (command == 'S') current.sweeping = false;
        if (command == 'R') {
            current.sweeping = true;
            current.clearAt = time;
        }
    }
    if (command == 'C' || (current.sweeping && time >= current.clearAt)) {
        current.assisted = true;
        current.clearAt = time + 1.0f;
        native<void>(base, 0x85d8d8);
    }
}
#endif

extern "C" void asterAdventureStart(Word base, Object board) {
    current.board = nullptr;
#ifdef ASTER_WSA_BATTLE_TOOLS
    native<int>(base, 0x148424, commandPath);
    native<int>(base, 0x148424, claimedPath);
#endif
    if (observedBattleBoard == board) observedBattleBoard = nullptr;
    restoreEgyptEndlessPlantUpdates(base, board);
    if (!board || board != gameBoard(base) || !playing(board)) return;
#ifdef ASTER_SOCIAL_LEVELS
    if (!socialContentEnabled(base)) return;
#endif
    Word day = AdventureRecords::levelId(field<const char*>(board, 0xc4));
    if (!day) return;
    int starIndex = field<unsigned char>(board, 0x8a0) ? field<int>(board, 0x7f0) : -1;
    if (starIndex < -1 || starIndex > 2) return;
    Object store = ownerStore(base);
    Word id = owner(store);
    if (id == ~0U) return;
    Object profile = native<Object>(base, 0x7a98dc, store);
    if (!profile) return;
    float start = field<float>(board, 0xcc);
    if (!(start > 0 && start <= now(base))) return;
    auto* bytes = reinterpret_cast<volatile unsigned char*>(&current);
    for (Word i = 0; i < sizeof(current); ++i) bytes[i] = 0;
    current.board = board;
    current.profile = profile;
    current.owner = id;
    current.day = day;
    current.stars = Word(starIndex + 1);
    current.startedAt = start;
    current.clock = {start, 0};
#ifdef ASTER_SOCIAL_LEVELS
    captureLoadout(base, board, profile);
    bindBorrowedCard(board);
#endif
    hasCompleted = false;
}

extern "C" void asterAdventureTick(Word base, Object board) {
    // A saved battle can restore directly to the live phase.
    restoreEgyptEndlessPlantUpdates(base, board);
    if (current.board != board || !current.board) return;
    if (!sameRun(base, board)) {
        current.board = nullptr;
        return;
    }
    const auto clock = gameClock(base);
    if (!clock) return;
    const float time = field<float>(clock, 0x24);
    const bool live = playing(board);
    current.clock.advance(time, field<float>(clock, 0x28), live);
#ifdef ASTER_SOCIAL_LEVELS
    if (live && current.borrowedCard.level && !current.borrowedDrop.id && !current.borrowedDrop.serial &&
        current.clock.elapsed >= current.borrowedDropTime) dropBorrowedCard(base, board);
#endif
#ifdef ASTER_WSA_BATTLE_TOOLS
    if (live && !field<unsigned char>(board, 0x7fe)) checkBattleTools(base, time);
#endif
}

static void recordPath(char* out, Word ownerId, Word day, Word stars, bool temporary, bool assisted) {
    constexpr char prefix[] = "/data/data/com.pvz2unline.aster/files/userdata/adventure-";
    constexpr char hex[] = "0123456789abcdef";
    for (char ch : prefix) {
        if (!ch) break;
        *out++ = ch;
    }
    if (assisted) {
        for (char ch : "test-") {
            if (!ch) break;
            *out++ = ch;
        }
    }
    for (int shift = 28; shift >= 0; shift -= 4) *out++ = hex[(ownerId >> shift) & 15];
    *out++ = '-';
    // Keep the A275 filenames and binary IDs for the two Egypt levels.
    if (day <= 2) {
        *out++ = char('0' + day);
    } else {
        for (int shift = 28; shift >= 0; shift -= 4) *out++ = hex[(day >> shift) & 15];
    }
    *out++ = '-';
    *out++ = char('0' + stars);
    const char* suffix = temporary ? ".run.tmp" : ".run";
    while ((*out++ = *suffix++)) {}
}

static bool readRecord(Word base, int fd, Word ownerId, Word day, Word stars, Record& out) {
    auto* bytes = reinterpret_cast<Object>(&out);
    Word size = 0;
    while (size < sizeof(Record)) {
        int n = native<int>(base, 0x148460, fd, bytes + size, sizeof(Record) - size);
        if (n <= 0) break;
        size += unsigned(n);
    }
    char tail;
    int extra = native<int>(base, 0x148460, fd, &tail, 1);
    if (extra != 0 || !AdventureRecords::valid(out, ownerId, day, stars, size)) return false;
    if (out.version == 1) out.loadout.slots = 0;
    if (out.version < AdventureRecords::schema) out.tacticalCukeUses = AdventureRecords::unknownCukeUses;
    return true;
}

static bool readBest(Word base, Word ownerId, Word day, Word stars, Record& out, bool assisted = false) {
    char path[128];
    recordPath(path, ownerId, day, stars, false, assisted);
    int fd = native<int>(base, 0x148448, path, 0, 0);
    if (fd < 0) return false;
    bool valid = readRecord(base, fd, ownerId, day, stars, out);
    native<int>(base, 0x147b90, fd);
    return valid;
}

static bool writeBytes(Word base, const void* data, Word length, const char* path, const char* temp) {
    int fd = native<int>(base, 0x148448, temp, 0x241, 0600);
    if (fd < 0) return false;
    auto* bytes = reinterpret_cast<const unsigned char*>(data);
    Word size = 0;
    while (size < length) {
        int n = native<int>(base, 0x1485d4, fd, bytes + size, length - size);
        if (n <= 0) break;
        size += unsigned(n);
    }
    bool synced = size == length && native<int>(base, 0x1485e0, fd) == 0;
    bool closed = native<int>(base, 0x147b90, fd) == 0;
    bool saved = synced && closed && native<int>(base, 0x147e6c, temp, path) == 0;
    if (!saved) native<int>(base, 0x148424, temp);
    return saved;
}

static bool writeBest(Word base, const Record& record, bool assisted) {
    char path[128], temp[128];
    recordPath(path, record.owner, record.day, record.stars, false, assisted);
    recordPath(temp, record.owner, record.day, record.stars, true, assisted);
    return writeBytes(base, &record, sizeof(Record), path, temp);
}

static bool capturePlant(Word base, Object registry, Object object, Plant& out) {
    if (!object || !field<unsigned char>(object, 0xb4)
        || field<unsigned char>(object, 0x1c9)) return false;
    Word column = field<Word>(object, 0xb0);
    Word row = field<Word>(object, 0xac);
    // The normal Plant level setter writes +0x38. The mini-mode and
    // override levels are separate fields.
    Word level = field<Word>(object, 0x38);
    if (column >= 9 || row >= 5 || level < 1 || level > 4) return false;
    Object type = native<Object>(base, 0x1da034, registry,
        reinterpret_cast<const WeakRef*>(object + 0xf8));
    if (!type) return false;
    const char* alias = field<const char*>(type, 4);
    if (!alias || !AdventureRecords::validPlantType(alias)) return false;
    for (Word n = 0; alias[n]; ++n) out.type[n] = alias[n];
    out.column = static_cast<unsigned char>(column);
    out.row = static_cast<unsigned char>(row);
    out.level = static_cast<unsigned char>(level);
    out.avatar = native<bool>(base, 0x4b56ac, object);
    return true;
}

static void captureFormation(Word base, Record& out) {
    Object registry = native<Object>(base, 0x11d74b4);
    if (!registry) return;
    Object plants = native<Object>(base, 0x11d7538, registry, 0x23U);
    if (!plants) return;
    // The Plant store's intrusive list contains live instances. The call
    // runs on the game thread before Board::Win can clear those instances.
    Object sentinel = plants + 0x30;
    Object node = field<Object>(sentinel, 4);
    for (Word i = 0; node && node != sentinel && i < 4096 &&
        out.count < AdventureRecords::maxPlants; ++i) {
        if (capturePlant(base, registry, field<Object>(node, 8), out.plants[out.count]))
            ++out.count;
        node = field<Object>(node, 4);
    }
}

extern "C" void asterAdventureWin(Word base, Object board) {
    if (!sameRun(base, board) || !playing(board)) return;
    Object store = ownerStore(base);
    if (native<Object>(base, 0x7a98dc, store) != current.profile) return;
    if (current.stars && field<unsigned char>(board, 0x7fe)) return;
    Word elapsed = current.clock.milliseconds();
    current.board = nullptr;
    if (!elapsed) return;
#ifdef ASTER_SOCIAL_LEVELS
    // Assisted runs do not compete with unassisted personal times.
    if (current.friendSunUsed) return;
#endif

    auto* bytes = reinterpret_cast<unsigned char*>(&completed);
    for (Word i = 0; i < sizeof(Record); ++i) bytes[i] = 0;
    completed.version = AdventureRecords::schema;
    completed.owner = current.owner;
    completed.day = current.day;
    completed.stars = current.stars;
    completed.elapsedMs = elapsed;
#ifdef ASTER_SOCIAL_LEVELS
    completed.tacticalCukeUses = current.tacticalCukeUses;
#else
    completed.tacticalCukeUses = AdventureRecords::unknownCukeUses;
#endif
    if (field<Word>(board, 0xb4) == 9 && field<Word>(board, 0xb8) == 5 &&
        AdventureRecords::formationSupported(field<const char*>(board, 0xc4))) {
        captureFormation(base, completed);
#ifdef ASTER_SOCIAL_LEVELS
        completed.loadout.slots = runLoadout.slots;
        for (Word slot = 0; slot < runLoadout.slots; ++slot) {
            const auto& card = runLoadout.cards[slot];
            if (!card.level) continue;
            for (Word i = 0; card.type[i]; ++i) completed.loadout.cards[slot].type[i] = card.type[i];
            completed.loadout.cards[slot].level = card.level;
        }
#endif
    }
    completed.checksum = AdventureRecords::digest(completed);
    hasCompleted = AdventureRecords::valid(completed, current.owner, current.day, current.stars);
    if (!hasCompleted) return;

#ifdef ASTER_WSA_BATTLE_TOOLS
    const bool assisted = current.assisted;
#else
    constexpr bool assisted = false;
#endif
    bool haveBest = readBest(base, current.owner, current.day, current.stars, prior, assisted);
    bool saved = (!haveBest || completed.elapsedMs < prior.elapsedMs) && writeBest(base, completed, assisted);
    native<int>(base, 0x147adc, 4, "AsterAdventure",
        "clear level=%s stars=%u time_ms=%u plants=%u best_saved=%u assisted=%u",
        field<const char*>(board, 0xc4), completed.stars, completed.elapsedMs, completed.count,
        Word(saved), Word(assisted));
    if (assisted) hasCompleted = false;
}

extern "C" const Record* asterAdventureLast(Word base) {
    return hasCompleted && owner(ownerStore(base)) == completed.owner ? &completed : nullptr;
}

extern "C" bool asterAdventureBest(Word base, Word day, Word stars, Record* out) {
    Word id = owner(ownerStore(base));
    return out && id != ~0U && day && stars <= 3
        && readBest(base, id, day, stars, *out);
}

#ifdef ASTER_SOCIAL_LEVELS
namespace { static void updateAdventureClockHud(Word base); }
#include "social_levels.h"
#endif

#include "arena_clock.h"
