#!/usr/bin/env python3
"""adt-camera.py IN.adt OUT.adt: the device tree MobileGestalt reads the cameras from (HackiOS loader.c, cam=5).

/arm-io/isp with camera-rear and camera-front only (still-camera, rear-facing-camera, front-facing-camera:
SpringBoard shows Camera.app), no compatible and no device_type, so no driver matches it; /product/camera with
no properties of its own (video-camera). Nothing else of the iPhone X's camera node: features such as
pearl-camera or flash would be offered to apps without the hardware behind them.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402


def child(node, name):
    for c in node.children:
        if c.name == name:
            return c
    return None


def new_node(name, props):
    n = adt.Node()
    n.props.append(('name', 0, name.encode() + b'\0'))
    for key, value in props:
        n.props.append((key, 0, struct.pack('<I', value)))
    return n


def main():
    root, _ = adt.parse(open(sys.argv[1], 'rb').read())
    arm_io, product = child(root, 'arm-io'), child(root, 'product')
    assert arm_io is not None and product is not None, 'no /arm-io or /product'
    if child(arm_io, 'isp') is None:
        arm_io.children.append(new_node('isp', [('camera-rear', 1), ('camera-front', 1)]))
    if child(product, 'camera') is None:
        product.children.append(new_node('camera', []))
    open(sys.argv[2], 'wb').write(adt.serialize(root))


if __name__ == '__main__':
    main()
