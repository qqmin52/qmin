"""二次探测 qq-botpy-sdk 的类与方法签名。

只读探测：不读取 .env，不发起网络请求。每项独立 try/except，
失败打印 ``SKIP: <原因>`` 后继续。
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
from collections.abc import Mapping


def _skip(reason: object) -> None:
    print(f"SKIP: {reason}")


def _signature(obj: object) -> str:
    try:
        return str(inspect.signature(obj))
    except Exception as exc:
        return f" -> SKIP: {exc}"


def _type_text(annotation: object) -> str:
    if isinstance(annotation, str):
        return annotation
    return getattr(annotation, "__name__", repr(annotation))


def _dump_message_class(module_name: str, class_name: str) -> None:
    print(f"\n===== {module_name}.{class_name} =====")
    try:
        module = importlib.import_module("botpy.message")
    except Exception as exc:
        _skip(f"import botpy.message: {exc}")
        return
    try:
        cls = getattr(module, class_name)
    except Exception as exc:
        _skip(f"getattr {class_name}: {exc}")
        return

    try:
        members = inspect.getmembers(cls)
    except Exception as exc:
        _skip(f"getmembers {class_name}: {exc}")
        return

    for name, member in members:
        if name.startswith("_"):
            continue
        if inspect.isroutine(member):
            print(f"{name}{_signature(member)}")
        else:
            print(f"{name}: {type(member).__name__}")


def _dump_botapi(module_name: str) -> None:
    print(f"\n===== {module_name}.BotAPI 方法 =====")
    try:
        module = importlib.import_module("botpy.message")
        cls = getattr(module, "BotAPI")
    except Exception as exc:
        _skip(f"定位 BotAPI: {exc}")
        return

    try:
        members = inspect.getmembers(cls)
    except Exception as exc:
        _skip(f"getmembers BotAPI: {exc}")
        return

    for name, member in members:
        if name.startswith("_"):
            continue
        if inspect.isroutine(member):
            print(f"{name}{_signature(member)}")


def _dump_client_callbacks() -> None:
    print("\n===== botpy.Client 回调签名 =====")
    try:
        client_cls = importlib.import_module("botpy").Client
    except Exception as exc:
        _skip(f"定位 Client: {exc}")
        return

    for name in ("on_message", "on_message_context", "on_raw_event"):
        try:
            member = getattr(client_cls, name)
            print(f"{name}{_signature(member)}")
        except Exception as exc:
            _skip(f"{name}: {exc}")


def _dump_payload_fields() -> None:
    print("\n===== botpy.types.gateway.MessagePayload 字段 =====")
    try:
        module = importlib.import_module("botpy.types.gateway")
        payload_cls = getattr(module, "MessagePayload")
    except Exception as exc:
        _skip(f"定位 MessagePayload: {exc}")
        return

    try:
        fields = dataclasses.fields(payload_cls)
        for field in fields:
            print(f"{field.name}: {_type_text(field.type)}")
        return
    except Exception as exc:
        print(f"SKIP: dataclasses.fields: {exc}")

    try:
        annotations = getattr(payload_cls, "__annotations__", None)
        if not annotations:
            _skip("MessagePayload 既无 dataclass fields 也无 __annotations__")
            return
        for name, annotation in annotations.items():
            print(f"{name}: {_type_text(annotation)}")
    except Exception as exc:
        _skip(f"__annotations__: {exc}")


def _dump_intents_flags() -> None:
    print("\n===== botpy.flags.Intents.VALID_FLAGS / DEFAULT_VALUE =====")
    try:
        flags_module = importlib.import_module("botpy.flags")
        intents_cls = flags_module.Intents
    except Exception as exc:
        _skip(f"定位 Intents: {exc}")
        return

    try:
        valid_flags = intents_cls.VALID_FLAGS
        print(f"VALID_FLAGS type: {type(valid_flags).__name__}")
        if isinstance(valid_flags, Mapping):
            for key, value in valid_flags.items():
                print(f"{key} = {value!r}")
        else:
            print(f"VALID_FLAGS = {valid_flags!r}")
    except Exception as exc:
        _skip(f"VALID_FLAGS: {exc}")

    try:
        default_value = intents_cls.DEFAULT_VALUE
        print(f"DEFAULT_VALUE type: {type(default_value).__name__}")
        print(f"DEFAULT_VALUE = {default_value!r}")
    except Exception as exc:
        _skip(f"DEFAULT_VALUE: {exc}")


def _dump_client_lifecycle() -> None:
    print("\n===== botpy.Client 生命周期方法签名 =====")
    try:
        client_cls = importlib.import_module("botpy").Client
    except Exception as exc:
        _skip(f"定位 Client: {exc}")
        return

    for name in ("start", "run", "close", "is_closed"):
        try:
            member = getattr(client_cls, name)
            print(f"{name}{_signature(member)}")
        except Exception as exc:
            _skip(f"{name}: {exc}")


def _dump_init_signatures() -> None:
    print("\n===== botpy.BotHttp / botpy.Token 构造签名 =====")
    try:
        botpy_module = importlib.import_module("botpy")
    except Exception as exc:
        _skip(f"import botpy: {exc}")
        return

    for name in ("BotHttp", "Token"):
        try:
            cls = getattr(botpy_module, name)
            print(f"{name}.__init__{_signature(cls.__init__)}")
        except Exception as exc:
            _skip(f"{name}: {exc}")


def main() -> None:
    for class_name in ("Message", "GroupMessage", "C2CMessage", "DirectMessage"):
        _dump_message_class("botpy.message", class_name)
    _dump_botapi("botpy.message")
    _dump_client_callbacks()
    _dump_payload_fields()
    _dump_intents_flags()
    _dump_client_lifecycle()
    _dump_init_signatures()


if __name__ == "__main__":
    main()
