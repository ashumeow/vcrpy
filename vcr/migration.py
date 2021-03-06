"""
Migration script for old 'yaml' and 'json' cassettes

.. warning:: Backup your cassettes files before migration.

It merges and deletes the request obsolete keys (protocol, host, port, path)
into new 'uri' key.
Usage::

    python -m vcr.migration PATH

The PATH can be path to the directory with cassettes or cassette itself
"""

import json
import os
import shutil
import sys
import tempfile
import yaml

from .serializers import compat, yamlserializer
from . import request

# Use the libYAML versions if possible
try:
    from yaml import CLoader as Loader
except ImportError:
    from yaml import Loader


PARTS = [
    'protocol',
    'host',
    'port',
    'path',
]


def build_uri(**parts):
    port = parts['port']
    scheme = parts['protocol']
    default_port = {'https': 433, 'http': 80}[scheme]
    parts['port'] = ':{0}'.format(port) if port != default_port else ''
    return "{protocol}://{host}{port}{path}".format(**parts)


def migrate_json(in_fp, out_fp):
    data = json.load(in_fp)
    for item in data:
        req = item['request']
        uri = dict((k, req.pop(k)) for k in PARTS)
        req['uri'] = build_uri(**uri)
        # convert headers to dict of lists
        headers = req['headers']
        for k in headers:
            headers[k] = [headers[k]]
    json.dump(data, out_fp, indent=4)


def _restore_frozenset():
    """
    Restore __builtin__.frozenset for cassettes serialized in python2 but
    deserialized in python3 and builtins.frozenset for cassettes serialized
    in python3 and deserialized in python2
    """

    if '__builtin__' not in sys.modules:
        import builtins
        sys.modules['__builtin__'] = builtins

    if 'builtins' not in sys.modules:
        sys.modules['builtins'] = sys.modules['__builtin__']


def _old_deserialize(cassette_string):
    _restore_frozenset()
    data = yaml.load(cassette_string, Loader=Loader)
    requests = [r['request'] for r in data]
    responses = [r['response'] for r in data]
    responses = [compat.convert_to_bytes(r['response']) for r in data]
    return requests, responses


def migrate_yml(in_fp, out_fp):
    (requests, responses) = _old_deserialize(in_fp.read())
    for req in requests:
        if not isinstance(req, request.Request):
            raise Exception("already migrated")
        else:
            req.uri = build_uri(
                protocol=req.__dict__['protocol'],
                host=req.__dict__['host'],
                port=req.__dict__['port'],
                path=req.__dict__['path'],
            )

            # convert headers to dict of lists
            headers = req.headers
            req.headers = {}
            for key, value in headers:
                req.add_header(key, value)

    data = yamlserializer.serialize({
        "requests": requests,
        "responses": responses,
    })
    out_fp.write(data)


def migrate(file_path, migration_fn):
    # because we assume that original files can be reverted
    # we will try to copy the content. (os.rename not needed)
    with tempfile.TemporaryFile(mode='w+') as out_fp:
        with open(file_path, 'r') as in_fp:
            migration_fn(in_fp, out_fp)
        with open(file_path, 'w') as in_fp:
            out_fp.seek(0)
            shutil.copyfileobj(out_fp, in_fp)


def try_migrate(path):
    try:  # try to migrate as json
        migrate(path, migrate_json)
    except Exception:  # probably the file is not a json
        try:  # let's try to migrate as yaml
            migrate(path, migrate_yml)
        except Exception:  # oops probably the file is not a cassette
            return False
    return True


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Please provide path to cassettes directory or file. "
                         "Usage: python -m vcr.migration PATH")

    path = sys.argv[1]
    if not os.path.isabs(path):
        path = os.path.abspath(path)
    files = [path]
    if os.path.isdir(path):
        files = (os.path.join(root, name)
                 for (root, dirs, files) in os.walk(path)
                 for name in files)
    for file_path in files:
            migrated = try_migrate(file_path)
            status = 'OK' if migrated else 'FAIL'
            sys.stderr.write("[{0}] {1}\n".format(status, file_path))
    sys.stderr.write("Done.\n")

if __name__ == '__main__':
    main()
