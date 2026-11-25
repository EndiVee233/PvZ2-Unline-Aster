#pragma once

extern "C" bool asterAdventureLayoutChallengeHud(Word base) {
    const auto app = gameApp(base);
    if (!app) return false;
    const auto bar = formationHud(base, "UITopBar");
    const float scale = field<float>(app, 0x698);
    const int viewport = field<int>(app, 0x524);
    if (!bar || !(scale > 0) || viewport <= 0) return false;

    static constexpr char keys[][25] = {
        "UIChallengeSunCounter", "UIChallengeSunCounter2",
        "UIChallengePlantCounter", "UIChallengePlantCounter2",
        "UIChallengeSunTimer", "UIChallengeZombieCombo",
        "UIChallengePlantFreeze", "UIChallengePlantSurvive",
        "UIChallengeBlowZombie",
    };

    // Fill the right third from right to left, following the stock HUD order.
    // The right edge stays clear of the level title and left-side sun bank.
    const float rowWidth = float(viewport) / 3.0f;
    const float gap = 10.0f * scale;
    float x = -gap;
    float y = 15.0f * scale;
    int rowHeight = 0;
    for (const auto& key : keys) {
        const auto widget = formationHud(base, key);
        if (!widget) continue;
        const int width = field<int>(widget, 0x30);
        const int height = field<int>(widget, 0x34);
        if (rowHeight && -x + width > rowWidth) {
            x = -gap;
            y += rowHeight + gap;
            rowHeight = 0;
        }

        native<void>(base, 0x977b90, widget, bar);
        field<Word>(widget, 0x3c) = 9; // Bottom-right corner of the top bar.
        field<Word>(widget, 0x38) = 3; // Top-right corner of the objective.
        native<void>(base, 0x9766cc, widget, x, y);
        x -= width + gap;
        if (height > rowHeight) rowHeight = height;
    }
    return true;
}
