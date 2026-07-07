import re


def _parse_group_id_list(raw: str) -> set[str]:
    return {
        item.strip()
        for item in re.split(r"[,\s]+", raw or "")
        if item.strip()
    }


def _is_allowed_chat(event, config) -> bool:
    allowed_group_ids = _parse_group_id_list(config.get("allowed_group_ids", "") if config else "")
    if not allowed_group_ids:
        return True
    message_obj = getattr(event, "message_obj", None)
    group_id = str(getattr(message_obj, "group_id", "") or "")
    if not group_id:
        return True
    return group_id in allowed_group_ids
