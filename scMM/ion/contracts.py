"""Versioned domain contracts; no HTTP types or implicit provenance inference."""

from copy import deepcopy
from dataclasses import dataclass, field

import numpy as np

from .identity import dataset_identity, json_identity

VALUE_SEMANTICS = frozenset(
    {"linear_abundance", "log_abundance", "standard_score", "other", "unknown"}
)
ORIGIN_KINDS = frozenset({"extraction", "imported_feature", "composite"})


def validate_schema(record):
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise ValueError("unsupported ion schema version")


@dataclass(frozen=True)
class MeasurementRoot:
    """Owned snapshot; callers receive copies, never the root's mutable arrays."""

    id: str
    origin_kind: str
    value_semantics: str
    identity: str
    _data: object = field(repr=False, compare=False)
    _source: dict = field(repr=False, compare=False)

    @classmethod
    def create(cls, data, *, root_id, source, origin_kind, value_semantics):
        if not isinstance(root_id, str) or not root_id:
            raise ValueError("root ID is required")
        if origin_kind not in ORIGIN_KINDS or value_semantics not in VALUE_SEMANTICS:
            raise ValueError("invalid root origin or value semantics")
        if min(data.shape) < 1:
            raise ValueError("measurement root must be nonempty")
        if not isinstance(source, dict):
            raise ValueError("measurement source must be a mapping")
        if "mz" not in data.var:
            raise ValueError("feature root requires measured m/z metadata")
        masses = np.asarray(data.var["mz"], dtype=float)
        if not np.isfinite(masses).all() or (masses <= 0).any():
            raise ValueError("feature m/z must be finite and positive")
        json_identity(source)
        candidate = data.copy()
        return cls(
            root_id,
            origin_kind,
            value_semantics,
            dataset_identity(candidate),
            candidate,
            deepcopy(source),
        )

    @property
    def data(self):
        self.validate()
        return self._data.copy()

    @property
    def source(self):
        return deepcopy(self._source)

    def validate(self):
        if dataset_identity(self._data) != self.identity:
            raise ValueError("measurement root identity changed")

    def metadata(self):
        return {
            "schema_version": 1,
            "id": self.id,
            "origin_kind": self.origin_kind,
            "value_semantics": self.value_semantics,
            "identity": self.identity,
            "source": self.source,
        }
