using Word = unsigned int;
using Object = unsigned char*;

namespace {
constexpr Word unavailable = ~0U;
constexpr Word maximumConfiguredLimit = 20000;
constexpr Word defaultSunLimit = 6500;
constexpr Word wordsPerFormation = 224;
Word configuredLimit;

struct PlantCost {
    const char alias[32];
    Word sun;
};
constexpr PlantCost plantCosts[] = {
#include "preset_plant_costs.inc"
};

template <typename T>
T& field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template <typename T, typename... Args>
T native(Word base, Word address, Args... args) {
    return reinterpret_cast<T (*)(Args...)>(base + address)(args...);
}

bool sameText(const char* a, const char* b) {
    if (!a) return false;
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

Object app(Word base) {
    Object slot = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    return slot ? field<Object>(slot, 0) : nullptr;
}

bool isPresetBoard(Word base, Object board) {
    return board && field<unsigned char>(reinterpret_cast<Object>(base), 0x1b2bd70)
        && sameText(field<const char*>(board, 0xc4), "arena_plant_test");
}

Word cost(Word base, Object registry, Object weakType) {
    Object type = native<Object>(base, 0x1da034, registry, weakType);
    if (!type) return unavailable;
    const char* name = field<const char*>(type, 4);
    for (const PlantCost& plant : plantCosts)
        if (sameText(name, plant.alias)) return plant.sun;
    return unavailable;
}

Word spentSun(Word base, Object registry) {
    if (!registry) return unavailable;
    Object store = native<Object>(base, 0x11d7538, registry, 0x23U);
    if (!store) return 0;
    Object sentinel = store + 0x30;
    Object node = field<Object>(sentinel, 4);
    Word spent = 0;
    // Count only live plants on the lawn. Cursor previews and removed plants
    // can still have registry objects during their animation.
    for (Word i = 0; node && node != sentinel && i < 4096; ++i, node = field<Object>(node, 4)) {
        Object plant = field<Object>(node, 8);
        if (!plant || !field<unsigned char>(plant, 0xb4) || field<unsigned char>(plant, 0x1c9)
            || field<Word>(plant, 0xac) >= 5 || field<Word>(plant, 0xb0) >= 9) continue;
        Word price = cost(base, registry, plant + 0xf8);
        if (price == unavailable) return unavailable;
        spent += price;
    }
    return spent;
}

}

extern "C" Word presetBudgetLimit() {
    return configuredLimit ? configuredLimit : defaultSunLimit;
}

extern "C" Word presetBudgetCatalogue(const Word* data, Word size) {
    if (!data || size < 2 || data[0] > 1000 || size != 2 + data[0] * wordsPerFormation)
        return size;
    Word limit = data[size - 1];
    if (limit > maximumConfiguredLimit) return size;
    configuredLimit = limit;
    return size - 1;
}

extern "C" void presetBudgetRefresh(Word base, Object board) {
    Word limit = presetBudgetLimit();
    Word spent = spentSun(base, native<Object>(base, 0x11d74b4));
    Word key = field<Word>(board, 0x130);
    Word shift = key & 31;
    Word encoded = (spent < limit ? limit - spent : 0) ^ key;
    Word balance = (encoded << shift) | (encoded >> ((32 - shift) & 31));
    if (field<Word>(board, 0x12c) == balance) return;
    field<Word>(board, 0x12c) = balance;
    // The HUD caches the latest sun-change event instead of reading the board.
    native<void>(base, 0x221b1c, board, 0);
}

extern "C" bool presetBudgetCanPlace(Word base, Object board, Object weakType) {
    if (!isPresetBoard(base, board)) return true;
    Object registry = native<Object>(base, 0x11d74b4);
    Word spent = spentSun(base, registry);
    Word limit = presetBudgetLimit();
    return spent <= limit && cost(base, registry, weakType) <= limit - spent;
}

extern "C" bool presetBudgetCanSave(Word base) {
    Object game = app(base);
    Object board = game ? field<Object>(game, 0x6bc) : nullptr;
    if (!isPresetBoard(base, board) || spentSun(base, native<Object>(base, 0x11d74b4)) <= presetBudgetLimit())
        return true;
    field<Word>(reinterpret_cast<Object>(base), 0x1b2c27c) = 33; // editorEvent
    return false;
}
