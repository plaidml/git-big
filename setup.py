#!/usr/bin/env python

from setuptools import setup
import git_big

setup(
    name='git-big',
    description='git big file manager',
    version=git_big.__version__,
    license='MIT License',
    author='Vertex AI',
    url='https://github.com/vertexai/git-big',
    packages=['git_big'],
    install_requires=[
        'apache-libcloud',
        'click',
        'gitpython',
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: Console",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
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
