"""Render Qin's authored road surfaces between native terrain and level events."""

import struct


def float_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def install_road_draw(engine, virtual_delta, hook, surfaces):
    strings = {}

    def label(value):
        return strings.setdefault(value, f"text_{len(strings)}")

    rows = []
    for alias, sprite, x, y, state in surfaces:
        rows.append(f".word {label(alias)}-road_table, {label(sprite)}-road_table, "
                    f"{float_bits(x)}, {float_bits(y)}, {state}")
    literals = "\n".join(f'{name}: .asciz "{value}"' for value, name in strings.items())
    entries = "\n".join(rows)

    # At this draw site the native camera has already set its projection.
    # Preserve the renderer's registers and execute the displaced load on return.
    hook(0xa02dd8, struct.pack("<I", 0xe597120c), f"""
        ldr r1,[r7,#0x20c]
        cmp r1,#0
        bxeq lr
        push {{r0-r12,lr}}
        ldr r0,[r1,#28]
        ldr r2,[r0,#-12]
        cmp r2,#9
        bne finish
        ldr r2,[r0]
        ldr r3,=0x7375616d
        cmp r2,r3
        ldreq r2,[r0,#4]
        ldreq r3,=0x75656c6f
        cmpeq r2,r3
        ldrbeq r2,[r0,#8]
        cmpeq r2,#109
        bne finish

        sub sp,sp,#72
        ldr r7,[r7,#0x238]
        adr r5,store_address
        ldr r0,[r5]
        ldr r0,[r5,r0]
        cmp r0,#0
        beq out
        bl #0x7a98dc
        cmp r0,#0
        beq out
        mov r6,r0
        adr r9,road_table
        mov r5,r9
        ldr r8,={len(surfaces) * 20}
        add r8,r9,r8

    road_loop:
        ldr r11,[r5,#16]
        cmp r11,#2
        beq load_surface
        mov r3,#0
        str r3,[sp,#56]
        str r3,[sp,#64]
        add r0,sp,#56
        ldr r1,[r5]
        add r1,r1,r9
        add r2,sp,#64
        blx #0x14ed0e0
        mov r0,r6
        add r1,sp,#56
        bl #0x708190
        mov r4,r0
        ldr r0,[sp,#56]
        sub r0,r0,#12
        add r1,sp,#64
        blx #0x14ebf58
        cmp r4,r11
        bne next_surface

    load_surface:
        mov r3,#0
        str r3,[sp,#16]
        str r3,[sp,#20]
        str r3,[sp,#24]
        str r3,[sp,#32]
        str r3,[sp,#36]
        ldr r1,[r5,#4]
        add r1,r1,r9
        str r1,[sp,#28]
        add r0,sp,#40
        add r1,sp,#16
        mov r2,#2
        bl #0x7e8a28
        ldr r10,[sp,#44]
        add r0,sp,#32
        mov r2,#0
        mov r3,#0
        bl #0x1d9bb4
        cmp r10,#0
        beq next_surface

        mov r0,r7
        mov r1,r10
        ldr r2,[r5,#8]
        ldr r3,[r5,#12]
        mov r4,#0
        str r4,[sp]
        ldr r4,=0xbf800000
        str r4,[sp,#4]
        str r4,[sp,#8]
        bl #0xa145ec

    next_surface:
        add r5,r5,#20
        cmp r5,r8
        blo road_loop
    out:
        add sp,sp,#72
    finish:
        pop {{r0-r12,pc}}
        .ltorg
    store_address: .word 0x5ab7d9ee
    road_table:
        {entries}
        {literals}
        .align 2
    """, link=True)
    relocation = engine.rindex(struct.pack("<I", 0x5ab7d9ee))
    struct.pack_into("<I", engine, relocation, (0x18300a4 - virtual_delta - relocation) & 0xffffffff)
