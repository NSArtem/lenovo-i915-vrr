# i915 VRR investigation: EDO EF10QBC64.C

Date: 2026-09-14  
Machine timezone: Asia/Yerevan  
Kernel tested: Linux 7.2.5  
Desktop tested: KDE Plasma / KWin 6.7.5, Wayland

## Summary

The internal OLED panel is VRR-capable. The same panel is exposed as
`vrr_capable=1` by `nvidia-drm`, while i915 exposes it as `vrr_capable=0`.

The i915 DPCD `Ignore MSA` test is not the failing condition. The relevant bit
is set. The likely i915 failure is the final refresh-range test: Linux 7.2.5
does not propagate the 60-165 Hz range from the panel's AMD VSDB v3 into
`drm_display_info.monitor_range`, which is the range used by i915.

## Hardware and display topology

- Integrated GPU: Intel Meteor Lake, PCI device `8086:7d67`, driver i915.
- Discrete GPU: NVIDIA GeForce RTX 5070 Laptop GPU, PCI device `10de:2d18`.
- NVIDIA driver tested: 610.57.04 open kernel module.
- Internal panel: EDO `EF10QBC64.C`.
- EDID manufacturer/model: EDO, product ID 16965 (`0x4245`).
- Native resolution: 2560x1600.
- Fixed modes advertised: approximately 60 Hz and 165 Hz.
- Display technology reported by DisplayID: Organic LED.

In hybrid/i915 display mode, eDP is attached to i915 and KDE reports the
output as VRR incapable. In discrete/MUX mode, eDP is attached directly to
NVIDIA. i915 remains loaded and bound to the Intel GPU, but its log says:

```
i915 0000:00:02.0: [drm] [ENCODER:507:DDI A/PHY A] failed to retrieve link info, disabling eDP
```

The active NVIDIA connector is `card1-eDP-1`.

## EDID observations

The full EDID is 384 bytes: base EDID 1.4, CTA-861 extension, and DisplayID
2.0 extension.

The base EDID does not contain a traditional `0xFD` Monitor Range Limits
descriptor. It also does not provide the range through the path currently
used to populate `drm_display_info.monitor_range`.

The CTA extension contains AMD VSDB v3:

```
Vendor-Specific Data Block (AMD), OUI 00-00-1A
Version: 3
Feature Caps: 0x02
Minimum Refresh Rate: 60 Hz
Maximum Refresh Rate: 165 Hz
```

The range is therefore present in the EDID, but encoded only in AMD VSDB v3.
The `Feature Caps` value is noteworthy: bit 0, interpreted by the proposed DRM
AMD-VSDB parser as `freesync_supported`, is clear even though the range is
present and other firmware/transport evidence indicates VRR support.

## VBT observation

The Intel Video BIOS Table was dumped while i915 controlled the display.
`intel_vbt_decode` reported for the relevant panel entries:

```
Panel 2: Variable Refresh Rate (VRR): yes
Panel 3: Variable Refresh Rate (VRR): yes
```

Thus the platform firmware enables VRR for the internal panel.

## DPCD observation and correction

Base receiver capability bytes:

```
14 1e c4 c1 00 00 03 c0 02 00 02 00 08 09 84 00
```

The extended receiver capability copy at DPCD `0x2200` contains the same 16
bytes.

The relevant register is **DPCD offset `0x07`**, not `0x05`:

```
DPCD[0x07] = 0xc0
DP_MSA_TIMING_PAR_IGNORED = BIT(6) = 0x40
0xc0 & 0x40 != 0
```

Therefore `drm_dp_sink_can_do_video_without_timing_msa()` returns true for
this panel. An earlier interpretation that used byte `0x05` was incorrect.

Relevant DRM definitions:

```c
#define DP_DOWN_STREAM_PORT_COUNT 0x007
#define DP_MSA_TIMING_PAR_IGNORED  (1 << 6)

return dpcd[DP_DOWN_STREAM_PORT_COUNT] &
       DP_MSA_TIMING_PAR_IGNORED;
```

The DPCD capability check is therefore not the source of rejection.

## i915 capability path

Linux 7.2.5 uses the following conditions in
`drivers/gpu/drm/i915/display/intel_vrr.c`:

```c
if (!HAS_VRR(display))
        return false;

if (connector_is_edp && !connector->panel.vbt.vrr)
        return false;

if (!drm_dp_sink_can_do_video_without_timing_msa(intel_dp->dpcd))
        return false;

return info->monitor_range.max_vfreq -
       info->monitor_range.min_vfreq > 10;
```

For this panel:

| Condition | Result |
|---|---:|
| Intel platform has VRR hardware | pass |
| VBT enables panel VRR | pass |
| DPCD Ignore MSA bit | pass |
| `monitor_range` contains 60-165 Hz | fail |

Linux 7.2.5 parses some AMD VSDB v3 fields but does not copy its FreeSync
minimum/maximum refresh rates into `monitor_range`. With no traditional range
descriptor, the final i915 range test fails and the connector is published as
`vrr_capable=0`.

## NVIDIA control experiment

After switching the laptop to discrete/MUX mode, NVIDIA directly controlled
the same eDP panel and the same EDID.

DRM/KMS properties reported:

```
Connector: eDP-1
Status: connected
vrr_capable: 1
Modes: 2560x1600@165.00, 2560x1600@60.00
```

KDE/KWin reported:

```
KScreen: Vrr: Automatic
KWin: Adaptive Sync: automatic
Renderer: NVIDIA GeForce RTX 5070 Laptop GPU
Driver: NVIDIA 610.57.04
```

At the idle desktop, the active CRTC property was:

```
VRR_ENABLED = 0
```

This is expected with KWin's `Automatic` policy: capability is exposed, but
VRR is enabled conditionally for eligible content such as a fullscreen game.
The NVIDIA result is strong evidence that the panel itself is VRR-capable and
that the i915 result is a capability-detection issue rather than a KWin issue.

## Upstream-oriented fix direction

The most acceptable architecture is:

1. Parse AMD VSDB FreeSync range in common DRM EDID code, not in i915.
2. Add an i915 eDP fallback that obtains the numeric range from
   `display_info.amd_vsdb` when the normal `monitor_range` is absent.
3. Keep the existing VBT and DPCD checks as independent evidence of eDP VRR
   capability.
4. Use the selected range consistently in `intel_vrr_is_capable()`,
   `intel_vrr_is_in_range()`, and `intel_vrr_compute_vmax()`.

Globally ignoring AMD VSDB's `freesync_supported` bit would be risky. For this
internal eDP case, however, VBT VRR=yes and DPCD Ignore MSA=1 independently
confirm capability; AMD VSDB can be treated only as the source of numeric
range limits. If maintainers reject that general eDP fallback, a narrowly
matched EDID quirk for EDO product `0x4245` is the fallback option.

As of this investigation, a DRM patch series titled
`drm/edid: Parse AMD VSDB FreeSync range in common code` exists, but i915 still
uses `display_info.monitor_range` directly.

## Files and checksums

```
6959011022d689768cab4c9dd63eff4a5d9810c6eae293b2fe0d12c75bdd2f24  edid.bin
5ff11c92fd6f97f04be5150038207fd0a28f5fa1fd2f7cc0a22c9d3eae1847d6  edp-dpcd-base.bin
5ff11c92fd6f97f04be5150038207fd0a28f5fa1fd2f7cc0a22c9d3eae1847d6  edp-dpcd-extended-0x2200.bin
03e18b5a131da5d5fe8ca9b120e219e6bee7206a8f3153f90a3362f977fafc82  i915-vbt.bin
```

The two DPCD files contain 16-byte receiver capability blocks. The extended
file was read starting at DPCD address `0x2200`.
