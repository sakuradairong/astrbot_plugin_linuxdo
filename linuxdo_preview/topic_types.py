from __future__ import annotations

from typing import NotRequired
from typing import TypeAlias
from typing import TypedDict

JsonValue: TypeAlias = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


class LinuxDoTag(TypedDict):
    name: NotRequired[str]


class LinuxDoPost(TypedDict):
    name: NotRequired[str]
    username: NotRequired[str]
    avatar_template: NotRequired[str]
    created_at: NotRequired[str]
    cooked: NotRequired[str]


class LinuxDoPostStream(TypedDict):
    posts: NotRequired[list[LinuxDoPost]]


class LinuxDoTopicData(TypedDict):
    title: NotRequired[str]
    fancy_title: NotRequired[str]
    category_id: NotRequired[int | str | None]
    category_name: NotRequired[str]
    last_posted_at: NotRequired[str]
    pinned: NotRequired[bool]
    closed: NotRequired[bool]
    archived: NotRequired[bool]
    posts_count: NotRequired[int | str | None]
    views: NotRequired[int | str | None]
    like_count: NotRequired[int | str | None]
    tags: NotRequired[list[str | LinuxDoTag]]
    post_stream: NotRequired[LinuxDoPostStream]
