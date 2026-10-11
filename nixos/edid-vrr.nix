# NixOS module: EDID override that gives i915 the internal panel's 60-165 Hz VRR range
# (0xFD range descriptor in the base EDID; the stock EDID has it only in AMD VSDB, see README).
{ pkgs, ... }:

let
  name = "edo-ef10qbc64-vrr.bin";
  edid = pkgs.runCommand "edid-edo-ef10qbc64-vrr" { } ''
    install -Dm444 ${../edid-vrr.bin} $out/lib/firmware/edid/${name}
  '';
in
{
  # Sets drm.edid_firmware=eDP-1:edid/<name>. i915 reads the eDP EDID once at connector init,
  # so the override takes effect on the next boot. NVIDIA (MUX mode) does not use it.
  hardware.display.edid.packages = [ edid ];
  hardware.display.outputs."eDP-1".edid = name;

  # The file is looked up when i915 probes the panel; keep it in the initrd too, for early KMS.
  boot.initrd.extraFirmwarePaths = [ "edid/${name}" ];
}
