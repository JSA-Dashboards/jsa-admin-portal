"""Column-mapping presets — replaces the HTML tool's localStorage `cornRiskDesk.importPresets`
blob. IMPORT_PRESETS.IS_DEFAULT marks the standing default ("QST Basic Corn") that beats
the generic last-used mapping whenever it exists.
"""
import json
from typing import Dict, Optional

from . import snowflake_client as sf

DEFAULT_PRESET_NAME = "QST Basic Corn"


def get_default_preset() -> Optional[dict]:
    df = sf.query_df("SELECT MAPPING_JSON FROM IMPORT_PRESETS WHERE IS_DEFAULT = TRUE LIMIT 1")
    if df.empty:
        return None
    return json.loads(df.iloc[0]["MAPPING_JSON"])


def get_last_used_mapping() -> Optional[dict]:
    df = sf.query_df("SELECT MAPPING_JSON FROM IMPORT_LAST_USED_MAPPING WHERE ID = 1")
    if df.empty or df.iloc[0]["MAPPING_JSON"] is None:
        return None
    return json.loads(df.iloc[0]["MAPPING_JSON"])


def set_last_used_mapping(mapping: dict, updated_by: str) -> None:
    sf.execute(
        """
        MERGE INTO IMPORT_LAST_USED_MAPPING t USING (SELECT 1 AS ID) s ON t.ID = s.ID
        WHEN MATCHED THEN UPDATE SET MAPPING_JSON = PARSE_JSON(%s), UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (ID, MAPPING_JSON) VALUES (1, PARSE_JSON(%s))
        """,
        (json.dumps(mapping), json.dumps(mapping)),
    )


def list_presets() -> Dict[str, dict]:
    df = sf.query_df("SELECT PRESET_NAME, MAPPING_JSON FROM IMPORT_PRESETS ORDER BY PRESET_NAME")
    return {row["PRESET_NAME"]: json.loads(row["MAPPING_JSON"]) for _, row in df.iterrows()}


def save_preset(name: str, mapping: dict, created_by: str, is_default: bool = False) -> None:
    sf.execute(
        """
        MERGE INTO IMPORT_PRESETS t USING (SELECT %s AS NAME) s ON t.PRESET_NAME = s.NAME
        WHEN MATCHED THEN UPDATE SET MAPPING_JSON = PARSE_JSON(%s), IS_DEFAULT = %s, UPDATED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT (PRESET_NAME, MAPPING_JSON, IS_DEFAULT, CREATED_BY)
                          VALUES (%s, PARSE_JSON(%s), %s, %s)
        """,
        (name, json.dumps(mapping), is_default, name, json.dumps(mapping), is_default, created_by),
    )


def delete_preset(name: str) -> None:
    sf.execute("DELETE FROM IMPORT_PRESETS WHERE PRESET_NAME = %s", (name,))
