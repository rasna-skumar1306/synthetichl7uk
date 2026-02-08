import json
import os
import random
import glob
from copy import deepcopy
from datetime import datetime, timedelta

# --- Configuration ---

INPUT_DIR = os.getenv("CHAOS_TARGET_DIR", "data/raw")
ERROR_RATE = 0.4

# 1. ADMINISTRATIVE CHAOS (Targets: Patient)

def error_admin_corrupt_nhs_number(resource):
    """Scenario: Typo in NHS Number (fails Mod11 check)."""
    if resource.get('resourceType') == 'Patient':
        for identifier in resource.get('identifier', []):
            if 'nhs-number' in identifier.get('system', ''):
                # Change the last digit to break the checksum
                original = identifier['value']
                # specific breakdown: 9999999999 is definitely invalid
                identifier['value'] = "9999999999" 
                return resource, "INVALID_NHS_NUMBER"
    return resource, "SKIPPED"

def error_admin_missing_name(resource):
    """Scenario: Clerk forgot to enter the surname."""
    if resource.get('resourceType') == 'Patient':
        if 'name' in resource and len(resource['name']) > 0:
            # Remove family name
            resource['name'][0]['family'] = "" 
            return resource, "MISSING_SURNAME"
    return resource, "SKIPPED"

# 2. CLINICAL CHAOS (Targets: Observation)

def error_clinical_impossible_value(resource):
    """Scenario: Device malfunction (Heart Rate 999 or BP 999/999)."""
    
    # 1. Attack Top-Level Values (Heart Rate)
    if 'valueQuantity' in resource:
        resource['valueQuantity']['value'] = 999
        return resource, "CRITICAL_VALUE_IMPOSSIBLE"
        
    # 2. Attack Nested Components (Blood Pressure)
    if 'component' in resource:
        for comp in resource['component']:
            if 'valueQuantity' in comp:
                comp['valueQuantity']['value'] = 999
                # We return immediately after breaking one thing
                return resource, "CRITICAL_VALUE_IMPOSSIBLE"

    return resource, "SKIPPED"

def error_clinical_future_timestamp(resource):
    """Scenario: Server clock sync error (Observation from tomorrow)."""
    if 'effectiveDateTime' in resource:
        # Set date to next year
        future_date = (datetime.now() + timedelta(days=365)).isoformat()
        resource['effectiveDateTime'] = future_date
        return resource, "INVALID_FUTURE_DATE"
    return resource, "SKIPPED"

def error_clinical_unit_mismatch(resource):
    """Scenario: The 'Mars Climate Orbiter' bug. Value is correct, Unit is wrong."""
    if resource.get('resourceType') == 'Observation':

        if 'valueQuantity' in resource:
            # Change Heart Rate units from 'beats/minute' to 'kg' (Nonsense)
            resource['valueQuantity']['unit'] = "kg"
            resource['valueQuantity']['code'] = "kg"
            return resource, "UNIT_MISMATCH"

        if 'component' in resource:
            for comp in resource['component']:
                if 'valueQuantity' in comp:
                    # Change Heart Rate units from 'beats/minute' to 'kg' (Nonsense)
                    comp['valueQuantity']['unit'] = "kg"
                    comp['valueQuantity']['code'] = "kg"
                    return resource, "UNIT_MISMATCH"

    return resource, "SKIPPED"

# --- The Master List ---
CHAOS_MENUS = {
    "Patient": [error_admin_corrupt_nhs_number, error_admin_missing_name],
    "Observation": [error_clinical_impossible_value, error_clinical_future_timestamp, error_clinical_unit_mismatch]
}

def run_chaos():
    files = glob.glob(f"{INPUT_DIR}/*.json")
    stats = {"scanned": len(files), "infected": 0}

    print(f"🔥 CHAOS ENGINE ONLINE. Targeting: {INPUT_DIR}")
    print(f"🎲 Infection Rate: {ERROR_RATE * 100}%")

    for file_path in files:
        with open(file_path, 'r') as f:
            data = json.load(f)

        file_is_corrupted = False
        error_report = []
        
        if data.get('resourceType') == 'Bundle':
            for entry in data.get('entry', []):
                resource = entry.get('resource', {})
                r_type = resource.get('resourceType')
                if r_type in CHAOS_MENUS:
                    if random.random() < ERROR_RATE:
                        chaos_func = random.choice(CHAOS_MENUS[r_type])
                        dirty_data, error_code = chaos_func(deepcopy(resource))
                        
                        if error_code != "SKIPPED":
                            entry['resource'] = dirty_data
                            file_is_corrupted = True
                            error_report.append(error_code)
                    
            if file_is_corrupted:
                with open(file_path, "w") as f:
                    json.dump(data, f, indent=2)
                
                stats["infected"] += 1
                unique_errors = list(set(error_report))
                print(f"   💀 Infected {os.path.basename(file_path)} -> {unique_errors}")

    print(f"----------------------------------------")
    print(f"📉 Chaos Report: Infected {stats['infected']} out of {stats['scanned']} files.")

if __name__ == "__main__":
    run_chaos()