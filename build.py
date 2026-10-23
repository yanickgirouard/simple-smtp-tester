#!/usr/bin/env python3
"""Build a portable single-file SMTP tester for the current Windows/Linux host."""

import hashlib
import importlib.util
import os
import platform
from pathlib import Path
import subprocess
import sys


def write_checksum(binary):
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    # Write bytes to prevent Windows text mode from translating LF into CRLF.
    # GNU sha256sum otherwise interprets the CR as part of the asset filename.
    binary.with_name(binary.name + '.sha256').write_bytes(
        '{}  {}\n'.format(digest, binary.name).encode('ascii'))


def main():
    system = platform.system().lower()
    if system not in ('windows', 'linux'):
        print('Build on Windows for the .exe or Linux for the ELF binary.', file=sys.stderr)
        return 1
    if importlib.util.find_spec('PyInstaller') is None:
        print('Install build dependencies first: python -m pip install -r requirements-build.txt',
              file=sys.stderr)
        return 1
    root = Path(__file__).resolve().parent
    architecture = platform.machine().lower()
    architecture = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(architecture, architecture)
    name = 'smtp-test-{}-{}'.format(system, architecture)
    work = root / 'build' / name
    work.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment['PYINSTALLER_CONFIG_DIR'] = str(work / 'cache')
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
        '--onefile', '--console', '--noupx', '--name', name,
        '--distpath', str(root / 'dist'), '--workpath', str(work / 'work'),
        '--specpath', str(work), str(root / 'smtp_test.py'),
    ], check=True, cwd=root, env=environment)
    binary = root / 'dist' / (name + ('.exe' if system == 'windows' else ''))
    subprocess.run([str(binary), '--help'], check=True)
    write_checksum(binary)
    print('\nPortable executable: {}'.format(binary))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as error:
        sys.exit(error.returncode or 1)
