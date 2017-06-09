#!/usr/bin/env python

from setuptools import setup
import git_big

setup(
    name='git-big',
    version=git_big.__version__,
    description='git big file manager',
    author='Vertex AI',
    packages=['git_big'],
    install_requires=[
        'apache-libcloud',
        'click',
        'gitpython',
        'pathspec',
    ],
    entry_points={'console_scripts': [
        'git-big=git_big.main:cli',
    ]}, )
