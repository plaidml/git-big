from os.path import exists
from subprocess import check_output

from click.testing import CliRunner

from git_big.main import cli

HOOKS = [
    'pre-push',
    'post-checkout',
    'post-merge',
]


def do_init(runner):
    check_output(['git', 'init'])
    result = runner.invoke(cli, ['init'])
    # check uuid was created
    check_output(['git', 'config', '--get', 'git-big.uuid'])
    # check .gitbig file was created
    assert exists('.gitbig')
    # check hooks were created
    for hook in HOOKS:
        assert exists('.git/hooks/%s' % hook)
    assert result.exit_code == 0


def test_init():
    runner = CliRunner()
    with runner.isolated_filesystem():
        do_init(runner)


def test_init_multi():
    runner = CliRunner()
    with runner.isolated_filesystem():
        do_init(runner)
        do_init(runner)
        for hook in HOOKS:
            assert not exists('.git/hooks/%s.git-big' % hook)


def test_init_chain():
    runner = CliRunner()
    with runner.isolated_filesystem():
        check_output(['git', 'init'])
        for hook in HOOKS:
            open('.git/hooks/%s' % hook, 'w').write('#!/bin/sh\necho "Hello"')
        do_init(runner)
        for hook in HOOKS:
            assert exists('.git/hooks/%s.git-big' % hook)
