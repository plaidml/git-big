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
from os.path import isfile, islink, join
from subprocess import call, check_call, check_output

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, HELLO_DIGEST, WORLD_CONTENT, WORLD_DIGEST,
                      check_locked_file, check_status)

import pytest


def make_origin(env):
    # add files
    foo = join(env.repo_dir, 'foo')
    open(foo, 'w').write(HELLO_CONTENT)
    check_output(['git', 'big', 'add', foo])

    bar = join(env.repo_dir, 'bar')
    open(bar, 'w').write(WORLD_CONTENT)
    check_output(['git', 'big', 'add', bar])

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
    clone = env.clone(cache_dir='clone_cache')

    # pull big files (initially soft)
    check_call(['git', 'big', 'pull'])

    assert islink(join(clone.repo_dir, 'foo'))
    assert islink(join(clone.repo_dir, 'bar'))

    assert not isfile(join(clone.repo_dir, 'foo'))
    assert not isfile(join(clone.repo_dir, 'bar'))

    # pull big files (now hard)
    check_output(['git', 'big', 'pull', '--hard'])

    assert isfile(join(clone.repo_dir, 'foo'))
    assert isfile(join(clone.repo_dir, 'bar'))


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


def test_pull_file(env):
    '''test the ability to pull individual big files'''

    # make the origin repo
    make_origin(env)

    # clone it
    clone = env.clone(cache_dir='clone_cache')

    # now pull a single file
    check_output(['git', 'big', 'pull', 'foo'])

    assert isfile(join(clone.repo_dir, 'foo'))
    assert not isfile(join(clone.repo_dir, 'bar'))

    # pulling a file again is ok
    check_output(['git', 'big', 'pull', 'foo'])

    assert isfile(join(clone.repo_dir, 'foo'))
    assert not isfile(join(clone.repo_dir, 'bar'))

    # pull another big file
    check_output(['git', 'big', 'pull', 'bar'])

    assert isfile(join(clone.repo_dir, 'foo'))
    assert isfile(join(clone.repo_dir, 'bar'))

    # pull an invalid file
    ret = call(['git', 'big', 'pull', 'does_not_exist'])
    assert ret != 0


def check_alt_hardlink(env, file_path, digest):
    root_dir = env.repo_dir
    cache_path = os.path.join(env.cache_dir, 'objects', digest[:2],
                              digest[2:4], digest)

    assert os.path.isfile(file_path)
    assert os.path.isfile(cache_path)
    assert os.stat(file_path).st_ino == os.stat(cache_path).st_ino

    with pytest.raises(Exception):
        with open(file_path) as file_:
            file_.write('fail')


def test_pull_hardlink(env):
    '''test the --hardlink option'''

    # make the origin repo
    make_origin(env)

    # clone it
    clone = env.clone(cache_dir='clone_cache')

    # now pull a single file and also specify an extra hardlink path
    alt_foo = join(env.root_dir, 'alt', 'foo')
    check_output(['git', 'big', 'pull', 'foo', '--hardlink', alt_foo])

    # ensure that the alt file appears and that its read-only
    check_alt_hardlink(clone, alt_foo, HELLO_DIGEST)


def test_pull_hardlink_dir(env):
    '''test the --hardlink option with multiple pulls'''

    # make the origin repo
    make_origin(env)

    # clone it
    clone = env.clone(cache_dir='clone_cache')

    # now pull a single file and also specify an extra hardlink directory
    alt_dir = join(env.root_dir, 'alt')
    check_output(['git', 'big', 'pull', '--hard', '--hardlink', alt_dir])

    # ensure that the alt files appear and that they're read-only
    check_alt_hardlink(clone, join(alt_dir, 'foo'), HELLO_DIGEST)
    check_alt_hardlink(clone, join(alt_dir, 'bar'), WORLD_DIGEST)
