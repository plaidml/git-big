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
from conftest import (HELLO_CONTENT, HELLO_DIGEST, check_locked_file,
                      check_status)


def test_create(env):
    '''Create a worktree, ensure big files are linked'''

    # add a file and commit
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)
    check_output(['git', 'big', 'add', file_])
    check_output(['git', 'commit', '-m', 'message'])

    # create a worktree
    check_output(['git', 'worktree', 'add', 'worktree'])

    # change directory into the worktree
    os.chdir('worktree')

    # pull big files into worktree
    check_output(['git', 'big', 'pull'])

    # verify link is working
    check_locked_file(env, 'foo', HELLO_DIGEST, '.')


def test_add(env):
    '''Adding a file to a worktree'''

    # create an initial commit
    touched = join(env.repo_dir, 'xxx')
    open(touched, 'w').close()
    check_output(['git', 'add', touched])
    check_output(['git', 'commit', '-m', 'commit'])

    # create a worktree
    check_output(['git', 'worktree', 'add', 'worktree'])

    # change directory into the worktree
    os.chdir('worktree')

    open('foo', 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['?? foo'])

    # add the file
    check_output(['git', 'big', 'add', 'foo'])

    # status should show two pending changes
    check_status(['A  .gitbig', 'A  foo'])

    # verify link is working
    check_locked_file(env, 'foo', HELLO_DIGEST, '.')
