"""Calculate coverage inside Atlas and list current risks.
Run: python3 02_stockout_risk.py --threshold-days 2
Optional: --facility CHI --drug DRG-01 --all --show-pipeline
"""
from demo_common import parser, connect, emit, run


def build_pipeline(threshold, facility=None, drug=None, show_all=False):
    match = {}
    if facility: match['facility_id'] = facility
    if drug: match['drug_id'] = drug
    pipeline = [{'$match': match}] if match else []
    pipeline += [
        {'$set': {'available': {'$max': [0, {'$subtract': [
            {'$subtract': ['$on_hand', {'$ifNull': ['$reserved', 0]}]},
            {'$ifNull': ['$quarantined', 0]}]}]}}},
        {'$set': {'days_supply': {'$cond': [
            {'$gt': ['$daily_demand', 0]}, {'$divide': ['$available', '$daily_demand']}, None]}}},
    ]
    if not show_all:
        pipeline.append({'$match': {'days_supply': {'$ne': None, '$lt': threshold}}})
    pipeline += [{'$sort': {'days_supply': 1}}, {'$project': {
        'facility_id': 1, 'drug_id': 1, 'drug': 1, 'available': 1,
        'daily_demand': 1, 'days_supply': 1}}]
    return pipeline


def main():
    p = parser(__doc__)
    p.add_argument('--threshold-days', type=float, default=2)
    p.add_argument('--facility')
    p.add_argument('--drug')
    p.add_argument('--all', action='store_true')
    p.add_argument('--show-pipeline', action='store_true')
    args = p.parse_args()
    if args.threshold_days <= 0:
        p.error('--threshold-days must be positive')
    pipeline = build_pipeline(args.threshold_days, args.facility, args.drug, args.all)
    if args.show_pipeline: emit(pipeline)
    with connect(args) as client:
        emit(list(client[args.database].inventory.aggregate(pipeline)))


if __name__ == '__main__':
    run(main)
