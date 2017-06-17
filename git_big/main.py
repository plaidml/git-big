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

import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import urlparse
import uuid
from StringIO import StringIO

import click
from libcloud import DriverType, get_driver
from libcloud.storage.types import ObjectDoesNotExistError

from . import __version__

BLOCKSIZE = 64 * 1024
CTX_SETTINGS = dict(help_option_names=['-h', '--help'])
DEV_NULL = open(os.devnull, 'w')

DRIVER_ALIASES = {
    'gs': 'google_storage',
}


def git(*args):
    return subprocess.check_output(['git'] + map(str, args), stderr=DEV_NULL)


class GitIndex(object):
    def add(self, paths):
        for path in paths:
            git('add', path)

    def remove(self, paths):
        for path in paths:
            git('rm', path)


class GitRepository(object):
    def __init__(self):
        try:
            self.git_dir = git('rev-parse', '--git-common-dir').rstrip()
        except subprocess.CalledProcessError:
            raise click.ClickException('git or git repository not found')
        self.working_dir = git('rev-parse', '--show-toplevel').rstrip()
        self.index = GitIndex()

    @property
    def active_branch(self):
        return git('rev-parse', '--abbrev-ref', 'HEAD').rstrip()


class DepotConfig(object):
    def __init__(self, **kwargs):
        self.__url = None
        self.__url_parts = None
        self.url = kwargs.get('url')
        self.key = kwargs.get('key')
        self.secret = kwargs.get('secret')

    def __iter__(self):
        yield 'url', self.url
        yield 'key', self.key
        yield 'secret', self.secret

    @property
    def url(self):
        return self.__url

    @url.setter
    def url(self, value):
        self.__url = value
        if value:
            self.__url_parts = urlparse.urlparse(value)

    @property
    def driver(self):
        scheme = self.__url_parts.scheme
        return DRIVER_ALIASES.get(scheme, scheme)

    @property
    def bucket(self):
        return self.__url_parts.hostname

    @property
    def prefix(self):
        return self.__url_parts.path

    def make_path(self, *paths):
        return '/'.join(map(str, paths))


class UserConfig(object):
    default_cache_dir = os.path.expanduser('~/.cache/git-big')

    def __init__(self, **kwargs):
        self.version = 1
        self.cache_dir = kwargs.get('cache_dir', self.default_cache_dir)
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
        yield 'files', self.files


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


class Config(RepoConfig):
    def __init__(self, repo_config, git_config, user_config):
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


class Entry(object):
    def __init__(self, config, repo, rel_path, digest):
        self.rel_path = rel_path
        self.digest = digest
        self.working_path = os.path.join(repo.working_dir, self.rel_path)
        self.anchor_path = os.path.join(repo.working_dir, '.gitbig-anchors',
                                        self.digest[:2], self.digest[2:4],
                                        self.digest)
        self.symlink_path = os.path.relpath(self.anchor_path,
                                            os.path.dirname(self.working_path))
        self.cache_path = os.path.join(config.objects_dir, self.digest[:2],
                                       self.digest[2:4], self.digest)
        if config.depot:
            self.depot_path = config.depot.make_path('objects', self.digest)
        else:
            self.depot_path = None
        self.depot_object = None
        self.in_depot = False

    @property
    def in_cache(self):
        return os.path.exists(self.cache_path)

    @property
    def in_anchors(self):
        return os.path.exists(self.anchor_path)

    @property
    def is_link(self):
        return os.path.islink(self.working_path)

    @property
    def in_working(self):
        return os.path.exists(self.working_path)

    @property
    def is_linked(self):
        return self.in_anchors and self.is_link and \
            os.readlink(self.working_path) == self.symlink_path


def compute_digest(path):
    algorithm = hashlib.sha256()
    with open(path, 'rb') as file_:
        while True:
            buf = file_.read(BLOCKSIZE)
            if not buf:
                break
            algorithm.update(buf)
    return algorithm.hexdigest()


def lock_file(path):
    '''remove writable permissions'''
    # click.echo('Locking file: %s' % path)
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    mask = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    os.chmod(path, perms & mask)


def unlock_file(path):
    '''add writable permissions'''
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    os.chmod(path, perms | stat.S_IWUSR | stat.S_IWGRP)


def make_executable(path):
    '''add executable permissions'''
    if not os.path.exists(path):
        return
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    os.chmod(path, perms | stat.S_IXUSR | stat.S_IXGRP)


class DepotIndex(object):
    def __init__(self, path):
        self.__index = set()
        self.path = path

    @property
    def index(self):
        self._load()
        return self.__index

    def has_digest(self, digest):
        return digest in self.index

    def add_digest(self, digest):
        self.index.add(digest)
        self._save()

    def _load(self):
        self.__index = set()
        if os.path.exists(self.path):
            with open(self.path, 'r') as file_:
                for line in file_:
                    self.__index.add(line.rstrip())

    def _save(self):
        dir_path = os.path.dirname(self.path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)
        with open(self.path, 'w') as file_:
            for digest in self.__index:
                file_.write(digest + '\n')


class Depot(object):
    def __init__(self, config, repo):
        self.config = config.depot
        self.repo = repo
        self.__bucket = None
        self.index = DepotIndex(os.path.join(config.cache_dir, 'index'))
        self.refs_path = self.config.make_path('refs', config.uuid)

    @property
    def bucket(self):
        if not self.__bucket:
            driver = get_driver(DriverType.STORAGE, self.config.driver)
            service = driver(self.config.key, self.config.secret)
            self.__bucket = service.get_container(self.config.bucket)
        return self.__bucket

    def _entry(self, entry):
        # use an index to prevent having to query the depot when we know
        # for certain that the object exists in the bucket
        if self.index.has_digest(entry.digest):
            entry.in_depot = True
            return

        try:
            entry.depot_object = self.bucket.get_object(entry.depot_path)
            entry.in_depot = True
            self.index.add_digest(entry.digest)
        except ObjectDoesNotExistError:
            pass

    def get_status(self, entry):
        self._entry(entry)

    def get(self, entry):
        self._entry(entry)
        if not entry.in_depot:
            click.echo('Object missing from depot: %s' % entry.digest)
            return
        click.echo('Pulling object: %s' % entry.digest)
        if not entry.depot_object:
            entry.depot_object = self.bucket.get_object(entry.depot_path)
        cache_dir = os.path.dirname(entry.cache_path)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        entry.depot_object.download(entry.cache_path)
        lock_file(entry.cache_path)
        self.index.add_digest(entry.digest)

    def put(self, entry):
        self._entry(entry)
        if not entry.in_depot:
            click.echo('Pushing object: %s' % entry.digest)
            self.bucket.upload_object(entry.cache_path, entry.depot_path)
            self.index.add_digest(entry.digest)

    def load_refs(self):
        refs = []
        try:
            obj = self.bucket.get_object(self.refs_path)
        except ObjectDoesNotExistError:
            return (None, refs)
        stream = obj.as_stream()
        for line in stream:
            refs.append(line.rstrip())
        return (obj, refs)

    def save_refs(self, refs):
        extra = {
            'meta_data': {
                'host': socket.gethostname(),
                'user': getpass.getuser(),
                'path': self.repo.git_dir,
            }
        }
        buf = '\n'.join(refs)
        stream = StringIO(buf)
        self.bucket.upload_object_via_stream(
            stream, self.refs_path, extra=extra)

    def delete_refs(self):
        try:
            obj = self.bucket.get_object(self.refs_path)
        except ObjectDoesNotExistError:
            return
        self.bucket.delete_object(obj)


class App(object):
    def __init__(self):
        self.repo = GitRepository()

        # Load user configuration, creating anew if none exists
        self.user_config_path = os.path.expanduser('~/.gitbig')
        if os.path.exists(self.user_config_path):
            with open(self.user_config_path, 'r') as file_:
                self.user_config = UserConfig(**json.load(file_))
        else:
            self.user_config = UserConfig()

        # Load repo configuration, creating anew if none exists
        self.repo_config_path = os.path.join(self.repo.working_dir, '.gitbig')
        if os.path.exists(self.repo_config_path):
            with open(self.repo_config_path, 'r') as file_:
                self.repo_config = self._load_config(file_)
        else:
            self.repo_config = RepoConfig()

        # Load git configuration
        self.git_config = GitConfig()

        # Combined view of overall configuration
        self.config = Config(self.repo_config, self.git_config,
                             self.user_config)

        if self.config.depot:
            self.depot = Depot(self.config, self.repo)
        else:
            self.depot = None

    def cmd_init(self):
        self._save_config()
        self._install_hooks()

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
        click.echo()
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
            click.echo('[ %s %s %s ] %s %s' %
                       (w_bit, c_bit, d_bit, entry.digest[:8], entry.rel_path))
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
        if not self.depot:
            click.echo('A depot must be configured before pushing.')
            return
        for entry in self._entries():
            self.depot.put(entry)
        self.depot.save_refs(self._find_reachable_objects())

    def cmd_pull(self):
        for entry in self._entries():
            if not entry.in_cache and self.depot:
                self.depot.get(entry)
            if entry.in_cache:
                if not entry.in_anchors:
                    anchor_dir = os.path.dirname(entry.anchor_path)
                    if not os.path.exists(anchor_dir):
                        os.makedirs(anchor_dir)
                    os.link(entry.cache_path, entry.anchor_path)

                if not entry.in_working:
                    click.echo('Linking: %s -> %s' % (entry.digest,
                                                      entry.rel_path))
                    entry_dir = os.path.dirname(entry.working_path)
                    if not os.path.exists(entry_dir):
                        os.makedirs(entry_dir)
                    os.symlink(entry.symlink_path, entry.working_path)
                elif not entry.is_link:
                    click.echo('Pull aborted, dirty file detected: "%s"' %
                               entry.rel_path)
                    raise SystemExit(1)
            else:
                click.echo('Missing object for file: %s' % entry.rel_path)
        self.depot.save_refs(self._find_reachable_objects())

    def cmd_drop(self):
        if not self.depot:
            click.echo('A depot must be configured.')
            return
        self.depot.delete_refs()

    def cmd_reachable(self):
        for digest in self._find_reachable_objects():
            click.echo(digest)
        obj, _ = self.depot.load_refs()
        if obj:
            click.echo(obj.extra)
            click.echo(obj.meta_data)

    def cmd_check(self):
        '''Do an integrity check of the local cache'''
        for root, _, files in os.walk(self.config.objects_dir):
            for file_ in files:
                path = os.path.join(root, file_)
                digest = compute_digest(path)
                if file_ != digest:
                    click.echo('Error: mismatched content.')
                    click.echo('  Path: %s' % path)
                    click.echo('  Hash: %s' % digest)

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
            for digest in index.files.itervalues():
                reachable.add(digest)
        return reachable

    def _load_config(self, file_):
        return RepoConfig(**json.load(file_))

    def _save_config(self):
        self.git_config.save()

        with open(self.user_config_path, 'w') as file_:
            json.dump(dict(self.user_config), file_, indent=4)
            file_.write('\n')

        if self.repo_config.files:
            with open(self.repo_config_path, 'w') as file_:
                json.dump(dict(self.repo_config), file_, indent=4)
                file_.write('\n')
            self.repo.index.add([self.repo_config_path])
        else:
            if os.path.exists(self.repo_config_path):
                os.unlink(self.repo_config_path)
                self.repo.index.remove([self.repo_config_path])

        rule = '/.gitbig-anchors'
        lines = []
        exclude_path = os.path.join(self.repo.git_dir, 'info', 'exclude')
        with open(exclude_path, 'r') as file_:
            for line in file_:
                lines.append(line.rstrip())
        if rule not in lines:
            lines.append(rule)
        with open(exclude_path, 'w') as file_:
            for line in lines:
                file_.write(line + '\n')

    def _install_hooks(self):
        self._install_hook('pre-push', 2)
        self._install_hook('post-checkout', 3)
        self._install_hook('post-merge', 1)

    def _install_hook(self, hook, nargs):
        args = ' '.join(['$%s' % x for x in range(1, nargs + 1)])
        hook_content = '#!/bin/sh\nexec git big hooks %s %s\n' % (hook, args)
        hooks_dir = os.path.join(self.repo.git_dir, 'hooks')
        hook_path = os.path.join(hooks_dir, hook)
        if os.path.exists(hook_path):
            with open(hook_path, 'r') as file_:
                existing_content = file_.read()
            if existing_content == hook_content:
                return
            os.rename(hook_path, os.path.join(hooks_dir, '%s.git-big' % hook))
        with open(hook_path, 'w') as file_:
            file_.write(hook_content)
        make_executable(hook_path)

    def _call_hook_chain(self, hook, *args):
        hooks_dir = os.path.join(self.repo.git_dir, 'hooks')
        hook_path = os.path.join(hooks_dir, '%s.git-big' % hook)
        if not os.path.exists(hook_path):
            return
        os.execv(hook_path, [hook_path] + list(args))

    def _entries(self):
        for rel_path, digest in self.config.files.iteritems():
            yield Entry(self.config, self.repo, rel_path, digest)

    def _walk(self, paths):
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file_ in files:
                        yield os.path.join(root, file_)
            else:
                yield path

    def _add_file(self, path):
        if os.path.islink(path):
            return

        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        digest = compute_digest(path)
        click.echo(rel_path)
        entry = Entry(self.config, self.repo, rel_path, digest)

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
            os.link(entry.cache_path, entry.anchor_path)

        os.symlink(entry.symlink_path, entry.working_path)
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
        entry = Entry(self.config, self.repo, rel_path, digest)
        self.repo.index.remove([entry.working_path])
        if rel_path in self.repo_config.files:
            click.echo(rel_path)
            del self.repo_config.files[rel_path]

    def _unlock_file(self, path):
        if not os.path.islink(path):
            return
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        digest = self.repo_config.files.get(rel_path)
        if not digest:
            return
        entry = Entry(self.config, self.repo, rel_path, digest)

        os.unlink(entry.working_path)
        self.repo.index.remove([entry.working_path])
        shutil.copy2(entry.cache_path, entry.working_path)
        unlock_file(entry.working_path)

        if rel_path in self.repo_config.files:
            del self.repo_config.files[rel_path]

    def _get_src_tgt_pairs(self, srcs, tgt):
        if len(srcs) > 1:
            if not os.path.isdir(tgt):
                click.echo(
                    'Destination must be a directoy when specifying multiple sources'
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

        entry = Entry(self.config, self.repo, rel_tgt, digest)
        os.symlink(entry.symlink_path, entry.working_path)
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

        src_entry = Entry(self.config, self.repo, rel_src, digest)
        tgt_entry = Entry(self.config, self.repo, rel_tgt, digest)
        os.symlink(tgt_entry.symlink_path, tgt_entry.working_path)
        os.unlink(src_entry.working_path)
        self.repo.index.add([tgt_entry.working_path])
        self.repo.index.remove([src_entry.working_path])
        self.repo_config.files[rel_tgt] = digest
        del self.repo_config.files[rel_src]


@click.group(context_settings=CTX_SETTINGS)
def cli():
    '''git big file manager'''
    pass


@cli.command()
@click.argument('topic', default=None, required=False, nargs=1)
@click.pass_context
def help(ctx, topic, **kw):
    '''Show this message and exit.'''
    if topic is None:
        click.echo(ctx.parent.get_help())
    else:
        click.echo(cli.commands[topic].get_help(ctx))


@cli.command('version')
def cmd_version():
    '''Print version and exit'''
    click.echo(__version__)


@cli.command('init')
def cmd_init():
    '''Initialize big files'''
    App().cmd_init()


@cli.command('clone')
@click.argument('repo')
@click.argument('to_path', required=False)
def cmd_clone(repo, to_path):
    '''Clone a repository with big files'''
    if not to_path:
        to_path = re.split('[:/]', repo.rstrip('/').rstrip('.git'))[-1]
    os.system('git clone %s %s' % (repo, to_path))
    os.chdir(to_path)
    app = App()
    app.cmd_init()
    app.cmd_pull()


@cli.command('status')
def cmd_status():
    '''View big file status'''
    App().cmd_status()


@cli.command('add')
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_add(paths):
    '''Add big files'''
    App().cmd_add(paths)


@cli.command('rm')
@click.argument('paths', nargs=-1, type=click.Path())
def cmd_remove(paths):
    '''Remove big files'''
    App().cmd_remove(paths)


@cli.command('unlock')
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_unlock(paths):
    '''Unlock big files'''
    App().cmd_unlock(paths)


@cli.command('mv')
@click.argument('sources', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=1, type=click.Path())
def cmd_move(sources, dest):
    '''Move big files'''
    App().cmd_move(sources, dest)


@cli.command('cp')
@click.argument('sources', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=1, type=click.Path())
def cmd_copy(sources, dest):
    '''Copy big files'''
    App().cmd_copy(sources, dest)


@cli.command('push')
def cmd_push():
    '''Push big files'''
    App().cmd_push()


@cli.command('pull')
def cmd_pull():
    '''Pull big files'''
    App().cmd_pull()


@cli.command('drop')
def cmd_drop():
    '''Notify depot that repository is gone'''
    App().cmd_drop()


@cli.group('hooks')
def cmd_hooks():
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
    App().cmd_hooks_post_checkout(previous, new, flag)


@cmd_hooks.command('post-merge')
@click.argument('flag')
def cmd_hooks_post_merge(flag):
    App().cmd_hooks_post_merge(flag)


@cli.group('dev')
def dev():
    pass


@dev.command('reachable')
def cmd_reachable():
    App().cmd_reachable()


@dev.command('check')
def cmd_check():
    App().cmd_check()


@cli.group('filter')
def cmd_filter():
    pass


@cmd_filter.command('process')
def cmd_process():
    import git_big.filter
    git_big.filter.cmd_process()
