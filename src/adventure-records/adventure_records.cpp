#include "records.h"

using Word = unsigned;
using Object = unsigned char*;
using AdventureRecords::Plant;
using AdventureRecords::Record;
using AdventureRecords::Stopwatch;

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

static Object gameBoard(Word base) {
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = holder ? field<Object>(holder, 0) : nullptr;
    return app ? field<Object>(app, 0x6bc) : nullptr;
}

static Object ownerStore(Word base) {
    return field<Object>(reinterpret_cast<Object>(base), 0x18300a4);
}

static Word owner(Object store) {
    return store ? field<Word>(store, 0x74) : ~0U;
}

static float now(Word base) {
    Object clock = field<Object>(reinterpret_cast<Object>(base), 0x1830528);
    return clock ? field<float>(clock, 0x24) : 0;
}

static bool playing(Object board) {
    return field<Word>(board, 0xc0) == 5 && !field<Word>(board, 0x7f4)
        && !field<unsigned char>(board, 0x8d5) && !field<unsigned char>(board, 0x7fd);
}

static Object observedBattleBoard;
static float observedBattleStart;

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
    constexpr Word plantActionsEnabled = 0x7fb;
    field<unsigned char>(board, plantActionsEnabled) = 1;
}

static bool sameRun(Word base, Object board) {
    return board && current.board == board && gameBoard(base) == board &&
        owner(ownerStore(base)) == current.owner &&
        field<float>(board, 0xcc) == current.startedAt &&
        AdventureRecords::egyptDay(field<const char*>(board, 0xc4)) == current.day;
}

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
    Word day = AdventureRecords::egyptDay(field<const char*>(board, 0xc4));
    if (!day || field<Word>(board, 0xb4) != 9 || field<Word>(board, 0xb8) != 5) return;
    int starIndex = field<unsigned char>(board, 0x8a0) ? field<int>(board, 0x7f0) : -1;
    if (starIndex < -1 || starIndex > 2) return;
    Object store = ownerStore(base);
    Word id = owner(store);
    if (id == ~0U) return;
    Object profile = native<Object>(base, 0x7a98dc, store);
    if (!profile) return;
    float start = field<float>(board, 0xcc);
    if (!(start > 0 && start <= now(base))) return;
    current = {};
    current.board = board;
    current.profile = profile;
    current.owner = id;
    current.day = day;
    current.stars = Word(starIndex + 1);
    current.startedAt = start;
    current.clock = {start, 0, true};
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
    const float time = now(base);
    const bool live = playing(board);
    current.clock.sample(time, live);
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
    *out++ = char('0' + day);
    *out++ = '-';
    *out++ = char('0' + stars);
    const char* suffix = temporary ? ".run.tmp" : ".run";
    while ((*out++ = *suffix++)) {}
}

static bool readBest(Word base, Word ownerId, Word day, Word stars, Record& out, bool assisted = false) {
    char path[128];
    recordPath(path, ownerId, day, stars, false, assisted);
    int fd = native<int>(base, 0x148448, path, 0, 0);
    if (fd < 0) return false;
    auto* bytes = reinterpret_cast<Object>(&out);
    Word size = 0;
    while (size < sizeof(Record)) {
        int n = native<int>(base, 0x148460, fd, bytes + size, sizeof(Record) - size);
        if (n <= 0) break;
        size += unsigned(n);
    }
    char tail;
    int extra = native<int>(base, 0x148460, fd, &tail, 1);
    native<int>(base, 0x147b90, fd);
    return size == sizeof(Record) && extra == 0 && AdventureRecords::valid(out, ownerId, day, stars);
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

struct WeakRef {
    Word id;
    Word serial;
};

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
    current.clock.sample(now(base), true);
    Word elapsed = current.clock.milliseconds();
    current.board = nullptr;
    if (!elapsed) return;

    auto* bytes = reinterpret_cast<unsigned char*>(&completed);
    for (Word i = 0; i < sizeof(Record); ++i) bytes[i] = 0;
    completed.version = AdventureRecords::schema;
    completed.owner = current.owner;
    completed.day = current.day;
    completed.stars = current.stars;
    completed.elapsedMs = elapsed;
    captureFormation(base, completed);
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
        "clear egypt%u stars=%u time_ms=%u plants=%u best_saved=%u assisted=%u",
        completed.day, completed.stars, completed.elapsedMs, completed.count, Word(saved), Word(assisted));
    if (assisted) hasCompleted = false;
}

extern "C" const Record* asterAdventureLast(Word base) {
    return hasCompleted && owner(ownerStore(base)) == completed.owner ? &completed : nullptr;
}

extern "C" bool asterAdventureBest(Word base, Word day, Word stars, Record* out) {
    Word id = owner(ownerStore(base));
    return out && id != ~0U && day >= 1 && day <= 2 && stars <= 3
        && readBest(base, id, day, stars, *out);
}

#ifdef ASTER_SOCIAL_LEVELS
#include "social_levels.h"
#endif

struct Color {
    int red, green, blue, alpha;
};

static void rectangle(Word base, Object graphics, int x, int y, int width, int height) {
    constexpr int left = 438;
    constexpr int top = 60;
    constexpr int scale = 2;
    native<void>(base, 0x1167010, graphics, left + x * scale, top + y * scale,
        width * scale, height * scale);
}

static void digit(Word base, Object graphics, unsigned value, int x, int y) {
    static constexpr unsigned char masks[] = {
        0x3f, 0x06, 0x5b, 0x4f, 0x66, 0x6d, 0x7d, 0x07, 0x7f, 0x6f
    };
    struct Segment {
        unsigned char x, y, width, height;
    };
    static constexpr Segment segments[] = {
        {2, 0, 6, 2}, {8, 2, 2, 5}, {8, 9, 2, 5}, {2, 14, 6, 2},
        {0, 9, 2, 5}, {0, 2, 2, 5}, {2, 7, 6, 2}
    };
    for (unsigned i = 0; i < 7; ++i) {
        if (!(masks[value] & (1U << i))) continue;
        const Segment& s = segments[i];
        rectangle(base, graphics, x + s.x, y + s.y, s.width, s.height);
    }
}

extern "C" void asterAdventureDrawClock(Word base, Object board, Object graphics) {
    if (!graphics || current.board != board || !sameRun(base, board) ||
        field<Word>(board, 0xc0) != 5 || field<Word>(board, 0x7f4)) return;
    Word tenths = current.clock.milliseconds() / 100;
    Word minutes = tenths / 600;
    Word seconds = tenths / 10 % 60;
    const Color previous = field<Color>(graphics, 0x4c);
    constexpr Color background{22, 25, 17, 172};
    constexpr Color numbers{255, 243, 191, 255};
    native<void>(base, 0x1166c30, graphics, &background);
    rectangle(base, graphics, -6, -5, 84, 26);
    native<void>(base, 0x1166c30, graphics, &numbers);
    digit(base, graphics, minutes / 10, 0, 0);
    digit(base, graphics, minutes % 10, 12, 0);
    rectangle(base, graphics, 26, 4, 2, 2);
    rectangle(base, graphics, 26, 10, 2, 2);
    digit(base, graphics, seconds / 10, 32, 0);
    digit(base, graphics, seconds % 10, 44, 0);
    rectangle(base, graphics, 56, 14, 2, 2);
    digit(base, graphics, tenths % 10, 62, 0);
    native<void>(base, 0x1166c30, graphics, &previous);
}
