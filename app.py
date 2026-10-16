"""Pharma Stockout | Python 3.10+ | streamlit run app.py"""
import copy
import json
import math
import uuid
from datetime import datetime, timezone

import pandas as pd
import plotly.express as px
import streamlit as st
from pymongo import MongoClient, UpdateOne
from pymongo.write_concern import WriteConcern

# EDIT HERE. No .env or OpenAI dependency is required.
ATLAS_URI = ""  # mongodb+srv://...
DATABASE_NAME = "pharma_stockout_demo"
GREEN = "#5CF2A5"

st.set_page_config(page_title="Agent Engine | Pharma Supply Command", page_icon="💊", layout="wide")

CSS = """
<style>
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] {background:#25282D;color:#F0F4F2;}
[data-testid="stSidebar"] {background:#202328;border-right:1px solid #3B4248;}
[data-testid="stSidebar"] * {color:#E7EEE9;}
.block-container {padding-top:2rem;max-width:1500px;}
h1,h2,h3 {letter-spacing:-.035em;color:#F0F4F2!important;}
h1 {font-size:2.8rem!important;}
p,label,[data-testid="stMarkdownContainer"],.stCaption {color:#DAE4DE;}
[data-testid="stMetric"] {background:#2D3238;padding:18px 22px;border:1px solid #41494F;border-radius:14px;}
[data-testid="stMetricValue"] {color:#5CF2A5;}
.stButton>button {background:#30373D;color:#F0F4F2;border:1px solid #53615B;border-radius:9px;min-height:42px;}
.stButton>button:hover {border-color:#5CF2A5;color:#5CF2A5;background:#35463E;}
.stButton>button[kind="primary"] {background:#5CF2A5;border-color:#5CF2A5;color:#153126;}
.stButton>button[kind="primary"] p {color:#153126!important;font-weight:700;}
.stButton>button:disabled {opacity:.45;}
[data-baseweb="select"]>div,[data-baseweb="input"],[data-baseweb="textarea"], input,textarea {background:#30363D!important;color:#F0F4F2!important;}
[data-baseweb="popover"],[data-baseweb="menu"], [role="listbox"], [role="option"] {background:#30363D!important;color:#F0F4F2!important;}
[data-baseweb="select"] span {color:#F0F4F2!important;}
[data-testid="stExpander"] {background:#2A2F35;border-color:#454E54;border-radius:10px;}
.stTabs [data-baseweb="tab-list"] {gap:22px;border-bottom:1px solid #434B51;}
.stTabs [aria-selected="true"] {color:#5CF2A5!important;}
.eyebrow {color:#5CF2A5;font-size:.75rem;letter-spacing:.16em;font-weight:700;}
.hero {padding:8px 0 18px;}.hero p {color:#B7C8BE;max-width:900px;font-size:1.02rem;}
.pill {display:inline-block;background:#314B3F;color:#82F7B9;border:1px solid #4D705D;padding:5px 10px;border-radius:30px;font-size:.72rem;letter-spacing:.04em;}
.step {background:#2D3339;border:1px solid #45534B;border-top:3px solid #5CF2A5;border-radius:10px;padding:15px;min-height:125px;margin-bottom:12px;}
.step small {color:#5CF2A5;letter-spacing:.1em;}.step h4 {color:#F0F4F2;margin:8px 0;font-size:1rem;}.step p {color:#B9CBBF;font-size:.85rem;margin:0;}
.result {background:#2D3E35;border-left:4px solid #5CF2A5;border-radius:8px;padding:20px;margin:14px 0;}
.footer {color:#A6B8AD;font-size:.78rem;margin-top:2rem;border-top:1px solid #41494F;padding-top:16px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def seed_data():
    facilities = [
        {"_id":"CHI", "name":"Chicago Medical Center", "location":{"type":"Point","coordinates":[-87.6298,41.8781]}},
        {"_id":"EVN", "name":"Evanston Regional", "location":{"type":"Point","coordinates":[-87.6877,42.0451]}},
        {"_id":"OAK", "name":"Oak Brook Hospital", "location":{"type":"Point","coordinates":[-87.9536,41.8398]}},
        {"_id":"NAP", "name":"Naperville Specialty", "location":{"type":"Point","coordinates":[-88.1535,41.7508]}},
        {"_id":"JOL", "name":"Joliet Community", "location":{"type":"Point","coordinates":[-88.0817,41.5250]}},
        {"_id":"WKG", "name":"Waukegan Health", "location":{"type":"Point","coordinates":[-87.8448,42.3636]}},
    ]
    drugs = [
        {"_id":"DRG-01","name":"Cefazolin 1 g vial","category":"Antibiotic"},
        {"_id":"DRG-02","name":"Sodium chloride 0.9% 1 L","category":"IV fluid"},
        {"_id":"DRG-03","name":"Ondansetron 4 mg vial","category":"Antiemetic"},
        {"_id":"DRG-04","name":"Heparin 5,000 units/mL","category":"Anticoagulant"},
        {"_id":"DRG-05","name":"Propofol 200 mg vial","category":"Anesthetic"},
        {"_id":"DRG-06","name":"Epinephrine 1 mg/mL","category":"Emergency"},
    ]
    inventory, shipments = [], []
    for fi, facility in enumerate(facilities):
        for di, drug in enumerate(drugs):
            daily = 40 + di * 12 + fi * 4
            inventory.append({"_id":f"{facility['_id']}:{drug['_id']}","facility_id":facility['_id'],"drug_id":drug['_id'],
                "drug":drug['name'],"daily_demand":daily,"on_hand":daily*(5+fi),"reserved":0,
                "quarantined":0,"lot":f"DEMO-{fi+1}{di+1}","updated_at":now()})
            shipments.append({"_id":f"SHIP:{facility['_id']}:{drug['_id']}","facility_id":facility['_id'],"drug_id":drug['_id'],
                "status":"On schedule","eta_hours":24,"quantity":daily*4,"supplier":"Demo Supply Co."})
    recalls = [{"_id":"SIM-RECALL-001","drug_id":"DRG-01","lot":"DEMO-11","active":False,
                "notice":"Synthetic lot-level quality notice. Not an FDA feed.","source":"SIMULATED FDA RECALL FIXTURE"}]
    memory = [{"_id":"MEM-001","title":"Delayed antibiotic shipment resolved by regional transfer",
               "drug_id":"DRG-01","cause":"Supplier delay","outcome":"Transfer reserved from Evanston; donor retained three days of supply."},
              {"_id":"MEM-002","title":"Demand surge after elective procedure backlog",
               "drug_id":"DRG-02","cause":"Demand surge","outcome":"Regional transfer plus replenishment order restored coverage."},
              {"_id":"MEM-003","title":"Quality notice blocked a lot from transfer",
               "drug_id":"DRG-01","cause":"Lot recall","outcome":"Affected lot quarantined; alternate facility supplied unaffected inventory."}]
    return {"facilities":facilities,"drugs":drugs,"inventory":inventory,"shipments":shipments,"recalls":recalls,"memory":memory,"incidents":[]}


@st.cache_resource
def connect(uri):
    client = MongoClient(uri, serverSelectionTimeoutMS=7000, connectTimeoutMS=7000, appname="PharmaStockoutDemo")
    client.admin.command("ping")
    return client


class Store:
    def __init__(self, uri):
        self.db = connect(uri)[DATABASE_NAME] if uri.strip() else None
        if "local_data" not in st.session_state:
            st.session_state.local_data = seed_data()

    def rows(self, collection):
        if self.db is not None:
            return list(self.db[collection].find({}, {"embedding":0}))
        return copy.deepcopy(st.session_state.local_data[collection])

    def put(self, collection, doc):
        if self.db is not None:
            self.db[collection].replace_one({"_id":doc["_id"]},doc,upsert=True)
        else:
            rows = st.session_state.local_data[collection]
            rows[:] = [r for r in rows if r['_id'] != doc['_id']] + [copy.deepcopy(doc)]

    def seed(self):
        # Insert missing fixture records only. Never overwrite live demo state.
        if self.db is None:
            return
        for name, rows in seed_data().items():
            if rows:
                self.db[name].bulk_write([UpdateOne({"_id":r["_id"]},{"$setOnInsert":r},upsert=True) for r in rows])
        self.db.inventory.create_index([("facility_id",1),("drug_id",1)],unique=True)
        self.db.facilities.create_index([("location","2dsphere")])
        self.db.incidents.create_index([("created_at",-1)])
        self.db.recalls.create_index([("drug_id",1),("active",1)])

    def risk(self):
        if self.db is not None:
            return list(self.db.inventory.aggregate([
                {"$set":{"available":{"$subtract":[{"$subtract":["$on_hand","$reserved"]},"$quarantined"]}}},
                {"$set":{"days_supply":{"$divide":["$available","$daily_demand"]}}},
                {"$sort":{"days_supply":1}}]))
        result = self.rows("inventory")
        for row in result:
            row['available'] = available(row)
            row['days_supply'] = available(row)/row['daily_demand']
        return sorted(result,key=lambda r:r['days_supply'])

    def nearby(self, facility):
        if self.db is not None:
            return list(self.db.facilities.aggregate([
                {"$geoNear":{"near":facility['location'],"distanceField":"distance_m","spherical":True,"maxDistance":160000}},
                {"$match":{"_id":{"$ne":facility['_id']}}}]))
        result=[]
        lon1,lat1=facility['location']['coordinates']
        for f in self.rows('facilities'):
            if f['_id']==facility['_id']:
                continue
            lon2,lat2=f['location']['coordinates']
            a=math.sin(math.radians(lat2-lat1)/2)**2+math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(math.radians(lon2-lon1)/2)**2
            f['distance_m']=6371000*2*math.atan2(math.sqrt(a), math.sqrt(1-a))
            if f['distance_m']<=160000:
                result.append(f)
        return sorted(result,key=lambda f:f['distance_m'])

    def approve(self, incident_id, donor_id):
        def operation(session=None):
            def get(collection, identity):
                if self.db is not None:
                    return self.db[collection].find_one({'_id':identity},session=session)
                return next((r for r in self.rows(collection) if r['_id']==identity),None)
            incident=get('incidents',incident_id)
            if not incident or incident['status']!='Awaiting approval':
                raise ValueError('This incident has already been handled or is no longer awaiting approval.')
            option=next((x for x in incident['candidates'] if x['inventory_id']==donor_id),None)
            if not option:
                raise ValueError('Choose a proposed donor.')
            donor=get('inventory',donor_id)
            target=get('inventory',incident['inventory_id'])
            active_recalls=[r for r in (self.db.recalls.find({'active':True},session=session) if self.db is not None else self.rows('recalls')) if r.get('active')]
            if any(r['drug_id']==donor['drug_id'] and r['lot']==donor['lot'] for r in active_recalls):
                raise ValueError('Donor lot is now recalled. Run a new investigation.')
            quantity=incident['quantity']
            if available(donor)-quantity < donor['daily_demand']*3:
                raise ValueError('Donor no longer has enough surplus to retain three days of supply.')
            if max(0,math.ceil(target['daily_demand']*3-available(target))) != quantity:
                raise ValueError('Recipient inventory changed. Run a new investigation.')
            donor['reserved']+=quantity
            donor['updated_at']=now()
            incident.update(status='Transfer reserved',approved_at=now(),selected_donor=option,
                transfer={'quantity':quantity,'status':'Reserved; awaiting simulated dispatch','recipient_received':False})
            if self.db is not None:
                self.db.inventory.replace_one({'_id':donor_id},donor,session=session)
                self.db.incidents.replace_one({'_id':incident_id},incident,session=session)
            else:
                self.put('inventory',donor)
                self.put('incidents',incident)
            return incident
        if self.db is not None:
            with self.db.client.start_session() as session:
                return session.with_transaction(operation,write_concern=WriteConcern('majority'))
        return operation()


def available(row):
    return max(0,row['on_hand']-row.get('reserved',0)-row.get('quarantined',0))


def inject_scenario(store, facility_id, drug_id, scenario):
    identity=f'{facility_id}:{drug_id}'
    row=next(r for r in store.rows('inventory') if r['_id']==identity)
    # New scenario uses a new synthetic lot. Old reservations and incidents remain intact.
    if any(i['inventory_id']==identity and i['status']=='Awaiting approval' for i in store.rows('incidents')):
        raise ValueError('Investigate or use a different facility/drug; an incident is already awaiting approval for this inventory.')
    row.update(daily_demand=60,on_hand=row['reserved']+45,quarantined=0,lot=f"SIM-{uuid.uuid4().hex[:8]}",updated_at=now())
    shipment=next(r for r in store.rows('shipments') if r['facility_id']==facility_id and r['drug_id']==drug_id)
    shipment.update(status='Delayed' if scenario=='Supplier delay' else 'On schedule',eta_hours=72 if scenario=='Supplier delay' else 24)
    if scenario=='Demand surge':
        row['daily_demand']=120
    if scenario=='Lot recall':
        row['on_hand']=row['reserved']+240
        row['quarantined']=220
        store.put('recalls',{'_id':f"RECALL:{row['lot']}",'drug_id':drug_id,'lot':row['lot'],'active':True,
            'notice':'Synthetic quality event: affected lot must not be transferred.','source':'SIMULATED FDA RECALL FIXTURE'})
    store.put('inventory',row)
    store.put('shipments',shipment)


def investigate(store, facility_id, drug_id):
    inventory_id=f'{facility_id}:{drug_id}'
    previous=next((i for i in store.rows('incidents') if i['inventory_id']==inventory_id and i['status']=='Awaiting approval'),None)
    if previous:
        return previous
    row=next(r for r in store.risk() if r['_id']==inventory_id)
    facility=next(f for f in store.rows('facilities') if f['_id']==facility_id)
    shipments=[s for s in store.rows('shipments') if s['facility_id']==facility_id and s['drug_id']==drug_id]
    recalls=[r for r in store.rows('recalls') if r['drug_id']==drug_id and r['active']]
    causes=[]
    if any(s['status']=='Delayed' for s in shipments): causes.append('Supplier delay')
    if row['daily_demand']>=100: causes.append('Demand surge')
    if any(r['lot']==row['lot'] for r in recalls): causes.append('Lot recall')
    quantity=max(0,math.ceil(3*row['daily_demand']-row['available']))
    donors={r['facility_id']:r for r in store.rows('inventory') if r['drug_id']==drug_id}
    candidates=[]
    for f in store.nearby(facility):
        donor=donors.get(f['_id'])
        if not donor or any(r['lot']==donor['lot'] for r in recalls): continue
        surplus=math.floor(available(donor)-3*donor['daily_demand'])
        # Straight-line distance with 30% road factor; synthetic courier speed/handling.
        km=f['distance_m']/1000
        eta=round(0.5+(km*1.3)/45,1)
        if quantity>0 and surplus>=quantity and eta<row['days_supply']*24:
            candidates.append({'inventory_id':donor['_id'],'facility':f['name'],'surplus':surplus,
                'distance_km':round(km,1),'eta_hours':eta,'donor_days_after':round((available(donor)-quantity)/donor['daily_demand'],1)})
    candidates.sort(key=lambda c:c['eta_hours'])
    memories=[m for m in store.rows('memory') if m['drug_id']==drug_id or m['cause'] in causes]
    is_risk=row['days_supply']<2
    incident={'_id':f"INC-{uuid.uuid4().hex[:8].upper()}",'created_at':now(),'inventory_id':inventory_id,
        'facility':facility['name'],'drug':row['drug'],'drug_id':drug_id,'days_supply':round(row['days_supply'],2),
        'quantity':quantity,'causes':causes or ['Low inventory; no confirmed external cause'],
        'candidates':candidates,'memories':memories,'status':'Awaiting approval' if is_risk and candidates else ('Escalation required' if is_risk else 'Healthy'),
        'tools':[
            {'name':'fetch_stockout_alerts','input':{'facility_id':facility_id,'drug_id':drug_id},'result':{'available':row['available'],'hours_supply':round(row['days_supply']*24,1),'daily_demand':row['daily_demand'],'shipments':shipments}},
            {'name':'check_fda_recalls [SIMULATED]','input':{'drug_id':drug_id,'lot':row['lot']},'result':{'source':'Seeded simulation, not live FDA data','active_drug_notices':recalls,'affected_target_lot':any(r['lot']==row['lot'] for r in recalls)}},
            {'name':'lookup_transfer_logistics','input':{'radius_km':160,'minimum_donor_days_remaining':3,'requested_units':quantity},'result':candidates},
            {'name':'retrieve_incident_memory [METADATA MATCH]','input':{'drug_id':drug_id,'causes':causes},'result':memories}
        ]}
    store.put('incidents',incident)
    return incident


def chart_style(fig):
    fig.update_layout(paper_bgcolor='#25282D',plot_bgcolor='#25282D',font_color='#DAE4DE',
        margin=dict(l=10,r=15,t=20,b=10),height=330,legend_title_text='')
    fig.update_xaxes(gridcolor='#3A4248',zerolinecolor='#3A4248')
    fig.update_yaxes(gridcolor='#3A4248',zerolinecolor='#3A4248')
    return fig


def main():
    with st.sidebar:
        st.markdown('<div class="eyebrow">SUPPLY COMMAND</div>',unsafe_allow_html=True)
        st.markdown('### Demo control room')
        st.caption('Synthetic pharmacy operations • Human approval')
        uri=st.text_input('Atlas connection string',value=ATLAS_URI,type='password',help='Leave blank for local session mode, or hardcode ATLAS_URI at the top of app.py.')
        st.caption(f'Database: {DATABASE_NAME}')
        try:
            store=Store(uri)
        except Exception:
            st.error('Atlas connection failed. Check URI, database user, IP access list, and network. Clear the URI to use local mode.')
            st.stop()
        backend='Atlas connected' if store.db is not None else 'Local session mode'
        st.markdown(f'<span class="pill">{backend}</span>',unsafe_allow_html=True)
        if st.button('Seed missing demo data',use_container_width=True):
            store.seed()
            st.success('Missing fixtures and indexes are ready. Existing records were preserved.')
        facilities=store.rows('facilities')
        drugs=store.rows('drugs')
        if not facilities or not drugs:
            st.info('Click “Seed missing demo data” to initialize this database.')
            st.stop()
        facility_id=st.selectbox('Facility',[f['_id'] for f in facilities],format_func=lambda v:next(f['name'] for f in facilities if f['_id']==v))
        drug_id=st.selectbox('Drug',[d['_id'] for d in drugs],format_func=lambda v:next(d['name'] for d in drugs if d['_id']==v))
        scenario=st.selectbox('New demo scenario',['Supplier delay','Demand surge','Lot recall'])
        if st.button('Simulate supply disruption',type='primary',use_container_width=True):
            inject_scenario(store,facility_id,drug_id,scenario)
            st.session_state.pop('active_incident',None)
            st.session_state['flash']='Disruption injected. Run the investigation to identify a response.'
            st.rerun()
        st.divider()
        st.caption('Monitoring runs on demand. Logistics and recall notices are simulated. Atlas queries and writes are real when connected.')
        if store.db is None:
            st.caption('Local data lasts for this browser session. Atlas preserves incidents across sessions.')

    st.markdown('<div class="hero"><div class="eyebrow">MONGODB ATLAS · AGENT ENGINE DEMO</div><h1>Pharma Supply Command</h1><p>Stay ahead of the stockout. Detect supply risk, investigate the cause, and coordinate a regional response.</p><span class="pill">Simulated agent workflow · Atlas-backed when connected</span></div>',unsafe_allow_html=True)
    if st.session_state.get('flash'):
        st.success(st.session_state.pop('flash'))
    risks=store.risk()
    incidents=store.rows('incidents')
    names={f['_id']:f['name'] for f in facilities}
    selected=next(r for r in risks if r['_id']==f'{facility_id}:{drug_id}')
    c1,c2,c3,c4=st.columns(4)
    c1.metric('Facilities monitored',len(facilities))
    c2.metric('Stockout risks · <2 days',sum(r['days_supply']<2 for r in risks))
    c3.metric('Selected drug coverage',f"{selected['days_supply']*24:.0f} hrs")
    c4.metric('Transfers reserved',sum(i['status']=='Transfer reserved' for i in incidents))
    st.write('')
    overview,workflow,history,atlas=st.tabs(['Supply overview','Agent workflow','Incident history','Atlas explorer'])
    with overview:
        left,right=st.columns([1.35,1])
        with left:
            st.subheader('Regional supply coverage')
            rows=[{'Facility':names[r['facility_id']],'Days of supply':round(r['days_supply'],2),'Status':'At risk' if r['days_supply']<2 else 'Covered'} for r in risks if r['drug_id']==drug_id]
            fig=px.bar(pd.DataFrame(rows),x='Days of supply',y='Facility',orientation='h',color='Status',color_discrete_map={'Covered':GREEN,'At risk':'#FFB86B'})
            fig.add_vline(x=2,line_dash='dot',line_color='#FFB86B')
            st.plotly_chart(chart_style(fig),use_container_width=True)
        with right:
            st.subheader('Selected inventory')
            st.markdown(f"**{names[facility_id]}**  \n{selected['drug']}")
            st.dataframe(pd.DataFrame([{'Measure':'On hand','Units':selected['on_hand']},{'Measure':'Reserved outbound','Units':selected['reserved']},{'Measure':'Quarantined','Units':selected['quarantined']},{'Measure':'Available','Units':selected['available']},{'Measure':'Daily demand','Units':selected['daily_demand']}]),hide_index=True,use_container_width=True)
            st.caption('Coverage excludes quarantined stock and outbound reservations. Approved inbound transfers do not count as received inventory.')
        st.subheader('Inventory watchlist')
        watch=[{'Facility':names[r['facility_id']],'Drug':r['drug'],'Available':r['available'],'Days of supply':round(r['days_supply'],2),'Status':'At risk' if r['days_supply']<2 else 'Covered'} for r in risks]
        st.dataframe(pd.DataFrame(watch),hide_index=True,use_container_width=True,height=300)
    with workflow:
        st.subheader('From signal to coordinated response')
        steps=[('01 / MONITOR','Detect inventory risk','Check usable stock and projected coverage.'),('02 / DIAGNOSE','Explain the disruption','Inspect shipments, demand, and lot notices.'),('03 / PLAN','Evaluate regional supply','Find surplus and estimate courier arrival.'),('04 / APPROVE','Reserve a transfer','Save the reservation and incident state.')]
        for col,(n,title,desc) in zip(st.columns(4),steps):
            col.markdown(f'<div class="step"><small>{n}</small><h4>{title}</h4><p>{desc}</p><span class="pill">Simulated agent workflow · Atlas-backed when connected</span></div>',unsafe_allow_html=True)
        st.caption('Deterministic agent simulation: Python orchestrates named tools. No LLM, hidden reasoning trace, or external agent service is required.')
        if st.button('Run monitoring & investigation',type='primary'):
            with st.spinner('Checking stock, recall fixtures, regional logistics, and prior incidents…'):
                incident=investigate(store,facility_id,drug_id)
                st.session_state['active_incident']=(backend,incident['_id'])
        active=st.session_state.get('active_incident')
        incident=next((i for i in store.rows('incidents') if active and active[0]==backend and i['_id']==active[1]),None)
        if incident:
            st.markdown(f"#### {incident['_id']} · {incident['status']}")
            st.write(f"{incident['facility']} · {incident['drug']}")
            st.write('**Findings:** '+', '.join(incident['causes']))
            for tool in incident['tools']:
                with st.expander(tool['name'],expanded=False):
                    st.caption('Tool input')
                    st.json(tool['input'])
                    st.caption('Recorded result')
                    st.json(tool['result'])
            if incident['status']=='Healthy':
                st.success('Coverage is above the alert threshold. No transfer is proposed.')
            elif incident['status']=='Escalation required':
                st.warning('No donor satisfies supply and arrival constraints. Escalate to the supply team for manual review.')
            else:
                options=incident['candidates']
                st.dataframe(pd.DataFrame(options).drop(columns=['inventory_id']),hide_index=True,use_container_width=True)
                st.caption('Distance is straight-line. ETA uses a synthetic road factor, courier speed, and handling time; it is not a routing service.')
                st.markdown(f'<div class="result"><b>Proposed action</b><br>Reserve {incident["quantity"]} units to restore the recipient to three days of usable supply after delivery. Each proposed donor retains at least three days.</div>',unsafe_allow_html=True)
                if incident['status']=='Awaiting approval':
                    donor=st.selectbox('Transfer source',[o['inventory_id'] for o in options],format_func=lambda v:next(o['facility'] for o in options if o['inventory_id']==v),key=incident['_id'])
                    if st.button('Approve & reserve transfer',type='primary'):
                        store.approve(incident['_id'],donor)
                        st.session_state['flash']='Transfer reserved. The recipient will gain coverage after delivery, not at approval.'
                        st.rerun()
                elif incident['status']=='Transfer reserved':
                    st.success(f"{incident['quantity']} units reserved at {incident['selected_donor']['facility']}. Awaiting simulated dispatch.")
            st.download_button('Download incident JSON',json.dumps(incident,indent=2,default=str),file_name=f"{incident['_id']}.json",mime='application/json')
        else:
            st.info('Inject a scenario using the sidebar, then run the investigation here.')
    with history:
        st.subheader('Persistent incident history')
        incidents=sorted(store.rows('incidents'),key=lambda i:i['created_at'],reverse=True)
        if incidents:
            chosen=st.selectbox('Open an incident',[i['_id'] for i in incidents],format_func=lambda v:next(f"{i['_id']} · {i['facility']} · {i['status']}" for i in incidents if i['_id']==v))
            record=next(i for i in incidents if i['_id']==chosen)
            st.json(record,expanded=False)
            if st.button('Open in agent workflow'):
                st.session_state['active_incident']=(backend,chosen)
                st.info('Incident loaded. Select the Agent workflow tab.')
        else:
            st.info('Run an investigation to create the first incident.')
        st.subheader('Prior incident memory')
        st.dataframe(pd.DataFrame(store.rows('memory')).drop(columns=['_id']),hide_index=True,use_container_width=True)
        st.caption('Memory uses explicit drug/cause matching. These are seeded operational summaries, not generated reasoning or vector search results.')
    with atlas:
        st.subheader('The operational data behind the workflow')
        st.caption(f'{backend} · {DATABASE_NAME} · Dedicated demo namespace')
        collection=st.selectbox('Collection',['inventory','facilities','drugs','shipments','recalls','memory','incidents'])
        records=store.rows(collection)
        st.write(f'**{len(records)} documents**')
        if records:
            st.json(records[:12],expanded=False)
        with st.expander('Stockout risk aggregation'):
            st.code('''[
  {"$set": {"available": {"$subtract": [
    {"$subtract": ["$on_hand", "$reserved"]}, "$quarantined"]}}},
  {"$set": {"days_supply": {"$divide": ["$available", "$daily_demand"]}}},
  {"$sort": {"days_supply": 1}}
]''',language='json')
        st.write('**Atlas responsibilities:** document storage, risk aggregation, geospatial donor lookup, historical context, and atomic transfer reservation with incident updates.')
        st.caption('Indexes are initialized by the seed button. No indexes are recreated on ordinary reruns. No live FDA, ERP, routing, OpenAI, or Agent Engine integration is included.')
    st.markdown('<div class="footer">PHARMA SUPPLY COMMAND · Synthetic data · On-demand monitoring · Human-approved reservations</div>',unsafe_allow_html=True)


if __name__=='__main__':
    try:
        main()
    except ValueError as exc:
        st.warning(str(exc))
    except Exception:
        st.error('The operation could not complete. For Atlas, verify connectivity, permissions, seeded data, and transaction support. No successful reservation is reported unless it commits.')
