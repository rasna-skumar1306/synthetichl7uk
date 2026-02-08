import os
import random
import datetime
from faker import Faker

fake = Faker('en_GB')
OUTPUT_DIR = "data/hl7_inbound"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def generate_nhs_number():
    """Generate a valid 10 digit NHS number using Modulus 11."""
    while True:
        digits = [random.randint(0, 9) for _ in range(9)]
        total = sum(digits[i] * (10 - i) for i in range(9))
        remainder = total % 11
        checksum = 11 - remainder

        if checksum == 11: checksum = 0
        if checksum == 10: continue

        digits.append(checksum)
        return "".join(map(str, digits))
    
def generate_msh(msg_type):
    """Generates a HL7 MSH Segment - Message Header."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    msg_control_id = str(random.randint(100000, 999999))

    # MSH|^~\&|SendingApp|SendingFac|ReceivingApp|ReceivingFac|DateTime||MsgType|ControlID|ProcessingID|Version
    return f"MSH|^~\\&|PAS_LEGACY|NORTH_TRUST|FHIR_RECEIVER|NHS_DATA_LAKE|{timestamp}||{msg_type}|{msg_control_id}|P|2.3", msg_control_id, timestamp


def generate_pid():
    """Generates a PID Segment - Patient Identity"""
    nhs_no = generate_nhs_number()
    gender = random.choice(["M", "F", "O"])
    dob = fake.date_of_birth(minimum_age=18, maximum_age=90).strftime("%Y%m%d")

    if gender == "M":
        first = fake.first_name_male()
        salutation = "MR"
    elif gender == "F":
        first = fake.first_name_female()
        salutation = "MS"
    else:
        first = fake.first_name_nonbinary()
        salutation = "MX" 

    last = fake.last_name().upper()
    phone = fake.phone_number()

    # PID|SetID||NHS_Number^^^NHS||Family^Given^Middle^Suffix^Prefix||DoB|Gender|||Address||Phone
    pid_segment = f"PID|1||{nhs_no}^^^NHS||{last}^{first}^^^^{salutation}||{dob}|{gender}|||{fake.postcode()}||{phone}"
    return pid_segment, last

def generate_pv1():
    """Generates PV1 (Patient Visit) - Required for ADT messages."""
    # PV1|SetID|PatientClass|AssignedLocation|...|AttendingDoctor
    # Class: I (Inpatient), E (Emergency), O (Outpatient)
    pat_class = random.choice(['I', 'E', 'O'])
    
    # Location: Ward^Room^Bed
    ward = random.choice(['CARDIO', 'A&E', 'ICU', 'GEN_MED'])
    room = random.randint(1, 20)
    bed = random.randint(1, 4)
    location = f"{ward}^{room}^{bed}"
    
    # Doctor: Code^Name
    doc_id = random.randint(100, 999)
    doc_name = fake.last_name().upper()
    doctor = f"{doc_id}^{doc_name}^DR"
    
    # PV1|SetID|PatientClass|AssignedLocation|...|AttendingDoctor
    return f"PV1|1|{pat_class}|{location}||||{doctor}"

def generate_vitals_segments(timestamp):
    """Generates OBR and OBX segments (Randomly HR or BP)."""
    obr_id = str(random.randint(1000, 9999))
    segments = []
    
    # Decide: Heart Rate (50%) or Blood Pressure (50%)
    if random.random() < 0.5:
        # --- SCENARIO A: HEART RATE ---
        # OBR|SetID|OrderID|FillID|UniversalServiceID|||Timestamp
        obr = f"OBR|1|ORD{obr_id}|FILL{obr_id}|8867-4^HEART RATE^LN|||{timestamp}"
        segments.append(obr)
        
        hr = random.randint(60, 100)
        # OBX|SetID|ValueType|ObsID|SubID|Value|Units|RefRange|AbnormalFlags|||Status
        obx = f"OBX|1|NM|8867-4^HEART RATE^LN||{hr}|/min||||F"
        segments.append(obx)
        
    else:
        # --- SCENARIO B: BLOOD PRESSURE (Complex) ---
        # 1. OBR (The Panel)
        # OBR|SetID|OrderID|FillID|UniversalServiceID|||Timestamp
        obr = f"OBR|1|ORD{obr_id}|FILL{obr_id}|85354-9^BP PANEL^LN|||{timestamp}"
        segments.append(obr)
        
        # Logic: Systolic > Diastolic
        sys = random.randint(100, 160)
        dia = random.randint(60, sys - 20)
        
        # 2. OBX (Systolic)
        # OBX|SetID|ValueType|ObsID|SubID|Value|Units|RefRange|AbnormalFlags|||Status
        obx_sys = f"OBX|1|NM|8480-6^SYSTOLIC BP^LN||{sys}|mm[Hg]||||F"
        segments.append(obx_sys)
        
        # 3. OBX (Diastolic)
        # OBX|SetID|ValueType|ObsID|SubID|Value|Units|RefRange|AbnormalFlags|||Status
        obx_dia = f"OBX|2|NM|8462-4^DIASTOLIC BP^LN||{dia}|mm[Hg]||||F"
        segments.append(obx_dia)
        
    return "\n".join(segments)

def generate_allergy():
    """Generates an AL1 Segment (Patient Allergy)."""
    # AL1|SetID|AllergyType|Allergen|Severity|Reaction
    
    # 1. Pick a dangerous allergen
    allergens = [
        ("DA", "Z88.0^PENICILLIN^CD"),    # Drug
        ("FA", "Z91.01^PEANUTS^CD"),      # Food
        ("MA", "Y45.1^ASPIRIN^CD"),       # Meds
        ("EA", "Z91.04^LATEX^CD")         # Environment
    ]
    type_code, allergen = random.choice(allergens)
    
    # 2. Pick severity
    severity = random.choice(["SV", "MO", "MI"]) # Severe, Moderate, Mild
    
    # 3. Pick reaction
    reactions = ["Hives", "Anaphylaxis", "Wheezing", "Nausea"]
    reaction = random.choice(reactions)
    
    # AL1|1|DA|Z88.0^PENICILLIN^CD|SV|Anaphylaxis
    return f"AL1|1|{type_code}|{allergen}|{severity}|{reaction}"

def run_legacy_feed():
    print("🏭 Starting Legacy HL7 Feed...")

    try:
        batch_size = int(os.getenv("BATCH_SIZE", "10"))
    except ValueError:
        print("⚠️  Invalid BATCH_SIZE. Defaulting to 10.")
        batch_size = 10

    print(f"🏭 Starting Legacy HL7 Feed... Generating {batch_size} messages.")
    
    for i in range(1, batch_size + 1):
        # TRAFFIC LOGIC: 30% ADT (Admin), 70% ORU (Results)
        is_admin_msg = random.random() < 0.3
        
        pid, name = generate_pid()
        
        if is_admin_msg:
            # === SCENARIO 1: PATIENT ADMISSION (ADT) ===
            # ADT^A01 (Admit) or ADT^A08 (Update)
            trigger = random.choice(['A01', 'A08'])
            is_allergen = random.random() < 0.5
            msg_type = f"ADT^{trigger}"
            
            msh, msg_id, ts = generate_msh(msg_type)
            pv1 = generate_pv1()
            al1 = generate_allergy()
            
            hl7_message = f"{msh}\n{pid}\n{pv1}"
            hl7_message = hl7_message + f"\n{al1}" if is_allergen else hl7_message
            prefix = "ADT"
            
        else:
            # === SCENARIO 2: LAB RESULT (ORU) ===
            msg_type = "ORU^R01"
            
            msh, msg_id, ts = generate_msh(msg_type)
            # ORU NEEDS OBR/OBX (No PV1 usually required for simple results)
            vitals = generate_vitals_segments(ts)
            
            hl7_message = f"{msh}\n{pid}\n{vitals}"
            prefix = "ORU"
        
        # Save to file
        filename = f"{OUTPUT_DIR}/{prefix}_{name}_{msg_id}.hl7"
        with open(filename, "w") as f:
            f.write(hl7_message)
            
        print(f"📠 Transmitted: {msg_type} -> {filename}")

if __name__ == "__main__":
    run_legacy_feed()