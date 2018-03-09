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

__version__ = '0.6.0'

import os
import os.path
import platform
import stat

def setupForWindows():
    if platform.system() == 'Windows':
         import jaraco.windows.filesystem as fs
         def linkit(src, dest):
            fs.link(src, dest)
            os.chmod(dest, stat.S_IWRITE | stat.S_IREAD) 
         if not hasattr(os, 'symlink'):
             os.link = linkit
             os.symlink = lambda src, dest: fs.symlink(src, dest, 0x2)
             os.path.islink = fs.islink
         if not hasattr(os, 'readlink'):
             os.readlink = fs.readlink

setupForWindows()
