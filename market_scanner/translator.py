from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

try:
    from deep_translator import GoogleTranslator as _Translator
except ImportError:
    _Translator = None


def _translate_values(values: list[str]) -> list[str]:
    if _Translator is None:
        return values

    translator = _Translator(source="en", target="ko")
    results = list(values)
    total = len(values)
    for index, value in enumerate(values):
        if not value or str(value).strip().lower() in {"", "nan"}:
            continue
        try:
            translated = translator.translate(str(value))
            if translated:
                results[index] = translated
        except Exception:
            pass
        if (index + 1) % 5 == 0 or index == total - 1:
            print(f"  translate {index + 1}/{total}", end="\r")
        time.sleep(0.15)
    print(" " * 40, end="\r")
    return results


def translate_scan_csv(
    csv_path: str | Path,
    sector_aliases: dict[str, str] | None = None,
) -> bool:
    path = Path(csv_path)
    df = pd.read_csv(path, encoding="utf-8-sig")

    if "sector" in df.columns and sector_aliases:
        df["sector"] = df["sector"].map(
            lambda value: sector_aliases.get(str(value), value) if pd.notna(value) else value
        )

    if _Translator is None:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        print("  deep-translator is not installed. Sector aliases only were applied.")
        return False

    local_name = df.get("name_local")
    english_name = df.get("name_en")
    symbol = df.get("symbol")

    if local_name is None or english_name is None or symbol is None:
        df.to_csv(path, index=False, encoding="utf-8-sig")
        return False

    mask = (
        local_name.isna()
        | local_name.eq("")
        | local_name.eq(english_name)
        | local_name.eq(symbol)
    )

    if mask.any():
        df.loc[mask, "name_local"] = _translate_values(df.loc[mask, "name_en"].astype(str).tolist())

    if "description" in df.columns:
        desc_mask = mask & df["description"].notna() & df["description"].ne("")
        if desc_mask.any():
            df.loc[desc_mask, "description"] = _translate_values(
                df.loc[desc_mask, "description"].astype(str).tolist()
            )

    df.to_csv(path, index=False, encoding="utf-8-sig")
    return True

