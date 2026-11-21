using Address = unsigned;
using Player = void*;

template<class Function>
static Function native(Address base, Address offset) {
    return reinterpret_cast<Function>(base + offset);
}

static bool equals(const char* value, const char* expected) {
    if (!value) return false;
    while (*value && *value == *expected) {
        ++value;
        ++expected;
    }
    return *value == *expected;
}

extern "C" int asterLegacyDangerRoomProgress(Address base, Player player,
                                             const char* const* key, const unsigned char* node) {
    const auto progress = native<int (*)(Player, const char* const*)>(base, 0x708104);
    const int status = progress(player, key);
    if (status >= 2 || *reinterpret_cast<const unsigned*>(node + 0x10) != 1) return status;

    const auto name = reinterpret_cast<const char* const*>(node + 0x14);
    const auto level = reinterpret_cast<const char* const*>(node + 0x18);
    const auto prerequisite = reinterpret_cast<const char* const*>(node + 0x1c);
    if (!equals(*name, "egypt_level_dangerroom") || !equals(*level, "egypt_dangerroom") ||
        !equals(*prerequisite, "egypt_level_11")) return status;

    // Existing profiles completed the prerequisite before this node could unlock.
    char allocator = 0;
    const char* previous = nullptr;
    native<void (*)(const char**, const char*, char*)>(base, 0x14ed0e1)(&previous, "egypt11", &allocator);
    const bool complete = native<bool (*)(Player, const char* const*)>(base, 0x708190)(player, &previous);
    native<void (*)(const char*, char*)>(base, 0x14ebf59)(previous - 12, &allocator);
    if (!complete) return status;

    // Use the stock unlock event and keep the normal game save cadence.
    native<void (*)(Player, const char* const*, const char* const*, int, bool)>(
        base, 0x7469e8)(player, name, level, 2, false);
    const int unlocked = progress(player, key);
    if (unlocked >= 2) {
        native<int (*)(int, const char*, const char*)>(base, 0x147adc)(
            4, "LegacyEndless", "Restored the Egypt map node from completed adventure progress");
    }
    return unlocked;
}
