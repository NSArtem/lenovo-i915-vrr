#!/usr/bin/env python3
"""Build edid-vrr.bin: original EDID plus a 0xFD range descriptor (60-165 Hz).

Linux 7.2 fills drm_display_info.monitor_range only from a base-EDID 0xFD
descriptor with the "range limits only" flag, and only when the EDID is 1.4
and the continuous-frequency feature bit is set (drm_get_monitor_range()).
"""
import sys

FEATURES = 0x18
CONTINUOUS_FREQ = 0x01
SLOT = 0x48  # second 18-byte descriptor, an empty 0x10 dummy in the original

# The two DisplayID type VII timings share pclk 782708 kHz and htotal 2720,
# i.e. hsync ~287.8 kHz; a tight H range keeps DRM from inferring DMT modes.
RANGE = bytes([
    0x00, 0x00, 0x00, 0xFD,
    0x0C,        # offsets: min and max H rate +255 kHz
    60, 165,     # min/max V rate, Hz
    287 - 255,   # min H rate, kHz
    288 - 255,   # max H rate, kHz
    79,          # max pixel clock / 10 MHz (790 MHz)
    0x01,        # range limits only, no GTF/CVT
    0x0A, 0x20, 0x20, 0x20, 0x20, 0x20, 0x20,
])


def main(src, dst):
    edid = bytearray(open(src, "rb").read())
    assert edid[:8] == bytes.fromhex("00ffffffffffff00"), "not an EDID"
    assert edid[0x12:0x14] == b"\x01\x04", "expected EDID 1.4"
    assert edid[SLOT:SLOT + 5] == bytes([0, 0, 0, 0x10, 0]), "slot is not a dummy descriptor"
    assert len(RANGE) == 18

    edid[SLOT:SLOT + 18] = RANGE
    edid[FEATURES] |= CONTINUOUS_FREQ
    edid[127] = -sum(edid[:127]) & 0xFF
    open(dst, "wb").write(edid)


if __name__ == "__main__":
    main(*sys.argv[1:3])
