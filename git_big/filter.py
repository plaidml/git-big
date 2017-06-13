# Copyright (c) 2017 Vertex.AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import print_function

import datetime
import hashlib
import os
import sys

BLOCKSIZE = 64 * 1024


def compute_digest(path):
    algorithm = hashlib.sha256()
    with open(path, 'rb') as file_:
        while True:
            buf = file_.read(BLOCKSIZE)
            if not buf:
                break
            algorithm.update(buf)
    return algorithm.hexdigest()


def read_packet(log):
    pkt_len = int(sys.stdin.read(4), 16)
    if pkt_len == 0:
        return None
    print('> %d bytes' % pkt_len, file=log)
    return sys.stdin.read(pkt_len - 4)


def read_lines(log):
    packets = read_until_flush(log)
    lines = []
    for packet in packets:
        line = packet.rstrip('\n')
        print('> ' + line, file=log)
        lines.append(line)
    return lines


def read_until_flush(log):
    packets = []
    while True:
        packet = read_packet(log)
        if packet:
            packets.append(packet)
        else:
            break
    return packets


def write_packet(line):
    pkt_line = '%04x%s' % (len(line) + 4, line)
    sys.stdout.write(pkt_line)


def write_line(log, line):
    write_packet(line + '\n')
    print('< ' + line, file=log)


def write_flush():
    sys.stdout.write('0000')
    sys.stdout.flush()


def cmd_process():
    now = datetime.datetime.now()
    log_name = 'filter-%s.log' % now.isoformat()
    with open(log_name, 'w') as log:
        lines = read_lines(log)
        if lines[0] != 'git-filter-client':
            write_line(log, 'status=error')
            write_flush()
            return

        versions = []
        for line in lines[1:]:
            key, value = line.split('=', 1)
            if key == 'version':
                versions.append(value)

        print('versions: %r' % versions, file=log)
        if '2' not in versions:
            write_line(log, 'status=error')
            write_flush()
            return

        write_line(log, 'git-filter-server')
        write_line(log, 'version=2')
        write_flush()

        capabilities = []
        lines = read_lines(log)
        for line in lines:
            key, value = line.split('=', 1)
            if key == 'capability':
                capabilities.append(value)

        print('capabilities: %r' % capabilities, file=log)

        write_line(log, 'capability=clean')
        write_line(log, 'capability=smudge')
        write_flush()

        command = None
        pathname = None
        lines = read_lines(log)
        for line in lines:
            key, value = line.split('=', 1)
            if key == 'command':
                command = value
            if key == 'pathname':
                pathname = value

        print('%s: %s' % (command, pathname), file=log)

        payload = read_until_flush(log)
        print('content: %s' % payload[0], file=log)

        write_line(log, 'status=success')
        write_flush()

        if command == 'clean':
            digest = compute_digest(pathname)
            write_packet(digest)
            anchor_path = '.git/git-big/anchors/%s' % digest
            anchor_dir = os.path.dirname(anchor_path)
            if not os.path.exists(anchor_dir):
                os.makedirs(anchor_dir)
            if os.path.join(anchor_path):
                os.unlink(pathname)
            else:
                os.rename(pathname, anchor_path)
            os.symlink(anchor_path, pathname)

        write_flush()

        write_flush()
