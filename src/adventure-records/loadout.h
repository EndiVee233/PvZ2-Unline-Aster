#pragma once

namespace {
static AdventureRecords::Loadout runLoadout;

static Object ordinarySeedBank(Word base, Object board) {
    Object bank = native<Object>(base, 0x20bb34, board);
    // Exclude conveyor belts and the other modes with specialized packets.
    return bank && field<Word>(bank, 0) == base + 0x17c00e0 ? bank : nullptr;
}

static Object seedPacket(Word base, Object registry, Object bank, Word slot) {
    alignas(8) WeakRef handle;
    native<void>(base, 0x895f0c, &handle, bank, slot);
    Object packet = native<Object>(base, 0x1da034, registry, &handle);
    native<void>(base, 0x1d9bb4, &handle, 0U, 0U, 0U);
    return packet && field<Word>(packet, 0) == base + 0x17c05f0 ? packet : nullptr;
}

static void captureLoadout(Word base, Object board, Object profile) {
    runLoadout.slots = 0;
    Object bank = ordinarySeedBank(base, board);
    if (!bank) return;
    const Word slots = field<unsigned char>(bank, 0x11d);
    if (!slots || slots > AdventureRecords::maxSlots) return;

    Object registry = native<Object>(base, 0x11d74b4);
    if (!registry) return;
    for (Word slot = 0; slot < slots; ++slot) {
        auto& card = runLoadout.cards[slot];
        card.level = 0;
        Object packet = seedPacket(base, registry, bank, slot);
        if (!packet) continue;
        const auto* handle = reinterpret_cast<const WeakRef*>(packet + 0xf0);
        if (!(handle->id | handle->serial)) continue;
        Object type = native<Object>(base, 0x1da034, registry, handle);
        if (!type) continue;
        const auto& alias = field<const char*>(type, 4);
        if (!alias || !AdventureRecords::validPlantType(alias)) continue;

        // Match the card renderer's two override fields and profile fallback.
        int level = field<int>(packet, 0x138);
        if (level == -1 || field<int>(packet, 0x13c) == -1) {
            level = native<int>(base, 0x717300, profile, &alias, 0U);
        }
        if (level > 4) continue;
        Word i = 0;
        do { card.type[i] = alias[i]; } while (alias[i++]);
        card.level = level > 0 ? Word(level) : 1U;
        runLoadout.slots = slots;
    }
}

static bool populateFormationSeedBank(Word base, Object board, Object bank,
                                      const AdventureRecords::Loadout& loadout) {
    if (!loadout.slots || !bank || ordinarySeedBank(base, board) != bank) return false;
    Object registry = native<Object>(base, 0x11d74b4);
    Object names = field<Object>(reinterpret_cast<Object>(base), 0x183049c);
    if (!registry || !names) return false;

    // Resize the native bank without refreshing it from the viewer's profile.
    native<void>(base, 0x896448, bank, loadout.slots, 1U);
    native<void>(base, 0x8962bc, bank, 1U);
    bool populated = false;
    for (Word slot = 0; slot < loadout.slots; ++slot) {
        Object packet = seedPacket(base, registry, bank, slot);
        if (!packet) continue;
        const auto& card = loadout.cards[slot];
        alignas(8) WeakRef type{0U, 0U};
        if (card.level) {
            const char* alias = nullptr;
            char allocator = 0;
            native<void>(base, 0x14ed0e1, &alias, card.type, &allocator);
            native<void>(base, 0x20cea8, &type, names, &alias);
            native<void>(base, 0x14ebf59, alias - 12, &allocator);
        }
        const bool found = (type.id || type.serial) && native<Object>(base, 0x1da034, registry, &type);
        if (!found) native<void>(base, 0x1d9bb4, &type, 0U, 0U, 0U);
        native<void>(base, 0x8ad824, packet, &type);
        native<void>(base, 0x1d9bb4, &type, 0U, 0U, 0U);
        if (!found) continue;
        field<int>(packet, 0x138) = int(card.level);
        // The independent image variant value 2 selects base plant art.
        // Other override values request the separate costume atlas.
        field<int>(packet, 0x13c) = 2;
        // Use the native pre-battle lock in addition to the Board input guard.
        field<unsigned char>(packet, 0x115) = 1;
        native<void>(base, 0x97a9c8, packet, 2U);
        populated = true;
    }
    return populated;
}
}
