from __future__ import print_function

import hashlib
import json
import os
import shutil
import stat
import tempfile

import click
import git
from libcloud import DriverType, get_driver
from libcloud.storage.types import ObjectDoesNotExistError

from . import __version__

CTX_SETTINGS = dict(help_option_names=['-h', '--help'])
BLOCKSIZE = 64 * 1024


class DepotConfig(object):
    def __init__(self, **kwargs):
        self.driver = kwargs.get('driver')
        self.key = kwargs.get('key')
        self.secret = kwargs.get('secret')
        self.bucket = kwargs.get('bucket')

    def __iter__(self):
        yield 'driver', self.driver
        yield 'key', self.key
        yield 'secret', self.secret
        yield 'bucket', self.bucket


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


class RepoConfig(UserConfig):
    def __init__(self, **kwargs):
        super(RepoConfig, self).__init__(**kwargs)
        self.files = kwargs.get('files', {})
        self.tracking = kwargs.get('tracking', {})

    def __iter__(self):
        yield 'version', self.version
        if self.cache_dir != self.default_cache_dir:
            yield 'cache_dir', self.cache_dir
        if self.depot.driver:
            yield 'depot', dict(self.depot)
        yield 'files', self.files
        yield 'tracking', self.tracking


class Config(RepoConfig):
    def __init__(self, user_config, repo_config):
        super(Config, self).__init__()
        self.cache_dir = repo_config.cache_dir or user_config.cache_dir
        if repo_config.depot.driver:
            self.depot = repo_config.depot
        elif user_config.depot.driver:
            self.depot = user_config.depot
        else:
            self.depot = None
        self.files = repo_config.files
        self.tracking = repo_config.tracking


class Entry(object):
    def __init__(self, rel_path, digest):
        self.rel_path = rel_path
        self.digest = digest
        self.working_path = None
        self.working_inode = None
        self.cache_path = None
        self.cache_inode = None
        self.depot_object = None
        self.in_working = False
        self.in_cache = False
        self.in_depot = False


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


class GitIgnore(object):
    def __init__(self, repo):
        self.gitignore_path = os.path.join(repo.working_dir, '.gitignore')
        self.dirty = False
        self.lines = []

    def load(self):
        if os.path.exists(self.gitignore_path):
            with open(self.gitignore_path, 'r') as file_:
                for line in file_:
                    self.lines.append(line.rstrip())

    def save(self):
        if self.dirty:
            with open(self.gitignore_path, 'w') as file_:
                for line in self.lines:
                    file_.write(line + '\n')

    def ignore(self, rel_path):
        rule = '/' + rel_path
        if rule not in self.lines:
            self.lines.append(rule)
            self.dirty = True

    def unignore(self, rel_path):
        rule = '/' + rel_path
        if rule in self.lines:
            self.lines.remove(rule)
            self.dirty = True


class Depot(object):
    def __init__(self, config):
        self.config = config.depot
        driver = get_driver(DriverType.STORAGE, self.config.driver)
        self.service = driver(self.config.key, self.config.secret)
        self.bucket = self.service.get_container(self.config.bucket)
        self.index_path = os.path.join(config.cache_dir, 'index')
        self.index = set()

    def _entry(self, entry):
        self._load_index()

        entry.depot_path = 'objects/' + entry.digest

        if entry.digest in self.index:
            entry.in_depot = True
            return

        try:
            entry.depot_object = self.bucket.get_object(entry.depot_path)
            entry.in_depot = True
            self.index.add(entry.digest)
            self._save_index()
        except ObjectDoesNotExistError:
            pass

    def _load_index(self):
        if not self.index and os.path.exists(self.index_path):
            self.index = set()
            with open(self.index_path, 'r') as index_file:
                for line in index_file:
                    self.index.add(line.rstrip())

    def _save_index(self):
        with open(self.index_path, 'w') as index_file:
            for digest in self.index:
                index_file.write(digest + '\n')

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
        entry.depot_object.download(entry.cache_path)
        entry.in_cache = True
        self.index.add(entry.digest)
        self._save_index()

    def put(self, entry):
        self._entry(entry)
        if not entry.in_depot:
            click.echo('Pushing object: %s' % entry.digest)
            self.bucket.upload_object(entry.cache_path, entry.depot_path)
            self.index.add(entry.digest)
            self._save_index()


class Cache(object):
    def __init__(self, config, upstream):
        self.config = config
        self.upstream = upstream
        self.cache_dir = self.config.cache_dir
        self.objects_dir = os.path.join(self.cache_dir, 'objects')

    def _entry(self, entry):
        entry.cache_path = os.path.join(self.objects_dir, entry.digest[:2],
                                        entry.digest[2:4], entry.digest)
        entry.in_cache = os.path.exists(entry.cache_path)
        if entry.in_cache:
            entry.cache_inode = os.stat(entry.cache_path).st_ino

    def get_status(self, entry):
        self._entry(entry)
        if self.upstream:
            self.upstream.get_status(entry)
        return entry

    def get(self, entry):
        self._entry(entry)
        # if not here, get from upstream
        if not entry.in_cache:
            self.upstream.get(entry)
            lock_file(entry.cache_path)

    def put(self, entry):
        self._entry(entry)
        # add file to the cache
        cache_dir = os.path.dirname(entry.cache_path)
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
        if not entry.in_cache:
            click.echo('Linking: %s -> %s' % (entry.rel_path, entry.digest))
            os.link(entry.working_path, entry.cache_path)
            lock_file(entry.cache_path)
        elif entry.working_inode != entry.cache_inode:
            click.echo('Re-linking: %s -> %s' % (entry.rel_path, entry.digest))
            os.unlink(entry.working_path)
            os.link(entry.cache_path, entry.working_path)
        self.upstream.put(entry)


class Working(object):
    def __init__(self, repo, config, upstream):
        self.repo = repo
        self.config = config
        self.upstream = upstream

    def _entry(self, entry):
        entry.working_path = os.path.join(self.repo.working_dir,
                                          entry.rel_path)
        entry.in_working = os.path.exists(entry.working_path)
        if entry.in_working:
            entry.working_inode = os.stat(entry.working_path).st_ino

    def get_status(self, entry):
        self._entry(entry)
        self.upstream.get_status(entry)

    def get(self, entry):
        self._entry(entry)
        self.upstream.get(entry)
        if not entry.in_cache:
            return  # we failed to find this object in the cache or the depot
        if not entry.in_working:
            click.echo('Linking: %s -> %s' % (entry.digest, entry.rel_path))
            entry_dir = os.path.dirname(entry.working_path)
            if not os.path.exists(entry_dir):
                os.makedirs(entry_dir)
            os.link(entry.cache_path, entry.working_path)
        elif entry.working_inode != entry.cache_inode:
            click.echo('Re-linking: %s -> %s' % (entry.digest, entry.rel_path))
            os.unlink(entry.working_path)
            os.link(entry.cache_path, entry.working_path)

    def put(self, entry):
        self._entry(entry)
        self.upstream.put(entry)


class App(object):
    def __init__(self):
        self.repo = git.Repo(search_parent_directories=True)
        self.user_config_path = os.path.expanduser('~/.gitbig')
        self.repo_config_path = os.path.join(self.repo.working_dir, '.gitbig')

        if os.path.exists(self.user_config_path):
            with open(self.user_config_path, 'r') as file_:
                self.user_config = UserConfig(**json.load(file_))
        else:
            self.user_config = UserConfig()

        if os.path.exists(self.repo_config_path):
            with open(self.repo_config_path, 'r') as file_:
                self.repo_config = RepoConfig(**json.load(file_))
        else:
            self.repo_config = RepoConfig()

        self.config = Config(self.user_config, self.repo_config)
        if self.config.depot:
            self.depot = Depot(self.config)
        else:
            self.depot = None
        self.cache = Cache(self.config, self.depot)
        self.working = Working(self.repo, self.config, self.cache)
        self.git_ignore = GitIgnore(self.repo)

    def _save_config(self):
        with open(self.user_config_path, 'w') as file_:
            json.dump(dict(self.user_config), file_, indent=4)
            file_.write('\n')

        with open(self.repo_config_path, 'w') as file_:
            json.dump(dict(self.repo_config), file_, indent=4)
            file_.write('\n')

    def cmd_init(self):
        self._save_config()

    def cmd_status(self):
        click.echo('On branch %s' % self.repo.active_branch.name)
        click.echo()
        click.echo('  Working')
        click.echo('    Linked')
        click.echo('      Cache')
        click.echo('        Depot')
        click.echo()
        for entry in self._entries():
            self.working.get_status(entry)
            w_bit = entry.in_working and 'W' or ' '
            c_bit = entry.in_cache and 'C' or ' '
            l_bit = entry.in_working and entry.in_cache and \
                entry.working_inode == entry.cache_inode and 'L' or ' '
            d_bit = entry.in_depot and 'D' or ' '
            click.echo('[ %s %s %s %s ] %s' % (w_bit, l_bit, c_bit, d_bit,
                                               entry.rel_path))
        click.echo()

    def cmd_add(self, paths):
        self.git_ignore.load()
        for path in self._walk(paths):
            self._add_file(path)
        self._save_config()
        self.git_ignore.save()

    def cmd_remove(self, paths):
        self.git_ignore.load()
        for path in self._walk(paths):
            self._remove_file(path)
        self._save_config()
        self.git_ignore.save()

    def cmd_unlock(self, paths):
        self.git_ignore.load()
        for path in self._walk(paths):
            self._unlock_file(path)
        self._save_config()
        self.git_ignore.save()

    def cmd_copy(self, srcs, tgt):
        self.git_ignore.load()
        for src, tgt in self._get_src_tgt_pairs(srcs, tgt):
            self._copy_file(src, tgt)
        self._save_config()
        self.git_ignore.save()

    def cmd_move(self, srcs, tgt):
        self.git_ignore.load()
        for src, tgt in self._get_src_tgt_pairs(srcs, tgt):
            self._move_file(src, tgt)
        self._save_config()
        self.git_ignore.save()

    def cmd_push(self):
        for entry in self._entries():
            self.working.put(entry)

    def cmd_pull(self):
        for entry in self._entries():
            self.working.get(entry)

    def _entries(self):
        for rel_path, digest in self.config.files.iteritems():
            yield Entry(rel_path, digest)

    def _walk(self, paths):
        for path in self._inner_walk(paths):
            if not os.path.islink(path):
                yield path

    def _inner_walk(self, paths):
        for path in paths:
            if os.path.isdir(path):
                for root, _, files in os.walk(path):
                    for file_ in files:
                        yield os.path.join(root, file_)
            else:
                yield path

    def _add_file(self, path):
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        digest = compute_digest(path)
        old_digest = self.repo_config.files.get(rel_path)
        if not old_digest or old_digest != digest:
            click.echo(rel_path)
        lock_file(path)
        self.git_ignore.ignore(rel_path)
        self.repo_config.files[rel_path] = digest

    def _remove_file(self, path):
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        if os.path.exists(path):
            os.unlink(path)
        self.git_ignore.unignore(rel_path)
        if rel_path in self.repo_config.files:
            click.echo(rel_path)
            del self.repo_config.files[rel_path]

    def _unlock_file(self, path):
        rel_path = os.path.relpath(
            os.path.abspath(path), self.repo.working_dir)
        # split the hardlink into two separate copies
        with tempfile.TemporaryFile() as tmp:
            shutil.copy2(path, tmp.name)
            shutil.move(tmp.name, path)
        unlock_file(path)
        self.git_ignore.unignore(rel_path)
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
        if rel_src not in self.repo_config.files:
            click.echo('Source not in index: %s' % src)
            return
        os.link(src, tgt)
        self.git_ignore.ignore(rel_tgt)
        self.repo_config.files[rel_tgt] = self.repo_config.files[rel_src]

    def _move_file(self, src, tgt):
        rel_src = os.path.relpath(os.path.abspath(src), self.repo.working_dir)
        rel_tgt = os.path.relpath(os.path.abspath(tgt), self.repo.working_dir)
        if rel_tgt.startswith('..') or rel_tgt.startswith('/'):
            click.echo('Destination must be inside repository: %s' % tgt)
            return
        if rel_src not in self.repo_config.files:
            click.echo('Source not in index: %s' % src)
            return
        os.rename(src, tgt)
        self.git_ignore.unignore(rel_src)
        self.git_ignore.ignore(rel_tgt)
        self.repo_config.files[rel_tgt] = self.repo_config.files[rel_src]
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


@cli.command()
def version():
    '''Print version and exit'''
    click.echo(__version__)


@cli.command()
def init():
    '''Initialize big files'''
    App().cmd_init()


@cli.command('status')
def cmd_status():
    '''View big file status'''
    App().cmd_status()


@cli.command()
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def add(paths):
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


@cli.command()
def push():
    '''Push big files'''
    App().cmd_push()


@cli.command()
def pull():
    '''Pull big files'''
    App().cmd_pull()
