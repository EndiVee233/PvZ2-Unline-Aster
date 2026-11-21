// Apply the tunnel animation's linear opacity ramp to newly spawned zombies.
using Word = unsigned;
using Object = unsigned char*;

template<class T> static T& field(Object object, Word offset) {
    return *reinterpret_cast<T*>(object + offset);
}

template<class R, class... A> static R call(Word base, Word offset, A... args) {
    return reinterpret_cast<R(*)(A...)>(base + offset)(args...);
}

struct Identity {
    Word object;
    Word serial;

    bool operator==(const Identity& other) const {
        return object == other.object && serial == other.serial;
    }
};

struct Entrance {
    Identity identity;
    float start;
    Word round;
};

static constexpr float duration = 0.5f;
static constexpr Word bucketCount = 512;
static Entrance entrances[bucketCount][8];
static Object currentBoard;
static Word currentRound;
static float lastSpawnTime;

static Identity identity(Object object, Word offset) {
    // The high bit distinguishes another weak reference representation.
    return {field<Word>(object, offset), field<Word>(object, offset + 4) & 0x7fffffffU};
}

static Entrance (&bucket(Identity key))[8] {
    Word hash = key.object ^ (key.object >> 16) ^ (key.serial * 0x9e3779b9U);
    return entrances[(hash ^ (hash >> 9)) & (bucketCount - 1)];
}

static Object board(Word base) {
    Object holder = field<Object>(reinterpret_cast<Object>(base), 0x1821674);
    Object app = holder ? field<Object>(holder, 0) : nullptr;
    return app ? field<Object>(app, 0x6bc) : nullptr;
}

static float gameTime(Word base) {
    return field<float>(call<Object>(base, 0x1f7380), 0x24);
}

extern "C" void asterZombieEntrance(Word base, Object ownerBoard, Object zombie) {
    if (ownerBoard != board(base) || field<unsigned char>(zombie, 0x60)) return;
    const Word phase = field<Word>(ownerBoard, 0xc0);
    if (phase != 4 && phase != 5) return;

    const Identity key = identity(zombie, 8);
    if (!(key.object | key.serial)) return;
    const float now = gameTime(base);
    if (ownerBoard != currentBoard || now < lastSpawnTime) {
        currentBoard = ownerBoard;
        ++currentRound;
    }
    lastSpawnTime = now;

    auto& slots = bucket(key);
    Entrance* slot = &slots[0];
    for (Entrance& candidate : slots) {
        if (candidate.round != currentRound || candidate.identity == key) {
            slot = &candidate;
            break;
        }
        if (candidate.start < slot->start) slot = &candidate;
    }
    *slot = {key, now, currentRound};
}

extern "C" void asterDrawZombieEntrance(Word base, Object zombie, Object rig,
                                          Object graphics, Object transform) {
    constexpr Word drawRig = 0x776b54;
    const Identity key = identity(zombie, 8);
    if (currentBoard && (key.object | key.serial)) {
        for (const Entrance& entry : bucket(key)) {
            if (entry.round != currentRound || !(entry.identity == key)) continue;
            const float elapsed = gameTime(base) - entry.start;
            if (!(elapsed >= 0 && elapsed < duration) || currentBoard != board(base)) break;
            // The tunnel fade also writes PopAnim's alpha at +0x84.
            Object animation = field<Object>(rig, 0x14);
            if (!animation) break;

            // Multiply and restore so native tunnel, invisibility and tint
            // changes continue to own the persistent animation color.
            int& alpha = field<int>(animation, 0x84);
            const int originalAlpha = alpha;
            alpha = int(float(originalAlpha) * (elapsed / duration));
            call<void>(base, drawRig, rig, graphics, transform);
            alpha = originalAlpha;
            return;
        }
    }
    call<void>(base, drawRig, rig, graphics, transform);
}
