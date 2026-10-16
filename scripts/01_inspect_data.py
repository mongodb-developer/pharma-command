"""Explore the seeded document model and indexes without changing any data.
Run: python3 01_inspect_data.py
"""
from demo_common import parser, connect, emit, run

COLLECTIONS = ('facilities', 'drugs', 'inventory', 'shipments', 'recalls', 'memory', 'incidents')


def main():
    args = parser(__doc__).parse_args()
    with connect(args) as client:
        db = client[args.database]
        existing = set(db.list_collection_names())
        for name in COLLECTIONS:
            print(f'\n--- {args.database}.{name} ---')
            if name not in existing:
                print('Not present. Seed data through the Streamlit app first.')
                continue
            collection = db[name]
            emit({'documents': collection.count_documents({}),
                  'sample': collection.find_one({}, {'embedding': 0}),
                  'indexes': [dict(index) for index in collection.list_indexes()]})


if __name__ == '__main__':
    run(main)
