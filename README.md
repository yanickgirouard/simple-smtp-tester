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

## Reading the client/server exchange

`C:` marks a command sent by the client (this script); `S:` marks a reply from
the SMTP server. Lines in square brackets describe the script's progress.
Server replies appear as Python bytes literals: `b'...'` represents the received
bytes, and `\r\n` is the SMTP line ending, not an error.

This successful example uses generic hostnames, addresses, and a queue ID:

```text
[Connect] Resolving and connecting to smtp.example.com:587...
[Connect] TCP connected; waiting for the server greeting.
S: b'220 ESMTP service ready at mail-node-01\r\n'
C: ehlo test-pc.example.com
S: b'250-smtp.example.com\r\n'
S: b'250-8BITMIME\r\n'
S: b'250-PIPELINING\r\n'
S: b'250-SIZE 31457280\r\n'
S: b'250-SMTPUTF8\r\n'
S: b'250-STARTTLS\r\n'
S: b'250-AUTH PLAIN LOGIN\r\n'
S: b'250 AUTH=PLAIN LOGIN\r\n'
[STARTTLS] Requesting TLS and validating the server certificate...
C: STARTTLS
S: b'220 Begin TLS negotiation now\r\n'
[STARTTLS] Established TLSv1.3; cipher TLS_AES_128_GCM_SHA256.
C: ehlo test-pc.example.com
S: b'250-smtp.example.com\r\n'
S: b'250-8BITMIME\r\n'
S: b'250-PIPELINING\r\n'
S: b'250-SIZE 31457280\r\n'
S: b'250-SMTPUTF8\r\n'
S: b'250-STARTTLS\r\n'
S: b'250-AUTH PLAIN LOGIN\r\n'
S: b'250 AUTH=PLAIN LOGIN\r\n'
[Authentication] Authenticating over TLS.
C: [authentication data hidden]
S: b'235 Authentication successful\r\n'
[Send] Sending envelope and UTF-8 MIME message.
C: mail FROM:<sender@example.com>
S: b'250 Sender address accepted\r\n'
C: rcpt TO:<recipient@example.com>
S: b'250 Recipient address accepted\r\n'
[Send] Message content is hidden from the transcript.
C: data
S: b'354 Continue\r\n'
S: b'250 Ok: queued as EXAMPLE-QUEUE-ID\r\n'
[Send] Server accepted the message. Inbox delivery is not confirmed.
C: quit
S: b'221 See you later\r\n'
[Complete] SMTP test succeeded.
```

Read the exchange in order:

| Phase | What the output tells you |
| --- | --- |
| Connect and `220` greeting | The TCP connection opened and the SMTP service is ready. This alone does not confirm TLS or permission to send mail. |
| `EHLO` and `250` capabilities | The client identifies itself as `test-pc.example.com`; the server lists supported SMTP features. `250-` means more lines follow in the same reply; `250 ` (with a space) ends it. These repeated codes are not retries. |
| `STARTTLS` and `220` | The server accepts the request to upgrade the connection. The following `Established TLSv1.3` line confirms the TLS handshake and certificate validation succeeded; the cipher names the negotiated encryption suite. |
| Second `EHLO` | Capabilities are requested again inside the encrypted connection. Features advertised after TLS can differ from those advertised before it. |
| Authentication and `235` | The supplied credentials were accepted. Authentication commands and encoded credentials are hidden by the script. Authentication is skipped when `--username` is omitted. |
| `MAIL FROM` and `250` | The server accepts the envelope sender, used for SMTP delivery and bounce handling. This is separate from the message's visible `From` header, although this script uses the same address for both. |
| `RCPT TO` and `250` | The server accepts the envelope recipient for this transaction. This does not yet mean the message has been accepted or delivered. |
| `DATA` and `354` | The server is ready to receive message headers and body. The script sends them and the terminating dot, but hides that content from the transcript. `354` is an intermediate response, not a failure. |
| Final `250` after `DATA` | The server accepted the complete message and assigned the example queue ID. This is the key submission success response. Delivery can still fail later, or the message can be filtered into spam. |
| `QUIT` and `221` | The server agrees to close the SMTP session. `[Complete]` confirms the script finished successfully. |

The capabilities in this example mean:

- `8BITMIME`: support for message bodies containing 8-bit data. This script uses
  base64 encoding for its UTF-8 body.
- `PIPELINING`: support for sending certain commands without waiting for each
  reply. Its presence does not mean this script uses it.
- `SIZE 31457280`: an advertised maximum message size of 31,457,280 bytes (30 MiB),
  including headers and encoding overhead.
- `SMTPUTF8`: support for internationalized email addresses and UTF-8 headers.
  This script still requires ASCII envelope addresses.
- `STARTTLS`: support for upgrading the existing connection to TLS.
- `AUTH PLAIN LOGIN` / `AUTH=PLAIN LOGIN`: advertisements of password
  authentication methods. Base64-encoded credentials are not encrypted by those
  mechanisms themselves; the script authenticates only after TLS is established.

For failures, look at the last server reply before `[Failed]`. A `4xx` response
usually indicates a temporary problem (for example, `451`); a `5xx` response
indicates a permanent rejection of that request (for example, `535` for rejected
credentials or `550` for a rejected recipient). Read the accompanying server text
for the specific cause. DNS, connection, timeout, and certificate errors can occur
without an SMTP reply, in which case the script's error message gives the cause.

Before sharing your own transcript, replace server and client hostnames, email
addresses, IP addresses, queue IDs, and any other identifying server text with
generic values, as above.

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
