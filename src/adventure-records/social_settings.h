#pragma once

namespace {
constexpr Word socialSettingId = 1060;
constexpr Word socialOffId = 1061;
constexpr Word socialOnId = 1062;
constexpr Word saveBackupId = 1063;
constexpr Word difficultyId = 1064;
constexpr Word difficultyFirstId = 1065;
constexpr Word difficultyMagic = 0x31444953;
constexpr char difficultyPath[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-difficulty.bin";
constexpr char difficultyTemp[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-difficulty.tmp";
constexpr char32_t difficultyLabel[] = U"星级挑战难度";
constexpr char32_t difficultyLabels[][3] = {U"简单", U"普通", U"困难"};
constexpr Word socialSettingMagic = 0x31434f53;
constexpr char socialSettingPath[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-content.bin";
constexpr char socialSettingTemp[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-content.tmp";
constexpr char32_t socialSettingLabel[] = U"社交版拓展内容";
static bool socialSettingLoaded;
static bool socialSettingEnabled;
static Object socialSettingsPage;
static bool showingDifficulty;
static bool difficultyLoaded;
static StarDifficulty savedDifficulty;
}

static Word readSocialSetting(Word base, const char* path, Word magic, Word max, Word fallback) {
    int fd = native<int>(base, 0x148448, path, 0, 0);
    if (fd < 0) return fallback;
    Word record[3]{};
    char extra;
    constexpr int recordSize = sizeof(record);
    const int size = native<int>(base, 0x148460, fd, record, recordSize);
    const int tail = size == recordSize ? native<int>(base, 0x148460, fd, &extra, 1U) : -1;
    native<int>(base, 0x147b90, fd);
    return size == recordSize && tail == 0 && record[0] == magic &&
        record[1] <= max && record[2] == ~record[1] ? record[1] : fallback;
}

static bool socialContentEnabled(Word base) {
    if (!socialSettingLoaded) {
        socialSettingEnabled = readSocialSetting(base, socialSettingPath, socialSettingMagic, 1, 0);
        socialSettingLoaded = true;
    }
    return socialSettingEnabled;
}

static StarDifficulty starDifficulty(Word base) {
    if (!difficultyLoaded) {
        constexpr Word hard = Word(StarDifficulty::Hard);
        savedDifficulty = StarDifficulty(readSocialSetting(base, difficultyPath, difficultyMagic, hard, hard));
        difficultyLoaded = true;
    }
    return savedDifficulty;
}

extern "C" void asterSocialSettingsRow(Word base, Object page) {
    Object scroll = field<Object>(page, 0xbc);
    if (!scroll) return;
    Object arrow = native<Object>(base, 0x1dd8f0, reinterpret_cast<Object>(base + 0x1848a98));
    if (!arrow) return;
    const char32_t* text = nullptr;
    makeText(base, text, socialSettingLabel);
    Object row = native<Object>(base, 0x8e4898, page, socialSettingId, &text, arrow);
    native<void>(base, 0x8e5924, scroll, row);
    freeText(base, text);
    if (socialContentEnabled(base) && !gameBoard(base)) {
        char32_t label[24];
        auto* end = append(append(label, difficultyLabel), U" · ");
        append(end, difficultyLabels[Word(starDifficulty(base))]);
        makeText(base, text, label);
        row = native<Object>(base, 0x8e4898, page, difficultyId, &text, arrow);
        native<void>(base, 0x8e5924, scroll, row);
        freeText(base, text);
    }
    if (!gameBoard(base)) {
        makeText(base, text, U"外置存档");
        row = native<Object>(base, 0x8e4898, page, saveBackupId, &text, arrow);
        native<void>(base, 0x8e5924, scroll, row);
        freeText(base, text);
    }
}

extern "C" Word asterSocialSettingsClick(Word base, Object page, Word id) {
    if (id <= 1 && socialSettingsPage == page) socialSettingsPage = nullptr;
    if (id == saveBackupId) {
        if (!gameBoard(base)) {
            const SocialMessage request{0, 0, 1, 8};
            writeBytes(base, &request, sizeof(request), dialogFile, dialogTemp);
        }
        return 1;
    }
    if (id == socialSettingId || id == difficultyId) {
        if (field<Object>(page, 0xc0) || field<Word>(page, 0xd4)) return 1;
        if (id == difficultyId && (!socialContentEnabled(base) || gameBoard(base))) return 1;
        showingDifficulty = id == difficultyId;
        socialSettingsPage = page;
        return 2;
    }
    if (socialSettingsPage != page) return 0;
    if (showingDifficulty) {
        if (id < difficultyFirstId || id > difficultyFirstId + Word(StarDifficulty::Hard)) return 0;
        const Word choice = id - difficultyFirstId;
        if (choice != Word(starDifficulty(base))) {
            const Word record[] = {difficultyMagic, choice, ~choice};
            if (writeBytes(base, record, sizeof(record), difficultyPath, difficultyTemp))
                savedDifficulty = StarDifficulty(choice);
        }
        native<void>(base, 0x8e7820, page);
        return 1;
    }
    if (id != socialOffId && id != socialOnId) return 0;
    const bool enabled = id == socialOnId;
    if (enabled != socialContentEnabled(base)) {
        const Word record[] = {socialSettingMagic, Word(enabled), ~Word(enabled)};
        if (writeBytes(base, record, sizeof(record), socialSettingPath, socialSettingTemp)) {
            socialSettingEnabled = enabled;
        }
    }
    native<void>(base, 0x8e7820, page);
    return 1;
}

extern "C" bool asterSocialSettingsTitle(Word base, Object holder) {
    if (!socialSettingsPage) return false;
    const char32_t* text = nullptr;
    makeText(base, text, showingDifficulty ? difficultyLabel : socialSettingLabel);
    native<void>(base, 0x14e9b0d, holder + 0xa0, &text);
    freeText(base, text);
    return true;
}

extern "C" bool asterSocialSettingsChoices(Word base, Object scroll, Object description) {
    if (!socialSettingsPage) return false;
    const Word fill = field<Word>(field<Object>(description, 0), 4);
    reinterpret_cast<void(*)(Object)>(fill)(description);
    static constexpr char32_t labels[][2] = {U"否", U"是"};
    const Word selected = showingDifficulty ? Word(starDifficulty(base)) : Word(socialContentEnabled(base));
    for (Word i = 0; i < (showingDifficulty ? 3U : 2U); ++i) {
        const char32_t* text = nullptr;
        makeText(base, text, showingDifficulty ? difficultyLabels[i] : labels[i]);
        Object row = native<Object>(base, 0x8e4edc, socialSettingsPage,
                                    (showingDifficulty ? difficultyFirstId : socialOffId) + i, &text,
                                    Word(selected == i));
        native<void>(base, 0x8e5924, scroll, row);
        freeText(base, text);
    }
    return true;
}
