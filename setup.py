#!/usr/bin/env python

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

from setuptools import setup
import git_big

setup(
    name='git-big',
    description=
    'Git Big is a command line extension to Git for managing Write Once Read Many (WORM) files.',
    version=git_big.__version__,
    license='Apache 2.0',
    author='Vertex AI',
    url='https://github.com/vertexai/git-big',
    packages=['git_big'],
    install_requires=[
        'apache-libcloud==1.5.0',
        'click',
        'tqdm',
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: Unix",
        "Operating System :: MacOS :: MacOS X",
        "Programming Language :: Python :: 2.7",
        "Topic :: Software Development :: Libraries",
        "Topic :: Software Development :: Version Control",
        "Topic :: Utilities",
    ],
    entry_points={'console_scripts': [
        'git-big=git_big.main:cli',
    ]}, )
