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
from subprocess import check_call

# pylint: disable=unused-argument,W0621
from conftest import HELLO_CONTENT, HELLO_DIGEST
from git_big.main import fs


def test_push(depot_env):
    '''Push a file up to the depot'''

    # add a file
    file_ = join(depot_env.repo_dir, 'foo')
    open(file_, 'w').write(HELLO_CONTENT)
    check_call(['git', 'big', 'add', file_])

    # push up to the depot
    check_call(['git', 'big', 'push'])

    assert fs.isfile(join(depot_env.bucket_dir, 'objects', HELLO_DIGEST))

    # 2nd push should be a nop
    check_call(['git', 'big', 'push'])
