"""Command line entry point."""
import argparse
import json
import sys
from . import __version__
from .audit import audit


def main(argv=None):
    parser = argparse.ArgumentParser(description='Audit documented claims against static source evidence.')
    parser.add_argument('root')
    parser.add_argument('--version', action='version', version=__version__)
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--ignore', action='append', default=[])
    parser.add_argument('--fail-on', choices=['LOW', 'MEDIUM', 'HIGH'], default='HIGH')
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return 1 if error.code else 0
    try:
        result = audit(args.root, args.ignore)
    except (OSError, UnicodeError, ValueError, SyntaxError) as error:
        print('error: ' + str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(result['status'])
        for finding in result['findings']:
            print(finding['rule_id'] + ' ' + finding['severity'] + ': ' + finding['message'])
            if args.verbose:
                for claim in finding['claims']:
                    print('  ' + claim['path'] + ': ' + claim['phrase'])
        if args.verbose:
            print('Evidence: ' + json.dumps(result['evidence'], sort_keys=True))
    levels = {'LOW': 0, 'MEDIUM': 1, 'HIGH': 2}
    return 2 if any(levels[f['severity']] >= levels[args.fail_on] for f in result['findings']) else 0


if __name__ == '__main__':
    sys.exit(main())
