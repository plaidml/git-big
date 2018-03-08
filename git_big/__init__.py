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

__version__ = '0.5.1'

import platform
if platform.system() == 'Windows':
   import os
   import os.path
   import win32file
   os.link = lambda(src, dest): win32file.CreateHardLink(
       os.path.abspath(dest), os.path.abspath(src)
   )
   os.symlink = lambda(src, dest): win32file.CreateSymbolicLink(
       os.path.abspath(dest), os.path.abspath(src), 0x2
   )
