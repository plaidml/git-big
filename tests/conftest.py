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

import contextlib
import os
import platform
import time
from subprocess import Popen, check_output

import pytest

from git_big.main import fs

if platform.system() == 'Windows':
    import git_big.windows
    git_big.windows.check()

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
        self.depot_config = None
        if not os.path.exists(self.bucket_dir):
            os.makedirs(self.bucket_dir)

    def git_big_init(self, depot_config):
        check_output(['git', 'config', 'git-big.cache-dir', self.cache_dir])
        check_output([
            'git',
            'big',
            'set-depot',
            '--url',
            depot_config['url'],
            '--key',
            depot_config['access_key'],
            '--secret',
            depot_config.get('secret_key', ''),
        ])
        check_output(['git', 'big', 'init'])
        self.depot_config = depot_config

    def clone(self, repo_dir='clone', cache_dir='cache'):
        ctx = Context(self.root_dir)
        ctx.repo_dir = os.path.join(self.root_dir, repo_dir)
        ctx.cache_dir = os.path.join(self.root_dir, cache_dir)
        check_output(['git', 'clone', self.repo_dir, ctx.repo_dir])
        os.chdir(ctx.repo_dir)
        ctx.git_big_init(self.depot_config)
        return ctx


@contextlib.contextmanager
def libcloud_env(ctx):
    depot_config = {
        'url': 'local://bucket',
        'access_key': ctx.depot_dir,
    }
    yield depot_config


@contextlib.contextmanager
def boto_env(ctx):
    bucket = 'bucket'
    minio_netloc = '127.0.0.1:9000'
    endpoint_url = 'http://{}'.format(minio_netloc)
    depot_config = {
        'url': 's3+{}/{}'.format(endpoint_url, bucket),
        'access_key': 'access_key',
        'secret_key': 'secret_key',
    }
    config_dir = os.path.join(ctx.root_dir, '.minio')
    env = dict(os.environ)
    env.update({
        'MINIO_ACCESS_KEY': depot_config['access_key'],
        'MINIO_SECRET_KEY': depot_config['secret_key'],
    })
    proc = Popen(
        [
            'minio', 'server', '--config-dir', config_dir, '--address',
            minio_netloc, ctx.depot_dir
        ],
        env=env)
    time.sleep(2)  # wait a bit for minio to startup
    try:
        yield depot_config
    finally:
        proc.terminate()


@pytest.fixture
def env(tmpdir):
    # tmpdir is magical: https://docs.pytest.org/en/latest/tmpdir.html
    context = Context(tmpdir)
    with libcloud_env(context) as depot_config:
        check_output(['git', 'init', context.repo_dir])
        os.chdir(context.repo_dir)
        context.git_big_init(depot_config)
        yield context


@pytest.fixture
def bare_env(tmpdir):
    # tmpdir is magical: https://docs.pytest.org/en/latest/tmpdir.html
    context = Context(tmpdir)
    with libcloud_env(context) as depot_config:
        check_output(['git', 'init', '--bare', context.repo_dir])
        os.chdir(context.repo_dir)
        context.git_big_init(depot_config)
        yield context


@pytest.fixture(params=[libcloud_env, boto_env])
def depot_env(tmpdir, request):
    # tmpdir is magical: https://docs.pytest.org/en/latest/tmpdir.html
    context = Context(tmpdir)
    with request.param(context) as depot_config:
        check_output(['git', 'init', context.repo_dir])
        os.chdir(context.repo_dir)
        context.git_big_init(depot_config)
        yield context


def check_locked_file(env, file_, digest, root_dir=None):
    if not root_dir:
        root_dir = env.repo_dir
    anchors_path = os.path.join(root_dir, '.gitbig-anchors', digest[:2],
                                digest[2:4], digest)
    symlink_path = os.path.relpath(anchors_path, os.path.dirname(file_))
    cache_path = os.path.join(env.cache_dir, 'objects', digest[:2],
                              digest[2:4], digest)

    assert fs.isfile(anchors_path)
    assert fs.isfile(cache_path)
    assert fs.islink(file_)
    assert fs.readlink(file_) == symlink_path
    assert os.stat(anchors_path).st_ino == os.stat(cache_path).st_ino

    # once the file is added, it should be read-only
    with pytest.raises(Exception):
        file_.write('fail')


def check_status(expected):
    status = check_output(['git', 'status', '-s']).decode()
    if expected:
        assert status == '\n'.join(expected) + '\n'
    else:
        assert status == ''
