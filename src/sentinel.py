import json
import os
import glob
import shutil
from datetime import datetime, timezone

# Configuration
INPUT_DIR = "data/raw"
ACCEPTED_DIR = "data/accepted"
REJECTED_DIR = "data/rejected"

REPORT_DIR = "reports/"
os.makedirs(REPORT_DIR, exist_ok=True)

# --- Validation Logic ---

def validate_nhs_number(nhs_no):
    """Re-calculates the checksum to catch typos/fakes."""
    if not nhs_no or len(nhs_no) != 10 or not nhs_no.isdigit():
        return False
    
    digits = [int(d) for d in nhs_no]
    checksum_digit = digits.pop() # The last one
    
    total = sum(digits[i] * (10 - i) for i in range(9))
    remainder = total % 11
    calc_checksum = 11 - remainder
    if calc_checksum == 11: calc_checksum = 0
    if calc_checksum == 10: return False # Invalid number
    
    return calc_checksum == checksum_digit

def validate_patient(data):
    """Checks Patient resources."""
    errors = []
    
    # Rule 1: NHS Number Integrity
    try:
        nhs_id = next(i for i in data.get('identifier', []) if "nhs-number" in i.get('system', ''))
        if not validate_nhs_number(nhs_id.get('value')):
            errors.append("Invalid NHS Number Checksum")
    except StopIteration:
        errors.append("Missing NHS Number")

    # Rule 2: Date Format (Must be YYYY-MM-DD)
    dob = data.get('birthDate')
    if dob:
        try:
            datetime.strptime(dob, "%Y-%m-%d")
        except ValueError:
            errors.append(f"Invalid Date Format: {dob}")
    
    # Rule 3: Mandatory Family Name (Admin Check)
    try:
        # Safely try to get the first name entry
        names = data.get('name', [])
        if not names:
            errors.append("Missing Name Record")
        else:
            # Check the official/first name record
            family_name = names[0].get('family', '')
            if not family_name:
                errors.append("Missing Family Name (Surname)")
                
    except (IndexError, AttributeError):
        errors.append("Corrupt Name Structure")
            
    return errors

def validate_observation(data):
    """Checks Clinical Observations."""
    errors = []
    
    # Rule 1: Future Dates
    eff_date = data.get('effectiveDateTime')
    if eff_date:
        try:
            # Parse the string to a datetime object
            dt = datetime.fromisoformat(eff_date.replace('Z', '+00:00'))
            
            # If the incoming date has no timezone (Naive), we force it to have one (UTC)
            # so we can compare it safely without crashing.
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            # Now both sides of the comparison are "Aware"
            if dt > datetime.now(timezone.utc):
                errors.append(f"Timestamp is in the future: {eff_date}")
                
        except ValueError:
            errors.append("Unparseable Timestamp")

    # Rule 2: Biological Plausibility (Heart Rate)
    # Check if it's a Heart Rate (LOINC 8867-4)
    coding = data.get('code', {}).get('coding', [])
    if any(c.get('code') == '8867-4' for c in coding):
        val = data.get('valueQuantity', {}).get('value')
        unit = data.get('valueQuantity', {}).get('unit')
        
        # Check Unit
        if unit != "beats/minute":
            errors.append(f"Invalid Unit for Heart Rate: {unit}")
            
        # Check Value (Dead or Exploding Heart)
        if val and (val < 0 or val > 300):
            errors.append(f"Clinically Impossible Heart Rate: {val}")
    
    # Rule 3:
    # Check if it's a Blood pressure - Systolic (LOINC 8480-6)
    # Rule 3: Blood Pressure Panel Check (LOINC 85354-9)
    if any(c.get('code') == '85354-9' for c in coding):
        components = data.get('component', [])

        sys_val = None
        dia_val = None
        
        for component in components:
            comp_codings = component.get('code', {}).get('coding', [])
            val = component.get('valueQuantity', {}).get('value')
            
            if val is None: continue

            # Check Systolic (8480-6)
            if any(c.get('code') == '8480-6' for c in comp_codings):
                sys_val = val
                if sys_val is not None and (sys_val < 50 or sys_val > 300):
                    errors.append(f"Clinically Impossible Systolic: {sys_val}")

            # Check Diastolic (8462-4)
            if any(c.get('code') == '8462-4' for c in comp_codings):
                dia_val = val
                if dia_val is not None and (dia_val < 40 or dia_val > 200):
                    errors.append(f"Clinically Impossible Diastolic: {dia_val}")

        if sys_val is not None and dia_val is not None:    
            if dia_val >= sys_val:
                errors.append(f"Pulse Pressure Error: Diastolic ({dia_val}) >= Systolic ({sys_val})")


    return errors

def validate_allergy(data):
    """Checks AllergyIntolerance resources."""
    errors = []
    
    # Rule 1: Must have a Patient link
    if 'patient' not in data or 'reference' not in data['patient']:
        errors.append("Orphaned Allergy (No Patient Link)")

    # Rule 2: Must have a Code (What are they allergic to?)
    if not data.get('code', {}).get('coding'):
        errors.append("Missing Allergen Code")
        
    # Rule 3: Criticality Safety Check
    # If it's High Risk, we don't reject it, but we log it (just for demo visibility)
    crit = data.get('criticality')
    if crit == 'high':
        # formatting trick to print to console in yellow/orange
        print(f"   ⚠️  SAFETY ALERT: High Criticality Allergy detected!")

    return errors

# ---HTML Report generator----

def generate_html_report(stats, errors_list):
    """Generates a visual HTML report for stakeholders."""
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: sans-serif; padding: 20px; background: #f4f4f9; }}
            h1 {{ color: #2c3e50; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }}
            .stats {{ display: flex; gap: 20px; }}
            .stat-box {{ flex: 1; text-align: center; padding: 20px; background: #ecf0f1; border-radius: 8px; }}
            .valid {{ background: #d4edda; color: #155724; }}
            .invalid {{ background: #f8d7da; color: #721c24; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th, td {{ text-align: left; padding: 12px; border-bottom: 1px solid #ddd; }}
            th {{ background-color: #2c3e50; color: white; }}
            tr:hover {{ background-color: #f1f1f1; }}
        </style>
    </head>
    <body>
        <h1>🛡️ NHS Data Quality Audit Report</h1>
        <p>Generated: {timestamp}</p>
        
        <div class="card stats">
            <div class="stat-box valid">
                <h2>{stats['valid']}</h2>
                <p>Accepted Records</p>
            </div>
            <div class="stat-box invalid">
                <h2>{stats['rejected']}</h2>
                <p>Rejected Records</p>
            </div>
            <div class="stat-box">
                <h2>{
                    0 if (stats['valid'] + stats['rejected']) == 0 
                    else int((stats['valid'] / (stats['valid'] + stats['rejected'])) * 100)
                }%</h2>
                <p>Quality Score</p>
            </div>
        </div>

        <div class="card">
            <h2>🚫 Rejection Log</h2>
            <table>
                <thead>
                    <tr>
                        <th>Filename</th>
                        <th>Reason</th>
                    </tr>
                </thead>
                <tbody>
    """
    
    for filename, reason in errors_list:
        html += f"<tr><td>{filename}</td><td>{reason}</td></tr>"
    
    html += """
                </tbody>
            </table>
        </div>
    </body>
    </html>
    """
    
    report_timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    report_file_name = f"{REPORT_DIR}/audit_report_{report_timestamp}.html"

    with open(report_file_name, "w", encoding="utf-8") as f:
        f.write(html)
    
    print("\n📄 Report generated: audit_report.html")

# --- The Engine ---

def run_sentinel():
    # Setup folders
    for d in [ACCEPTED_DIR, REJECTED_DIR]:
        os.makedirs(d, exist_ok=True)

    files = glob.glob(f"{INPUT_DIR}/*.json")
    print(f"🛡️  Sentinel Active. Scanning {len(files)} files...")
    
    stats = {"valid": 0, "rejected": 0}
    rejection_log = []

    for file_path in files:
        filename = os.path.basename(file_path)
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"❌ REJECTED {filename}: Corrupt JSON")
                continue

        # Route to specific validator
        # 1. Create a master list for the WHOLE file
        file_errors = [] 

        # 2. Check Patient
        if data.get('resourceType') == 'Patient':
            file_errors.extend(validate_patient(data))

        # 3. Check Bundle
        elif data.get('resourceType') == 'Bundle':
            for entry in data.get('entry', []):
                resource = entry.get('resource', {})
                
                if resource.get('resourceType') == 'Observation':
                    entry_errors = validate_observation(resource)

                elif resource.get('resourceType') == 'AllergyIntolerance':
                    entry_errors = validate_allergy(resource)

                else:
                    entry_errors = []
                
                # Add any found errors to the master list
                if entry_errors:
                    file_errors.extend(entry_errors)
        
        # Decision Time
        if not file_errors:
            shutil.copy(file_path, os.path.join(ACCEPTED_DIR, filename))
            stats["valid"] += 1
        else:
            shutil.copy(file_path, os.path.join(REJECTED_DIR, filename))
            stats["rejected"] += 1
            error_msg = ", ".join(file_errors)
            rejection_log.append((filename, error_msg)) 
            print(f"🚫 REJECTED {filename}: {error_msg}")

    # --- DYNAMIC LOGGING LOGIC ---
    log_path = "data/rejection_log.json"
    
    # 1. Load History (Dictionary: Filename -> Data)
    history_log = {}
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                # Map back to dict for easy lookup
                history_log = {entry['Filename']: entry for entry in json.load(f)}
        except json.JSONDecodeError:
            history_log = {}

    # 2. Process CURRENT Failures (Mark as Active)
    current_failures = set()
    for fname, reason in rejection_log:
        current_failures.add(fname)
        
        # Add or Update the record
        history_log[fname] = {
            "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "Filename": fname,
            "Error Type": reason,
            "Status": "🔴 Active"
        }

    # 3. Process RESOLVED Issues
    # If it's in history but NOT in current failures, it means it's fixed!
    for fname in history_log:
        if fname not in current_failures:
            # Only update if it was previously Active
            if history_log[fname]["Status"] == "🔴 Active":
                history_log[fname]["Status"] = "✅ Resolved"
                history_log[fname]["Timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Update time to show WHEN it was fixed
                print(f"✅ Issue Resolved: {fname}")

    # 4. Save Audit Trail
    # Convert dict to list and sort: Active first, then by time
    final_list = list(history_log.values())
    final_list.sort(key=lambda x: (x['Status'], x['Timestamp']), reverse=True)

    with open(log_path, "w") as f:
        json.dump(final_list, f, indent=2)

    print(f"💾 Audit Trail updated. Total Records: {len(final_list)}")

    generate_html_report(stats, rejection_log)
    print("\n--- 📊 Sentinel Report ---")
    print(f"Total Scanned: {len(files)}")

    if len(files) > 0:
        print(f"Accepted:      {stats['valid']}")
        print(f"Rejected:      {stats['rejected']}")
        print(f"Data Hygiene:  {int((stats['valid']/len(files))*100)}%")
    else:
        print("⚠️  No files found to scan.")

if __name__ == "__main__":
    run_sentinel()