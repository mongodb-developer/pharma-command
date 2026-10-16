"""Shared connection and output helpers. No Streamlit or .env dependency."""
import argparse
import getpass
from pymongo import MongoClient
from bson import json_util

DATABASE_NAME = "pharma_stockout_demo"


def parser(description):
    result = argparse.ArgumentParser(description=description)
    result.add_argument('--database', default=DATABASE_NAME)
    return result


def connect(args):
    uri = getpass.getpass('Atlas URI (hidden): ').strip()
    if not uri or '<' in uri:
        raise ValueError('Enter a complete Atlas connection string.')
    client = MongoClient(uri, serverSelectionTimeoutMS=7000,
                         connectTimeoutMS=7000, appname='PharmaWorkflowWalkthrough')
    try:
        client.admin.command('ping')
    except Exception:
        client.close()
        raise
    return client


def emit(value):
    print(json_util.dumps(value, indent=2))


def available(row):
    return max(0, row['on_hand'] - row.get('reserved', 0) - row.get('quarantined', 0))


def run(main):
    try:
        main()
    except (ValueError, LookupError) as exc:
        raise SystemExit(str(exc)) from None
    except Exception as exc:
        # Avoid printing connection strings or credentials in driver exceptions.
        raise SystemExit(f'Operation failed ({type(exc).__name__}). Check Atlas connectivity, permissions, and seeded data.') from None
