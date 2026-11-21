#pragma once

namespace {
static bool isFormationBoard(Object board) {
    return board && board == social.board &&
        (social.phase == SocialPhase::Viewing || social.phase == SocialPhase::Returning);
}

static void prepareFormationTitle(const char32_t* name, Word elapsedMs) {
    auto* end = append(social.viewTitle, name, 39);
    end = append(end, U"的阵型 - ");
    end = append(number(end, elapsedMs / 60000), U"分");
    append(number(end, elapsedMs / 1000 % 60, 2), U"秒");
}

static Object formationHud(Word base, const char* key) {
    const char* name = nullptr;
    char allocator = 0;
    native<void>(base, 0x14ed0e1, &name, key, &allocator);
    Object component = native<Object>(base, 0x97714c, &name);
    releaseString(base, name);
    return component;
}

static Object createFormationBackButton(Word base) {
    // Resolve the native HUD definition with the same interned-name pair
    // used when the PvP defense phase creates its save button.
    constexpr Word nameRegistry = 0x11e13a8;
    struct HudName { Word id; const char* canonical; };
    Word id = native<Word>(base, 0x11e2ed8, native<Object>(base, nameRegistry), U"UIStartGameButton");
    if (!id) return nullptr;
    native<void>(base, 0x11e153c, native<Object>(base, nameRegistry), id);
    HudName name{id, native<const char*>(base, 0x11e14cc, native<Object>(base, nameRegistry), id)};
    Object button = native<Object>(base, 0x9781e8, &name, 1U);
    native<void>(base, 0x11e1f08, native<Object>(base, nameRegistry), id);
    return button;
}

static bool showFormationHud(Word base, Object board) {
    Object app = gameApp(base);
    Object button = createFormationBackButton(base);
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
        "UISeedBank", "UISeedChooser", "UIShovel", "UISunBank", "UICoinBank",
        "UIGemBank", "UIPlantfood", "UIPowerupHolder", "UIPauseButton",
        "UIChangeSpeedButton", "UIViewBoardOrZombies", "UIProgressBar", "UINextWaveButton"
    };
    for (const auto& key : hidden) {
        Object component = formationHud(base, key);
        if (component) native<void>(base, 0x9766f4, component, 0U);
    }
    native<void>(base, 0x20b3d0, board, 1U);
    field<float>(board, 0x9f8) = 1.0f;
    return true;
}
}

extern "C" bool asterAdventureUpdateView(Word base, Object board) {
    if (!isFormationBoard(board)) return false;
    if (social.phase == SocialPhase::Viewing && !social.failed && !social.backRequested) {
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

extern "C" bool asterAdventureSuppressMessages(Word base) {
    return isFormationBoard(gameBoard(base));
}

extern "C" void asterAdventureTranslateTitle(Word base, const char32_t** output,
                                            const char32_t** input, Object board) {
    if (isFormationBoard(board) && social.viewTitle[0]) {
        makeText(base, *output, social.viewTitle);
        return;
    }
    native<void>(base, 0xd07bb4, output, input);
}
