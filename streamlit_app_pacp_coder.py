import streamlit as st
import pandas as pd
import io
import re

# ===== defaults from your script =====
DEFAULT_UNWANTED = {
    'AMH', 'MWL', 'TF', 'TS', 'TSA', 'TFA', 'MGO', 'MMC', 'MSC', 'ACB',
    'MWM', 'AEP', 'TFC', 'TB', 'ACOM', 'TFD', 'TBA', 'TBD', 'ATC', 'TBC', 'AOC'
}

# ---------- helpers ----------

def to_4digit_score(val: object) -> str:
    """
    Safely convert PACP quick ratings like '281E' or '2D00' or 3.0 to a 4-char string.
    We extract the first run of digits; if none, return '0000'.
    """
    if pd.isna(val):
        return "0000"
    s = str(val).strip()
    m = re.search(r"\d+", s)
    if not m:
        return "0000"
    return m.group(0).zfill(4)

def to_float_or_none(val: object):
    try:
        return float(val)
    except Exception:
        return None

def process_codes(df: pd.DataFrame, unwanted_codes: set):
    """
    This is your logic: drop unwanted, then detect continuous codes by S/F pairs,
    count them, and emit distinct PACP_CodeN cells.
    """
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

def process_files(conditions_xl, inspections_xl, ratings_xl, unwanted_codes: set) -> pd.DataFrame:
    # read from uploaded file-like objects
    dfc = pd.read_excel(conditions_xl)
    dfi = pd.read_excel(inspections_xl)
    dfr = pd.read_excel(ratings_xl)

    # merge inspections info
    dfm = dfc.merge(
        dfi[['InspectionID', 'Pipe_Segment_Reference',
             'Inspection_Date', 'Street', 'City',
             'Length_Surveyed', 'Height', 'Material',
             'Upstream_MH', 'Downstream_MH']],
        on='InspectionID', how='left'
    )

    # merge ratings
    dfm = dfm.merge(
        dfr[['InspectionID', 'STQuickRating', 'OMQuickRating', 'OverallPipeRatingsIndex']],
        on='InspectionID', how='left'
    )

    rows = []
    for (insp_id, seg_ref), group in dfm.groupby(['InspectionID', 'Pipe_Segment_Reference']):
        codes = process_codes(group, unwanted_codes)

        stquick = group['STQuickRating'].iloc[0] if 'STQuickRating' in group else None
        omquick = group['OMQuickRating'].iloc[0] if 'OMQuickRating' in group else None
        overall = group['OverallPipeRatingsIndex'].iloc[0] if 'OverallPipeRatingsIndex' in group else None

        # SAFE formatting
        str_score = to_4digit_score(stquick)
        om_score = to_4digit_score(omquick)

        # length surveyed 2 decimals
        ls_val = group['Length_Surveyed'].iloc[0] if 'Length_Surveyed' in group else None
        if pd.notna(ls_val):
            try:
                length_surveyed = round(float(ls_val), 2)
            except Exception:
                length_surveyed = None
        else:
            length_surveyed = None

        # overall to 2 decimals if numeric
        overall_float = to_float_or_none(overall)
        overall_fmt = round(overall_float, 2) if overall_float is not None else None

        row = {
            'InspectionID': insp_id,
            'Pipe_Segment_Reference': seg_ref,
            'Inspection_Date': group['Inspection_Date'].iloc[0] if 'Inspection_Date' in group else None,
            'Street': group['Street'].iloc[0] if 'Street' in group else None,
            'City': group['City'].iloc[0] if 'City' in group else None,
            'Length_Surveyed': length_surveyed,
            'Diameter': group['Height'].iloc[0] if 'Height' in group else None,
            'Material': group['Material'].iloc[0] if 'Material' in group else None,
            'Upstream_MH': group['Upstream_MH'].iloc[0] if 'Upstream_MH' in group else None,
            'Downstream_MH': group['Downstream_MH'].iloc[0] if 'Downstream_MH' in group else None,
            'STR Score': str_score,
            'OM Scores': om_score,
            'Overall Scores': overall_fmt
        }

        for i, code in enumerate(codes, start=1):
            row[f'PACP_Code{i}'] = code

        rows.append(row)

    return pd.DataFrame(rows)

# ===== Streamlit UI =====

st.title("PACP Coder 2.0 — Streamlit (using your attached logic)")
st.write(
    "Upload your three PACP Excel exports (Conditions, Inspections, Ratings). "
    "This runs the same S/F continuous logic as your script, **with adjustable unwanted codes**, "
    "and safe formatting of scores like '2D00' → '0002' / '0000' depending on digits found."
)

col1, col2, col3 = st.columns(3)
with col1:
    conditions_file = st.file_uploader("PACP_Conditions Excel", type=["xlsx", "xls"])
with col2:
    inspections_file = st.file_uploader("PACP_Inspections Excel", type=["xlsx", "xls"])
with col3:
    ratings_file = st.file_uploader("PACP_Ratings Excel", type=["xlsx", "xls"])

st.markdown("### Unwanted PACP codes")
st.caption("Defaults from your script are loaded. You can add more (comma-separated) or remove some.")
col_add, col_remove = st.columns(2)
with col_add:
    add_codes_text = st.text_area("Add codes (comma-separated)", value="", height=80,
                                  help="Example: SAG,DAGS,MH")
with col_remove:
    remove_codes_text = st.text_area("Remove codes (comma-separated)", value="", height=80,
                                     help="Codes to allow even though they're in the default list.")

run_btn = st.button("Process")

if run_btn:
    if not (conditions_file and inspections_file and ratings_file):
        st.error("Please upload all three files first.")
        st.stop()

    # build dynamic unwanted set
    unwanted = set(DEFAULT_UNWANTED)

    # add
    if add_codes_text.strip():
        for tok in add_codes_text.replace("\n", ",").split(","):
            cod = tok.strip().upper()
            if cod:
                unwanted.add(cod)

    # remove
    if remove_codes_text.strip():
        for tok in remove_codes_text.replace("\n", ",").split(","):
            cod = tok.strip().upper()
            if cod in unwanted:
                unwanted.remove(cod)

    try:
        df_out = process_files(conditions_file, inspections_file, ratings_file, unwanted)
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
    st.info("Upload the three files above, adjust unwanted codes if needed, then click **Process**.")
