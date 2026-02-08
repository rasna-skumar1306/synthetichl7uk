import os
import re
import glob
import datetime
from fhir.resources.patient import Patient
from fhir.resources.contactpoint import ContactPoint
from fhir.resources.observation import Observation
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.bundle import Bundle, BundleEntry
from fhir.resources.humanname import HumanName
from fhir.resources.identifier import Identifier
from fhir.resources.coding import Coding
from fhir.resources.quantity import Quantity
from fhir.resources.codeableconcept import CodeableConcept
from fhir.resources.R4B.allergyintolerance import AllergyIntolerance

# Configuration
INPUT_DIR = "data/hl7_inbound"
OUTPUT_DIR = "data/raw"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_hl7_date(hl7_date):
    """Converts HL7 YYYYMMDD to FHIR YYYY-MM-DD."""
    if not hl7_date: return None
    try:
        return datetime.datetime.strptime(hl7_date, "%Y%m%d").date().isoformat()
    except ValueError:
        return None
    
def parse_hl7_datetime(hl7_ts):
    """Converts HL7 YYYYMMDDHHMMSS to ISO 8601 (UTC)."""
    if not hl7_ts: return datetime.datetime.now().isoformat()
    try:
        # Simple parser (assuming local time for now, appending Z for UTC)
        dt = datetime.datetime.strptime(hl7_ts[:14], "%Y%m%d%H%M%S")
        return dt.isoformat() + "+00:00"
    except ValueError:
        return datetime.datetime.now().isoformat()
    
def clean_phone(phone):
    """Normalizes phone numbers (removes brackets, dashes, extensions)."""
    if not phone: return None

    base = phone.split('x')[0]

    clean = re.sub(r'[^0-9+]', '', base)
    
    return clean
    
def map_patient(segments):
    """Extracts PID segment and returns FHIR Patient."""
    # PID Segment Format:
    # PID|SetID||NHS_Number^^^NHS||Family^Given^Middle^Suffix^Prefix||DoB|Gender|||Address||Phone
    
    pid = next((s for s in segments if s.startswith("PID")), None)
    if not pid: return None
    
    fields = pid.split('|')
    
    # PID-3: NHS Number
    # PID-5: Name (Family^Given^Middle^Suffix^Prefix)
    # PID-7: DOB
    # PID-8: Gender
    # PID-11: Address
    # PID-13: Phone
    
    # Extract NHS Number
    nhs_raw = fields[3].split('^')[0]
    
    # Extract Name
    name_parts = fields[5].split('^')
    family = name_parts[0]
    given = name_parts[1] if len(name_parts) > 1 else ""
    prefix = name_parts[4] if len(name_parts) > 4 else ""

    # Build FHIR Resource
    p = Patient.model_construct()
    p.id = nhs_raw # Using NHS number as logical ID for this demo
    
    # Identifier
    ident = Identifier.model_construct()
    ident.system = "https://fhir.nhs.uk/nhs-number"
    ident.value = nhs_raw
    p.identifier = [ident]
    
    # Name
    hname = HumanName.model_construct()
    hname.family = family
    hname.given = [given]
    if prefix: hname.prefix = [prefix]
    p.name = [hname]
    
    # Demographics
    p.birthDate = parse_hl7_date(fields[7])
    
    # Gender Map
    hl7_sex = fields[8]
    if hl7_sex == 'M': p.gender = "male"
    elif hl7_sex == 'F': p.gender = "female"
    else: p.gender = "other"

    # Phone
    if len(fields) > 13:
        hl7_phone = clean_phone(fields[13])
        if hl7_phone:
            p_phone = ContactPoint.model_construct()
            p_phone.system = "phone"
            p_phone.use = "home"
            p_phone.value = hl7_phone

            p.telecom = [p_phone]
    
    return p

def map_encounter(segments, patient_id, msg_type):
    """Extracts PV1 segment and returns FHIR Encounter (for ADT messages)."""
    # PV1 Segment Format:
    # PV1|SetID|PatientClass|AssignedLocation|...|AttendingDoctor

    pv1 = next((s for s in segments if s.startswith("PV1")), None)
    if not pv1: return None
    
    fields = pv1.split('|')

    if "A01" in msg_type:       # Admit
        status = "in-progress"
    elif "A03" in msg_type:     # Discharge
        status = "finished"
    elif "A08" in msg_type:     # Update Patient Info
        status = "in-progress"
    else:
        status = "unknown"
    
    # Location (PV1-3: Ward^Room^Bed)
    loc_raw = fields[3].replace('^', '-')

    encounter_data = {
        "status": status,
        "class": {
            "system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
            "code": fields[2],
            "display": "Inpatient" if fields[2] == 'I' else "Emergency"
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "type": [{
            "text": f"Location: {loc_raw}"
        }]
    }

    enc = Encounter(**encounter_data)
    
    return enc

def map_observations(segments, patient_id):
    """Extracts OBX segments and groups them into FHIR Observations."""
    # OBR Segment Format:
    # OBR|SetID|OrderID|FillID|UniversalServiceID|||Timestamp

    # OBX Segment Format:
    # OBX|SetID|ValueType|ObsID|SubID|Value|Units|RefRange|AbnormalFlags|||Status

    obs_list = []
    
    # Containers for grouping BP parts
    sys_val = None
    dia_val = None
    eff_time = None
    
    for seg in segments:
        if seg.startswith("OBR"):
            fields = seg.split('|')
            eff_time = parse_hl7_datetime(fields[7]) # Timestamp from Order
            
        if seg.startswith("OBX"):
            fields = seg.split('|')
            # OBX-3: Code (8867-4^HEART RATE^LN)
            # OBX-5: Value
            
            code_full = fields[3]
            loinc = code_full.split('^')[0]
            val = int(fields[5])
            
            # Logic: Heart Rate (Create immediately)
            if loinc == "8867-4":
                obs = Observation.model_construct()
                obs.status = "final"
                obs.subject = {"reference": f"Patient/{patient_id}"}
                obs.code = CodeableConcept.model_construct(coding=[Coding.model_construct(system="http://loinc.org", code="8867-4", display="Heart rate")])
                obs.valueQuantity = Quantity.model_construct(value=val, unit="beats/minute", code="/min")
                obs.effectiveDateTime = eff_time
                obs_list.append(obs)
                
            # Logic: BP Parts (Store for grouping)
            elif loinc == "8480-6": # Systolic
                sys_val = val
            elif loinc == "8462-4": # Diastolic
                dia_val = val
                
    # If we found both parts of a BP, create the Panel
    if sys_val and dia_val:
        bp = Observation.model_construct()
        bp.status = "final"
        bp.subject = {"reference": f"Patient/{patient_id}"}
        bp.effectiveDateTime = eff_time
        
        # Panel Code
        bp.code = CodeableConcept.model_construct(coding=[Coding.model_construct(system="http://loinc.org", code="85354-9", display="Blood pressure panel")])
        
        # Components
        comp_sys = {
            "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6", "display": "Systolic"}]},
            "valueQuantity": {"value": sys_val, "unit": "mmHg"}
        }
        comp_dia = {
            "code": {"coding": [{"system": "http://loinc.org", "code": "8462-4", "display": "Diastolic"}]},
            "valueQuantity": {"value": dia_val, "unit": "mmHg"}
        }
        bp.component = [comp_sys, comp_dia]
        obs_list.append(bp)
        
    return obs_list

def map_allergies(segments, patient_id):
    """Extracts AL1 segments and returns FHIR AllergyIntolerance resources."""
    # AL1 Segment Format:
    # AL1|SetID|AllergyType|Allergen|Severity|Reaction
    resources = []
    
    for seg in segments:
        if seg.startswith("AL1"):
            fields = seg.split('|')
            
            # HL7: AL1-3 (Allergen Code), AL1-4 (Severity), AL1-5 (Reaction)
            allergen_raw = fields[3].split('^') # Z88.0^PENICILLIN
            severity_hl7 = fields[4]
            reaction_txt = fields[5]
            
            # HL7 'SV' -> FHIR 'high'
            # HL7 'MO'/'MI' -> FHIR 'low'
            crit = "high" if severity_hl7 == "SV" else "low"
            
            ai = AllergyIntolerance(
                clinicalStatus={
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical", "code": "active"}]
                },
                verificationStatus={
                    "coding": [{"system": "http://terminology.hl7.org/CodeSystem/allergyintolerance-verification", "code": "confirmed"}]
                },
                type="allergy",
                category=["medication" if fields[2] == "DA" else "food"],
                criticality=crit,
                code={
                    "coding": [{
                        "system": "http://hl7.org/fhir/sid/icd-10",
                        "code": allergen_raw[0],
                        "display": allergen_raw[1]
                    }]
                },
                patient={"reference": f"Patient/{patient_id}"},
                reaction=[{
                    "manifestation": [
                        {
                            "coding": [{"system": "http://snomed.info/sct", "display": reaction_txt}],
                            "text": reaction_txt
                        }
                    ],
                    "severity": "severe" if severity_hl7 == "SV" else "moderate"
                }]
            )
            resources.append(ai)
            
    return resources

def run_transformer():
    print("🤖 Starting HL7 -> FHIR Transformer...")
    
    files = glob.glob(f"{INPUT_DIR}/*.hl7")
    if not files:
        print("⚠️ No HL7 files found. Did you run 'legacy_feed.py'?")
        return

    for file_path in files:
        with open(file_path, 'r') as f:
            content = f.read().strip()
        
        segments = content.split('\n')
        msh = segments[0].split('|')
        msg_type = msh[8] # e.g., ADT^A01 or ORU^R01
        
        # 1. Transform Patient (Always present)
        patient = map_patient(segments)
        if not patient: continue
        
        resources = [patient]
        
        # 2. Route based on Message Type
        if "ADT" in msg_type:
            # Create Encounter
            encounter = map_encounter(segments, patient.id, msg_type)
            if encounter: resources.append(encounter)

            allergy = map_allergies(segments, patient.id)
            if allergy: 
                resources.extend(allergy)
                print(f"🔄 Transformed ADT: {patient.name[0].family} (Admit & Allergy)")
            else:
                print(f"🔄 Transformed ADT: {patient.name[0].family} (Admit)")
            
        elif "ORU" in msg_type:
            # Create Observations
            obs_list = map_observations(segments, patient.id)
            resources.extend(obs_list)
            print(f"🔄 Transformed ORU: {patient.name[0].family} ({len(obs_list)} Vitals)")

        # 3. Bundle it up
        entries = [BundleEntry(resource=r) for r in resources]
        bundle = Bundle(type="transaction", entry=entries)
        
        # 4. Save to RAW (for Sentinel to scan)
        filename = os.path.basename(file_path).replace('.hl7', '.json')
        with open(f"{OUTPUT_DIR}/{filename}", "w") as f:
            f.write(bundle.json(indent=2))

if __name__ == "__main__":
    run_transformer()