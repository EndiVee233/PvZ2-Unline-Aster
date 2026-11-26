// Included by tunnel.cpp after the shared board, animation and spawn helpers.

static constexpr char zoybeanGrowth[][sizeof("transition4")] = {
    "transition", "transition2", "plantfood", "transition4",
};
static constexpr char zoybeanIdle[][sizeof("idle4")] = {"idle", "idle2", "idle3", "idle4"};
// The builder appends 64 hold frames to each authored clip.
static constexpr int zoybeanIdleStarts[] = {0, 207, 407, 590};
static constexpr int zoybeanIdleLengths[] = {43, 41, 21, 60};
static constexpr float zoybeanGrowthSeconds[] = {36.f / 30, 31.f / 30, 34.f / 30, 38.f / 30};
static constexpr float zoybeanWait = (zoybeanCycleSeconds - zoybeanGrowthSeconds[0] -
    zoybeanGrowthSeconds[1] - zoybeanGrowthSeconds[2] - zoybeanGrowthSeconds[3]) / 4;
static constexpr char zoybeanSmoke[] = "POPANIM_EFFECTS_ZOYBEANPOD_SMOKE";

struct ZoybeanGrowth {
    Object board;
    Identity plant;
    float round;
    float due;
    float smokeAt;
    unsigned phase;
    bool food;
    bool smokeOpening;
};

struct ZoybeanAlly {
    Object board;
    Identity zombie;
    Identity projectile;
    float round;
    Point origin;
    float bornUntil;
    float smashStarted;
    float lastFrame;
    int level;
    bool giant;
    bool costume;
    bool gatling;
    bool struck;
    bool eating;
};

static ZoybeanGrowth zoybeanPlants[45];
static ZoybeanAlly zoybeanAllies[96];

#ifdef ASTER_ZOYBEAN_SHOWCASE
extern "C" Word asterZoybeanShowcaseRank(Word, Object board, Word col, Word row) {
    return col == 0 && row < 4 && equal(field<const char*>(board, 0xc4), "mausoleum1") ? row + 1 : 0;
}

static constexpr char zoybeanTestTag[] = "AsterZoybeanTest";

extern "C" Object asterZoybeanShowcaseSetRank(Word base, Object plant, Word rank) {
    if (!plant) return nullptr;
    const auto initialRank = field<Word>(plant, 0x38);
    if (initialRank != rank) {
        const auto setter = field<Word*>(plant, 0)[0xa4 / 4];
        reinterpret_cast<void(*)(Object, Word)>(setter)(plant, rank);
    }
    native<int>(base, 0x147adc, 4, zoybeanTestTag, "placement rank=%u initial=%u actual=%u",
                rank, initialRank, field<Word>(plant, 0x38));
    return plant;
}

extern "C" Word asterZoybeanShowcasePlantedRank(Word base, Object plant, Word rank) {
    const auto board = currentBoard(base);
    if (!board || !active(board) || !field<unsigned char>(board, 0x7fb) ||
        !equal(field<const char*>(board, 0xc4), "mausoleum1") ||
        !equal(plantAlias(base, plant), zoybeanAlias)) return rank;
    const auto cell = electriciteaCell(plant);
    native<int>(base, 0x147adc, 4, zoybeanTestTag, "manual placement rank=4 row=%d col=%d",
                cell.row + 1, cell.col + 1);
    return 4;
}

static bool zoybeanShowcaseGatlingHit(Object projectile) {
    const auto source = field<Identity>(projectile, 0x50);
    for (const auto& ally : zoybeanAllies)
        if (ally.board && ally.gatling && ally.zombie == source) return true;
    return false;
}
#endif

static bool zoybeanGiant(const char* alias) {
    return equal(alias, "zoybeanpod_gargantuar") || equal(alias, "zoybeanpod_gargantuar2");
}

static Object resolveZoybeanActor(Word base, Object registry, Identity id) {
    if (!registry || (!id.low && !id.high)) return nullptr;
    alignas(8) const Identity weak = id;
    const auto actor = native<Object>(base, 0x1da034, registry, &weak);
    return actor && identity(actor) == id && !native<Word>(base, 0x348944, actor) ? actor : nullptr;
}

static Object zoybeanEnemy(Word base, Object board, Point from, float reach) {
    Object nearest = nullptr;
    const auto live = liveZombies(base, board);
    for (auto slot = live.first; slot != live.end; ++slot) {
        const auto zombie = *slot;
        if (!lightningTarget(base, zombie) || (field<Word>(zombie, 0x1c) & 1U)) continue;
        const auto where = groundPosition(zombie);
        const float delta = where.x - from.x;
        if (delta < -12.f || delta > reach || rowAt(where.y) != rowAt(from.y)) continue;
        nearest = zombie;
        reach = delta;
    }
    return nearest;
}

static Object spawnZoybeanAlly(Word base, Object board, Object plant, const char* name,
                              Point origin, bool giant, bool costume, bool gatling) {
    const auto registry = native<Object>(base, 0x11d74b4);
    const float round = field<float>(board, 0xcc);
    const int level = field<int>(plant, 0x38);
    for (auto& slot : zoybeanAllies) {
        if (slot.board == board && slot.round == round && resolveZoybeanActor(base, registry, slot.zombie))
            continue;
        const auto zombie = spawnQinZombie(base, board, name, origin, level);
        if (!zombie) return nullptr;
        // Keep right-facing collisions with the authored right-facing art.
        native<void>(base, 0x23eedc, zombie, 1U);
        const auto rig = field<Object>(zombie, 0x84);
        if (rig) {
            native<void>(base, 0xa41cb8, zombie, 1U);
            native<void>(base, 0x77624c, rig, 0U);
        }
        playZombieClip(base, rig, giant ? "spawn" : "born", false);
        Identity shot{};
        if (gatling) {
            const auto sheet = field<Object>(plant, 0x190);
            const auto action = sheet ? field<Object>(sheet, 0x38) : nullptr;
            if (action) shot = {field<Word>(action, 8), field<Word>(action, 12)};
        }
        // Tofu enters on its first opaque frame. Giants keep their spawn effect.
        slot = {board, identity(zombie), shot, round, origin, battleTime(base) + (giant ? 37.f : 46.f) / 30,
                0, -1, level, giant, costume, gatling, false, false};
        return zombie;
    }
    return nullptr;
}

#ifdef ASTER_ZOYBEAN_SHOWCASE
static void showcaseZoybeanHats(Word base, Object board, Object plant) {
    const auto cell = electriciteaCell(plant);
    if (cell.row != 3 || cell.col != 0 || !equal(field<const char*>(board, 0xc4), "mausoleum1")) return;
    static constexpr char names[][sizeof("zombie_zoybeanpodgatlingpea")] = {
        "zombie_zoybeanpodgatlingpea", "zoybeanpod_gatling_cone", "zoybeanpod_gatling_bucket",
    };
    for (Word i = 0; i < sizeof(names) / sizeof(*names); ++i) {
        const Point preview{232.f + 128.f * i, firstLaneY + laneHeight * 4};
        const auto zombie = spawnZoybeanAlly(base, board, plant, names[i], preview, false, false, true);
        native<int>(base, 0x147adc, 4, zoybeanTestTag, "preview row=5 unit=%s ok=%d", names[i], int(zombie != nullptr));
    }
}
#endif

static void zoybeanSpawn(Word base, Object board, Object plant, bool giant) {
    const int level = field<int>(plant, 0x38);
    const bool costume = giant && field<unsigned char>(plant, 0x16c); // Plant::m_bAvatar
    const char* name = costume ? "zoybeanpod_gargantuar2" : "zoybeanpod_gargantuar";
    bool gatling = false;
    unsigned roll = 100;
    unsigned hatRoll = 100;
    if (!giant) {
        roll = native<unsigned>(base, 0x11317a8, 100U);
        switch (zoybeanUnit(level, roll)) {
        case ZoybeanUnit::basic: name = "zoybeanpod_basic"; break;
        case ZoybeanUnit::cone: name = "zoybeanpod_armor1"; break;
        case ZoybeanUnit::bucket: name = "zoybeanpod_armor2"; break;
        case ZoybeanUnit::gatling:
            gatling = true;
            hatRoll = native<unsigned>(base, 0x11317a8, 100U);
            switch (zoybeanHat(hatRoll)) {
            case ZoybeanHat::none: name = "zombie_zoybeanpodgatlingpea"; break;
            case ZoybeanHat::carrot: name = "zoybeanpod_gatling_cone"; break;
            case ZoybeanHat::watermelon: name = "zoybeanpod_gatling_bucket"; break;
            }
            break;
        }
    }
    const auto cell = electriciteaCell(plant);
    const Point origin{groundPosition(plant).x, firstLaneY + laneHeight * cell.row};
    [[maybe_unused]] const auto zombie = spawnZoybeanAlly(base, board, plant, name, origin, giant, costume, gatling);
#ifdef ASTER_ZOYBEAN_SHOWCASE
    native<int>(base, 0x147adc, 4, zoybeanTestTag, "spawn rank=%d row=%d unit=%s roll=%u hat=%u ok=%d",
                level, cell.row + 1, name, roll, hatRoll, int(zombie != nullptr));
    showcaseZoybeanHats(base, board, plant);
#endif
}

static bool bindZoybeanGrowth(Word base, Object rig) {
    const auto old = field<Object>(rig, 0x14);
    if (!old) return false;
    char allocator = 0;
    const char* resource;
    native<void>(base, 0x14ed0e1, &resource, "POPANIM_PLANT_ZOYBEANPOD_BATTLE", &allocator);
    alignas(8) Word handle[2]{};
    native<void>(base, 0xe45d08, handle, &resource);
    releaseText(base, resource);
    const auto registry = native<Object>(base, 0x11d74b4);
    const auto animation = registry ? native<Object>(base, 0x1da034, registry, handle) : nullptr;
    const auto replacement = animation && field<Object>(animation, 0x44) ?
        native<Object>(base, 0x118da7c, animation) : nullptr;
    native<void>(base, 0x1d9bb4, handle, 0U, 0U);
    if (!replacement) return false;

    const bool owned = field<unsigned char>(rig, 0x20);
    auto scale = reinterpret_cast<Word*>(replacement + 0x20);
    scale[0] = field<Word>(old, 0x20);
    scale[1] = field<Word>(old, 0x24);
    native<void>(base, 0x7749e4, rig, replacement, 1U);
    if (owned) native<void>(base, 0x11904ac, old);
    playZombieClip(base, rig, zoybeanIdle[0], true);
    return true;
}

static void keepZoybeanIdle(Word base, Object rig, unsigned index) {
    const auto frame = zombieClipFrame(rig);
    const int start = zoybeanIdleStarts[index];
    if (frame < start || frame >= start + zoybeanIdleLengths[index] - 1)
        playZombieClip(base, rig, zoybeanIdle[index], true);
}

static bool startZoybeanCycle(Word base, Object plant, Object board, Object rig, ZoybeanGrowth& state) {
    const float round = field<float>(board, 0xcc);
    const auto id = identity(plant);
    if (state.board == board && state.round == round && state.plant == id) return false;
    if (!bindZoybeanGrowth(base, rig)) return false;
    state = {board, id, round, battleTime(base) + zoybeanWait, 0, 1, false, false};
    return true;
}

static void startZoybeanFood(Word base, Object rig, ZoybeanGrowth& state, float now) {
    if (state.food) return;
    state.food = true;
    state.phase = 6;
    state.due = now + zoybeanGrowthSeconds[2];
    state.smokeAt = now + 6.f / 30;
    state.smokeOpening = true;
    playZombieClip(base, rig, zoybeanGrowth[2], false);
}

extern "C" void asterZoybeanPlantFood(Word base, Object plant) {
    if (!equal(plantAlias(base, plant), zoybeanAlias)) return;
    const auto board = currentBoard(base);
    const auto cell = electriciteaCell(plant);
    const auto rig = field<Object>(plant, 0x194);
    if (!board || !active(board) || !rig || !electriciteaValidCell(cell) ||
        !field<unsigned char>(plant, 0xb4)) return;
    auto& state = zoybeanPlants[cell.row * 9 + cell.col];
    startZoybeanCycle(base, plant, board, rig, state);
    if (state.board == board && state.plant == identity(plant) && !state.food) {
#ifdef ASTER_ZOYBEAN_SHOWCASE
        native<int>(base, 0x147adc, 4, zoybeanTestTag, "native plantfood rank=%d row=%d col=%d",
                    field<int>(plant, 0x38), cell.row + 1, cell.col + 1);
#endif
        startZoybeanFood(base, rig, state, battleTime(base));
    }
}

static void updateZoybeanPlant(Word base, Object plant, Object board) {
    const auto cell = electriciteaCell(plant);
    if (!electriciteaValidCell(cell)) return;
    auto& state = zoybeanPlants[cell.row * 9 + cell.col];
    const auto rig = field<Object>(plant, 0x194);
    if (!rig || field<Word>(plant, 0x90) == 3) return;
    const auto now = battleTime(base);
    [[maybe_unused]] const bool started = startZoybeanCycle(base, plant, board, rig, state);
#ifdef ASTER_ZOYBEAN_SHOWCASE
    if (started)
        native<int>(base, 0x147adc, 4, zoybeanTestTag, "plant rank=%d row=%d",
                    field<int>(plant, 0x38), cell.row + 1);
#endif
    if (state.board != board || state.round != field<float>(board, 0xcc) || !(state.plant == identity(plant))) return;
    if (state.smokeAt && now >= state.smokeAt) {
        electriciteaVisual(base, board, zoybeanSmoke, state.smokeOpening ? "open" : "start", groundPosition(plant), 0);
        if (state.smokeOpening) zoybeanSpawn(base, board, plant, state.food);
        state.smokeAt = 0;
    }
    if (now < state.due) {
        if (state.phase % 2) keepZoybeanIdle(base, rig, (state.phase - 1) / 2);
        return;
    }
    if (state.phase == 8) {
        state.phase = 1;
        state.due += zoybeanWait;
        state.food = false;
        playZombieClip(base, rig, zoybeanIdle[0], true);
        return;
    }
    const unsigned stage = (state.phase - 1) / 2;
    if (state.phase % 2) {
        playZombieClip(base, rig, zoybeanGrowth[stage], false);
        state.due += zoybeanGrowthSeconds[stage];
        if (stage == 1 || stage == 2) {
            state.smokeAt = now + (stage == 1 ? 15.f : 6.f) / 30;
            state.smokeOpening = stage == 2;
        }
    } else if (state.food) {
        playZombieClip(base, rig, zoybeanGrowth[3], false);
        state.phase = 8;
        state.due = now + zoybeanGrowthSeconds[3];
        return;
    } else {
        playZombieClip(base, rig, zoybeanIdle[stage + 1], true);
        state.due += zoybeanWait;
    }
    ++state.phase;
}

static void zoybeanShoot(Word base, Object board, Object registry, Object zombie, const ZoybeanAlly& ally) {
    alignas(8) const Identity projectile = ally.projectile;
    if (!registry || (!projectile.low && !projectile.high) ||
        !native<Object>(base, 0x1da034, registry, &projectile)) {
#ifdef ASTER_ZOYBEAN_SHOWCASE
        native<int>(base, 0x147adc, 4, zoybeanTestTag, "gatling projectile reference unavailable rank=%d", ally.level);
#endif
        return;
    }
    const auto from = groundPosition(zombie);
    // CN ZombieZoybeanpodGatlingPeaDefault SpawnOffset is {40, 0, 60}.
    [[maybe_unused]] const auto shot = native<Object>(base, 0x214ea4, board, from.x + 40.f, from.y,
                   field<float>(zombie, 0x18) + 60.f, &projectile, zombie, 0U);
#ifdef ASTER_ZOYBEAN_SHOWCASE
    native<int>(base, 0x147adc, 4, zoybeanTestTag, "gatling shot rank=%d row=%d x=%d ok=%d",
                ally.level, rowAt(from.y) + 1, int(from.x), int(shot != nullptr));
#endif
}

static void updateZoybeanGatling(Word base, Object board, Object registry, Object zombie, Object rig, ZoybeanAlly& ally) {
    const float frame = zombieClipFrame(rig);
    const bool eating = field<Word>(zombie, 0xd8) == 2;
    constexpr int walking[] = {181, 186, 191, 196};
    constexpr int biting[] = {244, 274, 304, 336, 366, 396, 429, 460};
    const int* frames = eating ? biting : walking;
    const unsigned size = eating ? sizeof(biting) / sizeof(int) : sizeof(walking) / sizeof(int);
    const float low = eating ? 224 : 134;
    const float high = eating ? 482 : 223;
    if (frame >= low && frame <= high) {
        const float previous = ally.eating == eating ? ally.lastFrame : low - 1;
        const float from = previous < low ? low - 1 : previous;
        for (unsigned i = 0; i < size; ++i) {
            const int cue = frames[i];
            if (frame >= from ? from < cue && cue <= frame : cue > from || cue <= frame)
                zoybeanShoot(base, board, registry, zombie, ally);
        }
        ally.lastFrame = frame;
    } else {
        ally.lastFrame = -1;
    }
    ally.eating = eating;
}

static void updateZoybeanGiant(Word base, Object board, Object zombie, Object rig, ZoybeanAlly& ally, float now) {
    const auto position = groundPosition(zombie);
    if (!ally.smashStarted) {
        if (!zoybeanEnemy(base, board, position, 72.f)) return;
        ally.origin = position;
        ally.smashStarted = now;
        ally.struck = false;
        playZombieClip(base, rig, "eat", false);
    }
    setPosition(zombie, ally.origin);
    if (!ally.struck && now - ally.smashStarted >= 38.f / 30) {
        ally.struck = true;
        if (const auto target = zoybeanEnemy(base, board, ally.origin, 82.f)) {
            const DamageInfo hit{reinterpret_cast<Word>(zombie), 1500.f, {}, int(zoybeanId), ally.level, {}};
            const auto damage = field<Word*>(target, 0)[0x74 / 4];
            reinterpret_cast<void(*)(Object, const DamageInfo*)>(damage)(target, &hit);
            if (ally.costume && lightningTarget(base, target)) native<void>(base, 0xa4adcc, target, 3.0f);
        }
    }
    if (now - ally.smashStarted >= 91.f / 30) {
        ally.smashStarted = 0;
        playZombieClip(base, rig, "walk", true);
    }
}

static void updateZoybeanAllies(Word base, Object board, float now) {
    const auto registry = native<Object>(base, 0x11d74b4);
    const float round = field<float>(board, 0xcc);
    for (auto& ally : zoybeanAllies) {
        if (!ally.board) continue;
        const auto zombie = ally.board == board && ally.round == round ?
            resolveZoybeanActor(base, registry, ally.zombie) : nullptr;
        if (!zombie || field<float>(zombie, bodyHealthOffset) <= 0) {
            ally.board = nullptr;
            continue;
        }
        const auto rig = field<Object>(zombie, 0x84);
        if (ally.bornUntil) {
            setPosition(zombie, ally.origin);
            if (now < ally.bornUntil) continue;
            ally.bornUntil = 0;
            native<void>(base, 0xa558f0, zombie, 1U, 0U);
            playZombieClip(base, rig, "walk", true);
        }
        if (ally.giant) updateZoybeanGiant(base, board, zombie, rig, ally, now);
        if (ally.gatling) updateZoybeanGatling(base, board, registry, zombie, rig, ally);
    }
}
