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

from os.path import join
from subprocess import check_output, check_call

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, HELLO_DIGEST, check_locked_file,
                      check_status)


def test_copy(env):
    '''Copying a file should create another link'''
    source = join(env.repo_dir, 'foo')
    open(source, 'w').write(HELLO_CONTENT)

    dest = join(env.repo_dir, 'bar')

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', source])

    # copy the link
    check_output(['git', 'big', 'cp', source, dest])

    # git should track the source and dest
    check_call(['git', 'status'])
    check_status(['A  .gitattributes', 'A  .gitbig', 'A  bar', 'A  foo'])

    # we should have two links to the same object
    check_locked_file(env, source, HELLO_DIGEST)
    check_locked_file(env, dest, HELLO_DIGEST)


def test_copy_after_commit(env):
    '''Copying a file after a commit should create another link'''
    source = join(env.repo_dir, 'foo')
    open(source, 'w').write(HELLO_CONTENT)

    dest = join(env.repo_dir, 'bar')

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', source])

    # make a commit
    check_output(['git', 'commit', '-m', 'commit'])

    # copy the link
    check_output(['git', 'big', 'cp', source, dest])

    # git should track the source and dest
    check_call(['git', 'status'])
    check_status(['M  .gitbig', 'A  bar'])

    # we should have two links to the same object
    check_locked_file(env, source, HELLO_DIGEST)
    check_locked_file(env, dest, HELLO_DIGEST)
