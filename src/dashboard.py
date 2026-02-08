import streamlit as st
import pandas as pd
import glob
import json
import os
import subprocess
import time
import plotly.express as px

# --- Configuration ---
DATA_DIR = "data"
DIRS = {
    "hl7": os.path.join(DATA_DIR, "hl7_inbound"),
    "fhir": os.path.join(DATA_DIR, "raw"),
    "accepted": os.path.join(DATA_DIR, "accepted"),
    "rejected": os.path.join(DATA_DIR, "rejected")
}

# Ensure directories exist
for d in DIRS.values():
    os.makedirs(d, exist_ok=True)

# --- UI Layout ---
st.set_page_config(page_title="NHS Integration Engine", page_icon="🏥", layout="wide")

st.title("🏥 NHS Synthetic Data Engine")
st.markdown("### HL7 V2.3 ➡️ FHIR R4B Transformer & Validator")

# --- Sidebar: Controls ---
st.sidebar.header("⚙️ Simulation Controls")

batch_size = st.sidebar.slider("Batch Size (Messages)", min_value=1, max_value=100, value=10)
chaos_mode = st.sidebar.checkbox("🔥 Inject Chaos (Bad Data)", value=False)

if st.sidebar.button("🚀 Run Simulation", type="primary"):
    with st.spinner("🔄 Generating Legacy HL7 Data..."):
        # 1. Clean old data
        subprocess.run(["rm", "-rf", f"{DATA_DIR}/*"])
        for d in DIRS.values(): os.makedirs(d, exist_ok=True)
        
        # 2. Run Generator
        env = os.environ.copy()
        env["BATCH_SIZE"] = str(batch_size)
        # Pass a flag to legacy_feed if you implement chaos there later
        subprocess.run(["python", "src/legacy_feed.py"], env=env)
        
    with st.spinner("🤖 Transforming to FHIR..."):
        subprocess.run(["python", "src/forge.py"])

    if chaos_mode:
        with st.spinner("🔥 Injecting Chaos (Bad Data)..."):
            subprocess.run(["python", "src/chaos.py"])
        
    with st.spinner("🛡️ Validating with Sentinel..."):
        subprocess.run(["python", "src/sentinel.py"])
        
    st.success("✅ Pipeline Complete!")
    time.sleep(1) # Refresh UI
    st.rerun()

# --- Main Dashboard ---

# 1. Metrics Row
col1, col2, col3, col4 = st.columns(4)

# Count files
hl7_count = len(glob.glob(f"{DIRS['hl7']}/*.hl7"))
fhir_count = len(glob.glob(f"{DIRS['fhir']}/*.json"))
accepted_count = len(glob.glob(f"{DIRS['accepted']}/*.json"))
rejected_count = len(glob.glob(f"{DIRS['rejected']}/*.json"))

col1.metric("1. Inbound HL7", hl7_count, delta="Legacy")
col2.metric("2. Transformed FHIR", fhir_count, delta="R4B JSON")
col3.metric("3. Validated (Accepted)", accepted_count, delta="Clean", delta_color="normal")
col4.metric("4. Rejected (Errors)", rejected_count, delta="Issues", delta_color="inverse")

st.divider()

# 2. Data Visualisation Row
m_col1, m_col2 = st.columns([2, 1])

with m_col1:
    st.subheader("📊 Live Data Feed (Latest 5)")
    
    # Load latest JSON files
    files = sorted(glob.glob(f"{DIRS['fhir']}/*.json"), key=os.path.getmtime, reverse=True)[:5]
    data_list = []
    
    for f in files:
        with open(f) as json_file:
            d = json.load(json_file)
            # Extract key info for the table
            try:
                # Find Patient resource in Bundle
                patient = next(r['resource'] for r in d['entry'] if r['resource']['resourceType'] == 'Patient')
                name = f"{patient['name'][0]['family'].upper()}, {patient['name'][0]['given'][0]}"
                pid = next(i['value'] for i in patient['identifier'] if 'nhs-number' in i['system'])
                data_list.append({"Filename": os.path.basename(f), "Patient": name, "NHS No": pid, "Type": "Bundle"})
            except:
                data_list.append({"Filename": os.path.basename(f), "Patient": "Unknown", "NHS No": "N/A", "Type": "Error"})
    
    if data_list:
        st.dataframe(pd.DataFrame(data_list), width='content')
    else:
        st.info("No data generated yet. Click 'Run Simulation'.")

with m_col2:
    st.subheader("🛡️ Sentinel Quality Gate")
    
    if accepted_count + rejected_count > 0:
        # Donut Chart using Plotly
        df_chart = pd.DataFrame({
            "Status": ["Accepted", "Rejected"],
            "Count": [accepted_count, rejected_count]
        })
        fig = px.pie(df_chart, values='Count', names='Status', hole=0.4, 
                     color='Status', color_discrete_map={'Accepted':'#2ecc71', 'Rejected':'#e74c3c'})
        st.plotly_chart(fig, width='content')
    else:
        st.markdown("Waiting for validation results...")

# 3. Drill Down (Rejected Files)
if rejected_count > 0:
    st.divider()
    st.subheader("🚫 Rejection Analysis")
    
    # 1. Read the Log File
    log_path = os.path.join(DATA_DIR, "rejection_log.json")
    
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                error_data = json.load(f)
            
            df_errors = pd.DataFrame(error_data)

            c1, c2 = st.columns([3, 1])
            with c1:
                st.markdown("### 📋 Audit Trail")
            with c2:
                show_all = st.checkbox("Show Resolved Issues", value=True)

            # Filter Logic
            if not show_all:
                df_errors = df_errors[df_errors["Status"] == "🔴 Active"]

            # Display Table with your config
            st.dataframe(
                df_errors, 
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Status": st.column_config.TextColumn("Status", width="small"),
                    "Filename": st.column_config.TextColumn("File Name", width="medium"),
                    "Error Type": st.column_config.TextColumn("Clinical/Admin Error", width="large"),
                    "Timestamp": st.column_config.TextColumn("Last Updated", width="medium"),
                }
            )
            
            # Download Button for the Report
            st.download_button(
                label="📥 Download Error Log (JSON)",
                data=json.dumps(error_data, indent=2),
                file_name="nhs_error_log.json",
                mime="application/json"
            )

        except json.JSONDecodeError:
            st.warning("Error log is empty or corrupt.")
    else:
        st.warning("Log file not found. Run simulation to generate.")

    # 2. Inspect Specific File (Visual JSON Diff)
    st.write("### 🔍 Inspect Raw JSON")
    rejected_files = glob.glob(f"{DIRS['rejected']}/*.json")
    selected_file = st.selectbox("Select a file to view content:", [os.path.basename(f) for f in rejected_files])
    
    if selected_file:
        with open(os.path.join(DIRS['rejected'], selected_file)) as f:
            st.json(json.load(f))