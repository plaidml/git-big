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
from subprocess import check_call, check_output

# pylint: disable=unused-argument,W0621
from conftest import HELLO_CONTENT


def test_subdir(env):
    '''Create a subdirectory, ensure big files work still'''

    # add a file and commit
    os.mkdir(join(env.repo_dir, 'foo'))
    prev_dir = os.getcwd()
    os.chdir(join(env.repo_dir, 'foo'))
    try:
        file_ = 'bar'
        open(file_, 'w').write(HELLO_CONTENT)
        check_call(['git', 'big', 'add', file_])
        check_output(['git', 'commit', '-m', 'message'])
    finally:
        os.chdir(prev_dir)
