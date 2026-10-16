# 🧪 Pharma Supply Command · Workflow Lab

![Atlas](https://img.shields.io/badge/MongoDB_Atlas-Workflow_Lab-00ED64?style=for-the-badge&logo=mongodb&logoColor=001E2B)
![Python](https://img.shields.io/badge/Python-Standalone_Scripts-38BDF8?style=for-the-badge)
![Mode](https://img.shields.io/badge/Atlas_Access-Read_Only-A78BFA?style=for-the-badge)

Five focused scripts expose the data and decisions behind the Streamlit demo. Use them for code walkthroughs, terminal demos, and exploring the document model. They do not modify Atlas inventory or incident state. The export script can create a local JSON file.

## 🟢 Setup

Copy this directory into the repo as `scripts/`. Keep `demo_common.py` beside the numbered scripts.

```bash
python3 -m pip install 'pymongo[srv]>=4.8,<5'
```

Each script prompts for your Atlas URI with a **masked terminal input**. Paste it and press Enter; the URI is not echoed or saved to a file. The default database is `pharma_stockout_demo`. No source edits, `.env`, Streamlit, LLM, or Agent Engine connection is required. Use a database user that can read the demo database, and allow your machine in Atlas network access. Run in an interactive terminal that supports hidden input.

Seed data and create indexes using the Streamlit app's **Seed missing demo data** button before running the lab. These scripts never seed records or recreate indexes themselves.

## 🟣 Explore the workflow

Run from the repo root after copying this folder to `scripts/`:

| Script | Demonstrates | Example |
| :--- | :--- | :--- |
| `01_inspect_data.py` | Collection counts, sample documents, and indexes | `python3 scripts/01_inspect_data.py` |
| `02_stockout_risk.py` | Server-side coverage calculations and threshold filtering | `python3 scripts/02_stockout_risk.py --show-pipeline` |
| `03_find_transfer_donors.py` | `$geoNear`, donor protection, recalled-lot exclusions, and ETA checks | `python3 scripts/03_find_transfer_donors.py --facility CHI --drug DRG-01` |
| `04_incident_history.py` | Recent incidents, state counts, and saved tool outputs | `python3 scripts/04_incident_history.py --limit 5` |
| `05_export_incident.py` | An incident JSON handoff for the existing memory helper | `python3 scripts/05_export_incident.py --incident INC-XXXXXXXX --output incident.json` |

Every script accepts `--database` and `--help`. Replace example incident IDs with real values from script 04.

## 🎬 Terminal demo sequence

1. Run script 01 to show the operational document model and indexes.
2. In Streamlit, inject a **Supplier delay** for Chicago / Cefazolin.
3. Run script 02 to show the stockout risk calculated inside Atlas.
4. Run script 03 to show eligible donors **and why other donors were excluded**.
5. Investigate and approve a transfer in Streamlit.
6. Run script 04 to show the persisted decision, then export that record with script 05.

Healthy seed data may produce no risk rows initially. Injecting a disruption in the app makes the risk walkthrough more interesting.

## 🧠 Hand the export to Agent Engine memory

With the previously supplied `agent_memory.py` in the repository root:

```python
import json
from agent_engine_sdk_memory import Memory
from agent_memory import write_incident_memory

with open('incident.json', encoding='utf-8') as source:
    incident = json.load(source)

with Memory(base_url='http://<container-host>:<published-memory-port>') as memory:
    write_incident_memory(memory, incident, user_id='demo-operator')
```

The memory SDK and its endpoint are separate from the operational Atlas connection. This snippet is an optional integration; the numbered scripts do not send memory writes. Follow `AGENT_MEMORY.md` for routing, identity, visibility, and duplicate-write considerations.

## 🔵 Details worth explaining

- **Coverage:** usable inventory excludes outbound reservations and quarantined stock.
- **Risk pipeline:** this lab guards zero demand by returning `null` coverage and clamps negative usable inventory to zero. Valid seeded data has positive demand and nonnegative usable inventory.
- **Donor search:** 160 km radius, three days of protected donor supply, and synthetic arrival before recipient depletion. Donor results are a current-data explanation, not a replay of historical candidate state or an approval.
- **History:** inspect a specific ID with `--incident` to see its recorded investigation tool results.
- **Exports:** `--output` refuses to overwrite an existing file. App-created incidents use JSON-native strings/numbers/objects; manually added BSON values may need conversion before memory handoff.
- **Scope:** no live FDA feed, real courier routing, dispatch, or automatic transfer execution.

## ✅ Validation

All files were syntax-checked. Donor eligibility rules and risk pipeline construction were exercised locally against fixtures. Live Atlas connectivity and server-side query execution require your own connection and were not exercised for this package.
