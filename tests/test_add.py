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

import os
from os.path import join
from subprocess import check_output

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, HELLO_DIGEST, WORLD_CONTENT, WORLD_DIGEST,
                      check_locked_file, check_status)


def add_file(env, file_, digest, expected_status):
    # add the file to git-big
    check_output(['git', 'big', 'add', file_])

    # git should now ignore the new file
    check_status(expected_status)

    check_locked_file(env, file_, digest)


def test_add(env):
    '''Adding a file should link to a single cache object'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    add_file(env, file_, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo'])


def test_add_same_multi(env):
    '''Adding a file a second time should be a nop'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    add_file(env, file_, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo'])
    add_file(env, file_, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo'])


def test_add_same_content(env):
    '''Adding a file with the same content twice should link to a single cache object'''
    file1 = join(env.repo_dir, 'foo')
    open(file1, 'w').write(HELLO_CONTENT)
    file2 = join(env.repo_dir, 'bar')
    open(file2, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? bar', '?? foo'])

    add_file(env, file1, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo', '?? bar'])
    add_file(env, file2, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  bar', 'A  foo'])


def test_add_changed(env):
    '''Adding a file and then changing its content should result in a new link'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    add_file(env, file_, HELLO_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo'])

    os.unlink(file_)
    open(file_, 'w').write(WORLD_CONTENT)

    add_file(env, file_, WORLD_DIGEST,
             ['A  .gitattributes', 'A  .gitbig', 'A  foo'])


def test_add_directory(env):
    '''Adding a directory should recursively add all files underneath'''
    dir1 = join(env.repo_dir, 'dir')
    file1 = join(dir1, 'foo')
    dir2 = join(dir1, 'dir')
    file2 = join(dir2, 'foo')
    os.makedirs(dir2)

    open(file1, 'w').write(HELLO_CONTENT)
    open(file2, 'w').write(WORLD_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? dir/'])

    # add the directory to git-big
    check_output(['git', 'big', 'add', 'dir'])

    # git should now ignore the new files
    check_status(
        ['A  .gitattributes', 'A  .gitbig', 'A  dir/dir/foo', 'A  dir/foo'])

    check_locked_file(env, file1, HELLO_DIGEST)
    check_locked_file(env, file2, WORLD_DIGEST)
