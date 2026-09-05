"""Strict atomic byte-envelope contract; no document parsing or remote fetching."""
import json
import unittest
from pydantic_ai.messages import BinaryContent


class EnvelopeTests(unittest.TestCase):
    def test_round_trip_preserves_order_bytes_and_completion(self):
        from kibernikto.telegram.peer_protocol import PeerEnvelope
        binaries = [BinaryContent(data=b'photo', media_type='image/png'),
                    BinaryContent(data=b'\x00audio', media_type='audio/wav'),
                    BinaryContent(data=b'file', media_type='application/octet-stream')]
        request = PeerEnvelope.create('request', 'selected task', binaries, request_id='a' * 32)
        decoded = PeerEnvelope.decode(request.encode())
        self.assertEqual(decoded.request_id, 'a' * 32)
        self.assertEqual(decoded.text, 'selected task')
        self.assertEqual([(b.data, b.media_type) for b in decoded.binaries],
                         [(b.data, b.media_type) for b in binaries])
        self.assertEqual(json.loads(request.encode())['end'], True)
        self.assertEqual(decoded.caption, 'KIBERNIKTO_PEER/1 request ' + 'a' * 32)

    def test_untrusted_envelopes_are_strict_and_bounded(self):
        from kibernikto.telegram.peer_protocol import PeerEnvelope, PeerProtocolError
        valid = json.loads(PeerEnvelope.create('request', 'task', []).encode())
        mutations = [dict(version=2), dict(version=True), dict(end=False), dict(end=1),
                     dict(request_id='../file'), dict(kind='other'), dict(url='https://example.com'),
                     dict(text='x' * 65537), dict(parts=[{'url': 'file:///etc/passwd'}]),
                     dict(parts=[{'data': '***', 'media_type': 'image/png', 'filename': None}]),
                     dict(parts=[{'data': '', 'media_type': 'image/png', 'filename': '../secret'}]),
                     dict(parts=[{'data': '', 'media_type': 'image/png', 'filename': None}] * 9)]
        for mutation in mutations:
            with self.subTest(mutation=list(mutation)), self.assertRaises(PeerProtocolError):
                PeerEnvelope.decode(json.dumps(valid | mutation).encode())
        with self.assertRaises(PeerProtocolError):
            PeerEnvelope.decode(b' ' * (3 * 1024 * 1024 + 1))
        with self.assertRaises(PeerProtocolError):
            PeerEnvelope.decode(b'{"version":1,"version":1}')
        with self.assertRaises(PeerProtocolError):
            PeerEnvelope.create('request', 'task', [BinaryContent(data=b'x' * (2 * 1024 * 1024 + 1),
                                                                media_type='application/octet-stream')]).encode()

    def test_filename_and_mime_survive_without_other_metadata(self):
        from kibernikto.telegram.peer_protocol import PeerEnvelope
        part = BinaryContent(data=b'hello', media_type='text/plain',
                             vendor_metadata={'filename': 'résumé.txt', 'private': 'not transmitted'})
        wire = PeerEnvelope.create('result', 'done', [part]).encode()
        self.assertNotIn(b'private', wire)
        result = PeerEnvelope.decode(wire)
        self.assertEqual(result.binaries[0].vendor_metadata, {'filename': 'résumé.txt'})
