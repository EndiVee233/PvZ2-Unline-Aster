#include "aster_wsa.h"

int main(void) {
    static const struct {
        const char *brand, *manufacturer, *model, *product, *device;
        int expected;
    } cases[] = {
        /* WSA 2407.40000.4.0 (Android 13) and its architecture-independent model. */
        {"Windows", "Microsoft Corporation", "Subsystem for Android(TM)", "windows_x86_64", "windows_x86_64", 1},
        {"Windows", "Microsoft Corporation", "Subsystem for Android(TM)", 0, 0, 1},
        {"WINDOWS", "MICROSOFT CORPORATION", 0, "WINDOWS_X86_64", "windows_x86_64", 1},
        {"Windows", "Microsoft Corporation", 0, "windows_arm64", "windows_arm64", 1},
        /* The OnePlus row is the system identity in the local MuMu Android 12 image. */
        {"OnePlus", "OnePlus", "IN2025", "OnePlus8Pro", "OnePlus8Pro", 0},
        {"Microsoft", "Microsoft Corporation", "Surface Duo", "duo", "duo", 0},
        {"google", "Google", "Pixel 8", "shiba", "shiba", 0},
        {"Android", "Google", "sdk_gphone64_x86_64", "sdk_gphone64_x86_64", "emu64xa", 0},
        {"google", "Google", "Chromebook", "brya", "brya", 0},
        {"Windows", "Example", "Subsystem for Android(TM)", "windows_x86_64", "windows_x86_64", 0},
        {"OnePlus", "Microsoft Corporation", "Subsystem for Android(TM)", "windows_arm64", "windows_arm64", 0},
        {"Windows phone", "Microsoft Corporation", "Subsystem for Android(TM)", 0, 0, 0},
        {"Windows", "Microsoft Corporation", "Subsystem for Android(TM) test", 0, 0, 0},
        {"Windows", "Microsoft Corporation", 0, "windows_x86_64", "windows_arm64", 0},
        {"Windows", "Microsoft Corporation", 0, "windows_x86_64", "", 0},
        {"Windows", "Microsoft Corporation", 0, "windows_unknown", "windows_unknown", 0},
        {"Window\xc5\xbf", "Microsoft Corporation", "Subsystem for Android(TM)", 0, 0, 0},
        {"", "", "", "", "", 0},
        {0, 0, 0, 0, 0, 0},
    };
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        if (aster_wsa_matches(cases[i].brand, cases[i].manufacturer,
                              cases[i].model, cases[i].product, cases[i].device)
                != cases[i].expected) return (int)i + 1;
    }
    return 0;
}
