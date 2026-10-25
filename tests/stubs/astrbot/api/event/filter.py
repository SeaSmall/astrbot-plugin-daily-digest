"""桩：模拟 AstrBot 的 filter 装饰器注册机制（仅用于冒烟测试）。"""
import enum

_registry = []


class EventMessageType(enum.Flag):
    GROUP_MESSAGE = enum.auto()
    PRIVATE_MESSAGE = enum.auto()
    OTHER_MESSAGE = enum.auto()
    ALL = GROUP_MESSAGE | PRIVATE_MESSAGE | OTHER_MESSAGE


def _register(kind, **kw):
    def deco(func):
        _registry.append({
            "kind": kind,
            "module": func.__module__,
            "name": func.__name__,
            "func": func,
            **kw,
        })
        return func
    return deco


def event_message_type(t):
    return _register("message", event_type=t)


def on_llm_request(**kw):
    return _register("llm_request", **kw)


def on_llm_response(**kw):
    return _register("llm_response", **kw)


def on_decorating_result(**kw):
    return _register("decorating_result", **kw)


def command(name, alias=None):
    return _register("command", command=name, alias=alias)