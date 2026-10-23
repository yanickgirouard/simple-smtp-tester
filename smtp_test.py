#!/usr/bin/env python3
"""Send an SMTP test message over mandatory STARTTLS on port 587."""

import argparse
import getpass
import smtplib
import ssl
import sys
from email import policy
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def progress(message):
    print(message, flush=True)


class TraceSMTP(smtplib.SMTP):
    """Print wire replies without exposing authentication or message data."""

    authenticating = False

    def connect(self, host='localhost', port=587, source_address=None):
        # SMTP.connect() does not update the TLS hostname when connecting after
        # construction. Keep SNI and certificate hostname validation correct.
        self._host = host
        return super().connect(host, port, source_address)

    def _print_debug(self, *args):
        # Only raw reply lines; smtplib's send events can expose passwords.
        if len(args) == 2 and args[0] == 'reply:':
            progress('S: ' + args[1])

    def _get_socket(self, host, port, timeout):
        progress('[Connect] Resolving and connecting to {}:{}...'.format(host, port))
        connection = super()._get_socket(host, port, timeout)
        progress('[Connect] TCP connected; waiting for the server greeting.')
        return connection

    def putcmd(self, cmd, args=''):
        if self.authenticating:
            progress('C: [authentication data hidden]')
        else:
            progress('C: ' + cmd + (' ' + args if args else ''))
        return super().putcmd(cmd, args)

    def login(self, user, password, *, initial_response_ok=True):
        self.authenticating = True
        try:
            return super().login(user, password, initial_response_ok=initial_response_ok)
        finally:
            self.authenticating = False
            self.user = self.password = None


def email_address(value):
    try:
        value.encode('ascii')
        address = Address(addr_spec=value)
        if (not address.username or not address.domain or address.addr_spec != value
                or any(character.isspace() for character in value)):
            raise ValueError('Expected a plain email address')
    except (ValueError, IndexError) as error:
        raise argparse.ArgumentTypeError(
            'Use one plain ASCII email address without a display name.'
        ) from error
    return value


def timeout_seconds(value):
    try:
        timeout = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError('Timeout must be an integer from 1 to 300.') from error
    if not 1 <= timeout <= 300:
        raise argparse.ArgumentTypeError('Timeout must be an integer from 1 to 300.')
    return timeout


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True, help='SMTP server hostname (port 587).')
    parser.add_argument('--from', dest='sender', required=True, type=email_address)
    parser.add_argument('--to', dest='recipient', required=True, type=email_address)
    parser.add_argument('--subject', required=True)
    parser.add_argument('--body', required=True, help='Plain text message body.')
    parser.add_argument('--username', help='Prompt securely for a password; omit for no authentication.')
    parser.add_argument('--timeout', type=timeout_seconds, default=30,
                        help='Connection and socket I/O timeout in seconds (default: 30).')
    parser.add_argument('--ca-file', help='Additional trusted CA certificate file in PEM format.')
    args = parser.parse_args(argv)
    if '\r' in args.subject or '\n' in args.subject:
        parser.error('Subject must not contain line breaks.')
    return args


def expect(reply, expected):
    code, response = reply
    if code not in expected:
        raise smtplib.SMTPResponseException(code, response)


def run(args):
    message = EmailMessage(policy=policy.SMTP)
    message['From'] = args.sender
    message['To'] = args.recipient
    message['Subject'] = args.subject
    message['Date'] = formatdate(localtime=True)
    message['Message-ID'] = make_msgid()
    message.set_content(args.body, charset='utf-8', cte='base64')

    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if args.ca_file:
        context.load_verify_locations(cafile=args.ca_file)
    password = getpass.getpass('SMTP password: ') if args.username else None

    smtp = TraceSMTP(timeout=args.timeout)
    smtp.set_debuglevel(1)
    try:
        expect(smtp.connect(args.host, 587), (220,))
        expect(smtp.ehlo(), (250,))
        if not smtp.has_extn('starttls'):
            raise smtplib.SMTPNotSupportedError('Server does not advertise STARTTLS.')
        progress('[STARTTLS] Requesting TLS and validating the server certificate...')
        smtp.starttls(context=context)
        progress('[STARTTLS] Established {}; cipher {}.'.format(
            smtp.sock.version(), smtp.sock.cipher()[0]))
        expect(smtp.ehlo(), (250,))
        if args.username:
            progress('[Authentication] Authenticating over TLS.')
            smtp.login(args.username, password)
            password = None
        progress('[Send] Sending envelope and UTF-8 MIME message.')
        expect(smtp.mail(args.sender), (250,))
        expect(smtp.rcpt(args.recipient), (250, 251))
        progress('[Send] Message content is hidden from the transcript.')
        expect(smtp.data(message.as_bytes()), (250,))
        progress('[Send] Server accepted the message. Inbox delivery is not confirmed.')
        expect(smtp.quit(), (221,))
        progress('[Complete] SMTP test succeeded.')
    finally:
        smtp.close()


def main(argv=None):
    args = parse_args(argv)
    try:
        run(args)
    except (OSError, smtplib.SMTPException, ValueError, EOFError) as error:
        print('[Failed] {}'.format(error), file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('\n[Cancelled]', file=sys.stderr, flush=True)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
