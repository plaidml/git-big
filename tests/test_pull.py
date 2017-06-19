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
from os.path import islink, join
from subprocess import check_call, check_output

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, HELLO_DIGEST, WORLD_CONTENT, WORLD_DIGEST,
                      check_locked_file, check_status)


def make_origin(env):
    # add a file
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)
    check_output(['git', 'big', 'add', file_])

    # push up to the depot
    check_output(['git', 'big', 'push'])

    # commit the changes
    check_call(['git', 'status'])
    check_output(['git', 'commit', '-m', 'commit message'])


def test_fresh_clone(env):
    '''Make a fresh clone and pull'''

    # make the origin repo
    make_origin(env)

    # clone it
    clone_dir = env.clone()

    # now pull big files
    check_output(['git', 'big', 'pull'])

    assert islink(join(clone_dir, 'foo'))


def check_anchors(env, expected):
    anchors_dir = join(env.repo_dir, '.gitbig-anchors')
    actual = []
    for _, _, files in os.walk(anchors_dir):
        for file_ in files:
            actual.append(file_)
    assert actual == expected


def test_checkout(env):
    '''Switch between branches, hooks should pull and update links'''
    # add a file
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)
    check_output(['git', 'big', 'add', file_])

    # commit the changes
    check_call(['git', 'status'])
    check_output(['git', 'commit', '-m', '1st commit'])
    check_status([])

    # make a new branch
    check_output(['git', 'checkout', '-b', 'changed'])

    # change a file
    check_output(['git', 'big', 'unlock', file_])
    open(file_, 'w').write(WORLD_CONTENT)
    check_output(['git', 'big', 'add', file_])

    # commit the changes
    check_call(['git', 'status'])
    check_output(['git', 'commit', '-m', '2nd commit'])
    check_status([])

    # switch back to 1st branch
    check_output(['git', 'checkout', 'master'])
    check_locked_file(env, file_, HELLO_DIGEST)
    check_anchors(env, [HELLO_DIGEST])

    # switch back to master branch
    check_output(['git', 'checkout', 'changed'])
    check_locked_file(env, file_, WORLD_DIGEST)
    check_anchors(env, [WORLD_DIGEST])

    # switch back to 1st branch
    check_output(['git', 'checkout', 'master'])
    check_locked_file(env, file_, HELLO_DIGEST)
    check_anchors(env, [HELLO_DIGEST])


def test_checkout_diff_types(env):
    '''Switch between branches, hooks should pull and update links.
    1st commit is a big file, 2nd commit is a normal file.'''
    # add a file
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)
    check_output(['git', 'big', 'add', file_])

    # commit the changes
    check_call(['git', 'status'])
    check_output(['git', 'commit', '-m', '1st commit'])
    check_status([])

    # make a new branch
    check_output(['git', 'checkout', '-b', 'changed'])

    # change a file
    check_output(['git', 'big', 'unlock', file_])
    open(file_, 'w').write(WORLD_CONTENT)
    check_output(['git', 'add', file_])

    # commit the changes
    check_call(['git', 'status'])
    check_output(['git', 'commit', '-m', '2nd commit'])
    check_status([])

    # switch back to 1st branch
    check_output(['git', 'checkout', 'master'])
    check_locked_file(env, file_, HELLO_DIGEST)

    # switch back to master branch
    check_output(['git', 'checkout', 'changed'])
    assert not islink(file_)

    # switch back to 1st branch
    check_output(['git', 'checkout', 'master'])
    check_locked_file(env, file_, HELLO_DIGEST)
