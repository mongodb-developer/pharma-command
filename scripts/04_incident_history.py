"""Inspect business history and recorded tool results in Atlas.
Run: python3 04_incident_history.py --limit 10
Optional: --incident INC-XXXXXXXX or --status 'Transfer reserved'
"""
from demo_common import parser, connect, emit, run


def main():
    p = parser(__doc__)
    p.add_argument('--incident')
    p.add_argument('--status')
    p.add_argument('--limit', type=int, default=10)
    args = p.parse_args()
    if not 1 <= args.limit <= 100: p.error('--limit must be between 1 and 100')
    match = {}
    if args.incident: match['_id'] = args.incident
    if args.status: match['status'] = args.status
    with connect(args) as client:
        db = client[args.database]
        if args.incident:
            record = db.incidents.find_one(match)
            if not record: raise LookupError('No incident matches these filters.')
            emit(record)
        else:
            records = list(db.incidents.find(match, {
                'facility': 1, 'drug': 1, 'status': 1, 'quantity': 1,
                'created_at': 1, 'approved_at': 1, 'selected_donor.facility': 1,
            }).sort('created_at', -1).limit(args.limit))
            emit({'recent_incidents': records, 'status_counts': list(db.incidents.aggregate([
                {'$match': match}, {'$group': {'_id': '$status', 'count': {'$sum': 1}}},
                {'$sort': {'count': -1}},
            ]))})


if __name__ == '__main__':
    run(main)
