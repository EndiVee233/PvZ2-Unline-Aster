#pragma once

namespace {
struct ClockRect { int x, y, width, height; };
struct ClockColor { int red, green, blue, alpha; };

struct ArenaClockHud {
    Object board, app;
    const char32_t* label;
    Word shownSeconds;
#ifdef ASTER_SOCIAL_ART
    Object background, face, hour, minute, center;
    Object digits[11];
    bool glyphsReady;
#endif
    int viewportWidth;
    float viewportScale, scale, centerX;
};
static ArenaClockHud arenaClock;

static bool showAdventureClock(Word base, Object board) {
    return sameRun(base, board) && field<Word>(board, 0xc0) == 5 &&
        !field<Word>(board, 0x7f4) &&
        AdventureRecords::formationSupported(field<const char*>(board, 0xc4));
}

static void freeClockLabel(Word base) {
    if (!arenaClock.label) return;
    char allocator = 0;
    native<void>(base, 0x14ea239, arenaClock.label - 3, &allocator);
    arenaClock.label = nullptr;
}

#ifdef ASTER_SOCIAL_LEVELS
static void updateAdventureClockHud(Word base) {
    const auto board = gameBoard(base);
    const auto app = gameApp(base);
    const bool visible = showAdventureClock(base, board);
    if (arenaClock.board && (!visible || arenaClock.board != board || arenaClock.app != app)) {
        freeClockLabel(base);
#ifdef ASTER_SOCIAL_ART
        if (arenaClock.app == app) changeMenuGroup(base, app, 2, false);
        arenaClock.background = arenaClock.face = arenaClock.hour = arenaClock.minute = arenaClock.center = nullptr;
        arenaClock.glyphsReady = false;
#endif
        arenaClock.board = arenaClock.app = nullptr;
        arenaClock.viewportWidth = 0;
    }
    if (!visible || arenaClock.board || !app) return;
#ifdef ASTER_SOCIAL_ART
    if (!field<Object>(reinterpret_cast<Object>(base), 0x183607c)) return;
#endif
    arenaClock.board = board;
    arenaClock.app = app;
    arenaClock.viewportWidth = 0;
#ifdef ASTER_SOCIAL_ART
    changeMenuGroup(base, app, 2, true);
    auto image = [&](const char* key) {
        ButtonSkin skin;
        resolveMenuSkin(base, skin, key, 2U);
        return skin.image;
    };
    arenaClock.background = image("IMAGE_ASTER_SOCIAL_ARENA_CLOCK_BACKGROUND");
    arenaClock.face = image("IMAGE_ASTER_SOCIAL_ARENA_CLOCK_FACE");
    arenaClock.hour = image("IMAGE_ASTER_SOCIAL_ARENA_CLOCK_HOUR");
    arenaClock.minute = image("IMAGE_ASTER_SOCIAL_ARENA_CLOCK_MINUTE");
    arenaClock.center = image("IMAGE_ASTER_SOCIAL_ARENA_CLOCK_CENTER");
    char key[] = "IMAGE_ASTER_SOCIAL_ARENA_CLOCK_DIGIT_00";
    arenaClock.glyphsReady = true;
    for (Word i = 0; i < 11; ++i) {
        key[sizeof(key) - 3] = '0' + i / 10;
        key[sizeof(key) - 2] = '0' + i % 10;
        arenaClock.digits[i] = image(key);
        arenaClock.glyphsReady &= arenaClock.digits[i] != nullptr;
    }
#endif
}
#endif

static void formatClock(Word seconds, char32_t* content) {
    auto* next = content;
    // The Arena HUD formats its whole seconds as "%d:%.2d".
    const Word minutes = seconds / 60;
    if (minutes >= 10) *next++ = U'0' + minutes / 10;
    *next++ = U'0' + minutes % 10;
    *next++ = U':';
    *next++ = U'0' + seconds % 60 / 10;
    *next++ = U'0' + seconds % 10;
    *next = 0;
}

static const char32_t* clockLabel(Word base, Word seconds) {
    if (arenaClock.label && arenaClock.shownSeconds == seconds) return arenaClock.label;
    freeClockLabel(base);
    char32_t content[6];
    formatClock(seconds, content);
    char allocator = 0;
    native<void>(base, 0x14eb451, &arenaClock.label, content, &allocator);
    arenaClock.shownSeconds = seconds;
    return arenaClock.label;
}

static void layoutAdventureClock(Word base, int width, float scale) {
    arenaClock.viewportWidth = width;
    arenaClock.viewportScale = scale;
    arenaClock.scale = scale;
    arenaClock.centerX = float(width) * 0.28f;
#ifdef ASTER_SOCIAL_LEVELS
    const auto sun = formationHud(base, "UISunBank");
    const auto progress = formationHud(base, "UIProgressBar");
    if (!sun || !progress) return;
    ClockRect sunBounds, progressBounds;
    native<void>(base, 0x97636c, &sunBounds, sun);
    native<void>(base, 0x97636c, &progressBounds, progress);
    const int left = sunBounds.x + sunBounds.width;
    const int right = progressBounds.x;
    if (left > 0 && right > left && right < width) {
        arenaClock.centerX = 0.5f * float(left + right);
        const float fit = float(right - left) / 112.0f;
        if (fit < scale) arenaClock.scale = fit;
    }
#else
    (void)base;
#endif
}

#ifdef ASTER_SOCIAL_ART
static void drawClockPiece(Word base, Object graphics, Object image, float scale,
                           float x, float y, float pivotX = 0, float pivotY = 0, float radians = 0) {
    if (!image) return;
    const auto sinf = field<float(*)(float)>(reinterpret_cast<Object>(base), 0x1822a98);
    const auto cosf = field<float(*)(float)>(reinterpret_cast<Object>(base), 0x1822a9c);
    const float s = radians && sinf ? scale * sinf(radians) : 0;
    const float c = radians && cosf ? scale * cosf(radians) : scale;
    const float matrix[] = {
        c, -s, x - c * pivotX + s * pivotY,
        s,  c, y - s * pivotX - c * pivotY,
        0,  0, 1,
    };
    native<void>(base, 0x116a268, graphics, image, matrix);
}

static void drawClockDigits(Word base, Object graphics, Word seconds, float scale,
                            float centerX, float centerY) {
    char32_t text[6];
    formatClock(seconds, text);
    Object glyphs[5];
    Word count = 0;
    int width = 0;
    for (const char32_t* ch = text; *ch; ++ch) {
        const auto glyph = arenaClock.digits[*ch == U':' ? 10 : *ch - U'0'];
        glyphs[count++] = glyph;
        width += field<int>(glyph, 0x28);
    }
    const float fit = width > 106 ? 66.0f * scale / width : 0.62f * scale;
    float x = centerX - width * fit * 0.5f;
    for (Word i = 0; i < count; ++i) {
        const auto glyph = glyphs[i];
        drawClockPiece(base, graphics, glyph, fit, x, centerY, 0, 24.0f);
        x += field<int>(glyph, 0x28) * fit;
    }
}
#endif
}

extern "C" void asterAdventureDrawClock(Word base, Object board, Object graphics) {
    if (!graphics || !showAdventureClock(base, board)) return;
    const auto app = gameApp(base);
    if (!app) return;
    const int width = field<int>(app, 0x524);
    const float scale = field<float>(app, 0x698);
    if (width <= 0 || !(scale > 0)) return;
    if (arenaClock.viewportWidth != width || arenaClock.viewportScale != scale) {
        layoutAdventureClock(base, width, scale);
    }

    constexpr Word lastSecond = AdventureRecords::maxElapsedMs / 1000;
    const Word seconds = current.clock.elapsed < float(lastSecond) ? Word(current.clock.elapsed) : lastSecond;
    const auto previousColor = field<ClockColor>(graphics, 0x4c);
    const auto previousTint = field<unsigned char>(graphics, 0x64);
    const auto previousFont = field<Object>(graphics, 0x5c);
    const float fit = arenaClock.scale;
    const float faceX = arenaClock.centerX - 34.0f * fit - field<float>(graphics, 8);
    const float centerY = 27.0f * scale - field<float>(graphics, 12);
#ifdef ASTER_SOCIAL_ART
    if (arenaClock.background && arenaClock.face && arenaClock.glyphsReady) {
        native<void>(base, 0x1166e74, graphics, false);
        drawClockPiece(base, graphics, arenaClock.background, 0.5f * fit,
                       faceX + 6.0f * fit, centerY - 21.0f * fit);
        constexpr float turn = 6.28318530718f;
        drawClockPiece(base, graphics, arenaClock.face, 0.37f * fit, faceX, centerY, 49.5f, 50.0f);
        drawClockPiece(base, graphics, arenaClock.hour, 0.27f * fit, faceX, centerY, 9.5f, 36.0f,
                       turn * float(seconds % 3600) / 3600.0f);
        drawClockPiece(base, graphics, arenaClock.minute, 0.34f * fit, faceX, centerY, 8.5f, 36.0f,
                       turn * float(seconds % 60) / 60.0f);
        drawClockPiece(base, graphics, arenaClock.center, 0.29f * fit, faceX, centerY, 13.5f, 13.5f);
        drawClockDigits(base, graphics, seconds, fit, faceX + 49.0f * fit, centerY);
    } else
#endif
    {
        const auto family = field<Object>(reinterpret_cast<Object>(base), 0x1842b50);
        if (!family) return;
        const auto wideFont = field<Object>(family, 0x24);
        const auto font = wideFont ? wideFont : field<Object>(family, 0x1c);
        if (!font) return;
        const auto label = clockLabel(base, seconds);
        if (!label) return;
        constexpr ClockColor background{17, 19, 16, 188};
        constexpr ClockColor white{255, 255, 255, 255};
        native<void>(base, 0x1166c30, graphics, &background);
        native<void>(base, 0x1167010, graphics, int(faceX + 7.0f * fit), int(centerY - 17.0f * fit),
                     int(80.0f * fit), int(34.0f * fit));
        const ClockRect text{int(faceX + 18.0f * fit), int(centerY - 18.0f * fit),
                             int(66.0f * fit), int(36.0f * fit)};
        native<void>(base, wideFont ? 0x97335c : 0x973270, graphics, &label, &text, font, &white, 5U, true);
        field<Object>(graphics, 0x5c) = previousFont;
    }
    native<void>(base, 0x1166c30, graphics, &previousColor);
    field<unsigned char>(graphics, 0x64) = previousTint;
}
