import base64
import contextlib
import io
from email import policy
from email.parser import BytesParser
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import smtp_test


ARGUMENTS = ['--host', 'localhost', '--from', 'sender@example.com',
             '--to', 'recipient@example.com', '--subject', 'Test café 😀',
             '--body', 'Hello café\n.Line', '--timeout', '2']


class ValidationTests(unittest.TestCase):
    def test_rejects_header_injection_and_invalid_addresses(self):
        for address in ['a@example.com\r\nRCPT TO:<b@example.com>',
                        'Name <a@example.com>', 'café@example.com', 'no-domain']:
            with self.subTest(address=address), self.assertRaises(Exception):
                smtp_test.email_address(address)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            smtp_test.parse_args(ARGUMENTS + ['--subject', 'Bad\nSubject'])
        self.assertEqual(error.exception.code, 2)

    def test_timeout_bounds(self):
        for value in ['0', '-1', '301', 'NaN']:
            with self.assertRaises(Exception):
                smtp_test.timeout_seconds(value)
        self.assertEqual(smtp_test.timeout_seconds('30'), 30)

    def test_connection_failure_is_nonzero(self):
        output = io.StringIO()
        with patch('socket.create_connection', side_effect=OSError('Connection refused')), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = smtp_test.main(ARGUMENTS)
        self.assertEqual(result, 1)
        self.assertIn('Connection refused', output.getvalue())


class LocalServer:
    def __init__(self, certificate, key, mode, port=0):
        self.mode = mode
        self.errors = []
        self.message = None
        self.commands = []
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(certificate, key)
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', port))
        self.listener.settimeout(5)
        self.listener.listen(1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self.serve, daemon=True)
        self.thread.start()

    def serve(self):
        connection = None
        stream = None
        try:
            connection, _ = self.listener.accept()
            connection.settimeout(5)
            stream = connection.makefile('rwb', buffering=0)

            def send(line):
                stream.write(line.encode('ascii') + b'\r\n')

            def read(prefix):
                line = stream.readline().decode('ascii').strip()
                self.commands.append(line)
                if not line.startswith(prefix):
                    raise AssertionError((prefix, line))
                return line

            send('220 localhost SMTP test')
            read('ehlo ')
            send('250-localhost')
            if self.mode == 'no-starttls':
                send('250 SIZE 100000')
                if stream.readline() != b'':
                    raise AssertionError('Client continued without STARTTLS')
                return
            send('250 STARTTLS')
            read('STARTTLS')
            send('220 Begin TLS')
            stream.close()
            try:
                connection = self.context.wrap_socket(connection, server_side=True)
            except (ssl.SSLError, ConnectionResetError):
                # A client rejecting this certificate may send a TLS alert or
                # reset the TCP connection (WinError 10054 on Windows).
                # Only tolerate these during this intentional handshake failure.
                if self.mode == 'untrusted':
                    return
                raise
            stream = connection.makefile('rwb', buffering=0)
            read('ehlo ')
            send('250-localhost')
            send('250 AUTH ' + ('PLAIN' if self.mode == 'plain' else 'LOGIN'))
            if self.mode == 'plain':
                line = read('AUTH PLAIN ')
                if base64.b64decode(line.split()[-1]) != b'\x00user\x00secret':
                    raise AssertionError('Bad PLAIN credentials')
                send('235 Authenticated')
            elif self.mode == 'login':
                line = read('AUTH LOGIN')
                if len(line.split()) == 2:
                    send('334 VXNlcm5hbWU6')
                    line = read('dXNlcg==')
                else:
                    if line.split()[-1] != 'dXNlcg==':
                        raise AssertionError('Bad LOGIN username')
                send('334 UGFzc3dvcmQ6')
                read('c2VjcmV0')
                send('235 Authenticated')
            read('mail FROM:<sender@example.com>')
            send('250 OK')
            read('rcpt TO:<recipient@example.com>')
            if self.mode == 'reject-recipient':
                send('550 Recipient rejected')
                return
            send('250 OK')
            read('data')
            send('354 Send message')
            lines = []
            while True:
                line = stream.readline()
                if not line:
                    raise AssertionError('Connection closed during DATA')
                if line == b'.\r\n':
                    break
                lines.append(line[1:] if line.startswith(b'..') else line)
            self.message = BytesParser(policy=policy.default).parsebytes(b''.join(lines))
            send('250 Queued test-id')
            read('quit')
            send('221 Bye')
        except Exception as error:
            self.errors.append(error)
        finally:
            if stream:
                stream.close()
            if connection:
                connection.close()
            self.listener.close()


class LocalServerTests(unittest.TestCase):
    def test_handshake_reset_is_expected_only_for_untrusted_certificate(self):
        for mode in ('untrusted', 'anonymous'):
            with self.subTest(mode=mode):
                # Reproduce the Windows peer reset on any OS, without sockets.
                server = LocalServer.__new__(LocalServer)
                server.mode = mode
                server.errors = []
                server.commands = []
                server.listener = Mock()
                connection = Mock()
                server.listener.accept.return_value = (connection, ('127.0.0.1', 12345))
                connection.makefile.return_value.readline.side_effect = [
                    b'ehlo test-client\r\n', b'STARTTLS\r\n']
                server.context = Mock()
                reset = ConnectionResetError(10054, 'Connection forcibly closed by peer')
                server.context.wrap_socket.side_effect = reset

                server.serve()

                self.assertEqual(server.errors, [] if mode == 'untrusted' else [reset])
                connection.close.assert_called_once()
                server.listener.close.assert_called_once()


@unittest.skipUnless(shutil.which('openssl'), 'TLS tests require openssl')
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.certificate = str(Path(cls.directory.name) / 'cert.pem')
        cls.key = str(Path(cls.directory.name) / 'key.pem')
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', cls.key, '-out', cls.certificate, '-days', '1',
                        '-subj', '/CN=localhost', '-addext', 'subjectAltName=DNS:localhost'],
                       check=True, capture_output=True)

    def exercise(self, mode):
        server = LocalServer(self.certificate, self.key, mode)
        original_connect = smtp_test.TraceSMTP.connect
        arguments = list(ARGUMENTS)
        if mode != 'untrusted':
            arguments += ['--ca-file', self.certificate]
        if mode in ('login', 'plain'):
            arguments += ['--username', 'user']
        output = io.StringIO()
        with patch.object(smtp_test.TraceSMTP, 'connect',
                          lambda client, host, port: original_connect(client, host, server.port)), \
                patch('smtp_test.getpass.getpass', return_value='secret'), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            result = smtp_test.main(arguments)
        server.thread.join(6)
        self.assertFalse(server.thread.is_alive(), 'Local server did not stop')
        self.assertEqual(server.errors, [])
        transcript = output.getvalue()
        self.assertIn("S: b'220 localhost SMTP test\\r\\n'", transcript)
        self.assertIn("S: b'250-localhost\\r\\n'", transcript)
        self.assertNotIn('secret', transcript)
        self.assertNotIn('c2VjcmV0', transcript)
        self.assertNotIn('AHVzZXIAc2VjcmV0', transcript)
        return result, transcript, server

    def test_starttls_with_and_without_authentication(self):
        for mode in ('anonymous', 'plain', 'login'):
            with self.subTest(mode=mode):
                result, transcript, server = self.exercise(mode)
                self.assertEqual(result, 0, transcript)
                self.assertIn('[STARTTLS] Established TLS', transcript)
                self.assertIn('250 Queued test-id', transcript)
                self.assertEqual(server.message['Subject'], 'Test café 😀')
                self.assertEqual(server.message.get_content().replace('\r\n', '\n'),
                                 'Hello café\n.Line\n')

    def test_missing_starttls_is_fatal(self):
        result, transcript, server = self.exercise('no-starttls')
        self.assertEqual(result, 1)
        self.assertIn('does not advertise STARTTLS', transcript)
        self.assertFalse(any(command.startswith('mail') for command in server.commands))

    def test_untrusted_certificate_is_fatal(self):
        result, transcript, server = self.exercise('untrusted')
        self.assertEqual(result, 1)
        self.assertIn('CERTIFICATE_VERIFY_FAILED', transcript)
        self.assertFalse(any(command.startswith('mail') for command in server.commands))

    def test_recipient_rejection_is_logged(self):
        result, transcript, _ = self.exercise('reject-recipient')
        self.assertEqual(result, 1)
        self.assertIn("S: b'550 Recipient rejected\\r\\n'", transcript)
        self.assertNotIn('[Complete]', transcript)


if __name__ == '__main__':
    unittest.main()
