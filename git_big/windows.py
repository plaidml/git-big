import os
import stat
import subprocess
import sys

import click

import jaraco.windows.filesystem as fs
import win32api
import win32con
import win32console
import win32event
import win32process
from win32com.shell import shell, shellcon


def _respawn_as_administrator():
    """Respawn ourselves with administrator rights.
    
    Spawns a duplicate process, elevated to administrator access.
    
    Raises:
        Exception: If we're unable to run the elevated process.
    
    Returns:
        int: The exit code of the elevated process.
    """
    #pylint: disable=no-name-in-module,import-error
    try:
        process = shell.ShellExecuteEx(
            lpVerb='runas',
            lpFile=sys.argv[0],
            lpParameters=' '.join(['--allocate-console'] + sys.argv[1:]),
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS)
    except:
        raise click.ClickException(
            'Could not elevate to administrator privileges')
    handle = process['hProcess']
    win32event.WaitForSingleObject(handle, win32event.INFINITE)
    exitcode = win32process.GetExitCodeProcess(handle)
    win32api.CloseHandle(handle)
    return exitcode


@click.command()
@click.option(
    '--allocate-console/--no-allocate-console',
    default=False,
    help='allocate a separate output console')
def cli(allocate_console):
    """Configures Windows systems for git-big."""

    if not shell.IsUserAnAdmin():
        return _respawn_as_administrator()
    try:
        if allocate_console:
            win32console.FreeConsole()
            win32console.AllocConsole()

        click.echo('Enabling developer mode')
        rkey = win32api.RegOpenKey(
            win32con.HKEY_LOCAL_MACHINE,
            'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock', 0,
            win32con.KEY_SET_VALUE)
        win32api.RegSetValueEx(rkey, 'AllowDevelopmentWithoutDevLicense', 0,
                               win32con.REG_DWORD, 1)
        click.echo('Enabling git core.symlinks system-wide')
        cmds = [
            [
                'git', 'config', '-f',
                os.path.abspath('/ProgramData/Git/config'), 'core.symlinks',
                'true'
            ],
            ['git', 'config', '--system', 'core.symlinks', 'true'],
            ['git', 'config', '--global', 'core.symlinks', 'true'],
        ]
        for cmd in cmds:
            click.echo('  ' + ' '.join(cmd))
            subprocess.check_call(cmd)
        click.echo('Successfully configured system for use with git-big.')
        click.echo(
            'N.B. You may need to run "git config core.symlinks true" in your local repositories'
        )

    finally:
        if allocate_console:
            click.pause()


def check_symlinks():
    key = win32api.RegOpenKey(
        win32con.HKEY_LOCAL_MACHINE,
        'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock', 0,
        win32con.KEY_READ)
    (val, _) = win32api.RegQueryValueEx(key,
                                        'AllowDevelopmentWithoutDevLicense')
    symlinks = subprocess.check_output(['git', 'config', 'core.symlinks'])
    if val != 1 or not 'true' in symlinks:
        print(
            'git-big requires symlinks to be enabled; run `git big windows-setup`'
        )
        raise SystemExit(1)
    # orig_relpath = os.path.relpath
    # orig_join = os.path.join
    # os.path.join = lambda start, *rest: orig_join(start, *rest).replace(os.path.sep,'/')
    # os.path.relpath = lambda to, rel: orig_relpath(
    #     to, rel).replace(os.path.sep, '/')


def monkey_patch():
    orig_isfile = os.path.isfile

    def link(src, dest):
        fs.link(src, dest)
        os.chmod(dest, stat.S_IWRITE | stat.S_IREAD)

    def isfile(src):
        if os.path.islink(src):
            src = os.path.abspath(
                os.path.join(
                    os.path.dirname(os.path.abspath(src)), fs.readlink(src)))
        return orig_isfile(src)

    if not hasattr(os, 'symlink'):
        os.link = link
        os.symlink = lambda src, dest: fs.symlink(src, dest, 0x2)
        os.path.islink = fs.islink
        os.path.isfile = isfile
    if not hasattr(os, 'readlink'):
        os.readlink = fs.readlink
