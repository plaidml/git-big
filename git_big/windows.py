import os
import subprocess
import sys

import jaraco.windows.filesystem as fs
import win32con
from win32com.shell import shell, shellcon

import win32api
import win32event
import win32process


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
            lpParameters=' '.join(sys.argv[1:]),
            fMask=shellcon.SEE_MASK_NOCLOSEPROCESS)
    except:
        sys.exit('Could not elevate to administrator privileges')
    handle = process['hProcess']
    win32event.WaitForSingleObject(handle, win32event.INFINITE)
    exitcode = win32process.GetExitCodeProcess(handle)
    win32api.CloseHandle(handle)
    return exitcode


class DevMode(object):
    HIVE = win32con.HKEY_LOCAL_MACHINE
    KEY = 'SOFTWARE\Microsoft\Windows\CurrentVersion\AppModelUnlock'
    NAME = 'AllowDevelopmentWithoutDevLicense'

    def check(self):
        if os.getenv('APPVEYOR'):
            return True
        key = win32api.RegOpenKey(DevMode.HIVE, DevMode.KEY, 0,
                                  win32con.KEY_READ)
        value, _ = win32api.RegQueryValueEx(key, DevMode.NAME)
        return value == 1

    def enable(self):
        key = win32api.RegOpenKey(DevMode.HIVE, DevMode.KEY, 0,
                                  win32con.KEY_SET_VALUE)
        win32api.RegSetValueEx(key, DevMode.NAME, 0, win32con.REG_DWORD, 1)


def enable_git_symlinks():
    print('Enabling git core.symlinks system-wide')
    cmds = [
        ['git', 'config', '--system', 'core.symlinks', 'true'],
        ['git', 'config', '--global', 'core.symlinks', 'true'],
    ]
    for cmd in cmds:
        print('  ' + ' '.join(cmd))
        subprocess.check_call(cmd)


def enable_dev_mode():
    print('Enabling developer mode')
    DevMode().enable()


def check():
    try:
        symlinks = subprocess.check_output(
            ['git', 'config', '--system', 'core.symlinks']).decode().rstrip()
        if DevMode().check() and symlinks == 'true':
            return True
    except subprocess.CalledProcessError:
        pass
    return False


def setup():
    if not shell.IsUserAnAdmin():
        return _respawn_as_administrator()
    enable_dev_mode()
    enable_git_symlinks()
    print('Successfully configured system for use with git-big.')


SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE = 0x2


class WindowsFileSystem(object):
    def islink(self, path):
        """Return True if path refers to an existing directory entry that is a symbolic link.
        """
        return fs.islink(path)

    def isfile(self, path, start=None):
        """Return True if path is an existing regular file.
        This follows symbolic links, so both islink() and isfile() can be true for the same path.
        """
        if self.islink(path):
            if not start:
                start = os.path.abspath('.')
            path = os.path.join(start, fs.readlink(path))
        return os.path.isfile(path)

    def readlink(self, path):
        return fs.readlink(path)

    def link(self, src, dst):
        fs.link(src, dst)

    def symlink(self, src, dst):
        flag = SYMBOLIC_LINK_FLAG_ALLOW_UNPRIVILEGED_CREATE
        if os.getenv('APPVEYOR'):
            flag = 0
        fs.symlink(src, dst, flag)


if __name__ == '__main__':
    enable_git_symlinks()
    enable_dev_mode()
