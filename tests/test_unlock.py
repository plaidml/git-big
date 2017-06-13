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

from os.path import isfile, islink, join
from subprocess import check_call, check_output

from conftest import (HELLO_CONTENT, HELLO_DIGEST, check_locked_file,
                      check_status)


def test_unlock(env):
    '''Unlocking a file should replace the symlink with a copy of the file'''
    file_ = join(env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['?? foo'])

    # add the file to git-big
    check_output(['git', 'big', 'add', file_])

    # git should now track the new file
    check_status(['A  .gitbig', 'A  foo'])

    # unlock the file
    check_output(['git', 'big', 'unlock', file_])

    # git should report that the file is untracked
    check_call(['git', 'status'])
    check_status(['?? foo'])

    # we should have a normal file
    assert not islink(file_)
    assert isfile(file_)

    # unlocked files should be writable
    open(file_, 'w').write('ok')


def test_unlock_one_of_two(env):
    '''Unlocking a single file out of multiple pending changes'''
    file1 = join(env.repo_dir, 'foo')
    open(file1, 'w').write(HELLO_CONTENT)
    file2 = join(env.repo_dir, 'bar')
    open(file2, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['?? bar', '?? foo'])

    # add the files to git-big
    check_output(['git', 'big', 'add', file1])
    check_output(['git', 'big', 'add', file2])

    # git should now track the new files
    check_status(['A  .gitbig', 'A  bar', 'A  foo'])

    # unlock the file
    check_output(['git', 'big', 'unlock', file1])

    # git should report that file1 is untracked but file2 is still tracked
    check_call(['git', 'status'])
    check_status(['A  .gitbig', 'A  bar', '?? foo'])

    # we should have a normal file and a linked file
    assert not islink(file1)
    assert isfile(file1)
    assert islink(file2)

    # unlocked files should be writable
    open(file1, 'w').write('ok')

    # locked files should remain read-only
    check_locked_file(env, file2, HELLO_DIGEST)


def test_unlock_after_commit(env):
    '''Unlocking a file after a commit'''
    file1 = join(env.repo_dir, 'foo')
    open(file1, 'w').write(HELLO_CONTENT)
    file2 = join(env.repo_dir, 'bar')
    open(file2, 'w').write(HELLO_CONTENT)

    # git should report that the repo is dirty
    check_status(['?? bar', '?? foo'])

    # add the files to git-big
    check_output(['git', 'big', 'add', file1])
    check_output(['git', 'big', 'add', file2])

    # make a commit
    check_output(['git', 'commit', '-m', 'commit'])

    # unlock the file
    check_output(['git', 'big', 'unlock', file1])

    # git should report that file1 is deleted and untracked but file2 is still tracked
    check_call(['git', 'status'])
    check_status(['M  .gitbig', 'D  foo', '?? foo'])

    # we should have a normal file and a linked file
    assert not islink(file1)
    assert isfile(file1)
    assert islink(file2)

    # unlocked files should be writable
    open(file1, 'w').write('ok')

    # locked files should remain read-only
    check_locked_file(env, file2, HELLO_DIGEST)

    # save the change
    check_output(['git', 'big', 'add', file1])

    # see that the file is now modified
    check_call(['git', 'status'])
    check_status(['M  .gitbig', 'M  foo'])
