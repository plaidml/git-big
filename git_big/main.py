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

import collections
import contextlib
import errno
import getpass
import hashlib
import io
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import uuid

import click
import progressbar
import six

import git_big.storage
from git_big.singleton import Singlet

from . import __version__

BLOCKSIZE = 1024 * 1024
CTX_SETTINGS = dict(help_option_names=['-h', '--help'])
DEV_NULL = io.open(os.devnull, 'w')
IS_WIN = platform.system() == 'Windows'

if IS_WIN:
    DEFAULT_CACHE_DIR = os.path.join(
        os.getenv('USERPROFILE'), '.cache', 'git-big')
else:
    DEFAULT_CACHE_DIR = os.path.expanduser('~/.cache/git-big')


def git(*args):
    return subprocess.check_output(
        ['git'] + list(map(str, args)), stderr=DEV_NULL).decode()


def human_size(num):
    if num is None:
        return ''
    if abs(num) < 1024:
        return '{:3.0f}{}'.format(num, 'B')
    num /= 1024.0
    for unit in ['K', 'M', 'G', 'T', 'P', 'E', 'Z']:
        if abs(num) < 1024.0:
            return '{:3.1f}{}'.format(num, unit)
        num /= 1024.0
    return '{:3.1f}{}'.format(num, 'Y')


class PosixFileSystem(object):
    def islink(self, path):
        return os.path.islink(path)

    def isfile(self, path):
        return os.path.isfile(path)

    def readlink(self, path):
        return os.readlink(path)

    def link(self, src, dst):
        return os.link(src, dst)

    def symlink(self, src, dst):
        return os.symlink(src, dst)


if IS_WIN:
    from git_big.windows import WindowsFileSystem
    fs = WindowsFileSystem()
else:
    fs = PosixFileSystem()


@contextlib.contextmanager
def atomic_open(dst_path, *args, **kwargs):
    tmp_file, tmp_path = tempfile.mkstemp()
    os.close(tmp_file)
    try:
        with io.open(tmp_path, *args, **kwargs) as file_:
            yield file_
        if IS_WIN and os.path.exists(dst_path):
            os.unlink(dst_path)
        try:
            os.rename(tmp_path, dst_path)
        except:
            shutil.copy2(tmp_path, dst_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


class GitIndex(object):
    def add(self, paths):
        for path in paths:
            git('add', '-f', path)

    def remove(self, paths):
        for path in paths:
            git('rm', path)


class GitRepository(object):
    def __init__(self):
        try:
            # HACK because common-dir doesn't seem to work in subdirs of the main repo!?
            # Should be: self.git_dir = git('rev-parse', '--git-common-dir').rstrip()
            self.git_dir = git('rev-parse', '--git-dir').rstrip()
            subdirs = os.path.normpath(self.git_dir).split(os.path.sep)
            if len(subdirs) >= 2 and subdirs[-2] == 'worktrees':
                self.git_dir = git('rev-parse', '--git-common-dir').rstrip()
        except subprocess.CalledProcessError:
            raise click.ClickException('git or git repository not found')
        self.working_dir = os.path.normpath(
            git('rev-parse', '--show-toplevel').rstrip())
        self.index = GitIndex()
        self.is_bare = git('rev-parse',
                           '--is-bare-repository').rstrip() == 'true'

    @property
    def active_branch(self):
        return git('rev-parse', '--abbrev-ref', 'HEAD').rstrip()


class DepotConfig(object):
    def __init__(self, **kwargs):
        self.url = kwargs.get('url')
        self.key = kwargs.get('key')
        self.secret = kwargs.get('secret')

    def __iter__(self):
        yield 'url', self.url
        yield 'key', self.key
        yield 'secret', self.secret

    def make_path(self, *paths):
        return '/'.join(map(str, paths))


class UserConfig(object):
    def __init__(self, **kwargs):
        self.version = 1
        self.cache_dir = kwargs.get('cache_dir', DEFAULT_CACHE_DIR)
        self.depot = DepotConfig(**kwargs.get('depot', {}))

    def __iter__(self):
        yield 'version', self.version
        yield 'cache_dir', self.cache_dir
        yield 'depot', dict(self.depot)


class RepoConfig(object):
    def __init__(self, **kwargs):
        self.version = 1
        self.files = kwargs.get('files', {})

    def __iter__(self):
        yield 'version', self.version
        yield 'files', collections.OrderedDict(sorted(self.files.items()))

    def merge(self, other):
        self.files.update(other.files)


def git_config_get(name, default=None):
    try:
        return git('config', name).rstrip()
    except:  # pylint: disable=W0702
        return default


class GitConfig(object):
    def __init__(self):
        self.uuid = git_config_get('git-big.uuid', uuid.uuid4())
        self.cache_dir = git_config_get('git-big.cache-dir')
        self.depot_url = git_config_get('git-big.depot.url')
        self.depot_key = git_config_get('git-big.depot.key')
        self.depot_secret = git_config_get('git-big.depot.secret')

    def save(self):
        git('config', 'git-big.uuid', self.uuid)
        git('config', 'merge.git-big.driver', 'git big merge-driver %O %A %B')


class Config(RepoConfig):
    def __init__(self, repo_config, git_config, user_config, working_dir):
        super(Config, self).__init__()
        self.cache_dir = git_config.cache_dir or user_config.cache_dir
        self.objects_dir = os.path.join(self.cache_dir, 'objects')
        self.uuid = git_config.uuid
        self.files = repo_config.files

        depot_config = DepotConfig(**dict(user_config.depot))
        if git_config.depot_url:
            depot_config.url = git_config.depot_url
        if git_config.depot_key:
            depot_config.key = git_config.depot_key
        if git_config.depot_secret:
            depot_config.secret = git_config.depot_secret

        if depot_config.url:
            self.depot = depot_config
        else:
            self.depot = None

        self.working_dir = working_dir
        self.anchors_dir = os.path.join(self.working_dir, '.gitbig-anchors')


class Entry(object):
    def __init__(self, config, rel_path, digest):
        self._depot_size = None
        self.rel_path = rel_path
        self.digest = digest
        self.working_path = os.path.join(config.working_dir, self.rel_path)
        self.anchor_path = os.path.join(config.anchors_dir, self.digest[:2],
                                        self.digest[2:4], self.digest)
        self.symlink_path = os.path.relpath(self.anchor_path,
                                            os.path.dirname(self.working_path))
        self.cache_path = os.path.join(config.objects_dir, self.digest[:2],
                                       self.digest[2:4], self.digest)
        if config.depot:
            self.depot_path = config.depot.make_path('objects', self.digest)
        else:
            self.depot_path = None

    @property
    def in_cache(self):
        return os.path.exists(self.cache_path)

    @property
    def in_anchors(self):
        return os.path.exists(self.anchor_path)

    @property
    def is_link(self):
        return fs.islink(self.working_path)

    @property
    def in_working(self):
        return os.path.exists(self.working_path)

    @property
    def is_linked(self):
        return self.in_anchors and self.is_link and \
            fs.readlink(self.working_path) == self.symlink_path

    @property
    def in_depot(self):
        return self._depot_size is not None

    @property
    def size(self):
        if self.in_working:
            return os.path.getsize(self.working_path)
        if self.in_cache:
            return os.path.getsize(self.cache_path)
        if self.in_depot:
            return self._depot_size
        return None


def make_progress_bar(name, size):
    widgets = [
        '%s: ' % name,
        progressbar.Percentage(),
        ' ',
        progressbar.Bar(),
        ' ',
        progressbar.ETA(),
        ' ',
        progressbar.DataSize(),
    ]
    return progressbar.ProgressBar(widgets=widgets, max_value=size)


def compute_digest(path, rel_path):
    algorithm = hashlib.sha256()
    size = os.path.getsize(path)
    with make_progress_bar(rel_path, size) as pbar:
        with io.open(path, 'rb') as file_:
            total_len = 0
            while True:
                buf = file_.read(BLOCKSIZE)
                if not buf:
                    break
                algorithm.update(buf)
                total_len += len(buf)
                pbar.update(total_len)
    return algorithm.hexdigest()


def lock_file(path):
    """remove writable permissions"""
    # click.echo('Locking file: %s' % path)
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    mask = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    os.chmod(path, perms & mask)


def unlock_file(path):
    """add writable permissions"""
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    os.chmod(path, perms | stat.S_IWUSR | stat.S_IWGRP)


def make_executable(path):
    """add executable permissions"""
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    os.chmod(path, perms | stat.S_IXUSR | stat.S_IXGRP)


def rmtree_err_handler(function, path, excinfo):
    excvalue = excinfo[1]
    if function == os.unlink and excvalue.errno == errno.EACCES:
        os.chmod(path, stat.S_IWUSR)
        function(path)


class DepotIndex(object):
    def __init__(self, path):
        self.__index = dict()
        self.path = path

    @property
    def index(self):
        self._load()
        return self.__index

    def has_digest(self, digest):
        return self.index.get(digest)

    def add_digest(self, digest, size):
        self.index[digest] = size
        self._save()

    def _load(self):
        self.__index = dict()
        if os.path.exists(self.path):
            with io.open(self.path, 'r', encoding='utf-8') as file_:
                for line in file_:
                    pair = line.rstrip().split(' ', 2)
                    if len(pair) == 2:
                        self.__index[pair[0]] = int(pair[1])

    def _save(self):
        dir_path = os.path.dirname(self.path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        with atomic_open(self.path, 'wb') as file_:
            for digest, size in self.__index.items():
                file_.write('{} {}\n'.format(digest, size).encode())


class Depot(object):
    def __init__(self, config, repo):
        self.config = config.depot
        self.repo = repo
        self.__storage = git_big.storage.get_driver(self.config)
        if not os.path.exists(config.cache_dir):
            os.makedirs(config.cache_dir)
        self.index = DepotIndex(os.path.join(config.cache_dir, 'index'))
        self.refs_path = self.config.make_path('refs', config.uuid)
        self.tmp_dir = os.path.join(config.cache_dir, 'tmp')
        if not os.path.exists(self.tmp_dir):
            os.makedirs(self.tmp_dir)

    def _entry(self, entry):
        # use an index to prevent having to query the depot when we know
        # for certain that the object exists in the bucket
        size = self.index.has_digest(entry.digest)
        if size is not None:
            entry._depot_size = size
            return

        size = self.__storage.has_object(entry.depot_path)
        if size is not None:
            entry._depot_size = size
            self.index.add_digest(entry.digest, size)

    def get_status(self, entry):
        self._entry(entry)

    def get(self, entry):
        self._entry(entry)
        if not entry.in_depot:
            click.echo('Object missing from depot: %s' % entry.digest)
            return
        # Make a temp location for download until we verify it's good
        tmp_file, tmp_path = tempfile.mkstemp(dir=self.tmp_dir)
        os.close(tmp_file)
        try:
            self.__storage.get_file(entry.depot_path, tmp_path)
            # Finalize and rename
            cache_dir = os.path.dirname(entry.cache_path)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            os.rename(tmp_path, entry.cache_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        # Lock and add to cache
        lock_file(entry.cache_path)
        self.index.add_digest(entry.digest, entry._depot_size)

    def put(self, entry):
        self._entry(entry)
        if not entry.in_depot:
            self.__storage.put_file(entry.depot_path, entry.cache_path)
            self.index.add_digest(entry.digest,
                                  os.path.getsize(entry.cache_path))

    def load_refs(self):
        refs = []
        obj = self.__storage.get_string(self.refs_path)
        if obj is None:
            return (None, None)
        for line in obj.data.splitlines():
            refs.append(line.rstrip())
        return (obj, refs)

    def save_refs(self, refs):
        metadata = {
            'host': socket.gethostname(),
            'user': getpass.getuser(),
            'path': self.repo.git_dir,
        }
        buf = '\n'.join(refs)
        self.__storage.put_string(self.refs_path, buf, metadata)

    def delete_refs(self):
        self.__storage.delete_object(self.refs_path)


class App(object):
    def __init__(self):
        self.repo = GitRepository()

        # Load user configuration, creating anew if none exists
        self.user_config_path = os.path.expanduser(
            os.path.join('~', '.gitbig'))
        if os.path.exists(self.user_config_path):
            with io.open(
                    self.user_config_path, 'r', encoding='utf-8') as file_:
                self.user_config = UserConfig(**json.load(file_))
        else:
            self.user_config = UserConfig()

        # Load repo configuration, creating anew if none exists
        self.repo_config_path = os.path.join(self.repo.working_dir, '.gitbig')
        if os.path.exists(self.repo_config_path):
            with io.open(
                    self.repo_config_path, 'r', encoding='utf-8') as file_:
                self.repo_config = self._load_config(file_)
        else:
            self.repo_config = RepoConfig()

        # Load git configuration
        self.git_config = GitConfig()

        # Combined view of overall configuration
        self.config = Config(self.repo_config, self.git_config,
                             self.user_config, self.repo.working_dir)

        if self.config.depot:
            self.depot = Depot(self.config, self.repo)
        else:
            self.depot = None

    def _check_depot(self, present_participle):
        if not self.depot:
            raise click.ClickException(
                'A depot must be configured before {}; run "git big set-depot"'.
                format(present_participle))

    def cmd_init(self):
        self._save_config()
        self._install_hooks()
        if not self.repo.is_bare:
            self._install_merger()

    def cmd_hooks_pre_push(self, remote, url):
        self.cmd_push()
        self._call_hook_chain('pre-push', remote, url)

    def cmd_hooks_post_checkout(self, previous, new, flag):
        self.cmd_pull()
        self._call_hook_chain('post-checkout', previous, new, flag)

    def cmd_hooks_post_merge(self, flag):
        self.cmd_pull()
        self._call_hook_chain('post-merge', flag)

    def cmd_status(self):
        click.echo('On branch %s' % self.repo.active_branch)
        click.echo()
        click.echo('  Working')
        click.echo('    Cache')
        click.echo('      Depot')
        click.echo('          SHA-256    Size Path')
        for entry in self._entries():
            if self.depot:
                self.depot.get_status(entry)
            if entry.is_linked:
                w_bit = 'W'
            elif entry.in_working:
                w_bit = '*'
            else:
                w_bit = ' '
            c_bit = entry.in_cache and 'C' or ' '
            d_bit = entry.in_depot and 'D' or ' '
            click.echo('[ {} {} {} ] {} {:>6} {}'.format(
                w_bit, c_bit, d_bit, entry.digest[:8], human_size(entry.size),
                entry.rel_path))
        click.echo()

    def cmd_add(self, paths):
        for path in self._walk(paths):
            self._add_file(path)
        self._save_config()

    def cmd_remove(self, paths):
        for path in self._walk(paths):
            self._remove_file(path)
        self._save_config()

    def cmd_unlock(self, paths):

        for path in self._walk(paths):
            self._unlock_file(path)
        self._save_config()

    def cmd_copy(self, srcs, tgt):
        for src, tgt in self._get_src_tgt_pairs(srcs, tgt):
            self._copy_file(src, tgt)
        self._save_config()

    def cmd_move(self, srcs, tgt):
        for src, tgt in self._get_src_tgt_pairs(srcs, tgt):
            self._move_file(src, tgt)
        self._save_config()

    def cmd_push(self):
        self._check_depot('pushing')
        for entry in self._entries():
            self.depot.put(entry)
        self.depot.save_refs(self._find_reachable_objects())

    def cmd_pull(self, paths=[], soft=True, extra=None):
        if paths:
            soft = False
        if not soft:
            self._check_depot('pulling')
        entries = list(self._entries(paths=paths))
        if paths and not entries:
            click.echo('Nothing to pull.')
            raise SystemExit(1)
        multi = len(entries) > 1
        # clear the anchors on each full pull
        if os.path.exists(self.config.anchors_dir) and not paths:
            shutil.rmtree(self.config.anchors_dir, onerror=rmtree_err_handler)
        # now go thru the index and populate all the anchors
        for entry in entries:
            # grab a copy from the depot if it exists
            if not entry.in_cache and self.depot and not soft:
                self.depot.get(entry)
            if entry.in_cache:
                # add hardlink from the anchor to the cache
                if not entry.in_anchors:
                    anchor_dir = os.path.dirname(entry.anchor_path)
                    if not os.path.exists(anchor_dir):
                        os.makedirs(anchor_dir)
                    fs.link(entry.cache_path, entry.anchor_path)
                # add a symlink from the working path to the anchor
                if not entry.in_working:
                    click.echo('Linking: %s -> %s' % (entry.digest[:8],
                                                      entry.rel_path))
                    entry_dir = os.path.dirname(entry.working_path)
                    if not os.path.exists(entry_dir):
                        os.makedirs(entry_dir)
                    fs.symlink(entry.symlink_path, entry.working_path)
                elif not entry.is_link:
                    click.echo('Pull aborted, dirty file detected: "%s"' %
                               entry.rel_path)
                    raise SystemExit(1)
                # if specified, add an extra hardlink to a user-defined location
                if extra:
                    if multi:
                        # if multiple paths should be pulled,
                        # treat the specified hardlink path as a directory
                        filename = os.path.basename(entry.working_path)
                        extra_path = os.path.join(extra, filename)
                    else:
                        # otherwise treat the hardlink as a path to the target
                        extra_path = extra
                    click.echo(
                        'Linking: %s -> %s' % (entry.digest[:8], extra_path))
                    extra_dir = os.path.dirname(extra_path)
                    if not os.path.exists(extra_dir):
                        os.makedirs(extra_dir)
                    fs.link(entry.cache_path, extra_path)
            else:
                click.echo(
                    'File "{}" not available locally; use `git big pull --hard` to download it'.
                    format(entry.rel_path))
        self.depot.save_refs(self._find_reachable_objects())

    def cmd_drop(self):
        self._check_depot('dropping')
        self.depot.delete_refs()

    def cmd_reachable(self):
        for digest in self._find_reachable_objects():
            click.echo(digest)
        obj, _ = self.depot.load_refs()
        if obj:
            click.echo(obj.last_modified)
            click.echo(obj.metadata)

    def cmd_check(self):
        """Do an integrity check of the local cache"""
        for root, _, files in os.walk(self.config.objects_dir):
            for file_ in files:
                path = os.path.join(root, file_)
                digest = compute_digest(path, file_[8:])
                if file_ != digest:
                    click.echo('Error: mismatched content.')
                    click.echo('  Path: %s' % path)
                    click.echo('  Hash: %s' % digest)

    def cmd_custom_merge(self, ancestor_path, current_path, other_path):  # pylint: disable=W0613
        with io.open(current_path, 'r', encoding='utf-8') as file_:
            current = self._load_config(file_)
        with io.open(other_path, 'r', encoding='utf-8') as file_:
            other = self._load_config(file_)
        current.merge(other)
        with atomic_open(current_path, 'wb') as file_:
            file_.write(json.dumps(dict(current), indent=4).encode())
            file_.write('\n'.encode())

    def _find_reachable_objects(self):
        reachable = set()
        objects = set()
        rev_list = git('rev-list', '--objects', '--all', '--', '.gitbig')
        for line in rev_list.splitlines():
            parts = line.split()
            if len(parts) > 1 and parts[1] == '.gitbig':
                objects.add(parts[0])
        for obj in objects:
            raw_index = git('show', obj)
            index = RepoConfig(**json.loads(raw_index))
            for digest in six.itervalues(index.files):
                reachable.add(digest)
        return reachable

    def _load_config(self, file_):
        return RepoConfig(**json.load(file_))

    def _save_config(self):
        self.git_config.save()

        with atomic_open(self.user_config_path, 'wb') as file_:
            file_.write(json.dumps(dict(self.user_config), indent=4).encode())
            file_.write('\n'.encode())

        if self.repo_config.files:
            with atomic_open(self.repo_config_path, 'wb') as file_:
                file_.write(
                    json.dumps(dict(self.repo_config), indent=4).encode())
                file_.write('\n'.encode())
            self.repo.index.add([self.repo_config_path])
        else:
            if os.path.exists(self.repo_config_path):
                os.unlink(self.repo_config_path)
                self.repo.index.remove([self.repo_config_path])

        exclude_path = os.path.join(self.repo.git_dir, 'info', 'exclude')
        self._ensure_line(exclude_path, '/.gitbig-anchors')

    def _ensure_line(self, path, to_add):
        changed = False
        lines = []
        if os.path.exists(path):
            with io.open(path, 'r', encoding='utf-8') as file_:
                for line in file_:
                    lines.append(line.rstrip())
        if to_add not in lines:
            lines.append(to_add)
            changed = True
        with atomic_open(path, 'wb') as file_:
            for line in lines:
                file_.write(line.encode())
                file_.write('\n'.encode())
        return changed

    def _install_hooks(self):
        self._install_hook('pre-push', 2)
        self._install_hook('post-checkout', 3)
        self._install_hook('post-merge', 1)

    def _install_merger(self):
        gitattrs = '.gitattributes'
        gitattrs_path = os.path.join(self.repo.working_dir, gitattrs)
        changed = self._ensure_line(gitattrs_path, '.gitbig merge=git-big')
        if changed:
            self.repo.index.add([gitattrs])

    def _install_hook(self, hook, nargs):
        args = ' '.join(['$%s' % x for x in range(1, nargs + 1)])
        hook_content = '#!/bin/sh\nexec git big hooks %s %s\n' % (hook, args)
        hooks_dir = os.path.join(self.repo.git_dir, 'hooks')
        hook_path = os.path.join(hooks_dir, hook)
        if os.path.exists(hook_path):
            with io.open(hook_path, 'r', encoding='utf-8') as file_:
                existing_content = file_.read()
            if existing_content == hook_content:
                return
            os.rename(hook_path, os.path.join(hooks_dir, '%s.git-big' % hook))
        with atomic_open(hook_path, 'wb') as file_:
            file_.write(hook_content.encode())
        make_executable(hook_path)

    def _call_hook_chain(self, hook, *args):
        hooks_dir = os.path.join(self.repo.git_dir, 'hooks')
        hook_path = os.path.join(hooks_dir, '%s.git-big' % hook)
        if not os.path.exists(hook_path):
            return
        os.execv(hook_path, [hook_path] + list(args))

    def _entries(self, paths=[]):
        keys = sorted(self.config.files.keys())
        for rel_path in keys:
            digest = self.config.files[rel_path]
            if not paths or rel_path in paths:
                yield Entry(self.config, rel_path, digest)

    def _walk(self, paths):
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file_ in files:
                        yield os.path.join(root, file_)
            else:
                yield path

    def _add_file(self, path):
        if fs.islink(path):
            return

        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        digest = compute_digest(path, rel_path)
        entry = Entry(self.config, rel_path, digest)

        if not entry.in_cache:
            cache_dir = os.path.dirname(entry.cache_path)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            os.rename(entry.working_path, entry.cache_path)
            lock_file(entry.cache_path)
        else:
            os.unlink(entry.working_path)

        if not entry.in_anchors:
            anchor_dir = os.path.dirname(entry.anchor_path)
            if not os.path.exists(anchor_dir):
                os.makedirs(anchor_dir)
            fs.link(entry.cache_path, entry.anchor_path)

        fs.symlink(entry.symlink_path, entry.working_path)
        self.repo.index.add([entry.working_path])

        self.repo_config.files[rel_path] = digest

    def _remove_file(self, path):
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        if os.path.exists(path):
            os.unlink(path)
        digest = self.repo_config.files.get(rel_path)
        if not digest:
            return
        entry = Entry(self.config, rel_path, digest)
        self.repo.index.remove([entry.working_path])
        click.echo(rel_path)
        del self.repo_config.files[rel_path]

    def _copy_via_chunk(self, src, dst):
        size = os.path.getsize(src)
        rel_path = os.path.relpath(os.path.abspath(dst), self.repo.working_dir)
        with io.open(src, 'rb') as src_file_, atomic_open(dst,
                                                          'wb') as dst_file_:
            with make_progress_bar(rel_path, size) as pbar:
                copied = 0
                while True:
                    buf = src_file_.read(BLOCKSIZE)
                    if not buf:
                        break
                    dst_file_.write(buf)
                    copied += len(buf)
                    pbar.update(copied)

    def _unlock_file(self, path):
        if not fs.islink(path):
            return
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        digest = self.repo_config.files.get(rel_path)
        if not digest:
            return
        entry = Entry(self.config, rel_path, digest)
        os.unlink(entry.working_path)
        self.repo.index.remove([entry.working_path])
        self._copy_via_chunk(entry.cache_path, entry.working_path)
        unlock_file(entry.working_path)
        del self.repo_config.files[rel_path]

    def _get_src_tgt_pairs(self, srcs, tgt):
        if len(srcs) > 1:
            if not os.path.isdir(tgt):
                click.echo(
                    'Destination must be a directory when specifying multiple sources'
                )
                return
            for src in srcs:
                yield (src, os.path.join(tgt, os.path.basename(src)))
        else:
            if os.path.isdir(tgt):
                yield (srcs[0], os.path.join(tgt, os.path.basename(srcs[0])))
            else:
                yield (srcs[0], tgt)

    def _copy_file(self, src, tgt):
        rel_tgt = os.path.relpath(os.path.abspath(tgt), self.repo.working_dir)
        if rel_tgt.startswith('..') or rel_tgt.startswith('/'):
            click.echo('Destination must be inside repository: %s' % tgt)
            return

        rel_src = os.path.relpath(os.path.abspath(src), self.repo.working_dir)
        digest = self.repo_config.files.get(rel_src)
        if not digest:
            click.echo('Source not in index: %s' % src)

        entry = Entry(self.config, rel_tgt, digest)
        fs.symlink(entry.symlink_path, entry.working_path)
        self.repo.index.add([entry.working_path])
        self.repo_config.files[rel_tgt] = digest

    def _move_file(self, src, tgt):
        rel_src = os.path.relpath(os.path.abspath(src), self.repo.working_dir)
        rel_tgt = os.path.relpath(os.path.abspath(tgt), self.repo.working_dir)
        if rel_tgt.startswith('..') or rel_tgt.startswith('/'):
            click.echo('Destination must be inside repository: %s' % tgt)
            return

        rel_src = os.path.relpath(os.path.abspath(src), self.repo.working_dir)
        digest = self.repo_config.files.get(rel_src)
        if not digest:
            click.echo('Source not in index: %s' % src)

        src_entry = Entry(self.config, rel_src, digest)
        tgt_entry = Entry(self.config, rel_tgt, digest)
        fs.symlink(tgt_entry.symlink_path, tgt_entry.working_path)
        os.unlink(src_entry.working_path)
        self.repo.index.add([tgt_entry.working_path])
        self.repo.index.remove([src_entry.working_path])
        self.repo_config.files[rel_tgt] = digest
        del self.repo_config.files[rel_src]


@click.group(context_settings=CTX_SETTINGS)
def cli():
    """git big file manager"""
    pass


@cli.command()
@click.argument('topic', default=None, required=False, nargs=1)
@click.pass_context
def help(ctx, topic, **kw):
    """Show this message and exit."""
    if topic is None:
        click.echo(ctx.parent.get_help())
    else:
        click.echo(cli.commands[topic].get_help(ctx))


@cli.command('version')
def cmd_version():
    """Print version and exit."""
    click.echo(__version__)


@cli.command('init')
def cmd_init():
    """Initialize a repository."""
    App().cmd_init()


@cli.command('set-depot')
@click.option('--url', prompt='Depot URL', help='The URL of the git-big depot')
@click.option('--secret', prompt=True, help='The git-big depot secret')
@click.option('--key', prompt=True, help='The git-big depot key')
def cmd_set_depot(url, secret, key):
    """Sets depot configuration."""
    git('config', 'git-big.depot.url', url)
    git('config', 'git-big.depot.key', key)
    git('config', 'git-big.depot.secret', secret)


@cli.command('clone')
@click.argument('repo')
@click.argument('to_path', required=False)
@click.option('--soft/--hard', default=True)
def cmd_clone(repo, to_path, soft):
    """Clone a repository with big files."""
    if not to_path:
        to_path = re.split('[:/]', repo.rstrip('/').rstrip('.git'))[-1]
    os.system('git clone %s %s' % (repo, to_path))
    os.chdir(to_path)
    app = App()
    app.cmd_init()
    app.cmd_pull(soft=soft)


@cli.command('status')
def cmd_status():
    """View big file status.
    Shows the status of each file recognized by git-big.
    """
    App().cmd_status()


@cli.command('add')
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_add(paths):
    """Add big files.

    Each specified path will be added to git-big.
    If a path refers to a directory, all files within the directory will be recursively added to the index.
    """
    App().cmd_add(paths)


@cli.command('rm')
@click.argument('paths', nargs=-1, type=click.Path())
def cmd_remove(paths):
    """Remove big files.

    Each specified path will be removed from git-big.
    If a path refers to a directory, all files within the directory will be recursively removed from the index.
    """
    App().cmd_remove(paths)


@cli.command('unlock')
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_unlock(paths):
    """Unlock big files.

    When a file is added to git-big, the working copy is set to read-only mode
    to prevent from accidental overwrites or deletions.
    Use this command to allow the file to be modified.
    The file must be added back to git-big when changes are complete.
    """
    App().cmd_unlock(paths)


@cli.command('mv')
@click.argument('sources', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=1, type=click.Path())
def cmd_move(sources, dest):
    """Move big files.

    Moves a big file in the same way that git mv would usually work.
    The index will be updated to refer to the new location of moved files.
    """
    App().cmd_move(sources, dest)


@cli.command('cp')
@click.argument('sources', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=1, type=click.Path())
def cmd_copy(sources, dest):
    """Copy big files.

    Copies a big file in the same way that git cp would usually work.
    The index will be updated to refer to the old and new location of copied files.
    """
    App().cmd_copy(sources, dest)


@cli.command('push')
def cmd_push():
    """Push big files.

    Uploads big files to any configured depot.
    """
    App().cmd_push()


@cli.command('pull')
@click.argument('paths', nargs=-1, type=click.Path())
@click.option('--soft/--hard', default=True)
@click.option('--extra', type=click.Path(writable=True, resolve_path=True))
def cmd_pull(paths, soft, extra):
    """Pull big files.

    Downloads big files from any configured depot.
    """
    App().cmd_pull(paths=paths, soft=soft, extra=extra)


@cli.command('drop')
def cmd_drop():
    """Internal command"""
    App().cmd_drop()


@cli.group('hooks')
def cmd_hooks():
    """Internal command"""
    pass


@cmd_hooks.command('pre-push')
@click.argument('remote')
@click.argument('url')
def cmd_hooks_pre_push(remote, url):
    App().cmd_hooks_pre_push(remote, url)


@cmd_hooks.command('post-checkout')
@click.argument('previous')
@click.argument('new')
@click.argument('flag')
def cmd_hooks_post_checkout(previous, new, flag):
    """Internal command"""
    App().cmd_hooks_post_checkout(previous, new, flag)


@cmd_hooks.command('post-merge')
@click.argument('flag')
def cmd_hooks_post_merge(flag):
    """Internal command"""
    App().cmd_hooks_post_merge(flag)


@cli.group('dev')
def dev():
    """Internal command"""
    pass


@dev.command('reachable')
def cmd_reachable():
    """Internal command"""
    App().cmd_reachable()


@dev.command('check')
def cmd_check():
    """Internal command"""
    App().cmd_check()


@cli.group('filter')
def cmd_filter():
    """Internal command"""
    pass


@cmd_filter.command('process')
def cmd_process():
    """Internal command"""
    import git_big.filter
    git_big.filter.cmd_process()


@cli.command('merge-driver')
@click.argument('ancestor', default='default')
@click.argument('current', default='default')
@click.argument('other', default='default')
def cmd_custom_merge(ancestor, current, other):
    """Internal command"""
    App().cmd_custom_merge(ancestor, current, other)


if IS_WIN:

    @cli.command('windows-setup')
    def cmd_windows_setup():
        """Configures Windows systems for git-big."""
        import git_big.windows
        git_big.windows.setup()


def main():
    if IS_WIN:
        import git_big.windows
        if not git_big.windows.check():
            click.echo(
                'git-big requires symlinks to be enabled; run `git big windows-setup`'
            )
            sys.exit(1)
    if not os.path.exists(DEFAULT_CACHE_DIR):
        os.makedirs(DEFAULT_CACHE_DIR)
    lock_path = os.path.join(DEFAULT_CACHE_DIR, 'lock')
    with Singlet(lock_path):
        cli()
