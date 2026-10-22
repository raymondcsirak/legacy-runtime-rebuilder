"""Command-line entry points. Reports use JSON; failures use nonzero exit codes."""
import argparse
import json
from pathlib import Path
import sys
import tarfile

from . import __version__
from .common import Error, write_json
from . import artifacts, host, sources


def parser():
    cli = argparse.ArgumentParser(description='Prepare and verify PHP2Shell source rebuilds. Never installs production packages.')
    cli.add_argument('--version', action='version', version=__version__)
    sub = cli.add_subparsers(dest='command')
    for command, description in [('inventory', 'Read installed PHP packages and known runtime paths'),
                                 ('audit', 'Find stale Linux PHP processes and loaded modules')]:
        item = sub.add_parser(command, help=description)
        item.add_argument('--runtime', action='append', default=[], help='Additional absolute runtime path')
        item.add_argument('--output', help='Write a new private JSON report')
    item = sub.add_parser('patches', help='Show pinned public backport provenance')
    item.add_argument('--output')
    for command in ('prepare', 'prepare-rpm'):
        item = sub.add_parser(command, help='Prepare a new copy of a trusted source tree or RPM build tree')
        item.add_argument('--branch', required=True, choices=[r['branch'] for r in sources.catalog()])
        item.add_argument('--output', required=True)
        item.add_argument('--cache', default='~/.cache/legacy-runtime-rebuilder')
        item.add_argument('--revision', default='rebuild1')
        if command == 'prepare':
            item.add_argument('--source', required=True, help='Extracted PHP tree, optionally with Debian quilt packaging')
        else:
            item.add_argument('--spec', required=True)
            item.add_argument('--sources', required=True)
            item.add_argument('--define', action='append', default=[], help='RPM macro definition, e.g. scl php72')
    item = sub.add_parser('build', help='Build prepared native packaging as an unprivileged builder user')
    item.add_argument('--tree', required=True)
    item.add_argument('--output', required=True)
    item.add_argument('--in-builder', action='store_true', help='Confirm execution inside a disposable matching builder')
    item = sub.add_parser('manifest', help='Record ELF hashes directly from trusted binary package payloads')
    item.add_argument('packages', nargs='+')
    item.add_argument('--output', required=True)
    item = sub.add_parser('verify', help='Compare installed native package versions and ELF files with an artifact manifest')
    item.add_argument('--manifest', required=True)
    item.add_argument('--output')
    return cli


def main(argv=None):
    cli = parser()
    args = cli.parse_args(argv)
    if not args.command:
        cli.print_help()
        return 2
    try:
        if any(not Path(p).is_absolute() for p in getattr(args, 'runtime', [])):
            raise Error('--runtime requires an absolute path')
        if args.command == 'inventory':
            result = host.inventory(args.runtime)
        elif args.command == 'audit':
            result = host.process_audit(extra_runtimes=args.runtime)
        elif args.command == 'patches':
            result = dict(schema=1, branches=sources.catalog(), warning='Legacy backports disable session upload-progress callbacks')
        elif args.command == 'prepare':
            result = sources.prepare_tree(args.source, args.output, args.branch, args.cache, args.revision)
        elif args.command == 'prepare-rpm':
            result = sources.prepare_rpm(args.spec, args.sources, args.output, args.branch,
                                         args.cache, args.define, args.revision)
        elif args.command == 'build':
            result = sources.build(args.tree, args.output, args.in_builder)
        elif args.command == 'manifest':
            result = artifacts.manifest(args.packages)
        elif args.command == 'verify':
            result = artifacts.verify(json.loads(Path(args.manifest).read_text(encoding='utf-8')))
        if args.command in ('manifest', 'inventory', 'audit', 'verify', 'patches') and args.output:
            write_json(args.output, result)
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        if args.command == 'audit' and result['status'] != 'current-on-disk':
            return 3
        if args.command == 'inventory' and (result['errors'] or result['processes']['errors']):
            return 3
        if args.command == 'verify' and result['failures']:
            return 3
        return 0
    except (Error, OSError, ValueError, KeyError, tarfile.TarError) as exc:
        print('error: ' + str(exc), file=sys.stderr)
        return 2
