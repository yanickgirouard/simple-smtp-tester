# SMTP STARTTLS tester

Python source plus a build script for standalone, single-file Windows and Linux
executables. Recipients of the binaries do not need Python or Python packages.
The raw script requires Python 3.9 or later and uses only the standard library.

Run the source on Windows (`py -3`) or Linux (`python3`):

```sh
python3 smtp_test.py --host smtp.example.com --from sender@example.com --to recipient@example.com --subject "SMTP test" --body "Hello" --username sender@example.com
```

Omit `--username` for unauthenticated SMTP. When supplied, the script securely
prompts for a password; passwords are not passed on the command line or printed.
Password authentication supports smtplib's CRAM-MD5, PLAIN, and LOGIN mechanisms.
OAuth is not supported.

The script uses port **587**, requires **STARTTLS** and TLS 1.2 or newer, validates
the server certificate, and displays TCP connection, TLS, authentication, and
message submission progress. Every server reply is printed as a raw Python bytes
literal, including status codes, multiline separators, and escaped CRLF (`\r\n`).
Client authentication data and message content are hidden. Mail is UTF-8 MIME.

Optional arguments:

- `--timeout 30`: connection and individual socket operation timeout in seconds
  (1–300). DNS resolution follows operating system resolver timeouts.
- `--ca-file company-ca.pem`: trust additional PEM CA certificates, for example
  for an internal SMTP server. Certificate verification stays enabled.

Exit codes: `0` success, `1` SMTP/network/TLS failure, `2` invalid arguments,
`130` user cancellation. Success means the SMTP server accepted the message,
which does not confirm inbox delivery. Review transcripts before sharing them.

## Build the portable binaries

The build script uses [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html)
to bundle the interpreter and dependencies. **Build on each target OS**:
Windows produces a Windows executable; Linux produces a Linux executable.
PyInstaller does not cross-compile between them. No launchers are required.

Windows (PowerShell or Command Prompt):

```text
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.venv\Scripts\python.exe build.py
```

Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-build.txt
.venv/bin/python build.py
```

Outputs on x86-64 hosts (other architectures use their own suffix):

| Build host | Standalone executable |
| --- | --- |
| Windows | `dist/smtp-test-windows-x86_64.exe` |
| Linux | `dist/smtp-test-linux-x86_64` |

Each build also produces a `.sha256` checksum and runs the binary's `--help` as
a smoke test. Copy the executable to a compatible machine and run it directly:

```text
smtp-test-windows-x86_64.exe --host smtp.example.com --from sender@example.com --to recipient@example.com --subject "Test" --body "Hello"
```

```sh
./smtp-test-linux-x86_64 --host smtp.example.com --from sender@example.com --to recipient@example.com --subject "Test" --body "Hello"
```

For both binaries from one build run, push this repository to GitHub and run
**Actions → Build portable executables → Run workflow**. The workflow builds on
Windows and Ubuntu 22.04 and uploads both executables and checksums as downloadable
artifacts. Version tags (`v*`) also trigger it. It does not publish a release.
After extracting a downloaded Linux artifact, restore its executable permission
if needed with `chmod +x smtp-test-linux-x86_64`.

Linux portability is bounded by CPU architecture, glibc, and system libraries:
build on the oldest Linux distribution you intend to support. The workflow's
Linux build targets glibc 2.35 or newer; Alpine/musl is not supported by that build.
One-file executables unpack bundled libraries into a temporary directory at
startup. The target must provide writable temporary storage that permits
executing unpacked code. System CA certificates are used for TLS validation.

## Tests

```sh
python3 -m unittest discover -s tests -v
```

Tests use a local SMTP server and a temporary TLS certificate, without contacting
external mail servers. TLS tests require the `openssl` command; they are skipped
if it is unavailable.
