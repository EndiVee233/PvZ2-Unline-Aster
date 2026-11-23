#pragma once

namespace {
static bool isFormationBoard(Object board) {
    return board && board == social.board &&
        (social.phase == SocialPhase::Viewing || social.phase == SocialPhase::Returning);
}

static void centerFormationLawn(Word base, Object board) {
    Object app = gameApp(base);
    if (!app) return;
    const float width = float(field<int>(app, 0x524));
    const float scale = field<float>(app, 0x690);
    if (width <= 0 || scale <= 0) return;
    // This origin centers the lawn before the camera applies its world matrix.
    const float lawnWidth = float(field<Word>(board, 0xb4)) * 64.0f * scale;
    field<int>(board, 0x2c) = int((width - lawnWidth) * 0.5f - 200.0f * scale);
}

static void prepareFormationTitle(const char32_t* name, Word elapsedMs) {
    auto* end = append(social.viewTitle, name, 16);
    if (end - social.viewTitle == 16 && name[16]) end = append(end, U"…");
    end = append(end, U"的阵型 - ");
    end = append(number(end, elapsedMs / 60000), U"分");
    end = append(number(end, elapsedMs / 1000 % 60, 2), U"秒 · 战术黄瓜 ");
    if (viewRecord.tacticalCukeUses == AdventureRecords::unknownCukeUses) {
        append(end, U"未记录");
    } else {
        append(number(end, viewRecord.tacticalCukeUses), U"次");
    }
}

static Object formationHud(Word base, const char* key) {
    const char* name = nullptr;
    char allocator = 0;
    native<void>(base, 0x14ed0e1, &name, key, &allocator);
    Object component = native<Object>(base, 0x97714c, &name);
    releaseString(base, name);
    return component;
}

static Object createAdventureHudWidget(Word base, const char32_t* alias) {
    // Resolve the native HUD definition with the same interned-name pair
    // used when the PvP defense phase creates its save button.
    constexpr Word nameRegistry = 0x11e13a8;
    struct HudName { Word id; const char* canonical; };
    Word id = native<Word>(base, 0x11e2ed8, native<Object>(base, nameRegistry), alias);
    if (!id) return nullptr;
    native<void>(base, 0x11e153c, native<Object>(base, nameRegistry), id);
    HudName name{id, native<const char*>(base, 0x11e14cc, native<Object>(base, nameRegistry), id)};
    Object button = native<Object>(base, 0x9781e8, &name, 1U);
    native<void>(base, 0x11e1f08, native<Object>(base, nameRegistry), id);
    return button;
}

static bool showFormationHud(Word base, Object board) {
    Object app = gameApp(base);
    Object button = createAdventureHudWidget(base, U"UIStartGameButton");
    if (!app || !button || !field<Object>(button, 0xf4)) return false;
    social.viewBack = button;

    // Retain the defense editor's label setter, HUD layer and vertical anchor.
    const char32_t* label = nullptr;
    makeText(base, label, U"返回地图");
    native<void>(base, 0x926b48, button, &label);
    freeText(base, label);
    field<Word>(button, 0x54) |= 8;
    const float* anchor = native<const float*>(base, 0x97620c, button);
    const float lift = float(int(field<float>(app, 0x698) * 59.0f));
    native<void>(base, 0x9766cc, button, anchor[0], anchor[1] - lift);
    native<void>(base, 0x9766f4, button, 1U);

    static constexpr char hidden[][24] = {
        "UISeedChooser", "UIShovel", "UISunBank", "UICoinBank",
        "UIGemBank", "UIPlantfood", "UIPowerupHolder", "UIPauseButton",
        "UIChangeSpeedButton", "UIViewBoardOrZombies", "UIProgressBar", "UINextWaveButton"
    };
    for (const auto& key : hidden) {
        Object component = formationHud(base, key);
        if (component) native<void>(base, 0x9766f4, component, 0U);
    }
    native<void>(base, 0x20b3d0, board, 1U);
    field<float>(board, 0x9f8) = 1.0f;
    centerFormationLawn(base, board);
    Object bank = formationHud(base, "UISeedBank");
    social.viewBank = nullptr;
    if (bank) {
        if (populateFormationSeedBank(base, board, bank, viewRecord.loadout)) social.viewBank = bank;
        native<void>(base, 0x9766f4, bank, Word(social.viewBank != nullptr));
    }
    return true;
}
}

extern "C" bool asterAdventureViewSeedBankRefresh(Word base, Object bank) {
    return bank && bank == social.viewBank && isFormationBoard(gameBoard(base));
}

extern "C" void asterAdventureRestoreChooserCards(Word base, Object chooser, Object savedCards) {
    // The hidden chooser can still run its initial update. Its saved cards
    // belong to the viewer and can address slots the preview has removed.
    if (isFormationBoard(gameBoard(base))) return;
    native<void>(base, 0x8a0308, chooser, savedCards);
}

extern "C" void asterAdventureDrawFormationCard(Word base, Object packet, Object graphics, Object art) {
    constexpr Word drawPacket = 0x8ab53c;
    Object bank = social.viewBank;
    if (!bank || !isFormationBoard(gameBoard(base)) ||
        field<Word>(packet, 0x40) != field<Word>(bank, 8) ||
        field<Word>(packet, 0x44) != field<Word>(bank, 12)) {
        native<void>(base, drawPacket, packet, graphics, art);
        return;
    }
    // Present a ready card with its normal cost and tier frame. Only these
    // draw-time values change while the actual packet retains its input lock.
    auto& mode = field<Word>(packet, 0x98);
    auto& flags = field<Word>(packet, 0x10c);
    auto& widgetFlags = field<Word>(packet, 0x54);
    const Word previousMode = mode;
    const Word previousFlags = flags;
    const Word previousWidgetFlags = widgetFlags;
    mode = 2;
    flags = (flags | 17U) & ~(2U | 4U | 8U | 32U | 64U | 256U | 512U);
    widgetFlags |= 4;
    native<void>(base, drawPacket, packet, graphics, art);
    widgetFlags = previousWidgetFlags;
    flags = previousFlags;
    mode = previousMode;
}

static float formationDrawOrigin(Object board, float width, float scale, float zoom, float shift) {
    const float lawnCenter = (200.0f + float(field<Word>(board, 0xb4)) * 32.0f) * scale;
    float origin = (width * 0.5f - shift) / zoom - lawnCenter;

    const int left = field<int>(board, 0x994);
    const int right = field<int>(board, 0x34);
    if (left <= 0 && right > 0) {
        const float minimum = (width - shift) / zoom - float(right);
        const float maximum = -shift / zoom - float(left);
        if (minimum <= maximum) {
            if (origin < minimum) origin = minimum;
            if (origin > maximum) origin = maximum;
        }
    }
    return origin;
}

extern "C" void asterAdventureDrawFormationCamera(Word base, Object board, Object graphics, const float* matrix) {
    constexpr Word drawBoard = 0x235048;
    Object app = graphics && isFormationBoard(board) ? gameApp(base) : nullptr;
    if (!app) {
        native<void>(base, drawBoard, board, graphics);
        return;
    }
    const float width = float(field<int>(app, 0x524));
    const float scale = field<float>(app, 0x690);
    const float zoom = matrix ? matrix[0] : 1.0f;
    const float shift = matrix ? matrix[2] : 0.0f;
    if (!(width > 0.0f && scale > 0.0f && zoom > 0.0f)) {
        native<void>(base, drawBoard, board, graphics);
        return;
    }

    // Change the origin before native image clipping. A device matrix shift
    // alone would move the already clipped view away from the viewport edge.
    auto& drawX = field<float>(graphics, 8);
    auto& boardX = field<int>(board, 0x2c);
    const float priorDrawX = drawX;
    const int priorBoardX = boardX;
    drawX = formationDrawOrigin(board, width, scale, zoom, shift);
    boardX += int(drawX - priorDrawX);
    native<void>(base, drawBoard, board, graphics);
    boardX = priorBoardX;
    drawX = priorDrawX;
}

extern "C" bool asterAdventureUpdateView(Word base, Object board) {
    if (!isFormationBoard(board)) return false;
    if (social.phase == SocialPhase::Viewing && !social.failed && !social.backRequested) {
        centerFormationLawn(base, board);
        native<void>(base, 0x20f4f8, board);
        native<void>(base, 0x9777e0);
    }
    return true;
}

extern "C" void asterAdventureViewButton(Word base, Object dispatcher, Object event, Object button) {
    if (social.phase == SocialPhase::Viewing && button == social.viewBack) {
        social.backRequested = true;
        return;
    }
    native<void>(base, 0x21df78, dispatcher, event);
}

extern "C" bool asterAdventureViewTouch(Word base, Object board, Object cursor, Object event) {
    if (!isFormationBoard(board)) {
        return native<bool>(base, 0x1a2e16c, base, board, cursor, event);
    }
    // Fixed HUD buttons normally receive input from this dispatcher. Give
    // the preview's button its stock press/move/release handling before
    // consuming the event, without dispatching it to the board's tools.
    if (social.phase == SocialPhase::Viewing && social.viewBack && event) {
        native<bool>(base, 0x926b94, social.viewBack, event);
    }
    return true;
}

extern "C" bool asterAdventureSuppressBoardEffects(Word base) {
    Object board = gameBoard(base);
    return isFormationBoard(board) ||
        (board && board == social.board && social.phase == SocialPhase::Loading);
}

extern "C" void asterAdventureTranslateTitle(Word base, const char32_t** output,
                                            const char32_t** input, Object board) {
    if (isFormationBoard(board) && social.viewTitle[0]) {
        makeText(base, *output, social.viewTitle);
        return;
    }
    native<void>(base, 0xd07bb4, output, input);
}
