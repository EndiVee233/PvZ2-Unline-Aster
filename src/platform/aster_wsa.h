#ifndef ASTER_WSA_H
#define ASTER_WSA_H

/* Android build identifiers are ASCII. The expected value is lowercase. */
static inline int aster_wsa_equal(const char *value, const char *expected) {
    if (!value) return 0;
    while (*expected) {
        unsigned char ch = (unsigned char)*value++;
        if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A';
        if (ch != (unsigned char)*expected++) return 0;
    }
    return *value == '\0';
}

static inline int aster_wsa_matches(const char *brand, const char *manufacturer,
                                    const char *model, const char *product,
                                    const char *device) {
    return aster_wsa_equal(brand, "windows") &&
           aster_wsa_equal(manufacturer, "microsoft corporation") &&
           (aster_wsa_equal(model, "subsystem for android(tm)") ||
            (aster_wsa_equal(product, "windows_x86_64") &&
             aster_wsa_equal(device, "windows_x86_64")) ||
            (aster_wsa_equal(product, "windows_arm64") &&
             aster_wsa_equal(device, "windows_arm64")));
}

#ifdef __ANDROID__
#include <sys/system_properties.h>

static inline int aster_is_wsa(void) {
    char brand[PROP_VALUE_MAX] = {0};
    char manufacturer[PROP_VALUE_MAX] = {0};
    char model[PROP_VALUE_MAX] = {0};
    char product[PROP_VALUE_MAX] = {0};
    char device[PROP_VALUE_MAX] = {0};
    __system_property_get("ro.product.brand", brand);
    __system_property_get("ro.product.manufacturer", manufacturer);
    __system_property_get("ro.product.model", model);
    __system_property_get("ro.product.name", product);
    __system_property_get("ro.product.device", device);
    return aster_wsa_matches(brand, manufacturer, model, product, device);
}
#endif

#endif
