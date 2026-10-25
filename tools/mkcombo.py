#!/usr/bin/env python3
"""mkcombo.py XNU_PAYLOAD IMAGE RAMDISK CMDLINE_FILE OUT

The boot image's ramdisk when it carries MIUI too: the XNU payload (tools/mkpayload.py), then an
uncompressed arm64 Image, its ramdisk and its command line, each 4 KiB aligned, and a 4 KiB trailer
page at the very end that says where they are (shim/linux.c, struct lnx_trailer: "SWEETLNX", image
offset and size, ramdisk offset and size, command line length, command line). The shim's XNU loader
only reads what the payload's own header describes, so what follows it is not in its way.
"""
import struct
import sys

PAGE = 4096


def pad(b):
    return b + b"\0" * (-len(b) % PAGE)


def main():
    payload, image, ramdisk, cmdfile, out = sys.argv[1:6]
    xnu = open(payload, "rb").read()
    if xnu[:8] != b"SWEETXNU":
        sys.exit("not an XNU payload: " + payload)
    img = open(image, "rb").read()
    if img[56:60] != b"ARMd":
        sys.exit("not an arm64 Image: " + image)
    rd = open(ramdisk, "rb").read()
    cmd = open(cmdfile, "rb").read().strip()
    if len(cmd) >= 2048:
        sys.exit("command line too long")
    blob = pad(xnu)
    image_off = len(blob)
    blob = pad(blob + img)
    rd_off = len(blob)
    blob = pad(blob + rd)
    trailer = struct.pack("<8sQQQQI", b"SWEETLNX", image_off, len(img), rd_off, len(rd), len(cmd)) + cmd
    blob += trailer.ljust(PAGE, b"\0")
    open(out, "wb").write(blob)
    print("%s: %d bytes (xnu %d, Image %d at %#x, ramdisk %d at %#x, cmdline %d)" % (
        out, len(blob), len(xnu), len(img), image_off, len(rd), rd_off, len(cmd)))


if __name__ == "__main__":
    main()
