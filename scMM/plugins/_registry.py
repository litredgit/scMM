"""Load only configured method entry points and validate their public declarations."""
# ruff: noqa: RUF001

import logging
import math
import re
from dataclasses import asdict, dataclass
from importlib.metadata import entry_points
from typing import get_args

from . import API_VERSION, ENTRY_POINT_GROUP, Method, MethodKind, Parameter, ParameterKind, Plugin
from ._bundled import BUNDLED

log = logging.getLogger(__name__)
ID = re.compile(r"[a-z][a-z0-9_-]{0,63}")


def enabled_ids(value):
    if not isinstance(value, (list, tuple)) or any(
        not isinstance(key, str) or ID.fullmatch(key) is None for key in value
    ):
        raise ValueError("enabled_plugins 必须是插件 ID 列表。")
    if len(value) != len(set(value)):
        raise ValueError("enabled_plugins 含重复的插件 ID。")
    return tuple(value)


def _value(parameter, value):
    kind = parameter.kind
    if kind == "integer":
        valid = type(value) is int
    elif kind == "number":
        valid = type(value) in {int, float} and math.isfinite(value)
    elif kind == "boolean":
        valid = type(value) is bool
    elif kind == "choice":
        valid = type(value) is str and value in parameter.choices
    else:
        valid = type(value) is str and 0 < len(value.strip()) <= 250
    if not valid:
        raise ValueError(f"参数 {parameter.label} 的值不合法。")
    if kind in {"integer", "number"} and (
        (parameter.minimum is not None and value < parameter.minimum)
        or (parameter.maximum is not None and value > parameter.maximum)
    ):
        raise ValueError(f"参数 {parameter.label} 超出范围。")
    return float(value) if kind == "number" else value


def _validate_method(method):
    if (
        not isinstance(method, Method)
        or not isinstance(method.id, str)
        or not ID.fullmatch(method.id)
        or not isinstance(method.label, str)
        or not method.label.strip()
        or method.kind not in get_args(MethodKind)
        or not callable(method.run)
        or not isinstance(method.parameters, tuple)
    ):
        raise ValueError("插件方法声明不合法。")
    if method.kind == "cell_extraction" and (
        not isinstance(method.intensity_definition, str) or not method.intensity_definition.strip()
    ):
        raise ValueError("定量方法必须声明强度定义。")
    keys = set()
    for parameter in method.parameters:
        if (
            not isinstance(parameter, Parameter)
            or not isinstance(parameter.key, str)
            or not ID.fullmatch(parameter.key)
            or parameter.key in keys
            or not isinstance(parameter.label, str)
            or not parameter.label.strip()
            or parameter.kind not in get_args(ParameterKind)
            or (
                parameter.kind == "observation"
                and method.kind not in {"preprocessing", "statistics"}
            )
        ):
            raise ValueError("插件参数声明不合法。")
        keys.add(parameter.key)
        if any(
            bound is not None and (type(bound) not in {int, float} or not math.isfinite(bound))
            for bound in (parameter.minimum, parameter.maximum)
        ) or (
            parameter.minimum is not None
            and parameter.maximum is not None
            and parameter.minimum > parameter.maximum
        ):
            raise ValueError("插件参数的数值范围不合法。")
        if parameter.kind == "choice" and (
            not parameter.choices
            or any(type(choice) is not str or not choice for choice in parameter.choices)
            or len(set(parameter.choices)) != len(parameter.choices)
        ):
            raise ValueError("插件枚举参数需声明互异的选项。")
        if parameter.default is not None:
            _value(parameter, parameter.default)


@dataclass(frozen=True)
class RegisteredMethod:
    id: str
    version: str
    method: Method

    def options(self, values):
        parameters = {p.key: p for p in self.method.parameters}
        if not isinstance(values, dict) or values.keys() - parameters.keys():
            raise ValueError("插件参数包含未知字段。")
        return {key: _value(p, values.get(key, p.default)) for key, p in parameters.items()}

    def observation_fields(self, options):
        return list(
            dict.fromkeys(options[p.key] for p in self.method.parameters if p.kind == "observation")
        )

    def provenance(self, options):
        return {"id": self.id, "version": self.version, "options": options}

    def view(self):
        return {
            "id": self.id,
            "version": self.version,
            "label": self.method.label,
            "kind": self.method.kind,
            "parameters": [asdict(parameter) for parameter in self.method.parameters],
        }


class MethodRegistry:
    def __init__(self, enabled=()):
        enabled = enabled_ids(enabled)
        self.bundled = frozenset(key for key in enabled if key in BUNDLED)
        self.methods = {}
        external = [key for key in enabled if key not in BUNDLED]
        if not external:
            return
        available = entry_points(group=ENTRY_POINT_GROUP)
        for key in external:
            try:
                entries = [entry for entry in available if entry.name == key]
                if len(entries) != 1:
                    raise ValueError("应恰好存在一个已安装的同名入口。")
                entry = entries[0]
                plugin = entry.load()
                if (
                    not isinstance(plugin, Plugin)
                    or type(plugin.api_version) is not int
                    or plugin.api_version != API_VERSION
                ):
                    raise ValueError("插件协议版本不兼容。")
                version = entry.dist.version
                if not isinstance(version, str) or not 0 < len(version) <= 128:
                    raise ValueError("插件安装包必须声明版本。")
                methods = {}
                for method in plugin.methods:
                    _validate_method(method)
                    identity = f"{key}:{method.id}"
                    if identity in methods:
                        raise ValueError("插件内存在重复的方法 ID。")
                    methods[identity] = RegisteredMethod(identity, version, method)
                if not methods:
                    raise ValueError("插件未声明方法。")
                self.methods.update(methods)
            except Exception as exc:
                log.warning("无法加载 scMM 插件 %s：%s", key, exc)

    def get(self, identity, *, kind=None, version=None):
        method = self.methods.get(identity)
        if method is None:
            raise ValueError(f"方法 {identity} 不可用，请检查服务器启用的插件。")
        if kind is not None and method.method.kind != kind:
            raise ValueError("该方法不适用于此步骤。")
        if version is not None and method.version != version:
            raise ValueError(f"方法 {identity} 的版本已改变，请重新选择并应用参数。")
        return method
