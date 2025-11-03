import streamlit as st
import pandas as pd
import io

# ===== original logic from your pacp_coder_2.0.py (slightly adapted for uploads) =====

# List of unwanted PACP codes to exclude
unwanted_codes = {
    'AMH', 'MWL', 'TF', 'TS', 'TSA', 'TFA', 'MGO', 'MMC', 'MSC', 'ACB',
    'MWM','AEP','TFC','TB','ACOM','TFD','TBA','TBD','ATC','TBC','AOC'
}

def process_codes(df: pd.DataFrame):
    # remove unwanted + null codes
    df_filtered = df[~df['PACP_Code'].isin(unwanted_codes) & df['PACP_Code'].notna()]
    if df_filtered.empty:
        return []

    so_lookup, fo_lookup, used_indices, continuous_counts = {}, {}, set(), {}

    # map Sxx / Fxx
    for idx, row in df_filtered.iterrows():
        code = str(row['PACP_Code']).strip()
        cont = str(row.get('Continuous', '')).strip().upper()
        if cont.startswith('S'):
            so_lookup[(code, cont[1:])] = idx
        elif cont.startswith('F'):
            fo_lookup[(code, cont[1:])] = idx

    # pair Sxx/Fxx of same code → count as continuous
    for (code, num), so_idx in so_lookup.items():
        if (code, num) in fo_lookup:
            fo_idx = fo_lookup[(code, num)]
            continuous_counts[code] = continuous_counts.get(code, 0) + 1
            used_indices.update([so_idx, fo_idx])

    final, seen_normal, seen_cont = [], set(), set()

    for idx, row in df_filtered.iterrows():
        code = str(row['PACP_Code']).strip()
        if idx in used_indices:
            # part of S/F matched continuous
            if code not in seen_cont:
                count = continuous_counts.get(code, 1)
                final.append(f"{code} ©" if count == 1 else f"{code} ©X{count}")
                seen_cont.add(code)
        else:
            # single occurrence codes
            if code not in seen_normal:
                count = (df_filtered['PACP_Code'] == code).sum()
                final.append(f"{code} X{count}" if count > 1 else code)
                seen_normal.add(code)

    return final

def process_files(conditions_xl, inspections_xl, ratings_xl) -> pd.DataFrame:
    # read from uploaded file-like objects
    df_conditions = pd.read_excel(conditions_xl)
    df_inspections = pd.read_excel(inspections_xl)
    df_ratings = pd.read_excel(ratings_xl)

    # merge inspections info (including date/street/city/etc.)
    df_merged = df_conditions.merge(
        df_inspections[['InspectionID', 'Pipe_Segment_Reference',
                        'Inspection_Date', 'Street', 'City',
                        'Length_Surveyed', 'Height', 'Material',
                        'Upstream_MH', 'Downstream_MH']],
        on='InspectionID', how='left'
    )

    # merge ratings
    df_merged = df_merged.merge(
        df_ratings[['InspectionID', 'STQuickRating', 'OMQuickRating', 'OverallPipeRatingsIndex']],
        on='InspectionID', how='left'
    )

    # group by (InspectionID, PSR)
    grouped_rows = []
    for (insp_id, seg_ref), group in df_merged.groupby(['InspectionID', 'Pipe_Segment_Reference']):
        codes = process_codes(group)

        # format scores exactly like your script
        stquick = group['STQuickRating'].iloc[0]
        omquick = group['OMQuickRating'].iloc[0]
        overall = group['OverallPipeRatingsIndex'].iloc[0]

        str_score = str(int(stquick)).zfill(4) if pd.notna(stquick) else "0000"
        om_score  = str(int(omquick)).zfill(4) if pd.notna(omquick) else "0000"

        row = {
            'InspectionID': insp_id,
            'Pipe_Segment_Reference': seg_ref,
            'Inspection_Date': group['Inspection_Date'].iloc[0],
            'Street': group['Street'].iloc[0],
            'City': group['City'].iloc[0],
            'Length_Surveyed': round(float(group['Length_Surveyed'].iloc[0]), 2)
                               if pd.notna(group['Length_Surveyed'].iloc[0]) else None,
            'Diameter': group['Height'].iloc[0],
            'Material': group['Material'].iloc[0],
            'Upstream_MH': group['Upstream_MH'].iloc[0],
            'Downstream_MH': group['Downstream_MH'].iloc[0],
            'STR Score': str_score,
            'OM Scores': om_score,
            'Overall Scores': round(float(overall), 2) if pd.notna(overall) else None
        }

        # add PACP_Code1..n
        for i, code in enumerate(codes, start=1):
            row[f'PACP_Code{i}'] = code

        grouped_rows.append(row)

    return pd.DataFrame(grouped_rows)

# ===== Streamlit UI =====

st.title("PACP Coder 2.0 — Streamlit Version (S/F-aware)")
st.write(
    "Upload your three PACP Excel exports (Conditions, Inspections, Ratings). "
    "This app will run the **same logic** as your pacp_coder_2.0 script, including:\n"
    "- excluding your unwanted codes,\n"
    "- pairing S/F continuous codes and marking them with © and counts,\n"
    "- merging inspection meta (date, street, city, etc.),\n"
    "- formatting STR/OM as 4-digit scores."
)

col1, col2, col3 = st.columns(3)
with col1:
    conditions_file = st.file_uploader("PACP_Conditions Excel", type=["xlsx", "xls"])
with col2:
    inspections_file = st.file_uploader("PACP_Inspections Excel", type=["xlsx", "xls"])
with col3:
    ratings_file = st.file_uploader("PACP_Ratings Excel", type=["xlsx", "xls"])

run_btn = st.button("Process")

if run_btn:
    if not (conditions_file and inspections_file and ratings_file):
        st.error("Please upload all three files.")
        st.stop()

    try:
        df_out = process_files(conditions_file, inspections_file, ratings_file)
    except Exception as e:
        st.exception(e)
        st.stop()

    st.success(f"Processed {len(df_out)} inspection rows.")
    st.dataframe(df_out, use_container_width=True)

    # download
    towrite = io.BytesIO()
    df_out.to_excel(towrite, index=False, sheet_name="PACP_Output")
    towrite.seek(0)

    st.download_button(
        label="Download PACP Output Excel",
        data=towrite,
        file_name="PACP_Output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
else:
    st.info("Upload the three files above and click **Process**.")
