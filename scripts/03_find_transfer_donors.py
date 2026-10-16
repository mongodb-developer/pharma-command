"""Explain donor eligibility using real Atlas geo queries. Does NOT reserve stock.
Run: python3 03_find_transfer_donors.py --facility CHI --drug DRG-01
"""
import math
from demo_common import parser, connect, emit, run, available


def evaluate(donor, active_recalls, quantity, depletion_hours, distance_m):
    """Same demo thresholds/ETA assumptions as app.py; return visible reasons."""
    surplus = math.floor(available(donor) - 3 * donor['daily_demand'])
    eta = round(0.5 + (distance_m / 1000 * 1.3) / 45, 1)
    reasons = []
    if any(r['lot'] == donor['lot'] for r in active_recalls): reasons.append('Donor lot recalled')
    if quantity <= 0: reasons.append('Recipient already has three days of supply')
    if surplus < quantity: reasons.append('Insufficient surplus after protecting three days')
    if eta >= depletion_hours: reasons.append('Estimated arrival is not before depletion')
    return {'eligible': not reasons, 'reasons': reasons, 'surplus_units': surplus,
            'distance_km': round(distance_m / 1000, 1), 'eta_hours': eta}


def main():
    p = parser(__doc__)
    p.add_argument('--facility', default='CHI')
    p.add_argument('--drug', default='DRG-01')
    args = p.parse_args()
    with connect(args) as client:
        db = client[args.database]
        facility = db.facilities.find_one({'_id': args.facility})
        target = db.inventory.find_one({'facility_id': args.facility, 'drug_id': args.drug})
        if not facility or not target: raise LookupError('Facility/inventory not found. Seed data and check IDs.')
        if target['daily_demand'] <= 0: raise ValueError('Positive daily demand is required.')
        quantity = max(0, math.ceil(3 * target['daily_demand'] - available(target)))
        hours = available(target) / target['daily_demand'] * 24
        recalls = list(db.recalls.find({'drug_id': args.drug, 'active': True}))
        nearby = db.facilities.aggregate([
            {'$geoNear': {'near': facility['location'], 'distanceField': 'distance_m',
                          'spherical': True, 'maxDistance': 160000}},
            {'$match': {'_id': {'$ne': args.facility}}},
        ])
        options = []
        for candidate in nearby:
            donor = db.inventory.find_one({'facility_id': candidate['_id'], 'drug_id': args.drug})
            if donor:
                options.append({'facility': candidate['name'], 'inventory_id': donor['_id'],
                    **evaluate(donor, recalls, quantity, hours, candidate['distance_m'])})
        options.sort(key=lambda r: r['eta_hours'])
        emit({'recipient': facility['name'], 'requested_units': quantity,
              'hours_to_depletion': round(hours, 1), 'candidates_including_exclusions': options,
              'note': 'Straight-line distance; simulated courier ETA. No reservation executed.'})


if __name__ == '__main__':
    run(main)
