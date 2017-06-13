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

from subprocess import check_output

# pylint: disable=unused-argument,W0621
import pytest

HOOKS = [
    'pre-push',
    'post-checkout',
    'post-merge',
]


@pytest.fixture
def setup(tmpdir):
    tmpdir.chdir()
    yield tmpdir


def do_init(tmpdir):
    check_output(['git', 'init'])
    check_output(['git', 'big', 'init'])
    # check uuid was created
    check_output(['git', 'config', 'git-big.uuid'])
    # check .gitbig file was created
    tmpdir.join('.gitbig').check(file=1)
    # check hooks were created
    for hook in HOOKS:
        assert tmpdir.join('.git', 'hooks', hook).check(file=1)


def test_init(setup):
    do_init(setup)


def test_init_multi(setup):
    do_init(setup)
    do_init(setup)
    for hook in HOOKS:
        assert setup.join('.git', 'hooks', hook + '.git-big').check(exists=0)


def test_init_chain(setup):
    check_output(['git', 'init'])
    for hook in HOOKS:
        file_ = setup.join('.git', 'hooks', hook)
        file_.write('#!/bin/sh\necho "Hello"')
    do_init(setup)
    for hook in HOOKS:
        assert setup.join('.git', 'hooks', hook + '.git-big').check(file=1)
