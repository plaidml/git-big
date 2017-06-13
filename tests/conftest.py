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
from subprocess import check_output

import pytest

HELLO_CONTENT = 'hello'
HELLO_DIGEST = '2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824'
WORLD_CONTENT = 'world'
WORLD_DIGEST = '486ea46224d1bb4fb680f34f7c9ad96a8f24ec88be73ea8e5a6c65260e9cb8a7'


class Context(object):
    def __init__(self, tmpdir):
        self.root_dir = str(tmpdir)
        self.cache_dir = os.path.join(self.root_dir, 'cache')
        self.repo_dir = os.path.join(self.root_dir, 'repo')
        self.depot_dir = os.path.join(self.root_dir, 'depot')
        self.bucket_dir = os.path.join(self.depot_dir, 'bucket')
        os.makedirs(self.bucket_dir)

    def git_big_init(self):
        check_output(['git', 'config', 'git-big.cache-dir', self.cache_dir])
        check_output(['git', 'config', 'git-big.depot.url', "local://bucket"])
        check_output(['git', 'config', 'git-big.depot.key', self.depot_dir])
        check_output(['git', 'big', 'init'])

    def clone(self, dirname='clone'):
        clone_dir = os.path.join(self.root_dir, dirname)
        check_output(['git', 'clone', self.repo_dir, clone_dir])
        os.chdir(clone_dir)
        self.git_big_init()
        return clone_dir


@pytest.fixture
def env(tmpdir):
    context = Context(tmpdir)
    check_output(['git', 'init', context.repo_dir])
    os.chdir(context.repo_dir)
    context.git_big_init()
    yield context


def check_locked_file(env, file_, digest):
    anchors_path = os.path.join(env.repo_dir, '.git', 'git-big', 'anchors',
                                digest[:2], digest[2:4], digest)
    symlink_path = os.path.relpath(anchors_path, os.path.dirname(file_))
    cache_path = os.path.join(env.cache_dir, 'objects', digest[:2],
                              digest[2:4], digest)

    assert os.path.isfile(anchors_path)
    assert os.path.isfile(cache_path)
    assert os.path.islink(file_)
    assert os.readlink(file_) == symlink_path
    assert os.stat(anchors_path).st_ino == os.stat(cache_path).st_ino

    # once the file is added, it should be read-only
    with pytest.raises(Exception):
        file_.write('fail')


def check_status(expected):
    status = check_output(['git', 'status', '-s'])
    if expected:
        assert status == '\n'.join(expected) + '\n'
    else:
        assert status == ''
