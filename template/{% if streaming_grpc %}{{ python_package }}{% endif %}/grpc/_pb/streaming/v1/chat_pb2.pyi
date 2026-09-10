# ruff: noqa
# mypy: ignore-errors
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional

DESCRIPTOR: _descriptor.FileDescriptor

class ChatMessage(_message.Message):
    __slots__ = ("seq", "text")
    SEQ_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    seq: int
    text: str
    def __init__(self, seq: _Optional[int] = ..., text: _Optional[str] = ...) -> None: ...
