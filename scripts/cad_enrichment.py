import re
import time

import pandas as pd
import requests
from bs4 import BeautifulSoup

from scripts.run_search import build_cad_lookup_link


REQUIRED_FIELDS = [
    "owner_name",
    "mailing_address",
    "appraised_value",
    "land_value",
    "improvement_value",
    "use_code",
]


def clean_money(value):
    if value is None or pd.isna(value):
        return pd.NA
    cleaned = re.sub(r"[$,\s]", "", str(value))
    return pd.to_numeric(cleaned, errors="coerce")


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def find_heading(soup, heading_text):
    return soup.find(
        lambda tag: tag.name in ["h1", "h2", "h3"]
        and clean_text(tag.get_text()).casefold() == heading_text.casefold()
    )


def siblings_until_next_heading(heading):
    if not heading:
        return []

    siblings = []
    for sibling in heading.find_next_siblings():
        if sibling.name in ["h1", "h2", "h3"]:
            break
        siblings.append(sibling)
    return siblings


def section_text_lines(soup, heading_text):
    heading = find_heading(soup, heading_text)
    lines = []
    for sibling in siblings_until_next_heading(heading):
        for text in sibling.stripped_strings:
            text = clean_text(text)
            if text:
                lines.append(text)
    return lines


def rows_from_table(table):
    rows = {}
    if not table:
        return rows

    for row in table.find_all("tr"):
        cells = [
            clean_text(cell.get_text(" ", strip=True))
            for cell in row.find_all(["th", "td"])
        ]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows[cells[0]] = cells[1:]
    return rows


def table_rows_in_section(soup, heading_text):
    heading = find_heading(soup, heading_text)
    rows = {}
    for sibling in siblings_until_next_heading(heading):
        for table in sibling.find_all("table"):
            rows.update(rows_from_table(table))
        if sibling.name == "table":
            rows.update(rows_from_table(sibling))
    return rows


def all_detected_labels(soup):
    labels = []
    for heading in soup.find_all(["h1", "h2", "h3"]):
        labels.append(
            {
                "section": "heading",
                "label": clean_text(heading.get_text()),
                "value": "",
            }
        )

    for table in soup.find_all("table"):
        for label, values in rows_from_table(table).items():
            labels.append(
                {
                    "section": "table",
                    "label": label,
                    "value": " | ".join(values),
                }
            )
    return labels


def parse_owner(soup):
    heading = find_heading(soup, "Owners")
    ownership_block = None
    for sibling in siblings_until_next_heading(heading):
        classes = sibling.get("class", [])
        if sibling.name == "div" and "ownership" in classes:
            ownership_block = sibling
            break

    if not ownership_block:
        return pd.NA, pd.NA, pd.NA

    lines = [clean_text(text) for text in ownership_block.stripped_strings]
    lines = [line for line in lines if line]
    if not lines:
        return pd.NA, pd.NA, pd.NA

    owner_name = lines[0]
    mailing_lines = lines[1:]
    mailing_address = " ".join(mailing_lines)
    mailing_city = pd.NA

    for line in reversed(mailing_lines):
        if "," in line:
            mailing_city = line.split(",", 1)[0].strip()
            break

    return owner_name, mailing_address, mailing_city


def first_value(rows, label):
    values = rows.get(label, [])
    if not values:
        return pd.NA
    return values[0]


def first_date(lines):
    for line in lines:
        match = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", line)
        if match:
            return match.group(0)
    return pd.NA


def non_empty(value):
    if value is None or pd.isna(value):
        return False
    return str(value).strip() != ""


def first_non_empty(*values):
    for value in values:
        if non_empty(value):
            return value
    return pd.NA


def parse_cad_html(account, html):
    soup = BeautifulSoup(html, "html.parser")
    detected_labels = all_detected_labels(soup)
    parcel_rows = table_rows_in_section(soup, "Parcel Summary")
    preliminary_rows = table_rows_in_section(soup, "Preliminary Values")
    value_history_rows = table_rows_in_section(soup, "Value History")

    owner_name, mailing_address, mailing_city = parse_owner(soup)
    transfer_date = first_date(section_text_lines(soup, "Document/Transfer History"))
    exemption_lines = section_text_lines(soup, "Exemptions")
    exemptions = "; ".join(exemption_lines) if exemption_lines else pd.NA

    record = {
        "ACCOUNT": str(account),
        "cad_lookup_link": build_cad_lookup_link(account),
        "owner_name": owner_name,
        "mailing_address": mailing_address,
        "mailing_city": mailing_city,
        "appraised_value": clean_money(
            first_non_empty(
                first_value(preliminary_rows, "Total Property Value"),
                first_value(value_history_rows, "Total Property Value"),
            )
        ),
        "land_value": clean_money(
            first_non_empty(
                first_value(preliminary_rows, "Total Land Value"),
                first_value(value_history_rows, "Total Land Value"),
            )
        ),
        "improvement_value": clean_money(
            first_non_empty(
                first_value(preliminary_rows, "Total Building Value"),
                first_value(value_history_rows, "Total Building Value"),
            )
        ),
        "transfer_date": transfer_date,
        "use_code": first_non_empty(
            first_value(parcel_rows, "Use Code"),
            first_value(preliminary_rows, "Use Code"),
        ),
        "exemptions": exemptions,
    }

    warnings = [
        field for field in REQUIRED_FIELDS if not non_empty(record.get(field))
    ]
    debug = {
        "ACCOUNT": str(account),
        "detected_labels": detected_labels,
        "parcel_summary_rows": parcel_rows,
        "preliminary_value_rows": preliminary_rows,
        "value_history_rows": value_history_rows,
        "warnings": warnings,
    }

    print(f"CAD parser debug for ACCOUNT {account}")
    for item in detected_labels:
        print(f"{item['section']}: {item['label']} => {item['value']}")
    if warnings:
        print(f"CAD parser warnings for ACCOUNT {account}: missing {warnings}")

    return record, debug


def enrich_account(account, timeout=20):
    account = str(account).strip()
    response = requests.get(
        build_cad_lookup_link(account),
        headers={"User-Agent": "commercial-land-finder/1.0"},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_cad_html(account, response.text)


def enrich_accounts(accounts, delay_seconds=3, progress_callback=None):
    records = []
    debug_logs = []
    errors = []

    for index, account in enumerate(accounts, start=1):
        try:
            record, debug = enrich_account(account)
            if debug["warnings"]:
                errors.append(
                    {
                        "ACCOUNT": str(account),
                        "error": "Missing fields: " + ", ".join(debug["warnings"]),
                    }
                )
            else:
                records.append(record)
            debug_logs.append(debug)
        except Exception as exc:
            errors.append({"ACCOUNT": str(account), "error": str(exc)})

        if progress_callback:
            progress_callback(index, len(accounts), account)

        if index < len(accounts):
            time.sleep(delay_seconds)

    return pd.DataFrame(records), errors, debug_logs
