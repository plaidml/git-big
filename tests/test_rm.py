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
from subprocess import check_output

# pylint: disable=unused-argument,W0621
from conftest import (HELLO_CONTENT, check_status)


def test_remove(env):
    '''Removing a file should remove the link and index entry'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', file_])

    # remove the file
    check_output(['git', 'big', 'rm', file_])

    # git should not report that there is an untracked file
    check_status(['A  .gitattributes'])

    # file should be gone
    assert not exists(file_)


def test_remove_after_commit(env):
    '''Removing a file after a commit should remove the link and index entry'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['A  .gitattributes', '?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', file_])

    # make a commit
    check_output(['git', 'commit', '-m', 'commit'])

    # remove the file
    check_output(['git', 'big', 'rm', file_])

    # git should show deletions
    check_status(['D  .gitbig', 'D  foo'])

    # file should be gone
    assert not exists(file_)
