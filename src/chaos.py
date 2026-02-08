import json
import os
import random
import glob
from copy import deepcopy
from datetime import datetime, timedelta

INPUT_DIR = "data/raw"
OUTPUT_DIR = "data/dirty"
ERROR_RATE = 0.4

# --- New Clinical Chaos Functions ---

def error_clinical_impossible_value(resource):
    """Scenario: Device malfunction (Heart Rate 999 or BP 999/999)."""
    
    # 1. Attack Top-Level Values (Heart Rate)
    if 'valueQuantity' in resource:
        resource['valueQuantity']['value'] = 999
        return resource, "CRITICAL_VALUE_IMPOSSIBLE"
        
    # 2. Attack Nested Components (Blood Pressure) <--- NEW
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
                if 'valueQuantity' in resource:
                    # Change Heart Rate units from 'beats/minute' to 'kg' (Nonsense)
                    resource['valueQuantity']['unit'] = "kg"
                    resource['valueQuantity']['code'] = "kg"
                    return resource, "UNIT_MISMATCH"

    return resource, "SKIPPED"

# --- The Master List ---
CHAOS_FUNCTIONS = [
    error_clinical_impossible_value,
    error_clinical_future_timestamp,
    error_clinical_unit_mismatch
]

def run_chaos():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    files = glob.glob(f"{INPUT_DIR}/*.json")
    stats = {"dirty": 0}

    print(f"🔥 Starting Clinical Chaos Engine...")

    for file_path in files:
        with open(file_path, 'r') as f:
            data = json.load(f)

        file_is_corrupted = False
        error_report = []
        
        if data.get('resourceType') == 'Bundle':
            for entry in data.get('entry', []):
                resource = entry.get('resource', {})

                if resource.get('resourceType') == 'Observation' and random.random() < ERROR_RATE:

                    chaos_func = random.choice(CHAOS_FUNCTIONS)
                    dirty_data, error_code = chaos_func(deepcopy(resource))
                    
                    if error_code != "SKIPPED":
                        filename = os.path.basename(file_path)
                        entry['resource'] = dirty_data
                        file_is_corrupted = True
                        error_report.append(error_code)
                    
                    if file_is_corrupted:
                        filename = os.path.basename(file_path)

                        combined_code = "_".join(set(error_report))
                        new_filename = f"CORRUPT_{combined_code}_{filename}"

                        with open(os.path.join(OUTPUT_DIR, new_filename), "w") as f:
                            json.dump(data, f, indent=2)
                        
                        print(f"❌ Injured Bundle: {combined_code}")
                        stats["dirty"] += 1

    print(f"💀 Total Clinical Errors Injected: {stats['dirty']}")

if __name__ == "__main__":
    run_chaos()