using Word = unsigned;
using Object = unsigned char*;

template<class T> static T field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class T, class... Args> static T native(Word base, Word address, Args... args) {
    return reinterpret_cast<T(*)(Args...)>(base + address)(args...);
}

static bool equal(const char* left, const char* right) {
    while (*left && *left == *right) {
        ++left;
        ++right;
    }
    return *left == *right;
}

static bool egyptChallenge(Word base) {
    Object slot = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = slot ? field<Object>(slot, 0) : nullptr;
    Object board = app ? field<Object>(app, 0x6bc) : nullptr;
    const char* level = board ? field<const char*>(board, 0xc4) : nullptr;
    return level && (equal(level, "festival_lv3_easy") || equal(level, "festival_lv3_normal")
                     || equal(level, "festival_lv3_hard"));
}

extern "C" Object asterZombossArt(Word base, Object result, const char* const* resource) {
    constexpr Word Animation = 0xe45d08;
    if (!egyptChallenge(base)) return native<Object>(base, Animation, result, resource);

    const char* old = *resource;
    const char* name = nullptr;
    if (equal(old, "POPANIM_EFFECTS_ZOMBOSS_TELEPORTATION_BALL")) {
        name = "POPANIM_EFFECTS_EGYBOSS_TELEPORTATION_BALL";
    } else if (equal(old, "POPANIM_EFFECTS_ZOMBOSS_TELEPORT_BALL_EXIT")) {
        name = "POPANIM_EFFECTS_EGYBOSS_TELEPORT_BALL_EXIT";
    }
    if (!name) return native<Object>(base, Animation, result, resource);

    char allocator = 0;
    const char* alias = nullptr;
    native<void>(base, 0x14ed0e1, &alias, name, &allocator);
    Object animation = native<Object>(base, Animation, result, &alias);
    native<void>(base, 0x14ebf59, alias - 12, &allocator);
    return animation;
}
