#pragma once

namespace {
constexpr Word friendAvatarCount = 6;
constexpr Word communityAvatarCount = 12;
constexpr Word unknownFriendAvatar = ~0U;
static constexpr char communityAvatarKeys[communityAvatarCount][40] = {
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_1", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_2",
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_3", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_4",
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_5", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_6",
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_7", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_8",
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_9", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_10",
    "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_11", "IMAGE_ASTER_SOCIAL_CN_USER_AVATAR_12"
};
static constexpr char friendAvatarKeys[friendAvatarCount][36] = {
#ifdef ASTER_SOCIAL_ART
    "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_1", "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_2",
    "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_3", "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_4",
    "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_5", "IMAGE_ASTER_SOCIAL_ARENA_AVATAR_6",
#else
    "IMAGE_UI_PACKETS_SUNFLOWER", "IMAGE_UI_PACKETS_PEASHOOTER",
    "IMAGE_UI_PACKETS_WALLNUT", "IMAGE_UI_PACKETS_BONKCHOY",
    "IMAGE_UI_PACKETS_CABBAGEPULT", "IMAGE_UI_PACKETS_REPEATER",
#endif
};

static Word friendAvatarIndex(Word owner, Word id) {
    // Use the same owner-seeded ordering across social pages.
    Word seed = owner;
    Word order[friendAvatarCount] = {0, 1, 2, 3, 4, 5};
    for (Word i = friendAvatarCount - 1; i > 0; --i) {
        seed = 1664525U * seed + 1013904223U;
        const Word j = ((seed >> 16) * (i + 1)) >> 16;
        const Word saved = order[j];
        order[j] = order[i];
        order[i] = saved;
    }
    return order[(id - 1) % friendAvatarCount];
}

static bool validFriendAvatar(Word avatar) {
    return avatar < communityAvatarCount || avatar == unknownFriendAvatar;
}

}
