using Word = unsigned;
using Pointer = unsigned char*;

template<class T> static T field(const unsigned char* object, Word offset) {
    return *reinterpret_cast<const T*>(object + offset);
}

static constexpr Word sunType = 0x178b860;
static constexpr Word sunBombType = 0x17f64d0;
static constexpr Word plantFoodType = 0x178ae38;

static bool sunBomb(Word type, Pointer item) {
    // The minigame clears its armed state in place when the bomb turns into sun.
    if (type == sunBombType) return field<Word>(item, 0x16c) == 1;
    return type == sunType && field<unsigned char>(item, 0x168);
}

static bool arenaPlantFood(Word base, Word type) {
    if (type != plantFoodType) return false;
    Pointer holder = field<Pointer>(reinterpret_cast<Pointer>(base), 0x1821674);
    Pointer app = holder ? field<Pointer>(holder, 0) : nullptr;
    Pointer board = app ? field<Pointer>(app, 0x6bc) : nullptr;
    const char* name = board ? field<const char*>(board, 0xc4) : nullptr;
    if (!name) return false;
    // Includes the regular attack board and the introductory attack tutorial.
    for (char expected : "arena_battle_") {
        if (!expected) break;
        char actual = *name++;
        if (actual >= 'A' && actual <= 'Z') actual += 'a' - 'A';
        if (actual != expected) return false;
    }
    return true;
}

extern "C" bool asterAllowProgrammaticPickup(Word base, Pointer item) {
    const Word type = field<Word>(item, 0) - base;
    return !sunBomb(type, item) && !arenaPlantFood(base, type);
}

extern "C" bool asterAllowPickupTouch(Word base, Pointer item, Word phase) {
    const Word type = field<Word>(item, 0) - base;
    // The desktop A key and hover synthesize TouchMove (1). Let a real
    // TouchDown (0) on a bomb continue through the stock hit test.
    return !arenaPlantFood(base, type) && (phase == 0 || !sunBomb(type, item));
}
