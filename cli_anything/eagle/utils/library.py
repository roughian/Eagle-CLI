from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from cli_anything.eagle.utils.folders import normalize_folder_path


@dataclass(frozen=True)
class SmartFolderRecord:
    id: str
    name: str
    path: str
    depth: int
    parent_id: str | None
    parent_path: str | None
    raw: dict[str, Any]


def flatten_smart_folders(
    folders: list[dict[str, Any]],
    *,
    parent_id: str | None = None,
    parent_path: str | None = None,
    depth: int = 0,
) -> list[SmartFolderRecord]:
    records: list[SmartFolderRecord] = []
    for folder in folders:
        name = str(folder.get("name", ""))
        path = f"{parent_path}/{name}" if parent_path else name
        record = SmartFolderRecord(
            id=str(folder.get("id", "")),
            name=name,
            path=path,
            depth=depth,
            parent_id=parent_id,
            parent_path=parent_path,
            raw=folder,
        )
        records.append(record)
        children = folder.get("children") or []
        if isinstance(children, list):
            records.extend(
                flatten_smart_folders(
                    children,
                    parent_id=record.id,
                    parent_path=record.path,
                    depth=depth + 1,
                )
            )
    return records


def find_smart_folders_by_name(
    records: list[SmartFolderRecord],
    query: str,
    *,
    exact: bool = False,
    parent_id: str | None = None,
) -> list[SmartFolderRecord]:
    normalized = query.casefold()
    matches: list[SmartFolderRecord] = []
    for record in records:
        if parent_id is not None and record.parent_id != parent_id:
            continue
        haystack = record.name.casefold()
        if exact and haystack == normalized:
            matches.append(record)
        elif not exact and normalized in haystack:
            matches.append(record)
    return matches


def find_smart_folder_by_path(records: list[SmartFolderRecord], path: str) -> SmartFolderRecord | None:
    normalized = normalize_folder_path(path).casefold()
    for record in records:
        if record.path.casefold() == normalized:
            return record
    return None


def smart_folder_rule_rows(records: list[SmartFolderRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records:
        conditions = record.raw.get("conditions") or []
        if not isinstance(conditions, list):
            continue
        for condition_index, condition in enumerate(conditions):
            if not isinstance(condition, dict):
                continue
            rules = condition.get("rules") or []
            if not isinstance(rules, list):
                continue
            for rule_index, rule in enumerate(rules):
                if not isinstance(rule, dict):
                    continue
                rows.append(
                    {
                        "smart_folder_id": record.id,
                        "smart_folder_name": record.name,
                        "smart_folder_path": record.path,
                        "condition_index": condition_index,
                        "condition_boolean": condition.get("boolean", "TRUE"),
                        "condition_match": condition.get("match", "AND"),
                        "rule_index": rule_index,
                        "property": rule.get("property"),
                        "method": rule.get("method"),
                        "value": rule.get("value"),
                    }
                )
    return rows


def summarize_smart_folder_rules(records: list[SmartFolderRecord]) -> dict[str, Any]:
    rows = smart_folder_rule_rows(records)
    conditions_total = 0
    folders_with_rules = 0
    for record in records:
        conditions = record.raw.get("conditions") or []
        if isinstance(conditions, list):
            conditions_total += len(conditions)
        if any(row["smart_folder_id"] == record.id for row in rows):
            folders_with_rules += 1

    property_counts = Counter(str(row.get("property") or "") for row in rows if row.get("property"))
    method_counts = Counter(str(row.get("method") or "") for row in rows if row.get("method"))
    pair_counts = Counter(
        (str(row.get("property") or ""), str(row.get("method") or ""))
        for row in rows
        if row.get("property") and row.get("method")
    )
    return {
        "smart_folder_count": len(records),
        "smart_folders_with_rules": folders_with_rules,
        "condition_count": conditions_total,
        "rule_count": len(rows),
        "properties": [{"property": key, "count": value} for key, value in property_counts.most_common()],
        "methods": [{"method": key, "count": value} for key, value in method_counts.most_common()],
        "property_methods": [
            {"property": property_name, "method": method_name, "count": value}
            for (property_name, method_name), value in pair_counts.most_common()
        ],
    }


def translate_smart_folder_to_item_filter(record: SmartFolderRecord) -> dict[str, Any]:
    params = {
        "limit": 20,
        "offset": 0,
        "order_by": None,
        "keyword": None,
        "ext": None,
        "tags": [],
        "folders": [],
        "folder_names": [],
        "folder_paths": [],
    }
    supported_rules: list[dict[str, Any]] = []
    unsupported_rules: list[dict[str, Any]] = []
    conditions = record.raw.get("conditions") or []
    if not isinstance(conditions, list):
        conditions = []

    for condition_index, condition in enumerate(conditions):
        if not isinstance(condition, dict):
            continue
        boolean = str(condition.get("boolean", "TRUE")).upper()
        match = str(condition.get("match", "AND")).upper()
        rules = condition.get("rules") or []
        if not isinstance(rules, list):
            continue

        if boolean != "TRUE":
            for rule_index, rule in enumerate(rules):
                if isinstance(rule, dict):
                    unsupported_rules.append(
                        {
                            "condition_index": condition_index,
                            "rule_index": rule_index,
                            "property": rule.get("property"),
                            "method": rule.get("method"),
                            "value": rule.get("value"),
                            "reason": f"Unsupported condition boolean: {boolean}",
                        }
                    )
            continue

        if match != "AND":
            for rule_index, rule in enumerate(rules):
                if isinstance(rule, dict):
                    unsupported_rules.append(
                        {
                            "condition_index": condition_index,
                            "rule_index": rule_index,
                            "property": rule.get("property"),
                            "method": rule.get("method"),
                            "value": rule.get("value"),
                            "reason": f"Unsupported condition match: {match}",
                        }
                    )
            continue

        for rule_index, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            property_name = str(rule.get("property", "") or "")
            method_name = str(rule.get("method", "") or "")
            value = rule.get("value")
            normalized_rule = {
                "condition_index": condition_index,
                "rule_index": rule_index,
                "property": property_name,
                "method": method_name,
                "value": value,
            }

            if property_name == "type" and method_name == "equal" and isinstance(value, str) and value.strip():
                ext_value = value.strip().lstrip(".").lower()
                existing_ext = params["ext"]
                if existing_ext and str(existing_ext).casefold() != ext_value.casefold():
                    unsupported_rules.append(
                        {
                            **normalized_rule,
                            "reason": f"Conflicting type rule: {existing_ext} vs {ext_value}",
                        }
                    )
                    continue
                params["ext"] = ext_value
                supported_rules.append(normalized_rule)
                continue

            if property_name in {"folders", "folder"} and method_name == "intersection" and isinstance(value, list):
                folder_ids = [str(item) for item in value if str(item)]
                if not folder_ids:
                    unsupported_rules.append({**normalized_rule, "reason": "Folder rule does not contain any IDs"})
                    continue
                params["folders"].extend(folder_ids)
                supported_rules.append(normalized_rule)
                continue

            if property_name == "tags" and method_name == "intersection" and isinstance(value, list):
                tags = [str(item) for item in value if str(item)]
                if not tags:
                    unsupported_rules.append({**normalized_rule, "reason": "Tag rule does not contain any tag names"})
                    continue
                params["tags"].extend(tags)
                supported_rules.append(normalized_rule)
                continue

            unsupported_rules.append(
                {
                    **normalized_rule,
                    "reason": f"Unsupported smart-folder rule: {property_name}/{method_name}",
                }
            )

    params["tags"] = _unique_preserve_order(params["tags"])
    params["folders"] = _unique_preserve_order(params["folders"])
    return {
        "item_filter": params,
        "supported_rules": supported_rules,
        "unsupported_rules": unsupported_rules,
        "supported_rule_count": len(supported_rules),
        "unsupported_rule_count": len(unsupported_rules),
        "is_fully_supported": len(unsupported_rules) == 0,
    }


def build_library_summary(data: dict[str, Any]) -> dict[str, Any]:
    from cli_anything.eagle.utils.folders import flatten_folders

    folder_records = flatten_folders(list(data.get("folders") or []))
    smart_folder_records = flatten_smart_folders(list(data.get("smartFolders") or []))
    smart_rule_summary = summarize_smart_folder_rules(smart_folder_records)
    library = data.get("library") or {}

    return {
        "library_name": library.get("name"),
        "library_path": library.get("path"),
        "application_version": data.get("applicationVersion"),
        "folder_count": len(folder_records),
        "root_folder_count": len(data.get("folders") or []),
        "max_folder_depth": max((record.depth for record in folder_records), default=0),
        "smart_folder_count": len(smart_folder_records),
        "root_smart_folder_count": len(data.get("smartFolders") or []),
        "max_smart_folder_depth": max((record.depth for record in smart_folder_records), default=0),
        "quick_access_count": len(data.get("quickAccess") or []),
        "tag_group_count": len(data.get("tagsGroups") or []),
        "smart_rule_condition_count": smart_rule_summary["condition_count"],
        "smart_rule_count": smart_rule_summary["rule_count"],
        "smart_rule_properties": [row["property"] for row in smart_rule_summary["properties"]],
        "smart_rule_methods": [row["method"] for row in smart_rule_summary["methods"]],
    }


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: list[str] = []
    for item in items:
        if item not in seen:
            seen.append(item)
    return seen
