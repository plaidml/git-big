import os
import subprocess
import sys

from win32com.shell import shell, shellcon
import win32api
import win32con
import win32console
import win32event
import win32process

import click


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
    hProcess = process['hProcess']
    win32event.WaitForSingleObject(hProcess, win32event.INFINITE)
    exitcode = win32process.GetExitCodeProcess(hProcess)
    win32api.CloseHandle(hProcess)
    return exitcode


@click.command()
@click.option(
    '--allocate-console/--no-allocate-console',
    default=False,
    help='allocate a separate output console')
def cli(allocate_console):
    """Configures Windows systems for use with git-big"""

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
            subprocess.check_call(cmd, shell=True)
        click.echo('Successfully configured system for use with git-big.')
        click.echo(
            'N.B. You may need to run "git config core.symlinks true" in your local repositories'
        )

    finally:
        if allocate_console:
            click.pause()
