// Settings and collectible updates for the shared ARM32 engine.
using U = unsigned;
using P = unsigned char*;

template<class T> static T& at(P object, U offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R call(U base, U offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

template<class... A> static int imported(U base, U offset, A... args) {
    const U address = at<U>(reinterpret_cast<P>(base), offset);
    return reinterpret_cast<int(*)(A...)>(address)(args...);
}

static constexpr U menuId = 1050, offId = 1051, onId = 1052;
static constexpr U magic = 0x314b5041;
static const U label[] = {0x81ea, 0x52a8, 0x62fe, 0x53d6, 0};
static const char path[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/auto-pickup.bin";
static const char temporary[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/auto-pickup.tmp";
static bool loaded, enabled;
static P settings;

static void load(U base) {
    if (loaded) return;
    loaded = true;
    int fd = imported(base, 0x1822ebc, path, 0, 0);
    if (fd < 0) return;
    U record[3] = {};
    char extra;
    int length = imported(base, 0x1822ec4, fd, record, 12U);
    int tail = length == 12 ? imported(base, 0x1822ec4, fd, &extra, 1U) : -1;
    imported(base, 0x1822bd4, fd);
    enabled = length == 12 && tail == 0 && record[0] == magic && record[1] == 1 && record[2] == ~1U;
}

static bool save(U base, bool value) {
    U record[3] = {magic, U(value), ~U(value)};
    int fd = imported(base, 0x1822ebc, temporary, 0x241, 0600);
    if (fd < 0) return false;
    bool ok = imported(base, 0x1822f40, fd, record, 12U) == 12;
    if (ok) ok = imported(base, 0x1822f44, fd) == 0;
    if (imported(base, 0x1822bd4, fd) != 0) ok = false;
    if (ok) ok = imported(base, 0x1822cc8, temporary, path) == 0;
    if (!ok) imported(base, 0x1822ccc, temporary);
    return ok;
}

static void wide(U base, P* value, const U* text) {
    char allocator = 0;
    call<void>(base, 0x14eb451, value, text, &allocator);
}

static void release(U base, P text) {
    if (!text) return;
    char allocator = 0;
    call<void>(base, 0x14ea239, text - 12, &allocator);
}

extern "C" void asterPickupSettings(U base, P ui) {
    load(base);
    P scroll = at<P>(ui, 0xbc);
    if (!scroll) return;
    P arrow = call<P>(base, 0x1dd8f0, reinterpret_cast<P>(base + 0x1848a98));
    if (!arrow) return;
    P text = nullptr;
    wide(base, &text, label);
    P row = call<P>(base, 0x8e4898, ui, menuId, &text, arrow);
    call<void>(base, 0x8e5924, scroll, row);
    release(base, text);
}

extern "C" U asterPickupClick(U base, P ui, U id) {
    if (id <= 1 && settings == ui) settings = nullptr;
    if (id == menuId) {
        if (at<P>(ui, 0xc0) || at<U>(ui, 0xd4)) return 1;
        settings = ui;
        return 2;
    }
    if (settings != ui || (id != offId && id != onId)) return 0;
    const bool value = id == onId;
    if (value != enabled && save(base, value)) enabled = value;
    call<void>(base, 0x8e7820, ui);
    return 1;
}

extern "C" U asterPickupTitle(U base, P holder) {
    if (!settings) return 0;
    P text = nullptr;
    wide(base, &text, label);
    call<void>(base, 0x14e9b0d, holder + 0xa0, &text);
    release(base, text);
    return 1;
}

extern "C" U asterPickupRows(U base, P scroll, P description) {
    if (!settings) return 0;
    const U fill = at<U>(at<P>(description, 0), 4);
    reinterpret_cast<void(*)(P)>(fill)(description);
    static const U labels[2][2] = {{0x5173, 0}, {0x5f00, 0}};
    for (U i = 0; i < 2; ++i) {
        P text = nullptr;
        wide(base, &text, labels[i]);
        P row = call<P>(base, 0x8e4edc, settings, offId + i, &text, U(enabled == (i == 1)));
        call<void>(base, 0x8e5924, scroll, row);
        release(base, text);
    }
    return 1;
}

static bool startsWith(const char* name, const char* prefix) {
    if (!name) return false;
    while (*prefix) {
        if (*name++ != *prefix++) return false;
    }
    return true;
}

extern "C" void asterPickupUpdate(U base, P item) {
    const U type = at<U>(item, 0) - base;
    const char* kind;
    U index;
    switch (type) {
        case 0x178b860: kind = "sun"; index = 0; break;
        case 0x178ae38: kind = "plantfood"; index = 1; break;
        case 0x178a870: kind = "coin"; index = 2; break;
        default: return;
    }
    load(base);
    if (!enabled || at<U>(item, 0x94) != 0 || (at<U>(item, 0x8c) & 0x80)) return;
    P holder = at<P>(reinterpret_cast<P>(base), 0x1821674);
    P app = holder ? at<P>(holder, 0) : nullptr;
    P board = app ? at<P>(app, 0x6bc) : nullptr;
    if (!board || at<unsigned char>(board, 0x8d5)) return;
    const U phase = at<U>(board, 0xc0);
    if (phase != 4 && phase != 5) return;
    const char* name = at<const char*>(board, 0xc4);
    if (startsWith(name, "tutorial") || startsWith(name, "arena_battle_attack_tutorial")
            || startsWith(name, "arena_plant_tutorial")) return;
    const U modal = at<U>(at<P>(app, 0), 0x12c);
    if (reinterpret_cast<int(*)(P, int)>(modal)(app, 1)) return;

    // Both the current Chinese release and Aster construct a 0.5-second
    // game-clock deadline. Reuse the Aster deadline and the native tap event.
    P clock = call<P>(base, 0x1f7380);
    if (at<float>(clock, 0x24) > at<float>(item, 0x160)) {
        static U reported[3];
        if (reported[index] < 4) {
            ++reported[index];
            call<int>(base, 0x147adc, 4, "AsterPickup", "collect type=%s", kind);
        }
        call<void>(base, 0x27b558, item);
    }
}

struct WorldArchive {
    char name[9];
    char path[72];
    char archive[14];
    char manifest[36];
    U length;
};

#define WORLD(name, title, length) {#name, "/sdcard/Android/data/com.pvz2unline.aster/files/" #name ".rsb.smf", \
                                    #name ".rsb", "properties\\resources" #title ".rton", length}
static const WorldArchive worlds[] = {
    WORLD(egypt, Egypt, 0x55c1000), WORLD(pirate, Pirate, 0x2c42000), WORLD(cowboy, Cowboy, 0x2d20000),
    WORLD(kongfu, Kongfu, 0x4624000), WORLD(future, Future, 0x499b000), WORLD(dark, Dark, 0x43e6000),
    WORLD(beach, Beach, 0x4ac6000), WORLD(iceage, Iceage, 0x43f1000), WORLD(skycity, Skycity, 0x5b8d000),
    WORLD(lostcity, Lostcity, 0x30cb000),
};
#undef WORLD

static bool installedWorld(U base, const WorldArchive& archive) {
    int fd = imported(base, 0x1822ebc, archive.path, 0, 0);
    if (fd < 0) return false;
    U length = U(imported(base, 0x1822ec0, fd, 0, 2));
    imported(base, 0x1822bd4, fd);
    return length == archive.length;
}

extern "C" U asterLocalWorldAvailable(U base, P manager, P name, U stock) {
    if (call<U>(base, stock, manager, name)) return 1;
    const char* world = name ? at<const char*>(name, 0) : nullptr;
    for (const WorldArchive& archive : worlds) {
        if (!startsWith(world, archive.name)) continue;
        const char* end = archive.name;
        while (*end) { ++end; ++world; }
        if (*world) return 0;
        return installedWorld(base, archive);
    }
    return 0;
}

extern "C" void asterMountCampaignWorlds(U base, P resources, U mode, U setting,
                                         P egyptArchive, P egyptManifest, U required) {
    const U loadArchive = 0x11c1964;
    U result = call<U>(base, loadArchive, resources, mode, setting, egyptArchive, egyptManifest, required);
    call<int>(base, 0x147adc, 4, "AsterWorld", "archive egypt loaded=%u", result);
    // Each packaged world has an independent manifest. Keep processing the
    // remaining worlds if the framework rejects any one manifest.
    for (U i = 1; i < sizeof(worlds) / sizeof(worlds[0]); ++i) {
        const WorldArchive& world = worlds[i];
        if (!installedWorld(base, world)) continue;
        P archive = nullptr, manifest = nullptr;
        char allocator = 0;
        call<void>(base, 0x14ed0e1, &archive, world.archive, &allocator);
        call<void>(base, 0x14ed0e1, &manifest, world.manifest, &allocator);
        result = call<U>(base, loadArchive, resources, mode, setting, &archive, &manifest, required);
        call<int>(base, 0x147adc, 4, "AsterWorld", "archive %s loaded=%u", world.name, result);
        call<void>(base, 0x14ebf59, manifest - 12, &allocator);
        call<void>(base, 0x14ebf59, archive - 12, &allocator);
    }
}

static constexpr char festivalEndless[] = "festival_dangerroom_level_endless";
static U emptyFestivalCheckpointOwner = ~0U;

static bool isFestivalEndless(const char* name) {
    return startsWith(name, festivalEndless) && !name[sizeof(festivalEndless) - 1];
}

static U currentProfile(U base) {
    P manager = at<P>(reinterpret_cast<P>(base), 0x18300a4);
    return manager ? at<U>(manager, 0x74) : ~0U;
}

static bool emptySeedBank(U base, P board) {
    P bank = call<P>(base, 0x20bb34, board);
    if (!bank) return false;
    U count = at<unsigned char>(bank, 0x11d);
    if (count == 0 || count > 16) return false;
    P handles = call<P>(base, 0x11d74b4);
    for (U index = 0; index < count; ++index) {
        U packetHandle[2];
        call<void>(base, 0x895f0c, packetHandle, bank, index);
        P packet = call<P>(base, 0x1da034, handles, packetHandle);
        bool empty = packet && !(at<U>(packet, 0xf0) | at<U>(packet, 0xf4));
        call<void>(base, 0x1d9bb4, packetHandle, 0U, 0U);
        if (!empty) return false;
    }
    return true;
}

extern "C" void asterIdentifyEmptyFestivalCheckpoint(U base) {
    P holder = at<P>(reinterpret_cast<P>(base), 0x1821674);
    P app = holder ? at<P>(holder, 0) : nullptr;
    P board = app ? at<P>(app, 0x6bc) : nullptr;
    if (!board || !isFestivalEndless(at<const char*>(board, 0xc4))) return;
    P modules = at<P>(board, 0x938);
    if (!modules) return;
    P type = call<P>(base, 0x3f8538);
    P lastStand = call<P>(base, 0x43af38, modules, type);
    if (!lastStand || at<U>(lastStand, 0x34) != 3 || !emptySeedBank(base, board)) return;
    emptyFestivalCheckpointOwner = currentProfile(base);
    call<int>(base, 0x147adc, 4, "AsterEndless", "detected empty Festival pre-battle checkpoint");
}

extern "C" U asterAllowFestivalCheckpoint(U base, P store, P header, U context, U checkOwner) {
    if (!call<U>(base, checkOwner, store, header, context)) return 0;
    if (emptyFestivalCheckpointOwner != ~0U && emptyFestivalCheckpointOwner == at<U>(header, 0x18)
            && currentProfile(base) == emptyFestivalCheckpointOwner
            && isFestivalEndless(at<const char*>(header, 4))) {
        call<int>(base, 0x147adc, 4, "AsterEndless", "reloading Festival floor from saved progress");
        return 0;
    }
    return 1;
}

extern "C" void asterFestivalBattleReady(U base, P board) {
    if (emptyFestivalCheckpointOwner != ~0U && currentProfile(base) == emptyFestivalCheckpointOwner
            && isFestivalEndless(at<const char*>(board, 0xc4)) && !emptySeedBank(base, board)) {
        emptyFestivalCheckpointOwner = ~0U;
    }
}
