#pragma once

namespace {
constexpr Word socialSettingId = 1060;
constexpr Word socialOffId = 1061;
constexpr Word socialOnId = 1062;
constexpr Word saveBackupId = 1063;
constexpr Word socialSettingMagic = 0x31434f53;
constexpr char socialSettingPath[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-content.bin";
constexpr char socialSettingTemp[] = "/data/data/com.pvz2unline.aster/files/userdataNo_Backup/social-content.tmp";
constexpr char32_t socialSettingLabel[] = U"社交版拓展内容";
static bool socialSettingLoaded;
static bool socialSettingEnabled;
static Object socialSettingsPage;
}

static bool socialContentEnabled(Word base) {
    if (socialSettingLoaded) return socialSettingEnabled;
    socialSettingLoaded = true;
    int fd = native<int>(base, 0x148448, socialSettingPath, 0, 0);
    if (fd < 0) return false;
    Word record[3]{};
    char extra;
    constexpr int recordSize = sizeof(record);
    const int size = native<int>(base, 0x148460, fd, record, recordSize);
    const int tail = size == recordSize ? native<int>(base, 0x148460, fd, &extra, 1U) : -1;
    native<int>(base, 0x147b90, fd);
    socialSettingEnabled = size == recordSize && tail == 0 && record[0] == socialSettingMagic &&
        record[1] == 1U && record[2] == ~1U;
    return socialSettingEnabled;
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
    if (id == socialSettingId) {
        if (field<Object>(page, 0xc0) || field<Word>(page, 0xd4)) return 1;
        socialSettingsPage = page;
        return 2;
    }
    if (socialSettingsPage != page || (id != socialOffId && id != socialOnId)) return 0;
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
    makeText(base, text, socialSettingLabel);
    native<void>(base, 0x14e9b0d, holder + 0xa0, &text);
    freeText(base, text);
    return true;
}

extern "C" bool asterSocialSettingsChoices(Word base, Object scroll, Object description) {
    if (!socialSettingsPage) return false;
    const Word fill = field<Word>(field<Object>(description, 0), 4);
    reinterpret_cast<void(*)(Object)>(fill)(description);
    static constexpr char32_t labels[][2] = {U"否", U"是"};
    const bool enabled = socialContentEnabled(base);
    for (Word i = 0; i < 2; ++i) {
        const char32_t* text = nullptr;
        makeText(base, text, labels[i]);
        Object row = native<Object>(base, 0x8e4edc, socialSettingsPage, socialOffId + i, &text,
                                    Word(enabled == (i == 1)));
        native<void>(base, 0x8e5924, scroll, row);
        freeText(base, text);
    }
    return true;
}
