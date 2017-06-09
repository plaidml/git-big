from __future__ import print_function

import hashlib
import json
import os
import stat

import click
import git
from libcloud import DriverType, get_driver
from libcloud.storage.types import ObjectDoesNotExistError
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

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
        self.cache_path = None
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
    '''make file read-only'''
    # click.echo('Locking file: %s' % path)
    mode = os.stat(path).st_mode
    perms = stat.S_IMODE(mode)
    mask = ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    os.chmod(path, perms & mask)


def ignore_file(working_root, rel_path):
    gitignore_path = os.path.join(working_root, '.gitignore')
    with open(gitignore_path, 'r+') as gitignore_file:
        lines = []
        for line in gitignore_file:
            lines.append(line.rstrip())
        spec = PathSpec.from_lines(GitWildMatchPattern, lines)
        if not spec.match_file(rel_path):
            lines.append('/' + rel_path)
            gitignore_file.seek(0)
            for line in lines:
                gitignore_file.write(line + '\n')


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
        entry.depot_object.download(entry.cache_path)
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
        if not entry.in_cache:
            click.echo('Linking: %s -> %s' % (entry.rel_path, entry.digest))
            cache_dir = os.path.dirname(entry.cache_path)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            os.link(entry.working_path, entry.cache_path)
            lock_file(entry.cache_path)
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

    def get_status(self, entry):
        self._entry(entry)
        self.upstream.get_status(entry)

    def get(self, entry):
        self._entry(entry)
        # if not here, get from upstream
        if not entry.in_working:
            self.upstream.get(entry)
            click.echo('Linking: %s -> %s' % (entry.digest, entry.rel_path))
            entry_dir = os.path.dirname(entry.working_path)
            if not os.path.exists(entry_dir):
                os.makedirs(entry_dir)
            os.link(entry.cache_path, entry.working_path)

    def put(self, entry):
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
        click.echo('    Cache')
        click.echo('      Depot')
        click.echo()
        for entry in self._entries():
            self.working.get_status(entry)
            w_bit = entry.in_working and 'W' or ' '
            c_bit = entry.in_cache and 'C' or ' '
            d_bit = entry.in_depot and 'D' or ' '
            click.echo('[ %s %s %s ] %s' % (w_bit, c_bit, d_bit,
                                            entry.rel_path))
        click.echo()

    def cmd_add(self, paths):
        for path in paths:
            if os.path.isdir(path):
                self._add_directory(path)
            else:
                self._add_file(path)
        self._save_config()

    def cmd_remove(self, paths):
        pass

    def cmd_unlock(self, paths):
        pass

    def cmd_copy(self, src, tgt):
        pass

    def cmd_move(self, src, tgt):
        pass

    def cmd_push(self):
        for entry in self._entries():
            self.working.put(entry)

    def cmd_pull(self):
        for entry in self._entries():
            self.working.get(entry)

    def _entries(self):
        for rel_path, digest in self.config.files.iteritems():
            yield Entry(rel_path, digest)

    def _add_directory(self, path):
        for root, _, files in os.walk(path):
            for file_ in files:
                self._add_file(os.path.join(root, file_))

    def _add_file(self, working_path):
        if not os.path.isfile(working_path):
            return
        if os.path.islink(working_path):
            return
        rel_path = os.path.relpath(
            os.path.abspath(working_path), self.repo.working_dir)
        digest = compute_digest(working_path)
        old_digest = self.repo_config.files.get(rel_path)
        if not old_digest or old_digest != digest:
            click.echo(rel_path)
        lock_file(working_path)
        ignore_file(self.repo.working_dir, rel_path)
        self.repo_config.files[rel_path] = digest


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
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_remove(paths):
    '''Remove big files'''
    App().cmd_remove(paths)


@cli.command('unlock')
@click.argument('paths', nargs=-1, type=click.Path(exists=True))
def cmd_unlock(paths):
    '''Unlock big files'''
    App().cmd_unlock(paths)


@cli.command('mv')
@click.argument('source', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=-1, type=click.Path())
def cmd_move(source, dest):
    '''Move big files'''
    App().cmd_move(source, dest)


@cli.command('cp')
@click.argument('source', nargs=-1, type=click.Path(exists=True))
@click.argument('dest', nargs=-1, type=click.Path())
def cmd_copy(source, dest):
    '''Copy big files'''
    App().cmd_copy(source, dest)


@cli.command()
def push():
    '''Push big files'''
    App().cmd_push()


@cli.command()
def pull():
    '''Pull big files'''
    App().cmd_pull()
