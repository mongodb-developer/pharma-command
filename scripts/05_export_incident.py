"""Export an incident to JSON for inspection or the Agent Engine memory helper.
Run: python3 05_export_incident.py --incident INC-XXXXXXXX --output incident.json
Without --output, emits JSON to stdout. Never changes Atlas data.
"""
import json
from pathlib import Path
from demo_common import parser, connect, emit, run


def main():
    p = parser(__doc__)
    p.add_argument('--incident', required=True)
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    with connect(args) as client:
        record = client[args.database].incidents.find_one({'_id': args.incident})
    if not record: raise LookupError('Incident not found. Copy an ID from 04_incident_history.py.')
    if args.output:
        # Exclusive creation avoids accidentally overwriting an existing export.
        try:
            payload = json.dumps(record, indent=2, ensure_ascii=False)
        except TypeError:
            raise ValueError('Incident contains non-JSON-native values; inspect it with script 04.') from None
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(payload + '\n')
        print(f'Exported {record["_id"]} to {args.output}')
    else:
        emit(record)


if __name__ == '__main__':
    run(main)
