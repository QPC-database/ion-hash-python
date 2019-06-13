import hashlib
import pytest
from six import StringIO
from io import BytesIO
from os.path import abspath, join

import amazon.ion.simpleion as ion
import amazon.ion.reader as ion_reader
from amazon.ion.reader_managed import managed_reader
from amazon.ion.reader_text import text_reader
from amazon.ion.reader_binary import binary_reader
from amazon.ion.reader import NEXT_EVENT
from amazon.ion.core import IonEventType
from amazon.ionhash.hasher import hasher
from amazon.ionhash.hasher import HashEvent


def _test_data(algorithm):
    path = abspath(join(abspath(__file__), '..', '..', 'tests', 'ion_hash_tests.ion'))
    f = open(path)
    ion_tests = ion.loads(f.read(), single_value=False)
    f.close()

    def _has_algorithm(ion_test):
        return algorithm in ion_test['expect']

    return filter(_has_algorithm, ion_tests)


_IVM = "$ion_1_0 "


def _test_name(ion_test):
    if ion_test.ion_annotations.__len__() > 0:
        test_name = ion_test.ion_annotations[0].text
    else:
        test_name = ion.dumps(ion_test['ion'], binary=False).__str__()
        if test_name.startswith(_IVM):
            test_name = test_name[len(_IVM):]

    return " " + test_name


def _to_buffer(ion_test, binary):
    if 'ion' in ion_test:
        v = ion.dumps(ion_test['ion'], binary=binary)

    if '10n' in ion_test:
        v = bytearray([0xE0, 0x01, 0x00, 0xEA])  # $ion_1_0
        for byte in ion_test['10n']:
            v.append(byte)

        if not binary:
            value = ion.load(BytesIO(v))
            v = ion.dumps(value, binary=False)

    if binary:
        return BytesIO(v)
    else:
        return StringIO(v)


@pytest.mark.parametrize("ion_test", _test_data("identity"), ids=_test_name)
def test_binary(ion_test):
    buf = _to_buffer(ion_test, binary=True)
    _run_test(ion_test, _reader_provider("binary"), buf)


@pytest.mark.parametrize("ion_test", _test_data("md5"), ids=_test_name)
def test_binary_md5(ion_test):
    buf = _to_buffer(ion_test, binary=True)
    _run_test(ion_test, _reader_provider("binary"), buf)


@pytest.mark.parametrize("ion_test", _test_data("identity"), ids=_test_name)
def test_text(ion_test):
    buf = _to_buffer(ion_test, binary=False)
    _run_test(ion_test, _reader_provider("text"), buf)


@pytest.mark.parametrize("ion_test", _test_data("md5"), ids=_test_name)
def test_text_md5(ion_test):
    buf = _to_buffer(ion_test, binary=False)
    _run_test(ion_test, _reader_provider("text"), buf)


'''
@pytest.mark.parametrize("ion_test", _test_data(), ids=_test_name)
def test_no_step_in(ion_test):
    pass


@pytest.mark.parametrize("ion_test", _test_data(), ids=_test_name)
def test_writer(ion_test):
    pass
'''


def _run_test(ion_test, reader_provider, buf):
    expect = ion_test['expect']
    for algorithm in expect:
        expected_updates = []
        expected_digests = []
        final_digest = None
        for sexp in expect[algorithm]:
            annot = sexp.ion_annotations[0].text
            if annot == "update":
                expected_updates.append(_sexp_to_bytearray(sexp))
                pass
            elif annot == "digest":
                expected_digests.append(_sexp_to_bytearray(sexp))
            elif annot == "final_digest":
                final_digest = _sexp_to_bytearray(sexp)

        _consume_value(reader_provider, buf, algorithm, expected_updates, expected_digests, final_digest)


_actual_updates = []
_actual_digests = []


def _consume_value(reader_provider, buf, algorithm, expected_updates, expected_digests, final_digest):
    global _actual_updates
    _actual_updates = []
    global _actual_digests
    _actual_digests = []

    buf.seek(0)
    reader = hasher(
        ion_reader.blocking_reader(managed_reader(reader_provider(), None), buf),
        _hash_function_provider(algorithm))

    next(reader)
    event = reader.send(NEXT_EVENT)
    while event.event_type is not IonEventType.STREAM_END:
        event = reader.send(NEXT_EVENT)

    if expected_updates.__len__() > 0:
        assert _actual_updates == expected_updates

    actual_digest_bytes = reader.send(HashEvent.DIGEST)

    if final_digest is not None:
        assert _actual_digests[-1] == final_digest
        assert actual_digest_bytes == final_digest
    else:
        assert _actual_digests == expected_digests
        assert actual_digest_bytes == expected_digests[-1]


def _sexp_to_bytearray(sexp):
    ba = bytearray()
    for b in sexp:
        ba.append(b)
    return ba


def _reader_provider(type):
    def _f():
        if type == "binary":
            return binary_reader()
        elif type == "text":
            return text_reader(is_unicode=True)
    return _f


def _hash_function_provider(algorithm):
    def _f():
        if algorithm == "identity":
            return _IdentityHash()
        elif algorithm == "md5":
            return _MD5Hash()
    return _f


class _IdentityHash:
    def __init__(self):
        self._bytes = bytearray()

    def update(self, _bytes):
        _actual_updates.append(_bytes)
        self._bytes.extend(_bytes)

    def digest(self):
        _bytes = self._bytes
        self._bytes = bytearray()
        _actual_digests.append(_bytes)
        return _bytes


class _MD5Hash:
    def __init__(self):
        self._m = hashlib.md5()

    def update(self, _bytes):
        self._m.update(_bytes)
        _actual_updates.append(_bytes)

    def digest(self):
        digest = self._m.digest()
        self._m = hashlib.md5()
        _actual_digests.append(digest)
        return digest

