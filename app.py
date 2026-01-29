import streamlit as st
import sqlite3
import json
import openai

# -------------------------------
# ✅ CONFIG
# -------------------------------
DB_PATH = "hs_attributes.db"
MODEL_NAME = "gpt-4.1-mini"

# -------------------------------
# ✅ DOMAIN MAPPING (HS2 → Domain)
# -------------------------------
hs_mapping = {
    "01-05": "Live Animals",
    "06-14": "Vegetable Products",
    "15": "Animal, Vegetable Or Microbial Fats And Oils And Their Cleavage Products; Prepared Edible Fats; Animal Or Vegetable Waxes",
    "16-24": "Prepared Foodstuffs; Beverages, Spirits And Vinegar; Tobacco And Manufactured Tobacco Substitutes",
    "25-27": "Mineral Products",
    "28-38": "Products Of The Chemical Or Allied Industries",
    "39-40": "Plastics And Articles Thereof; Rubber And Articles Thereof",
    "41-43": "Raw Hides And Skins, Leather, Furskins; Articles Of Animal Gut",
    "44-46": "Wood And Articles Of Wood; Cork; Basketware and Wickerwork",
    "47-49": "Pulp Of Wood; Recovered Paper; Paper and Paperboard Articles",
    "50-63": "Textile And Textile Articles",
    "64-67": "Footwear, Headgear, Artificial Flowers; Articles Of Human Hair",
    "68-70": "Articles Of Stone, Plaster, Cement, Asbestos, Mica; Glass And Glassware",
    "71": "Natural Or Cultured Pearls, Precious Metals, and Articles Thereof; Imitation Jewellery",
    "72-83": "Base Metals And Articles Of Base Metal",
    "84-85": "Machinery And Mechanical Appliances; Electrical Equipment; Sound and TV Recorders",
    "86-89": "Vehicles, Aircraft, Vessels And Associated Transport Equipment",
    "90-92": "Optical, Medical Or Surgical Instruments; Clocks; Musical Instruments",
    "93": "Arms And Ammunition; Parts And Accessories Thereof",
    "94-96": "Miscellaneous Manufactured Articles",
    "97": "Works Of Art, Collectors' Pieces And Antiques"
}

def get_domain(hs_code: str):
    try:
        hs_int = int(str(hs_code).zfill(4)[:2])
        for k, v in hs_mapping.items():
            if "-" in k:
                lo, hi = map(int, k.split("-"))
                if lo <= hs_int <= hi:
                    return v
            elif int(k) == hs_int:
                return v
    except:
        pass
    return "General Trade Goods"

# -------------------------------
# ✅ FETCH ATTRIBUTES FROM SQLITE
# -------------------------------
def fetch_reference_attributes(hs4: str, db_path=DB_PATH):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        SELECT extracted_attributes
        FROM hs_attribute_store
        WHERE hs4 = ?
        LIMIT 1
    """, (hs4,))

    row = cur.fetchone()
    conn.close()

    if row and row[0]:
        return row[0]  # this is stored JSON string
    return None

# -------------------------------
# ✅ YOUR FINAL PARENT → CHILD PROMPT
# -------------------------------
def build_final_prompt(hs_code, domain, item_description, reference_attributes_json):
    return f"""
You are a Lead Trade Data Taxonomist for a global trade intelligence platform.

Your task is to generate the final customer-facing flat JSON attribute map for a product, by using:

- Parent Reference Attributes (from HS4 database)
- Child Item Description (from website listing)
- HS Code + Domain



 INPUTS

- HS Code: {hs_code}
- Domain: {domain}
- Item Description (Child): {item_description}
- Reference Attributes JSON (Parent): {reference_attributes_json}



 STEP 1 — INTERNAL ALIGNMENT (DO NOT OUTPUT)

Before generating final JSON, internally analyze:

1. Treat Reference Attributes as Parent attribute universe
2. Treat Item Description as Child product instance
3. For every Parent attribute, decide one of these:
    - INHERIT DIRECTLY → keep same key and value
    - FILTER VALUES → keep key but select only relevant values from list
    - UPDATE VALUE → keep key but replace value using Item Description
    - DROP ATTRIBUTE → if not relevant to this item description
4. Identify if Item Description contains any new explicit attributes not present in Parent**, and add them only if fully supported.



 ATTRIBUTE VALUE FILTERING

For any attribute (whether from Parent or derived independently), assign only values that are clearly aligned with the item description and product type.

When evaluating attribute values, retain only those that clearly match both the Child Item Description and the identified Product Type, and discard any value that belongs to a different product context or introduces noise.

Avoid vague, generic, or tangential matches — assign only values that would make sense to an informed customer reading the product description**.

Eliminate values that dilute product clarity or overlap semantically.

For any list-type attribute (from Parent or Child):

- Include a maximum of 5 values
- Ensure all values are distinct, non-overlapping, and semantically unique
- Each value must be clearly aligned with the Item Description and Product Type



 CAS NUMBER & CHEMICAL FORMULA RULE (CONDITIONAL — if hs code {hs_code} starts in this range 28–38 Only)

If the HS Code starts from 28 to 38 (Chemical / Allied Industries), then apply CAS handling as follows:

If the Parent Reference JSON contains a CAS Number attribute: assign only CAS values that are clearly and uniquely associated with the chemical/product type in the Item Description; if no parent CAS matches and the chemical name is unambiguous, first generate from domain knowledge only if highly confident , otherwise omit CAS.

If the Parent Reference JSON does NOT contain a CAS Number attribute but the Item Description contains a chemical name: identify and assign the correct CAS Number and corresponding Chemical Formula from domain knowledge only if highly confident and unambiguous; otherwise omit both.

 STEP 2 — FINAL ATTRIBUTE GENERATION RULES (STRICT)

1. PRODUCT IDENTITY

- Output exactly one key: "Product Type".
- "Product Type" must be a single string, derived only from the item description — never from Parent reference data.
- Select the most specific and accurate product name based on the child-level description only. Do not generalize or pick alternate names from parent attributes.
- Do not create "Product Type 2" or similar variants.
- Never assign vague or generic values like "Goods" or "Materials".



 2. PARENT → CHILD INHERITANCE (MANDATORY)

- The Parent attributes are the reference attribute universe
- Use the Parent attributes as the first priority for extraction
- Only keep Parent attributes if they are relevant to the Child Item Description

 Attribute handling rules:

- If Parent attribute is universally true for the child → keep as-is
- If Parent attribute has many values → select only values relevant to child description
- If Parent attribute key is relevant but value differs → update the value using child description
- If Parent attribute is not relevant to child → omit it

---

 3. CHILD-ONLY ATTRIBUTES (ALLOWED BUT STRICT)

After extracting relevant attributes from the Parent Reference JSON, independently analyze the Item Description and Domain to identify any additional missing attributes not previously captured.

Only include attributes that are:

- Explicitly stated or very strongly implied in the item description
- Unique from previously extracted attributes
- Domain-relevant and technically meaningful
- All values must be precise, verifiable, and relevant to a knowledgeable customer


---

4. VALUE RULES

- Output only values that are explicitly stated, or clearly supported by the product type and domain
- Preserve units exactly as written (%, mm, µm, mesh, kg, etc.)
- Numeric fields must contain only numeric value + unit, without extra words
- Consolidate ranges (e.g., "12–15%")
- Do not output:
    - Placeholder values like "N/A" or "Not specified"
    - Repeated values or synonyms
- All list-type attributes must be limited to 5 maximum values, whether extracted from Parent or Child


 STEP 3 — STRUCTURE

- Output a SINGLE flat JSON object
- No nesting
- No repeated keys
- No bullet points
- No markdown
- No explanation text
- No hs code attribute
- No Attributes with empty arrays or empty strings



 FINAL OUTPUT FORMAT

Return ONLY a valid flat JSON object.

Do not include any intermediate reasoning or comments.
""".strip()

# -------------------------------
# ✅ OPENAI CALL
# -------------------------------
def call_llm(prompt):
    response = openai.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "You are a Lead Trade Data Taxonomist. Return ONLY a valid flat JSON object."},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content

# -------------------------------
# ✅ STREAMLIT UI
# -------------------------------
st.set_page_config(page_title="HS Code Attribute POC", layout="wide")
st.title("✅ HS4 Attribute Inheritance POC (Parent → Child)")

st.sidebar.header("🔑 OpenAI Key")
api_key = st.sidebar.text_input("Enter OpenAI API Key", type="password")

if api_key:
    openai.api_key = api_key

col1, col2 = st.columns(2)

with col1:
    hs_code = st.text_input("HS Code (e.g., 25084010)", value="")
    item_description = st.text_area("Item Description (Child)", height=150)

with col2:
    st.markdown("### 🔍 Reference Attributes (Parent from DB)")
    hs4 = str(hs_code).strip()[:4] if hs_code else ""
    reference_json = None

    if hs4:
        reference_json = fetch_reference_attributes(hs4)

    if reference_json:
        st.code(reference_json, language="json")
    else:
        st.warning("No Parent reference attributes found yet (check DB or HS4).")

st.markdown("---")

if st.button("🚀 Generate Final Customer Attributes"):
    if not api_key:
        st.error("Please enter OpenAI API Key in sidebar.")
    elif not hs_code or not item_description:
        st.error("Please enter HS Code and Item Description.")
    elif not reference_json:
        st.error("No reference attributes found for this HS4 in DB.")
    else:
        domain = get_domain(hs_code)

        st.info(f"✅ Detected Domain: **{domain}** | HS4: **{hs4}**")

        final_prompt = build_final_prompt(
            hs_code=hs_code,
            domain=domain,
            item_description=item_description,
            reference_attributes_json=reference_json
        )

        with st.expander("📌 Final Prompt (Debug View)"):
            st.write(final_prompt)

        try:
            llm_output = call_llm(final_prompt)

            st.markdown("## ✅ FINAL OUTPUT (Customer Attributes)")
            st.code(llm_output, language="json")

            # optional: render json nicely
            try:
                parsed = json.loads(llm_output)
                st.json(parsed)
            except:
                pass

        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
