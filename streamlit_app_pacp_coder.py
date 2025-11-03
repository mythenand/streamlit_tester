import streamlit as st
import pandas as pd
import io
import re

# ===== default unwanted codes (same as your script) =====
DEFAULT_UNWANTED_STR = (
    "ACB, ACOM, AEP, AMH, AOC, ATC, MGO, MMC, MSC, MWL, MWM, "
    "TB, TBA, TBC, TBD, TF, TFA, TFC, TFD, TS, TSA"
)

def parse_unwanted(text: str) -> set:
    codes = set()
    for tok in re.split(r"[,\s]+", text.strip()):
        tok = tok.strip().upper()
        if tok:
            codes.add(tok)
    return codes

def process_codes(df: pd.DataFrame, unwanted_codes: set):
    """
    Exact shape of your original logic: drop unwanted, detect S/F pairs,
    count continuous, and emit one entry per code.
    """
    df_filtered = df[~df['PACP_Code'].isin(unwanted_codes) & df['PACP_Code'].notna()]
    if df_filtered.empty:
        return []

    so_lookup, fo_lookup, used_indices, continuous_counts = {}, {}, set(), {}

    # build S/F lookups
    for idx, row in df_filtered.iterrows():
        code = str(row['PACP_Code']).strip()
        cont = str(row.get('Continuous', '')).strip().upper()
        if cont.startswith('S'):
            so_lookup[(code, cont[1:])] = idx
        elif cont.startswith('F'):
            fo_lookup[(code, cont[1:])] = idx

    # match Sxx/Fxx
    for (code, num), s_idx in so_lookup.items():
        if (code, num) in fo_lookup:
            f_idx = fo_lookup[(code, num)]
            continuous_counts[code] = continuous_counts.get(code, 0) + 1
            used_indices.update([s_idx, f_idx])

    final = []
    seen_normal = set()
    seen_cont = set()

    for idx, row in df_filtered.iterrows():
        code = str(row['PACP_Code']).strip()
        if idx in used_indices:
            # part of a continuous pair
            if code not in seen_cont:
                cnt = continuous_counts.get(code, 1)
                final.append(f"{code} ©" if cnt == 1 else f"{code} ©X{cnt}")
                seen_cont.add(code)
        else:
            # non-continuous
            if code not in seen_normal:
                cnt = (df_filtered['PACP_Code'] == code).sum()
                final.append(f"{code} X{cnt}" if cnt > 1 else code)
                seen_normal.add(code)

    return final

def process_files(conditions_xl, inspections_xl, ratings_xl, unwanted_codes: set) -> pd.DataFrame:
    # read Excel
    df_conditions = pd.read_excel(conditions_xl)
    df_inspections = pd.read_excel(inspections_xl)
    df_ratings = pd.read_excel(ratings_xl)

    # merge inspections first (include date, street, city etc.)
    df_merged = df_conditions.merge(
        df_inspections[
            [
                "InspectionID",
                "Pipe_Segment_Reference",
                "Inspection_Date",
                "Street",
                "City",
                "Length_Surveyed",
                "Height",
                "Material",
                "Upstream_MH",
                "Downstream_MH",
            ]
        ],
        on="InspectionID",
        how="left",
    )

    # merge ratings
    df_merged = df_merged.merge(
        df_ratings[
            [
                "InspectionID",
                "STQuickRating",
                "OMQuickRating",
                "OverallPipeRatingsIndex",
            ]
        ],
        on="InspectionID",
        how="left",
    )

    rows = []
    # group like your script
    for (insp_id, seg_ref), group in df_merged.groupby(
        ["InspectionID", "Pipe_Segment_Reference"]
    ):
        codes = process_codes(group, unwanted_codes)

        # these three lines below are the part that caused your error in the streamlit version —
        # we now copy your original script's behavior: str(...).zfill(4) instead of int(...)
        stquick_val = group["STQuickRating"].iloc[0]
        omquick_val = group["OMQuickRating"].iloc[0]
        overall_val = group["OverallPipeRatingsIndex"].iloc[0]

        str_score = (
            str(stquick_val).zfill(4) if pd.notna(stquick_val) else "0000"
        )
        om_score = (
            str(omquick_val).zfill(4) if pd.notna(omquick_val) else "0000"
        )

        # length surveyed → 2 decimals like your script
        ls = group["Length_Surveyed"].iloc[0]
        if pd.notna(ls):
            try:
                ls = round(float(ls), 2)
            except Exception:
                ls = None
        else:
            ls = None

        # overall score → 2 decimals if numeric
        if pd.notna(overall_val):
            try:
                overall_fmt = round(float(overall_val), 2)
            except Exception:
                overall_fmt = None
        else:
            overall_fmt = None

        row = {
            "InspectionID": insp_id,
            "Pipe_Segment_Reference": seg_ref,
            "Inspection_Date": group["Inspection_Date"].iloc[0],
            "Street": group["Street"].iloc[0],
            "City": group["City"].iloc[0],
            "Length_Surveyed": ls,
            "Diameter": group["Height"].iloc[0],
            "Material": group["Material"].iloc[0],
            "Upstream_MH": group["Upstream_MH"].iloc[0],
            "Downstream_MH": group["Downstream_MH"].iloc[0],
            "STR Score": str_score,
            "OM Scores": om_score,
            "Overall Scores": overall_fmt,
        }

        # add PACP_Code1..N
        for i, code in enumerate(codes, start=1):
            row[f"PACP_Code{i}"] = code

        rows.append(row)

    return pd.DataFrame(rows)

# ===================== Streamlit UI =====================

st.title("PACP Coder 2.0 — Streamlit (same output as script)")

col1, col2, col3 = st.columns(3)
with col1:
    conditions_file = st.file_uploader("1) PACP_Conditions", type=["xlsx", "xls"])
with col2:
    inspections_file = st.file_uploader("2) PACP_Inspections", type=["xlsx", "xls"])
with col3:
    ratings_file = st.file_uploader("3) PACP_Ratings", type=["xlsx", "xls"])

st.markdown("### 2) Options")
st.write("**Unwanted PACP codes (comma/space separated)**")
unwanted_text = st.text_area(
    "Edit or add to this list:",
    value=DEFAULT_UNWANTED_STR,
    height=100,
)

run_btn = st.button("Process")

if run_btn:
    if not (conditions_file and inspections_file and ratings_file):
        st.error("Please upload all three PACP Excel files.")
        st.stop()

    unwanted_set = parse_unwanted(unwanted_text)

    try:
        df_out = process_files(
            conditions_file, inspections_file, ratings_file, unwanted_set
        )
    except Exception as e:
        st.exception(e)
        st.stop()

    st.success(f"Processed {len(df_out)} inspection rows.")
    st.dataframe(df_out, use_container_width=True)

    # download
    bio = io.BytesIO()
    df_out.to_excel(bio, index=False, sheet_name="PACP_Output")
    bio.seek(0)
    st.download_button(
        "Download PACP_Output.xlsx",
        data=bio,
        file_name="PACP_Output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("Upload the 3 files and click **Process**.")
