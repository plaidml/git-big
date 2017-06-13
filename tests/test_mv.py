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

from os.path import exists, join
from subprocess import check_output, check_call

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, HELLO_DIGEST, check_locked_file,
                      check_status)


def test_move(env):
    '''Moving a file should move the link'''
    source = join(env.repo_dir, 'foo')
    open(source, 'w').write(HELLO_CONTENT)

    dest = join(env.repo_dir, 'bar')

    # git should report that the repo is dirty
    check_status(['?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', source])

    # move the link
    check_output(['git', 'big', 'mv', source, dest])

    # git should track the dest
    check_call(['git', 'status'])
    check_status(['A  .gitbig', 'A  bar'])

    # the file should now be moved
    assert not exists(source)
    check_locked_file(env, dest, HELLO_DIGEST)


def test_move_after_commit(env):
    '''Moving a file after a commit should move the link'''
    source = join(env.repo_dir, 'foo')
    open(source, 'w').write(HELLO_CONTENT)

    dest = join(env.repo_dir, 'bar')

    # git should report that the repo is dirty
    check_status(['?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', source])

    # make a commit
    check_output(['git', 'commit', '-m', 'commit'])

    # move the link
    check_output(['git', 'big', 'mv', source, dest])

    # git should track the dest
    check_call(['git', 'status'])
    check_status(['M  .gitbig', 'R  foo -> bar'])

    # the file should now be moved
    assert not exists(source)
    check_locked_file(env, dest, HELLO_DIGEST)
