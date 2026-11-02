#!/usr/bin/env python3
"""Generate xnu/patches/0200-sweet-wifi.patch: adds the WiFi seam files to the XNU tree
(bsd/dev + bsd/sys) and a bsd/conf/files hunk, anchored on the sweet_gpu.c line that 0083
adds (so 0200 applies cleanly after 0083 via strict git apply)."""
import os

REF = os.path.dirname(os.path.abspath(__file__))            # wifi-port/
OUT = os.path.join(REF, '..', 'xnu', 'patches', '0200-sweet-wifi.patch')

# (source under wifi-port/, dest path in xnu tree) -- order doesn't matter for new files
FILES = [
    ('xnu/files/bsd/sys/hakios.qrtr.h', 'bsd/sys/hakios.qrtr.h'),
    ('xnu/files/bsd/sys/hakios.qmi.h',  'bsd/sys/hakios.qmi.h'),
    ('xnu/files/bsd/dev/hakios.qmi.c',  'bsd/dev/hakios.qmi.c'),
]
# bsd/conf/files lines to add (after the sweet_gpu.c anchor), in order
CONF_ADD = [
    'bsd/dev/hakios.qmi.c\t\t\tstandard',
]

def newfile_hunk(src, dest):
    raw = open(os.path.join(REF, src), 'rb').read()
    tnl = raw.endswith(b'\n')
    lines = raw.decode('utf-8', 'surrogateescape').split('\n')
    if lines and lines[-1] == '':
        lines = lines[:-1]
    n = len(lines)
    out = [f'--- /dev/null\n', f'+++ b/{dest}\n', f'@@ -0,0 +1,{n} @@\n']
    body = ['+' + l + '\n' for l in lines]
    if not tnl:
        body[-1] = body[-1].rstrip('\n') + '\n'
        body.append('\\ No newline at end of file\n')
    return ''.join(out) + ''.join(body)

# The real post-series bsd/conf/files, pulled from an xnu-buildtree artifact (ground truth).
CONF_REF = '/tmp/claude-1000/-home-marnov-xmiphones/690fa516-fb7e-40dd-a391-65727c184559/scratchpad/bt/xnu/bsd/conf/files'
ANCHOR = 'bsd/dev/sweet_camera.c'   # add our wifi entries right after this line (last sweet dev file)

def conf_hunk():
    lines = open(CONF_REF).read().split('\n')
    if lines and lines[-1] == '':
        lines = lines[:-1]
    idx = next(i for i, l in enumerate(lines) if l.startswith(ANCHOR))
    before = lines[idx - 3:idx + 1]          # 4 lines of context ending at the anchor
    after = lines[idx + 1:idx + 4]           # 3 lines of context after
    start = idx - 3 + 1                       # 1-based line number of first context line
    old = len(before) + len(after)
    new = old + len(CONF_ADD)
    body = [' ' + l for l in before] + ['+' + l for l in CONF_ADD] + [' ' + l for l in after]
    return '--- a/bsd/conf/files\n+++ b/bsd/conf/files\n' + \
        f'@@ -{start},{old} +{start},{new} @@\n' + '\n'.join(body) + '\n'

def main():
    parts = [conf_hunk()]
    for src, dest in FILES:
        parts.append(newfile_hunk(src, dest))
    open(OUT, 'w', newline='').write(''.join(parts))
    print('wrote', os.path.normpath(OUT), '-', len(FILES), 'files +', len(CONF_ADD), 'conf lines')

if __name__ == '__main__':
    main()
