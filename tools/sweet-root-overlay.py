#!/usr/bin/env python3
"""Put back, on a fresh SWEET iOS root, everything the davinci (Mi 9T) phone got on top of
tools/mkiosroot.sh + tools/sweet-root-tweaks.py: the "mod image" inject steps of 2026-10-20/21 and
every file, plist edit and dyld-cache patch pushed to the running phone up to 2026-10-25.

  sudo sweet-root-overlay.py [--dry-run] [--base DIR] [--only G,..] [--skip G,..]
                             [--accept-changed] [--no-chown] [--reference-launchd PLIST] MOUNTED_ROOT

MOUNTED_ROOT is the root made by build_root.sh (HFS+ mounted rw, after sweet-root-tweaks.py).
Idempotent: every step checks what is there first. --dry-run only reports (no root needed).
Source files come from the PC tree under --base (default /home/marnov/xmiphones); each one carries
the sha256 (first 16 hex) of the copy that is on the phone, so a rebuilt source is refused unless
--accept-changed.

Groups (all on by default):
  gl      GLES/CA stack in backboardd: Mesa libs, libredwood-gl, metalshim + the two re-exec shims,
          kgsl_test, sweet_push + hello_gl          (inject_gltest.sh / inject_kgsltest.sh + pushes)
  metal   RedwoodMetal.bundle (Metal plug-in for IOAcceleratorES "sgx", kernel 0146 + sweetmetal=1)
          and libredwoodair.dylib
  launchd xpc/launchd.plist jobs (shims for backboardd/SpringBoard/mediaserverd, com.sweet.push/gltest/kgsltest),
          the standalone com.apple.backboardd.plist, launchd disabled.plist (vmd, axassetsd)
  flags   /usr/local/gltest switch files read by metalshim / eagl / RedwoodMetal / the kernel
  apps    staged system apps -> /Applications (metal/stageapps.c), MetalDemo.app
  dyld    shared-cache patches (checked against the original bytes before writing)
  tools   on-phone dev tools in /usr/local/gltest (rmv, rfindt, lsreg, mtl*, vk*, ...)
  legacy  old flat GLES layout copies in /usr/local/gltest (still on the phone, unused)
  assets  Vulkan-era SPIR-V test inputs and the modem firmware blobs in /usr/local/gltest

NOT done here (user/runtime state, see the end of this file): LaunchServices DB rebuilds and
csstore renames, SplashBoard / chrono snapshot moves, PosterBoard store renames, MCM containers
made by mkcont, lsreg/extreg registrations (lsd registers /Applications on first boot by itself),
anything pushed to /tmp. Kernel-side pieces (IOAcceleratorES service, boot-args) are in the boot image.
"""
import argparse, hashlib, os, plistlib, shutil, struct, sys

# ---------------------------------------------------------------------------------------------
# Files: (group, path in root, source under --base, mode, sha256[:16] of the copy on the phone)
# Owner is root:wheel for all (sweet_push and the inject scripts ran as root).
# Provenance: device pull 2026-10-24 (scratchpad devcopy/, dev_usrlocal.txt) + the push log in the
# Claude session transcripts (push_file.py / push.sh, last push per path).
FILES = [
    ('launchd', 'usr/local/gltest/sweettime', 'davinci-ios/gpu/userland/metal/sweettime', 0o755, '12ffbb8fc9df4a7a'),  # 2026-10-26: time of day = RTC (kern.sweet_rtc, 0162) + kept offset (job com.sweet.time)
    ('launchd', 'usr/local/lib/libsweet-media.dylib', 'davinci-ios/camera/userland/libsweet-media.dylib', 0o755, 'da63efefb143ea7a'),  # 2026-10-28: mediaserverd camera (sweetcam=5; frames only on the graph's Start, no boot-probe pop-up), camera/userland/build.sh
    ('launchd', 'usr/local/lib/sweet_media_shim', 'davinci-ios/camera/userland/sweet_media_shim', 0o755, '9c48829ed46d8fb5'),  # 2026-10-26: mediaserverd ProgramArguments[0]; inserts libsweet-media (execs without it if missing)
    ('launchd', 'usr/local/gltest/scset', 'davinci-ios/gpu/userland/metal/scset', 0o755, 'a838fc11ea8053b7'),  # 2026-10-25: publishes Plugin:InterfaceNamer *QUIET* at boot (job com.sweet.scquiet)
    ('assets', 'usr/local/gltest/inplace_copy_lpf.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/inplace_copy_lpf.fragment.spv', 0o644, '05f9adab013b54c8'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/inplace_copy_lph.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/inplace_copy_lph.fragment.spv', 0o644, '05f9adab013b54c8'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/pushtest.txt', 'backup/ios-root-sources-20261025/phone-only/pushtest.txt', 0o644, '27418b83376d15a3'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/tile_downsample_1.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/tile_downsample_1.fragment.spv', 0o644, '8f6128a7136ecfc6'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/tile_downsample_2.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/tile_downsample_2.fragment.spv', 0o644, '5921a7fd1c52d2a4'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/tile_downsample_2_w025.kernel.spv', 'backup/ios-root-sources-20261025/phone-only/tile_downsample_2_w025.kernel.spv', 0o644, '10a5b0e5aaff1dd5'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/tile_downsample_4.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/tile_downsample_4.fragment.spv', 0o644, '45d10b7b2f2cfeab'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/tile_downsample_8.fragment.spv', 'backup/ios-root-sources-20261025/phone-only/tile_downsample_8.fragment.spv', 0o644, 'ae987ed63ce8e24e'),  # only on the phone; pulled 2026-10-25
    ('assets', 'usr/local/gltest/vkq_w.txt', 'backup/ios-root-sources-20261025/phone-only/vkq_w.txt', 0o644, 'a30a043314fa8929'),  # only on the phone; pulled 2026-10-25
    ('gl', 'usr/local/lib/libEGL.1.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libEGL.1.dylib', 0o644, '6e5e8e49257a5899'),  # inject_gltest.sh (mod image 10-21); = device copy 10-24
    ('gl', 'usr/local/lib/libGLESv2.2.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libGLESv2.2.dylib', 0o644, 'd998cf48af611b95'),  # inject_gltest.sh; = device copy 10-24
    ('gl', 'usr/local/lib/libglapi.0.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libglapi.0.dylib', 0o644, 'c2c5647d9ea258ab'),  # inject_gltest.sh; = device copy 10-24
    ('gl', 'usr/local/lib/libgallium-24.2.8.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libgallium-24.2.8.dylib', 0o755, 'e003f1637d005ddf'),  # push 2026-10-25 00:01Z (build-fdgl, sweet stats + restore->sysmem)
    ('gl', 'usr/local/lib/msm_dri.so', 'davinci-ios/gpu/userland/mesa/gltest/libgallium-24.2.8.dylib.bak-nofetchbarrier', 0o644, 'd2de82901800515e'),  # device copy 10-24 == this .bak (legacy, unused by eagl)
    ('gl', 'usr/local/lib/libredwood-gl.dylib', 'davinci-ios/gpu/hackios-port/obj/libredwood-gl.dylib', 0o755, '4baa16b92f671bac'),  # 2026-10-27 eagl.c: planar surfaces (camera preview) refilled when they change
    ('gl', 'usr/local/lib/metalshim.dylib', 'davinci-ios/gpu/userland/metal/metalshim.dylib.device-20261024', 0o755, '28b8318855cef160'),  # push 2026-10-23 23:48Z (metalshim_vbl); == device copy 10-24. NOT metal/metalshim.dylib (older)
    ('gl', 'usr/local/lib/sweet_shim', 'davinci-ios/gpu/userland/metal/sweet_shim', 0o755, 'f2c858d06ebb141c'),  # push 10-22; SpringBoard ProgramArguments[0]; == device copy
    ('gl', 'usr/libexec/backboardd_shim', 'davinci-ios/gpu/userland/metal/bbd_shim', 0o755, '9232fe0e6b48628b'),  # push 10-21 17:18Z; backboardd ProgramArguments[0]
    ('gl', 'usr/libexec/kgsl_test', 'davinci-ios/gpu/userland/kgsl_test', 0o755, 'c6092232e0eb561f'),  # inject_kgsltest.sh (mod image); job com.sweet.kgsltest
    ('gl', 'usr/local/gltest/sweet_push', 'davinci-ios/gpu/userland/push/sweet_push', 0o755, '3674708eb0015123'),  # inject_gltest.sh + push 10-23; job com.sweet.push. MUST be 0755
    ('gl', 'usr/local/gltest/hello_gl', 'davinci-ios/gpu/userland/mesa/gltest/hello_gl', 0o755, '57d864c7ecb5f3e3'),  # inject_gltest.sh; job com.sweet.gltest (disabled)
    ('gl', 'usr/local/lib/libvulkan_freedreno.dylib', 'davinci-ios/gpu/userland/mesa/build-tu/src/freedreno/vulkan/libvulkan_freedreno.dylib', 0o755, 'a47aa312aa44dcf6'),  # push 10-21 (turnip, Vulkan era); == device copy
    # (usr/local/lib/logshim: pushed 10-24, no longer on the phone 2026-10-25 -- left out)
    ('metal', 'System/Library/Extensions/RedwoodMetal.bundle/RedwoodMetal', 'davinci-ios/gpu/userland/metal/redwood/RedwoodMetal', 0o755, '2b1b52e2bb095405'),  # 10-28: backboardd switch file, GLES IR -> AIR via libGLVMPlugin, setProvokingVertexMode:, views = the texture, unanswered-selector net, allowlist names with spaces
    ('metal', 'System/Library/Extensions/RedwoodMetal.bundle/Info.plist', 'davinci-ios/gpu/userland/metal/redwood/metal_plugin.plist', 0o644, '96f6896e6e1137cb'),  # push 10-25 06:32Z
    ('metal', 'usr/local/lib/libredwoodair.dylib', 'davinci-ios/gpu/userland/metal/redwood/libredwoodair.dylib', 0o755, 'c17463da45713130'),  # 10-28: buffer address space from the pointer type when the metadata has none (GLES IR modules)
    ('apps', 'Applications/MetalDemo.app/MetalDemo', 'davinci-ios/gpu/userland/metal/demoapp/MetalDemo', 0o755, 'f34277acc0078ae5'),  # push 10-25 07:53Z (signed with demoapp/ents.plist)
    ('apps', 'Applications/MetalDemo.app/Info.plist', 'davinci-ios/gpu/userland/metal/demoapp/Info.plist', 0o644, '1dc8e501ab0ac4b1'),  # push 10-25 07:53Z
    ('apps', 'Applications/MetalDemo.app/AppIcon60x60@2x.png', 'davinci-ios/gpu/userland/metal/demoapp/AppIcon60x60@2x.png', 0o644, '2aa4673331efbbb0'),  # push 10-25 07:53Z
    ('apps', 'Applications/MetalDemo.app/AppIcon60x60@3x.png', 'davinci-ios/gpu/userland/metal/demoapp/AppIcon60x60@3x.png', 0o644, 'dc855d78b615fb70'),  # push 10-25 07:53Z
    ('tools', 'usr/local/gltest/rmv', 'davinci-ios/gpu/userland/metal/rmv', 0o755, '1ee7f44554816f75'),  # dev tool push
    ('tools', 'usr/local/gltest/rls', 'davinci-ios/gpu/userland/metal/rls', 0o755, '42ca52506ca5344f'),  # dev tool push
    ('tools', 'usr/local/gltest/rfindt', 'davinci-ios/gpu/userland/metal/rfindt', 0o755, 'aa21d0015ee140c5'),  # dev tool push
    ('tools', 'usr/local/gltest/extq', 'davinci-ios/gpu/userland/metal/extq', 0o755, 'e6c88878bfdae3cc'),  # dev tool push
    ('tools', 'usr/local/gltest/extreg', 'davinci-ios/gpu/userland/metal/extreg', 0o755, 'dc413e174557cfc4'),  # dev tool push
    ('tools', 'usr/local/gltest/lsinfo', 'davinci-ios/gpu/userland/metal/lsinfo', 0o755, '5b8e61d9ad9c1e31'),  # dev tool push
    ('tools', 'usr/local/gltest/framegrab', 'davinci-ios/gpu/userland/metal/framegrab', 0o755, '6c3a789dd8c550dd'),  # dev tool push
    ('tools', 'usr/local/gltest/lsreg', 'davinci-ios/gpu/userland/metal/lsreg', 0o755, '14b845cfdc860b82'),  # dev tool push
    ('tools', 'usr/local/gltest/mkcont', 'davinci-ios/gpu/userland/metal/mkcont', 0o755, '229a43ee9957bdde'),  # dev tool push
    ('tools', 'usr/local/gltest/widgetreload', 'davinci-ios/gpu/userland/metal/widgetreload', 0o755, 'cfa2ba80496a388b'),  # dev tool push
    ('tools', 'usr/local/gltest/vmstat', 'davinci-ios/gpu/userland/metal/vmstat', 0o755, '700dbd58a8ae1953'),  # dev tool push
    ('tools', 'usr/local/gltest/metalmps', 'davinci-ios/gpu/userland/metal/metalmps', 0o755, '9499c52d9b8a5742'),  # dev tool push
    ('tools', 'usr/local/gltest/metaltex', 'davinci-ios/gpu/userland/metal/metaltex', 0o755, 'a4d9f7cfc22c7159'),  # dev tool push
    ('tools', 'usr/local/gltest/metaltest', 'davinci-ios/gpu/userland/metal/metaltest', 0o755, '8ebaab27e2801a0f'),  # dev tool push
    ('tools', 'usr/local/gltest/mtlprobe', 'davinci-ios/gpu/userland/metal/mtlprobe', 0o755, '9f0aee9272cf6032'),  # dev tool push
    ('tools', 'usr/local/gltest/fbfill', 'davinci-ios/gpu/userland/metal/fbfill', 0o755, 'd56c56ad3ab60f1f'),  # dev tool push
    ('tools', 'usr/local/gltest/pmwake', 'davinci-ios/gpu/userland/metal/pmwake', 0o755, 'dd0c1b84bcb82852'),  # dev tool push
    ('tools', 'usr/local/gltest/kgsl_present_test', 'davinci-ios/gpu/userland/metal/kgsl_present_test', 0o755, '7c057c711fb9c81a'),  # dev tool push
    ('tools', 'usr/local/gltest/vkcompute', 'davinci-ios/gpu/userland/metal/vkcompute', 0o755, '895c80453de0217a'),  # dev tool push
    ('tools', 'usr/local/gltest/vkinput', 'davinci-ios/gpu/userland/metal/vkinput', 0o755, 'd21753fe8506a037'),  # dev tool push
    ('tools', 'usr/local/gltest/vkpanel', 'davinci-ios/gpu/userland/metal/vkpanel', 0o755, '26a9d5bc15f44781'),  # dev tool push
    ('tools', 'usr/local/gltest/vkquad', 'davinci-ios/gpu/userland/metal/vkquad', 0o755, '79aae24ac524d0a7'),  # dev tool push
    ('tools', 'usr/local/gltest/vkrender', 'davinci-ios/gpu/userland/metal/vkrender', 0o755, '28c433b3d24bf2ec'),  # dev tool push
    ('tools', 'usr/local/gltest/vksurf', 'davinci-ios/gpu/userland/metal/vksurf', 0o755, '766c01b7c8d0a4cd'),  # dev tool push
    ('tools', 'usr/local/gltest/vktest', 'davinci-ios/gpu/userland/metal/vktest', 0o755, '96c9726068e79863'),  # dev tool push
    ('tools', 'usr/local/gltest/vktile', 'davinci-ios/gpu/userland/metal/vktile', 0o755, 'c744d3a90c7274a6'),  # dev tool push
    ('tools', 'usr/local/gltest/rmv.bin', 'davinci-ios/gpu/userland/metal/rmv', 0o644, '1ee7f44554816f75'),  # push 10-24 (copy of rmv, mode 0644)
    ('tools', 'usr/local/gltest/metal_test', 'davinci-ios/gpu/userland/metal/redwood/metal_test', 0o755, 'e56fad3619fdf29f'),  # Metal test push 10-25
    ('tools', 'usr/local/gltest/mtltry', 'davinci-ios/gpu/userland/metal/redwood/mtltry', 0o755, '5b857e0dcb0beacf'),  # Metal test push 10-25
    ('tools', 'usr/local/gltest/mtlcompute', 'davinci-ios/gpu/userland/metal/redwood/mtlcompute', 0o755, '72d4d6a73dc9915d'),  # Metal test push 10-25
    ('tools', 'usr/local/gltest/mtlrender', 'davinci-ios/gpu/userland/metal/redwood/mtlrender', 0o755, 'ffdf43bfb19f170c'),  # Metal test push 10-25
    ('tools', 'usr/local/gltest/mtldrawable', 'davinci-ios/gpu/userland/metal/redwood/mtldrawable', 0o755, '3c2090af17572d37'),  # Metal test push 10-25
    ('legacy', 'usr/local/gltest/libEGL.1.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libEGL.1.dylib', 0o644, '6e5e8e49257a5899'),  # legacy flat GLES layout; == device copy 10-24
    ('legacy', 'usr/local/gltest/libGLESv2.2.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libGLESv2.2.dylib', 0o644, 'd998cf48af611b95'),  # legacy flat GLES layout; == device copy 10-24
    ('legacy', 'usr/local/gltest/libglapi.0.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libglapi.0.dylib', 0o644, 'c2c5647d9ea258ab'),  # legacy flat GLES layout; == device copy 10-24
    ('legacy', 'usr/local/gltest/libgallium-24.2.8.dylib', 'davinci-ios/gpu/userland/mesa/gltest/libgallium-24.2.8.dylib.bak-nofetchbarrier', 0o644, 'd2de82901800515e'),  # legacy flat GLES layout; == device copy 10-24
    ('legacy', 'usr/local/gltest/msm_dri.so', 'davinci-ios/gpu/userland/mesa/gltest/libgallium-24.2.8.dylib.bak-nofetchbarrier', 0o644, 'd2de82901800515e'),  # legacy flat GLES layout; == device copy 10-24
    ('assets', 'usr/local/gltest/alpha_linear_premultiply_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/alpha_linear_premultiply_lpf.compute.spv', 0o644, '36604ebbdf4dd8d8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/alpha_linear_premultiply_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/alpha_linear_premultiply_lpf.fragment.spv', 0o644, '945b26aafd6b8c39'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/alpha_linear_premultiply_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/alpha_linear_premultiply_lph.fragment.spv', 0o644, 'a3fab1f8fc169399'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/alpha_threshold_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/alpha_threshold_lpf.compute.spv', 0o644, 'c34f0a2e31705353'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/alpha_threshold_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/alpha_threshold_lpf.fragment.spv', 0o644, '55ba7a044b428042'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/alpha_threshold_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/alpha_threshold_lph.fragment.spv', 0o644, '6fa12989c6f2ed38'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/apply_apl_dimming_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/apply_apl_dimming_lpf.fragment.spv', 0o644, '2c64321cf4f2b0e4'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/apply_apl_dimming_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/apply_apl_dimming_lph.fragment.spv', 0o644, 'b25ca5286ab52a9a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_50_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_50_frag_lpf.fragment.spv', 0o644, 'aaa65b978a220863'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_50_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_50_frag_lph.fragment.spv', 0o644, 'e0f12930f845e121'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_75_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_75_frag_lpf.fragment.spv', 0o644, 'f6d5e56dcb7fb8d9'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_75_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_75_frag_lph.fragment.spv', 0o644, '5d7065053da692d4'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_frag_lpf.fragment.spv', 0o644, '4d5a73918b3b56fb'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/asg_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/asg_frag_lph.fragment.spv', 0o644, '0dac1373c2519214'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/attachment_clear_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/attachment_clear_frag_lpf.fragment.spv', 0o644, 'a6c12808143fcfa7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/attachment_clear_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/attachment_clear_frag_lph.fragment.spv', 0o644, 'a6c12808143fcfa7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/axial_shading_frag_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/axial_shading_frag_lpf.compute.spv', 0o644, '5414318b041c14ce'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/axial_shading_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/axial_shading_frag_lpf.fragment.spv', 0o644, '131f68ec93992c99'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/axial_shading_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/axial_shading_frag_lph.fragment.spv', 0o644, '8c7ec9267efbc9bf'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_frag_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_frag_lpf.compute.spv', 0o644, 'd7719d397f2e7ae7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_frag_lpf.fragment.spv', 0o644, '8ded7949b48a1e1a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_frag_lph.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_frag_lph.compute.spv', 0o644, 'd7719d397f2e7ae7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_frag_lph.fragment.spv', 0o644, '8ded7949b48a1e1a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_vert_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_vert_lpf.compute.spv', 0o644, '3aee85b0eeda1fce'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_vert_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_vert_lpf.fragment.spv', 0o644, '2ee8afe989df1d35'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_vert_lph.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_vert_lph.compute.spv', 0o644, '437e3119d8d406e8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/buffer_image_blit_vert_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/buffer_image_blit_vert_lph.fragment.spv', 0o644, '02d129a939875870'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/compute_apl.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/compute_apl.kernel.spv', 0o644, '19a376c457cbf63d'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/compute_apl_fast.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/compute_apl_fast.kernel.spv', 0o644, '0ab613a55570a4e4'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/conic_shading_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/conic_shading_frag_lpf.fragment.spv', 0o644, '9f341a70e571015c'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/conic_shading_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/conic_shading_frag_lph.fragment.spv', 0o644, '9efa01e988921520'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_linearize_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/display_overdrive_linearize_lpf.compute.spv', 0o644, '17950ae507e1c4b3'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_linearize_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/display_overdrive_linearize_lpf.fragment.spv', 0o644, 'cc3b10d01508104e'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_linearize_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/display_overdrive_linearize_lph.fragment.spv', 0o644, 'e12ecd80c92a1de6'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_lut_gen_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/display_overdrive_lut_gen_lpf.fragment.spv', 0o644, '0f796eb0d0b380fc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_lut_gen_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/display_overdrive_lut_gen_lph.fragment.spv', 0o644, '0f796eb0d0b380fc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_srgb_sampler_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/display_overdrive_srgb_sampler_lpf.fragment.spv', 0o644, 'cc3b10d01508104e'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/display_overdrive_srgb_sampler_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/display_overdrive_srgb_sampler_lph.fragment.spv', 0o644, 'e12ecd80c92a1de6'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_4_frag_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/downsample_4_frag_lpf.compute.spv', 0o644, '9b66a86696caf6e1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_4_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/downsample_4_frag_lpf.fragment.spv', 0o644, '0044d1cf27c37203'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_4_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_4_frag_lph.fragment.spv', 0o644, '48f40e3b71098029'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_6_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_6_frag_lpf.fragment.spv', 0o644, 'a2283378796409d2'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_6_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_6_frag_lph.fragment.spv', 0o644, 'a2283378796409d2'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_8_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_8_frag_lpf.fragment.spv', 0o644, 'd8e3a1bbd2bebf51'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_8_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_8_frag_lph.fragment.spv', 0o644, 'fe10bb5f0fb39afc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_blur_2_frag_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/downsample_blur_2_frag_lpf.compute.spv', 0o644, '75330b96a1d62fc0'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_blur_2_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/downsample_blur_2_frag_lpf.fragment.spv', 0o644, '2a01bb53d79b3ee1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_blur_2_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_blur_2_frag_lph.fragment.spv', 0o644, '2a01bb53d79b3ee1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_blur_4_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_blur_4_frag_lpf.fragment.spv', 0o644, 'adc124442cf832f3'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/downsample_blur_4_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/downsample_blur_4_frag_lph.fragment.spv', 0o644, '2bec7341b36397d7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/edr_scale_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/edr_scale_lpf.fragment.spv', 0o644, 'aa0cf44aae6b7740'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/edr_scale_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/edr_scale_lph.fragment.spv', 0o644, 'b1cde361df11cb40'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/fixed_frag_lph_cpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/fixed_frag_lph_cpf.fragment.spv', 0o644, '21b6a484a6ad5c3c'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/fixed_frag_lph_cph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/fixed_frag_lph_cph.fragment.spv', 0o644, '3b9ed39abc4e308a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/harmony_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/harmony_lpf.fragment.spv', 0o644, 'f62864c9b31aa780'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/harmony_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/harmony_lph.fragment.spv', 0o644, 'e1ef6d43cd332805'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/home_affordance_base_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/home_affordance_base_lpf.fragment.spv', 0o644, '67a90e305ebb2b5b'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/home_affordance_base_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/home_affordance_base_lph.fragment.spv', 0o644, '837aa9f7abcd7b99'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/inplace_copy_lpf.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/inplace_copy_lpf.kernel.spv', 0o644, 'f117a10025db4e81'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/inplace_copy_lph.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/inplace_copy_lph.kernel.spv', 0o644, 'f117a10025db4e81'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/luma_boost_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/luma_boost_lpf.fragment.spv', 0o644, 'b883c2f3ca5f4deb'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/luma_boost_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/luma_boost_lph.fragment.spv', 0o644, 'dedb8efc92712c87'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_11_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_11_frag_lpf.fragment.spv', 0o644, 'b691484b1a7b0b45'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_11_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_11_frag_lph.fragment.spv', 0o644, '14aa52e1415e89c3'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_15_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_15_frag_lpf.fragment.spv', 0o644, 'fbc468e132786e47'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_15_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_15_frag_lph.fragment.spv', 0o644, '1c36844be136ee58'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_19_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_19_frag_lpf.fragment.spv', 0o644, '7eb6ffcfce251414'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_19_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_19_frag_lph.fragment.spv', 0o644, '1481e0894e9cc3ce'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_23_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_23_frag_lpf.fragment.spv', 0o644, '361a09caa51764e1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_23_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_23_frag_lph.fragment.spv', 0o644, 'ecdd19f3abf746b8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_27_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_27_frag_lpf.fragment.spv', 0o644, '310dd3af959f3709'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_27_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_27_frag_lph.fragment.spv', 0o644, 'c0e1c98379c3c5c7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_7_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_7_frag_lpf.fragment.spv', 0o644, '0a6e1e8c9ad47426'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/narrow_blur_7_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/narrow_blur_7_frag_lph.fragment.spv', 0o644, 'dd14a8ae6d2b4f8a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/p3_clamp_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/p3_clamp_lpf.fragment.spv', 0o644, 'ceca63eb8492eb69'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/p3_clamp_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/p3_clamp_lph.fragment.spv', 0o644, 'c3465024730806b7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_blit_frag_eo_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_blit_frag_eo_lpf.fragment.spv', 0o644, '8d45aa91d25489e7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_blit_frag_eo_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_blit_frag_eo_lph.fragment.spv', 0o644, '381b488656a9955f'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_blit_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_blit_frag_lpf.fragment.spv', 0o644, '22fca62ab1e273b3'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_blit_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_blit_frag_lph.fragment.spv', 0o644, '683a516e835ee353'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_clear_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_clear_frag_lpf.fragment.spv', 0o644, 'a6c12808143fcfa7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_clear_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_clear_frag_lph.fragment.spv', 0o644, 'a6c12808143fcfa7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_cubic_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_cubic_frag_lpf.fragment.spv', 0o644, 'fae2ef1cfa3fc0a1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_cubic_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_cubic_frag_lph.fragment.spv', 0o644, 'fae2ef1cfa3fc0a1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_rect_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_rect_frag_lpf.fragment.spv', 0o644, '6d9b1b8ce8bc2719'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_rect_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_rect_frag_lph.fragment.spv', 0o644, '6d9b1b8ce8bc2719'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_curve_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_curve_frag_lpf.fragment.spv', 0o644, '6c7a47881f5f70a8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_curve_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_curve_frag_lph.fragment.spv', 0o644, '6c7a47881f5f70a8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_line_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_line_frag_lpf.fragment.spv', 0o644, 'bfb6ae87c09e30d7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_line_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_line_frag_lph.fragment.spv', 0o644, 'bfb6ae87c09e30d7'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_miter_join_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_miter_join_frag_lpf.fragment.spv', 0o644, '58be4aa29b8f1eae'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_miter_join_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_miter_join_frag_lph.fragment.spv', 0o644, '58be4aa29b8f1eae'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_round_join_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_round_join_frag_lpf.fragment.spv', 0o644, '1c9fab15bc7f23bc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/path_stroke_round_join_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/path_stroke_round_join_frag_lph.fragment.spv', 0o644, '1c9fab15bc7f23bc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/quad_vert.spv', 'davinci-ios/gpu/userland/metal/air_work/quad_vert.spv', 0o644, '47d4ee544b91044e'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/radial_complex_shading_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/radial_complex_shading_frag_lpf.fragment.spv', 0o644, '9086509cb7be6e2d'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/radial_complex_shading_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/radial_complex_shading_frag_lph.fragment.spv', 0o644, '1dd0a9bc7ea294c9'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/radial_shading_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/radial_shading_frag_lpf.fragment.spv', 0o644, '0eaf32e3bbbbc89a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/radial_shading_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/radial_shading_frag_lph.fragment.spv', 0o644, '61059c6f8b9604a6'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/read_surf_frag.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/read_surf_frag.fragment.spv', 0o644, 'af0493421fc2012e'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/single_pass_blur_3_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/single_pass_blur_3_lpf.fragment.spv', 0o644, '8aa9be258f6a35df'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/single_pass_blur_3_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/single_pass_blur_3_lph.fragment.spv', 0o644, '1c9f671a70e82047'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/std_vert0_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/std_vert0_lpf.compute.spv', 0o644, 'd911f1c4b44b56e9'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/std_vert0_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/std_vert0_lpf.fragment.spv', 0o644, 'e8ee8cfc2f76ba09'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/std_vert1_lpf.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/std_vert1_lpf.compute.spv', 0o644, 'dadddab754be8810'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/std_vert1_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_core/std_vert1_lpf.fragment.spv', 0o644, '9fe5e276ee6fac5a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/stroke_line_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/stroke_line_frag_lpf.fragment.spv', 0o644, '6373bd98046d95b8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/stroke_line_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/stroke_line_frag_lph.fragment.spv', 0o644, '6373bd98046d95b8'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/sum_apl_and_compute_dimming_factor.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/sum_apl_and_compute_dimming_factor.kernel.spv', 0o644, '6129557590663807'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/tile_downsample_1.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/tile_downsample_1.kernel.spv', 0o644, '2e8b50b942f2e427'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/tile_downsample_2.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/tile_downsample_2.kernel.spv', 0o644, 'dfbc194073bd0e5e'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/tile_downsample_4.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/tile_downsample_4.kernel.spv', 0o644, 'e8d301ae8d77195a'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/tile_downsample_8.kernel.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/tile_downsample_8.kernel.spv', 0o644, 'ecb2a5a43d4543dc'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/upsample_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/upsample_frag_lpf.fragment.spv', 0o644, 'fbbc7991c42004c0'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/upsample_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/upsample_frag_lph.fragment.spv', 0o644, '504bdb7c15ee19b1'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/variable_blur_downsample_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/variable_blur_downsample_frag_lpf.fragment.spv', 0o644, '37ef2e74a929acd2'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/variable_blur_downsample_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/variable_blur_downsample_frag_lph.fragment.spv', 0o644, 'c62a879c5dec8eef'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/variable_blur_frag_lpf.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/variable_blur_frag_lpf.fragment.spv', 0o644, '6bb16889572e50c5'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/variable_blur_frag_lph.fragment.spv', 'davinci-ios/gpu/userland/metal/air_work/spv_named/variable_blur_frag_lph.fragment.spv', 0o644, '6bb16889572e50c5'),  # Vulkan-era SPIR-V test input
    ('assets', 'usr/local/gltest/VALIDATION_path_blit.compute.spv', 'davinci-ios/gpu/userland/metal/air_work/VALIDATION_path_blit_frag_eo_lpf.compute.spv', 0o644, 'f9501f5b86cecc1c'),  # push 10-21
    ('assets', 'usr/local/gltest/subpass_read.frag.spv', 'davinci-ios/gpu/userland/metal/subpass_read.frag.spv', 0o644, '4c3c6fa7dccb9147'),  # push 10-21
    ('assets', 'usr/local/gltest/modem.b00', 'davinci-ios/fw-wifi/modem.b00', 0o644, 'e456be7686144bdd'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b01', 'davinci-ios/fw-wifi/modem.b01', 0o644, 'dde2dd059359d094'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b02', 'davinci-ios/fw-wifi/modem.b02', 0o644, '559d535e55552ec7'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b03', 'davinci-ios/fw-wifi/modem.b03', 0o644, '99f31ddd43d6cfd3'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b04', 'davinci-ios/fw-wifi/modem.b04', 0o644, 'b61dc9b11a29ab1a'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b05', 'davinci-ios/fw-wifi/modem.b05', 0o644, 'd099cc6653143040'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b06', 'davinci-ios/fw-wifi/modem.b06', 0o644, 'b03cbeef358ccbe2'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b07', 'davinci-ios/fw-wifi/modem.b07', 0o644, 'd8d57f4703663cb1'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b08', 'davinci-ios/fw-wifi/modem.b08', 0o644, '99a33299352c187e'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b09', 'davinci-ios/fw-wifi/modem.b09', 0o644, '75ef96f3ed705212'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b10', 'davinci-ios/fw-wifi/modem.b10', 0o644, '97944253fd23f1d2'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b11', 'davinci-ios/fw-wifi/modem.b11', 0o644, '4eed46773d4eeb5c'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b12', 'davinci-ios/fw-wifi/modem.b12', 0o644, '6c697d8e7e22e72d'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b14', 'davinci-ios/fw-wifi/modem.b14', 0o644, 'b7de02dad947996e'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b15', 'davinci-ios/fw-wifi/modem.b15', 0o644, '45a7d85bebf0f6a8'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b16', 'davinci-ios/fw-wifi/modem.b16', 0o644, '85576779e745853f'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b17', 'davinci-ios/fw-wifi/modem.b17', 0o644, 'fb9381e2f1fdf260'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b18', 'davinci-ios/fw-wifi/modem.b18', 0o644, '7e4dc7ea0016d37d'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b19', 'davinci-ios/fw-wifi/modem.b19', 0o644, '1dc2e6de21d2fc66'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b21', 'davinci-ios/fw-wifi/modem.b21', 0o644, 'f73b13ebf4061f2e'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b22', 'davinci-ios/fw-wifi/modem.b22', 0o644, 'a77372b44d034017'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b23', 'davinci-ios/fw-wifi/modem.b23', 0o644, '3a594bb3be5ad630'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b24', 'davinci-ios/fw-wifi/modem.b24', 0o644, '185be16517781990'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b25', 'davinci-ios/fw-wifi/modem.b25', 0o644, '6b12bd1e7ef338f0'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b26', 'davinci-ios/fw-wifi/modem.b26', 0o644, 'c3bc3bb87e8a7119'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b27', 'davinci-ios/fw-wifi/modem.b27', 0o644, '95612409f41db4ef'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b28', 'davinci-ios/fw-wifi/modem.b28', 0o644, '0240d910b6c0639c'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.b29', 'davinci-ios/fw-wifi/modem.b29', 0o644, 'd3a604282a7b9f60'),  # modem fw push 10-23 (WiFi plan)
    ('assets', 'usr/local/gltest/modem.mdt', 'davinci-ios/fw-wifi/modem.mdt', 0o644, '4c35a784ce0fe7ca'),  # modem fw push 10-23 (WiFi plan)
]

# ---------------------------------------------------------------------------------------------
# Switch files in /usr/local/gltest. eagl/redwood-gl/RedwoodMetal test "exists and size > 0",
# metalshim tests "exists". Values = last state pushed (2026-10-25); None = must NOT exist.
FLAGS = {
    # metalshim.m: in backboardd, dlopen libredwood-gl (CA -> freedreno GLES). ESSENTIAL.
    'ca_gles': b'1',
    # RedwoodMetal allowlist (backboardd only via the metal_backboardd switch file, not installed here)
    'metal_allow': b'metal_test\nmtltry\nmtlcompute\nmtlrender\nmtldrawable\nMetalDemo\nMobileNotes\nPreferences\n',  # 10-26: Notes (PencilKit), Settings (CoreImage icons; with metal_profile=1)
    # kernel 0115 (sweetcpufreq=1): CPU/L3/GPU clock rows (devtools/clocks.sh); all max
    'clocks': b'l3=10 little=9 big=12 gpu=0\n',
    # eagl: environment for backboardd's Mesa; shader cache dir MUST be writable by uid 501
    'gl_env': b'MESA_SHADER_CACHE_DIR=/var/tmp/mesa_shader_cache\n',
    # eagl worker_priority(): disabled (gl_no_worker_prio non-empty), gl_worker_prio then unused
    'gl_no_worker_prio': b'1\n', 'gl_no_worker_prio.off': None, 'gl_worker_prio': b'54\n',
    # eagl rt ring ON: the flag was renamed away (rmv, 2026-10-25 08:26Z)
    'gl_no_rt_ring': None, 'gl_no_rt_ring.off': b'1\n',
    # eagl timeline lines + slow-call log, as last set for bench/measure (07:43Z); empty both = quiet
    'gl_timeline': b'1\n', 'gl_timeline.off': b'1\n', 'gl_slow': b'1000\n',
    'gl_flush_mode': b'0\n', 'gl_skip_class': b'0\n', 'gl_trace_now': b'2\n',
    # present but empty = off (0-byte files on the phone 2026-10-24)
    'gl_release_flush': b'', 'gl_no_dirty': b'', 'fd_sysmem': b'', 'gl_teximage_as_sub': b'',
    # metalshim Vulkan-era switches that exist on the phone (vkcap: log-only capture in shimmed procs)
    'vkcap': b'1', 'vkupload': b'1', 'vkq_nodraw': b'0', 'backboardd': b'x',   # as on the phone 2026-10-25
}

# launchd: the three jobs exactly as in the phone's launchd.plist (davinci-ios/launchd.plist.device-20261024.bak)
SWEET_JOBS = {
    '/System/Library/LaunchDaemons/com.sweet.time.plist': {  # 2026-10-26: the PMIC RTC free-runs; sweettime keeps the offset
        'EnablePressuredExit': False, 'EnableTransactions': False, 'KeepAlive': True, 'Label': 'com.sweet.time',
        'POSIXSpawnType': 'Interactive', 'ProcessType': 'Interactive', 'ProgramArguments': ['/usr/local/gltest/sweettime'],
        'RunAtLoad': True, 'StandardErrorPath': '/dev/console', 'StandardOutPath': '/dev/console'},
    '/System/Library/LaunchDaemons/com.sweet.scquiet.plist': {  # 2026-10-25: configd's InterfaceNamer never publishes here (no en0); SCNetworkInterfaceCopyAll waited forever (Settings > About)
        'EnablePressuredExit': False, 'EnableTransactions': False, 'KeepAlive': False, 'Label': 'com.sweet.scquiet',
        'LaunchOnlyOnce': True, 'POSIXSpawnType': 'Interactive', 'ProcessType': 'Interactive',
        'ProgramArguments': ['/usr/local/gltest/scset'], 'RunAtLoad': True},
    '/System/Library/LaunchDaemons/com.sweet.push.plist': {  # inject_gltest.sh: USB-net file daemon :5566
        'EnablePressuredExit': False, 'EnableTransactions': False, 'KeepAlive': True,
        'Label': 'com.sweet.push', 'POSIXSpawnType': 'Interactive', 'ProcessType': 'Interactive',
        'ProgramArguments': ['/usr/local/gltest/sweet_push'], 'RunAtLoad': True,
        'StandardErrorPath': '/dev/console', 'StandardOutPath': '/dev/console'},
    '/System/Library/LaunchDaemons/com.sweet.gltest.plist': {  # inject_gltest.sh, later disabled on the phone
        'Disabled': True, 'EnablePressuredExit': False, 'EnableTransactions': False,
        'EnvironmentVariables': {'EGL_LOG_LEVEL': 'debug', 'EGL_PLATFORM': 'surfaceless', 'GALLIUM_DRIVER': 'msm',
                                 'LIBGL_DEBUG': 'verbose', 'LIBGL_DRIVERS_PATH': '/usr/local/lib', 'MESA_DEBUG': '1',
                                 'MESA_LOADER_DRIVER_OVERRIDE': 'msm'},
        'KeepAlive': {'Crashed': True}, 'Label': 'com.sweet.gltest', 'POSIXSpawnType': 'Interactive',
        'ProcessType': 'Interactive', 'ProgramArguments': ['/usr/local/gltest/hello_gl'], 'RunAtLoad': False,
        'StandardErrorPath': '/dev/console', 'StandardOutPath': '/dev/console'},
    '/System/Library/LaunchDaemons/com.sweet.kgsltest.plist': {  # inject_kgsltest.sh (still runs at boot)
        'EnablePressuredExit': False, 'EnableTransactions': False, 'KeepAlive': {'Crashed': True},
        'Label': 'com.sweet.kgsltest', 'POSIXSpawnType': 'Interactive', 'ProcessType': 'Interactive',
        'ProgramArguments': ['/usr/libexec/kgsl_test'], 'RunAtLoad': True,
        'StandardErrorPath': '/dev/console', 'StandardOutPath': '/dev/console'},
}
BBD_KEY = '/System/Library/LaunchDaemons/com.apple.backboardd.plist'
SB_KEY = '/System/Library/LaunchDaemons/com.apple.SpringBoard.plist'
BBD_SHIM, SWEET_SHIM = '/usr/libexec/backboardd_shim', '/usr/local/lib/sweet_shim'
METALSHIM = '/usr/local/lib/metalshim.dylib'
MS_KEY, MEDIA_SHIM = '/System/Library/LaunchDaemons/com.apple.mediaserverd.plist', '/usr/local/lib/sweet_media_shim'

# launchd's disabled.plist as on the phone after 2026-10-25 (launchd's own first-boot entries + ours)
DISABLED = {
    'com.apple.bootpd': True, 'com.apple.dhcp6d': True, 'com.apple.ftp-proxy-embedded': False,
    'com.apple.magicswitchd.companion': True, 'com.apple.relevanced': True, 'com.apple.security.otpaird': True,
    'com.apple.voicemail.vmd': True,            # vmd XPC-retry flood (no CommCenter), 2026-10-25
    'com.apple.accessibility.axassetsd': True,  # speech plug-ins crash ~18x/boot, 2026-10-25
    'com.apple.fairplayd.H2': True,             # exits at once, never reads its port: every sync FairPlay call
                                                # (lockdownd, checkpointd -> Notes, Photos) hung forever, 2026-10-26
}
OURS_DISABLED = {k: DISABLED[k] for k in ('com.apple.voicemail.vmd', 'com.apple.accessibility.axassetsd',
                                          'com.apple.fairplayd.H2')}

# dyld shared cache (iOS 16.7.x 20H392 iPhone10,3). VA unslid; file offset checked against the mapping.
DYLD_DIRS = ['System/Library/Caches/com.apple.dyld',
             'private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld']
DYLD_PATCHES = [
    # SpringBoard: +[SBFolderView countOfAdditionalPagesToKeepVisibleInOneDirection] mov x0,#0 -> #1
    # (home-screen widget re-entry hitch), metal/cpatch 2026-10-25 11:02Z
    ('dyld_shared_cache_arm64.21', 0x1c53dcfc0, 0x268cfc0, '000080d2', '200080d2', 'patch'),
    # Metal: MTLCreateSystemDefaultDevice must be Apple's prologue. The phone had a nil trampoline
    # (pushed dsc_arm64.01.redirect, 2026-10-21) that metal/cachefix put back to these bytes
    # 2026-10-25 06:46Z. A fresh IPSW cache already has them: check, and restore only the trampoline.
    ('dyld_shared_cache_arm64.01', 0x181a37760, 0x19db760,
     'f0962db0100244f9500000b400021fd6000080d2c0035fd6',
     'ff0302d1f44f06a9fd7b07a9fdc30191881a30f008c544f9', 'restore'),
]

STAGED, APPS = 'private/var/staged_system_apps', 'Applications'
GROUPS = ['gl', 'metal', 'launchd', 'flags', 'apps', 'dyld', 'tools', 'legacy', 'assets']


class Overlay:
    def __init__(self, a):
        self.root, self.base, self.dry, self.a = a.root, a.base, a.dry_run, a
        self.errors, self.done = [], 0

    def say(self, *m):
        print(('[dry] ' if self.dry else '') + ' '.join(str(x) for x in m))

    def p(self, rel):
        return os.path.join(self.root, rel)

    def mkdirs(self, rel):
        parts = rel.strip('/').split('/')
        for i in range(1, len(parts) + 1):
            d = self.p('/'.join(parts[:i]))
            if not os.path.isdir(d):
                self.say('mkdir', '/' + '/'.join(parts[:i]))
                if not self.dry:
                    os.mkdir(d, 0o755)
                    self.own(d, 0o755)

    def own(self, path, mode, uid=0, gid=0):
        if not self.a.no_chown:
            os.chown(path, uid, gid)
        os.chmod(path, mode)

    def put(self, rel, data, mode, uid=0, gid=0):
        """Write bytes atomically if content/mode/owner differ."""
        path = self.p(rel)
        if os.path.isfile(path):
            st = os.stat(path)
            same_owner = self.a.no_chown or (st.st_uid, st.st_gid) == (uid, gid)
            if open(path, 'rb').read() == data and (st.st_mode & 0o7777) == mode and same_owner:
                return
        self.say('write', '/' + rel, f'({len(data)} bytes, {mode:o})')
        self.done += 1
        if self.dry:
            return
        self.mkdirs(os.path.dirname(rel))
        tmp = path + '.overlay-tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        self.own(tmp, mode, uid, gid)
        os.replace(tmp, path)

    def remove(self, rel):
        if os.path.lexists(self.p(rel)):
            self.say('remove', '/' + rel)
            self.done += 1
            if not self.dry:
                os.unlink(self.p(rel))

    # -- groups --------------------------------------------------------------------------------
    def files(self, group):
        for g, rel, src, mode, sha in FILES:
            if g != group:
                continue
            s = os.path.join(self.base, src)
            if not os.path.isfile(s):
                self.errors.append(f'missing source {s} for /{rel}')
                continue
            data = open(s, 'rb').read()
            h = hashlib.sha256(data).hexdigest()[:16]
            if h != sha and not self.a.accept_changed:
                self.errors.append(f'/{rel}: source {src} changed (sha {h}, phone has {sha}); --accept-changed to use it')
                continue
            self.put(rel, data, mode)

    def g_flags(self):
        for name, val in FLAGS.items():
            rel = 'usr/local/gltest/' + name
            if val is None:
                self.remove(rel)
            else:
                self.put(rel, val, 0o644)

    def g_launchd(self):
        # 1. the launchd job cache
        rel = 'System/Library/xpc/launchd.plist'
        path = self.p(rel)
        st = os.stat(path)
        raw = open(path, 'rb').read()
        d = plistlib.loads(raw)
        jobs = d['LaunchDaemons']
        bbd = jobs[BBD_KEY]
        # backboardd: launchd strips DYLD_* so the env alone does nothing; bbd_shim re-execs with
        # DYLD_INSERT_LIBRARIES=metalshim (push 10-21 17:18Z, xpc_launchd_fixed.plist)
        bbd['ProgramArguments'] = [BBD_SHIM]
        bbd.setdefault('EnvironmentVariables', {})['DYLD_INSERT_LIBRARIES'] = METALSHIM
        # SpringBoard: generic sweet_shim in front (metal/patch-launchd-inject.py, push 10-22 03:52Z)
        sb = jobs[SB_KEY]
        pa = sb.get('ProgramArguments') or [sb['Program']]
        if pa[0] != SWEET_SHIM:
            sb['ProgramArguments'] = [SWEET_SHIM] + pa
        sb.pop('Program', None)
        # mediaserverd: sweet_media_shim in front (camera/userland, libsweet-media.dylib = the camera, sweetcam=5)
        ms = jobs[MS_KEY]
        pa = ms.get('ProgramArguments') or [ms['Program']]
        if pa[0] != MEDIA_SHIM:
            ms['ProgramArguments'] = [MEDIA_SHIM] + pa
        ms.pop('Program', None)
        for k, job in SWEET_JOBS.items():
            for other in [o for o, j in jobs.items() if o != k and isinstance(j, dict) and j.get('Label') == job['Label']]:
                del jobs[other]
            jobs[k] = job
        new = plistlib.dumps(d, fmt=plistlib.FMT_BINARY)
        if plistlib.loads(new) != plistlib.loads(raw):
            self.say('edit', '/' + rel, '(backboardd + SpringBoard + mediaserverd shims, com.sweet.{push,gltest,kgsltest})')
            self.put(rel, new, st.st_mode & 0o7777, st.st_uid, st.st_gid)
        if self.a.reference_launchd:
            ref = plistlib.load(open(self.a.reference_launchd, 'rb'))['LaunchDaemons']
            mine = plistlib.loads(new)['LaunchDaemons']
            diff = sorted(k for k in set(ref) | set(mine) if ref.get(k) != mine.get(k))
            print(f'reference launchd.plist: {len(diff)} jobs differ' + (': ' + ', '.join(diff[:20]) if diff else ''))
        # 2. the standalone plist (not read by launchd here; edited on the phone too, bbd_fixed2.plist)
        rel = BBD_KEY.lstrip('/')
        st = os.stat(self.p(rel))
        raw = open(self.p(rel), 'rb').read()
        j = plistlib.loads(raw)
        j['ProgramArguments'] = [BBD_SHIM]
        j.setdefault('EnvironmentVariables', {})['DYLD_INSERT_LIBRARIES'] = METALSHIM
        if j != plistlib.loads(raw):
            self.put(rel, plistlib.dumps(j, fmt=plistlib.FMT_BINARY), st.st_mode & 0o7777, st.st_uid, st.st_gid)
        # 3. launchd's disabled jobs (pushed 2026-10-25 08:39Z/08:44Z as XML)
        rel = 'private/var/db/com.apple.xpc.launchd/disabled.plist'
        cur = plistlib.load(open(self.p(rel), 'rb')) if os.path.isfile(self.p(rel)) else {}
        want = dict(DISABLED)
        want.update({k: v for k, v in cur.items() if k not in OURS_DISABLED})  # keep launchd's own
        want.update(OURS_DISABLED)
        if want != cur or not os.path.isfile(self.p(rel)):
            self.put(rel, plistlib.dumps(want), 0o644)

    def g_apps(self):
        # metal/stageapps.c (run on the phone 2026-10-22 23:53Z, moved all 32): what HackiOS
        # select-system.py does at image build; first-boot setup that normally installs them is skipped
        src = self.p(STAGED)
        if os.path.isdir(src):
            for n in sorted(os.listdir(src)):
                if not n.endswith('.app'):
                    continue
                if os.path.lexists(self.p(f'{APPS}/{n}')):
                    self.say(f'skip staged {n} (already in /Applications)')
                    continue
                self.say('move', f'/{STAGED}/{n} -> /{APPS}/{n}')
                self.done += 1
                if not self.dry:
                    os.rename(os.path.join(src, n), self.p(f'{APPS}/{n}'))
        self.mkdirs('Applications/MetalDemo.app')
        # Foundation's item-replacement directory for a not-yet-existing URL in an app container walks up to
        # Containers/Data and mkdirs tmp there as mobile: root-owned, EACCES, and Notes' drawing died in a
        # Coherence try! (2026-10-26, found with kernel 0152 sweettrace=MobileNotes)
        rel = 'private/var/mobile/Containers/Data/tmp'
        if os.path.isdir(self.p('private/var/mobile/Containers/Data')) and not os.path.isdir(self.p(rel)):
            self.say('mkdir', '/' + rel, '(501:501 755)')
            self.done += 1
            if not self.dry:
                os.mkdir(self.p(rel), 0o755)
                self.own(self.p(rel), 0o755, 501, 501)
        self.files('apps')

    def g_dyld(self):
        seen = set()
        for name, va, off, orig, new, kind in DYLD_PATCHES:
            o, n = bytes.fromhex(orig), bytes.fromhex(new)
            for dd in DYLD_DIRS:
                path = self.p(f'{dd}/{name}')
                if not os.path.isfile(path):
                    self.errors.append(f'dyld: {path} missing')
                    continue
                ino = os.stat(path).st_ino
                with open(path, 'rb') as f:
                    hdr = f.read(0x200)
                    if hdr[:7] != b'dyld_v1':
                        self.errors.append(f'dyld: {path} is not a shared cache')
                        continue
                    moff, mcnt = struct.unpack_from('<II', hdr, 0x10)
                    fo = None
                    for i in range(mcnt):
                        f.seek(moff + 32 * i)
                        addr, size, foff = struct.unpack('<QQQ', f.read(24))
                        if addr <= va and va + len(o) <= addr + size:
                            fo = foff + (va - addr)
                    if fo != off:
                        self.errors.append(f'dyld: {name} VA {va:#x} maps to {fo}, expected {off:#x}: different cache?')
                        continue
                    f.seek(off)
                    cur = f.read(len(o))
                rel = path[len(self.root):]
                # both kinds: n is what must end up there, o the only bytes we may overwrite
                # ('patch': o = Apple's; 'restore': o = our old trampoline, n = Apple's)
                if cur == n:
                    print(f'dyld {rel} @{off:#x}: already {"patched" if kind == "patch" else "Apple bytes"}')
                    continue
                if cur != o:
                    self.errors.append(f'dyld {rel} @{off:#x}: unexpected bytes {cur.hex()} -- left alone')
                    continue
                if ino in seen:          # hard link already written through the other path
                    continue
                seen.add(ino)
                self.say(f'dyld {rel} @{off:#x}: {cur.hex()} -> {n.hex()}')
                self.done += 1
                if not self.dry:
                    with open(path, 'r+b') as f:   # in place: keeps the OS-root/cryptex hard link
                        f.seek(off)
                        f.write(n)

    def run(self, groups):
        for g in groups:
            print(f'== {g}')
            if g == 'flags':
                self.g_flags()
            elif g == 'launchd':
                self.g_launchd()
            elif g == 'apps':
                self.g_apps()
            elif g == 'dyld':
                self.g_dyld()
            else:
                self.files(g)
        print(f'{self.done} change(s) {"would be made" if self.dry else "made"}')
        for e in self.errors:
            print('ERROR:', e, file=sys.stderr)
        return 1 if self.errors else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('root')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--base', default='/home/marnov/xmiphones')
    ap.add_argument('--only', default='')
    ap.add_argument('--skip', default='')
    ap.add_argument('--accept-changed', action='store_true', help='install sources whose sha differs from the phone copy')
    ap.add_argument('--no-chown', action='store_true', help='testing on a scratch tree as a normal user')
    ap.add_argument('--reference-launchd', help='compare the edited launchd.plist with this one (e.g. launchd.plist.device-20261024.bak)')
    a = ap.parse_args()
    if not os.path.isdir(os.path.join(a.root, 'System/Library/xpc')):
        sys.exit(f'{a.root}: not an iOS root')
    if not a.dry_run and not a.no_chown and os.geteuid() != 0:
        sys.exit('run as root (or --dry-run)')
    groups = [g for g in (a.only.split(',') if a.only else GROUPS) if g and g not in a.skip.split(',')]
    bad = [g for g in groups if g not in GROUPS]
    if bad:
        sys.exit(f'unknown group(s) {bad}; groups: {GROUPS}')
    sys.exit(Overlay(a).run(groups))


if __name__ == '__main__':
    main()

# ---------------------------------------------------------------------------------------------
# On the phone but deliberately NOT reproduced (user/runtime state, or dev-loop scratch):
#   /private/var/mobile/Library/SplashBoard/Snapshots/com.apple.Preferences.old, chrono
#   snapshot-cache.old + cal-upnext.snapshot.moved, PRBPosterExtensionDataStore(.fresh/.bak),
#   LaunchServices *.csstore(.bak/.bak2/.bak3/.pre119), MCM containers (mkcont), lsreg/extreg
#   registrations, /usr/local/gltest/*.log, metalshim.log, /tmp/* (tool binaries + *_args files),
#   /System/Library/xpc/launchd.plist.sweetbak (backup of an intermediate launchd.plist),
#   /usr/local/gltest/{pushtest.txt,vkq_w.txt} and 9 SPIR-V files whose sources are gone (see report).
