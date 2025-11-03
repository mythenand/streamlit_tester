import streamlit as st
import pandas as pd
import io
import re

# ===== default unwanted codes (same as your earlier version) =====
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
    Build the code list for ONE inspection/segment:
      - normalize codes to UPPER + strip
      - drop unwanted on the normalized code
      - detect S/F continuous pairs on normalized code
      - for non-continuous counts, DO NOT include S/F rows
    """
    # make a working copy with normalized columns
    work = df.copy()
    work["code_clean"] = work["PACP_Code"].astype(str).str.strip().str.upper()
    work["cont_clean"] = work.get("Continuous", "").astype(str).str.strip().str.upper()

    # filter unwanted on cleaned code
    work = work[~work["code_clean"].isin(unwanted_codes) & work["code_clean"].notna()]
    if work.empty:
        return []

    so_lookup, fo_lookup = {}, {}
    used_indices = set()
    continuous_counts = {}

    # 1) build S/F lookups on cleaned code
    for idx, row in work.iterrows():
        code = row["code_clean"]
        cont = row["cont_clean"]
        if cont.startswith("S"):
            so_lookup[(code, cont[1:])] = idx
        elif cont.startswith("F"):
            fo_lookup[(code, cont[1:])] = idx

    # 2) match S/F pairs
    for (code, num), s_idx in so_lookup.items():
        if (code, num) in fo_lookup:
            f_idx = fo_lookup[(code, num)]
            continuous_counts[code] = continuous_counts.get(code, 0) + 1
            used_indices.update([s_idx, f_idx])

    # 3) rows that are NOT in S/F pairs = real non-continuous rows
    noncont_df = work[~work.index.isin(used_indices)]

    final = []
    seen_cont = set()
    seen_noncont = set()

    # 4) walk original filtered order
    for idx, row in work.iterrows():
        code = row["code_clean"]

        if idx in used_indices:
            # part of a continuous pair
            if code not in seen_cont:
                pair_count = continuous_counts.get(code, 1)
                # show © or ©Xn
                final.append(f"{code} ©" if pair_count == 1 else f"{code} ©X{pair_count}")
                seen_cont.add(code)
        else:
            # non-continuous → count ONLY among noncont_df
            if code not in seen_noncont:
                noncont_count = (noncont_df["code_clean"] == code).sum()
                final.append(f"{code} X{noncont_count}" if noncont_count > 1 else code)
                seen_noncont.add(code)

    return final

def process_files(conditions_xl, inspections_xl, ratings_xl, unwanted_codes: set) -> pd.DataFrame:
    # read
    df_conditions = pd.read_excel(conditions_xl)
    df_inspections = pd.read_excel(inspections_xl)
    df_ratings = pd.read_excel(ratings_xl)

    # merge inspections (PSR + meta)
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

    out_rows = []
    for (insp_id, psr), group in df_merged.groupby(["InspectionID", "Pipe_Segment_Reference"]):
        codes = process_codes(group, unwanted_codes)

        stquick_val = group["STQuickRating"].iloc[0]
        omquick_val = group["OMQuickRating"].iloc[0]
        overall_val = group["OverallPipeRatingsIndex"].iloc[0]

        # keep your original style: just zfill the string, don't int()
        str_score = str(stquick_val).zfill(4) if pd.notna(stquick_val) else "0000"
        om_score  = str(omquick_val).zfill(4) if pd.notna(omquick_val) else "0000"

        # length surveyed → 2 decimals
        ls_val = group["Length_Surveyed"].iloc[0]
        if pd.notna(ls_val):
            try:
                ls_val = round(float(ls_val), 2)
            except Exception:
                ls_val = None
        else:
            ls_val = None

        # overall → 2 decimals if numeric
        if pd.notna(overall_val):
            try:
                overall_fmt = round(float(overall_val), 2)
            except Exception:
                overall_fmt = None
        else:
            overall_fmt = None

        row = {
            "InspectionID": insp_id,
            "Pipe_Segment_Reference": psr,
            "Inspection_Date": group["Inspection_Date"].iloc[0],
            "Street": group["Street"].iloc[0],
            "City": group["City"].iloc[0],
            "Length_Surveyed": ls_val,
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

        out_rows.append(row)

    return pd.DataFrame(out_rows)

# =================== STREAMLIT UI ===================

st.title("PACP Coder 2.0 — streamlit")

c1, c2, c3 = st.columns(3)
with c1:
    f_cond = st.file_uploader("1) PACP_Conditions", type=["xlsx", "xls"])
with c2:
    f_insp = st.file_uploader("2) PACP_Inspections", type=["xlsx", "xls"])
with c3:
    f_rate = st.file_uploader("3) PACP_Ratings", type=["xlsx", "xls"])

st.markdown("### 2) Options")
st.write("**Unwanted PACP codes (comma/space separated)**")
unwanted_text = st.text_area(
    "Edit/add/remove:",
    value=DEFAULT_UNWANTED_STR,
    height=100,
)

run = st.button("Process")

if run:
    if not (f_cond and f_insp and f_rate):
        st.error("Please upload all 3 files.")
        st.stop()

    unwanted_set = parse_unwanted(unwanted_text)

    try:
        df_out = process_files(f_cond, f_insp, f_rate, unwanted_set)
    except Exception as e:
        st.exception(e)
        st.stop()

    st.success(f"Processed {len(df_out)} inspection rows.")
    st.dataframe(df_out, use_container_width=True)

    # download
    buf = io.BytesIO()
    df_out.to_excel(buf, index=False, sheet_name="PACP_Output")
    buf.seek(0)
    st.download_button(
        "Download PACP_Output.xlsx",
        data=buf,
        file_name="PACP_Output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
else:
    st.info("Upload files, adjust unwanted codes, then click **Process**.")
