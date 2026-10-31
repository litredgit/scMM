"""Internal immutable source catalogue; not connected to user-facing persistence yet."""

from copy import deepcopy
from uuid import uuid4

from scMM.ion.contracts import MeasurementRoot, validate_schema
from scMM.ion.identity import axis_identity, dataset_identity, json_identity
from scMM.ion.semantics import value_states, write_value_states

from .workbench import AnalysisWorkspace


class DataViewCatalog:
    """Own roots and isolated analysis branches until complete project storage is available."""

    def __init__(self):
        self._roots = {}
        self._views = {}
        self._branches = {}
        self.active_branch_id = None
        self.revision = 0
        self.registry = {"grouping": {}, "annotation": {}, "evidence": {}, "reviews": []}
        self.source_matrices = {}
        self.project_presentation = {}

    def add_measurement(self, data, *, source, origin_kind, value_semantics):
        root_id, view_id, branch_id = (uuid4().hex for _ in range(3))
        root = MeasurementRoot.create(
            data,
            root_id=root_id,
            source=source,
            origin_kind=origin_kind,
            value_semantics=value_semantics,
        )
        branch = AnalysisWorkspace()
        measured = root.data
        states = value_states(measured)
        states["X"] = {**states["X"], "space": value_semantics}
        write_value_states(measured, states)
        branch.replace(measured, source=str(source.get("kind", "")))
        view = {
            "schema_version": 1,
            "id": view_id,
            "root_id": root_id,
            "root_identity": root.identity,
            "level": "L0",
            "variable_kind": "feature",
            "cell_ids": list(data.obs_names),
            "feature_ids": list(data.var_names),
        }
        self._roots[root_id] = root
        self._views[view_id] = view
        self._branches[branch_id] = {"view_id": view_id, "workspace": branch}
        self.active_branch_id = branch_id
        self.revision += 1
        return deepcopy(view), branch_id

    @property
    def workspace(self):
        if self.active_branch_id is None:
            raise ValueError("no active analysis branch")
        from .analysis_inputs import bind_analysis_input

        entry = self._branches[self.active_branch_id]
        bind_analysis_input(
            entry["workspace"], self._views[entry["view_id"]], self.active_branch_id
        )
        return entry["workspace"]

    def measurement(self, root_id):
        return self._roots[root_id].data

    def views(self):
        return deepcopy(list(self._views.values()))

    def create_feature_view(self, *, root_id, cell_ids, feature_ids, expected_revision):
        """Create an L0 selection branch, preserving IDs and the full immutable root."""
        self._check_revision(expected_revision)
        root = self._roots[root_id]
        data = root.data
        cells, features = list(cell_ids), list(feature_ids)
        for ids, axis in ((cells, data.obs_names), (features, data.var_names)):
            if not ids or len(ids) != len(set(ids)) or not set(ids).issubset(set(axis)):
                raise ValueError("selection contains empty, duplicate or unknown IDs")
        selected = data[cells, features].copy()
        from scMM.util.lifecycle import invalidate_derived

        invalidate_derived(selected)
        states = value_states(selected)
        states["X"] = {**states["X"], "space": root.value_semantics}
        write_value_states(selected, states)
        branch = AnalysisWorkspace()
        branch.replace(selected, source="measurement_selection")
        view_id, branch_id = uuid4().hex, uuid4().hex
        view = {
            "schema_version": 1,
            "id": view_id,
            "root_id": root_id,
            "root_identity": root.identity,
            "level": "L0",
            "variable_kind": "feature",
            "cell_ids": cells,
            "feature_ids": features,
        }
        self._views[view_id] = view
        self._branches[branch_id] = {"view_id": view_id, "workspace": branch}
        self.revision += 1
        return deepcopy(view), branch_id

    def activate(self, branch_id, *, expected_revision):
        self._check_revision(expected_revision)
        target = self._branches[branch_id]
        view = self._views[target["view_id"]]
        validate_schema(view)
        root = self._roots.get(view["root_id"])
        if root is not None:
            root.validate()
        if root is None and view.get("root_available", True):
            raise ValueError("missing measurement root")
        if root is not None and root.identity != view["root_identity"]:
            raise ValueError("view source identity changed")
        target["workspace"]._validate(target["workspace"].require_data())
        self.active_branch_id = branch_id
        self.revision += 1

    def _check_revision(self, expected):
        if expected != self.revision:
            raise ValueError("stale data catalogue revision")

    def identity(self):
        """Include inactive changes in the catalogue's dirty identity."""
        return (
            self.revision,
            self.active_branch_id,
            tuple(
                (key, value["workspace"].token, dataset_identity(value["workspace"].require_data()))
                for key, value in sorted(self._branches.items())
            ),
        )

    def export_state(self):
        """Built-in containers only; maintenance/storage choose their own model policy."""
        from .analysis_inputs import bind_analysis_input

        for branch_id, entry in self._branches.items():
            bind_analysis_input(entry["workspace"], self._views[entry["view_id"]], branch_id)
        return {
            "schema_version": 1,
            "roots": {
                key: {"metadata": root.metadata(), "data": root.data}
                for key, root in self._roots.items()
            },
            "views": deepcopy(self._views),
            "branches": {
                key: {
                    **deepcopy(
                        {field: value for field, value in entry.items() if field != "workspace"}
                    ),
                    "workspace": deepcopy(vars(entry["workspace"])),
                }
                for key, entry in self._branches.items()
            },
            "active_branch_id": self.active_branch_id,
            "revision": self.revision,
            "project_presentation": deepcopy(self.project_presentation),
            "registry": deepcopy(self.registry),
            "source_matrices": {key: data.copy() for key, data in self.source_matrices.items()},
        }

    @classmethod
    def from_state(cls, state):
        validate_schema(state)
        candidate = cls()
        candidate.project_presentation = deepcopy(state.get("project_presentation", {}))
        candidate.registry = deepcopy(
            state.get("registry", {"grouping": {}, "annotation": {}, "evidence": {}, "reviews": []})
        )
        json_identity(candidate.registry)
        candidate.source_matrices = {
            key: data.copy() for key, data in state.get("source_matrices", {}).items()
        }
        for key, record in state["roots"].items():
            meta = record["metadata"]
            validate_schema(meta)
            if key != meta["id"]:
                raise ValueError("root namespace mismatch")
            root = MeasurementRoot.create(
                record["data"],
                root_id=key,
                source=meta["source"],
                origin_kind=meta["origin_kind"],
                value_semantics=meta["value_semantics"],
            )
            if root.identity != meta["identity"]:
                raise ValueError("root identity mismatch")
            candidate._roots[key] = root
        candidate._views = deepcopy(state["views"])
        if not set(candidate.source_matrices).issubset(candidate._views):
            raise ValueError("source matrix references unknown view")
        for key, view in candidate._views.items():
            validate_schema(view)
            if view.get("level") not in {"L0", "L1", "L2"} or view.get("variable_kind") != (
                "empirical_compound" if view["level"] == "L2" else "feature"
            ):
                raise ValueError("view variable type conflicts with representation level")
            axis_identity(view["cell_ids"])
            axis_identity(view.get("variable_ids", view["feature_ids"]))
            axis_identity(view["feature_ids"])
            root = candidate._roots.get(view["root_id"])
            if root is None and (
                view.get("root_available", True)
                or view.get("level") != "L2"
                or view.get("variable_kind") != "empirical_compound"
            ):
                raise ValueError("missing measurement root")
            if view.get("level") == "L2" and key not in candidate.source_matrices:
                raise ValueError("missing complete compound source")
            if key != view["id"] or (root is not None and view["root_identity"] != root.identity):
                raise ValueError("view identity mismatch")
            if root is not None and (
                not set(view["cell_ids"]).issubset(set(root.data.obs_names))
                or not set(view["feature_ids"]).issubset(set(root.data.var_names))
            ):
                raise ValueError("view axis outside measurement root")
            if (
                key in candidate.source_matrices
                and dataset_identity(candidate.source_matrices[key], allow_missing=True)
                != view["source_identity"]
            ):
                raise ValueError("source view identity changed")
            if key in candidate.source_matrices:
                source = candidate.source_matrices[key]
                if list(source.obs_names) != view["cell_ids"] or list(source.var_names) != view.get(
                    "variable_ids", view["feature_ids"]
                ):
                    raise ValueError("source matrix axes differ from its view")
        for key, entry in state["branches"].items():
            branch = AnalysisWorkspace()
            if set(entry["workspace"]) != set(vars(branch)):
                raise ValueError("invalid analysis branch fields")
            branch.__dict__.update(deepcopy(entry["workspace"]))
            branch._validate(branch.require_data())
            branch._validate(branch._original)
            if entry["view_id"] not in candidate._views:
                raise ValueError("unknown source view")
            view = candidate._views[entry["view_id"]]
            branch_cells = entry.get("materialization", {}).get("cell_ids", view["cell_ids"])
            branch_variables = entry.get("materialization", {}).get(
                "variable_ids", view.get("variable_ids", view["feature_ids"])
            )
            if (
                list(branch._original.obs_names) != branch_cells
                or list(branch._original.var_names) != branch_variables
                or not set(branch.data.obs_names).issubset(set(view["cell_ids"]))
                or not set(branch.data.var_names).issubset(
                    set(view.get("variable_ids", view["feature_ids"]))
                )
            ):
                raise ValueError("analysis branch axes differ from its source view")
            if any(
                item["workspace"].dataset_id == branch.dataset_id
                for item in candidate._branches.values()
            ):
                raise ValueError("analysis branches must have distinct dataset identities")
            candidate._branches[key] = {**deepcopy(entry), "workspace": branch}
        if (
            state["active_branch_id"] is not None
            and state["active_branch_id"] not in candidate._branches
        ):
            raise ValueError("unknown active branch")
        if type(state["revision"]) is not int or state["revision"] < 0:
            raise ValueError("invalid catalogue revision")
        candidate.active_branch_id = state["active_branch_id"]
        candidate.revision = state["revision"]
        return candidate


def initialize_catalog(project, data, *, source, origin_kind, linearity, preserve_active=False):
    """Internal opt-in; ordinary extraction/import remains unchanged until S7."""
    if project.ion_state is not None:
        raise ValueError("measurement catalogue already initialized")
    catalog = DataViewCatalog()
    view, branch_id = catalog.add_measurement(
        data, source=source, origin_kind=origin_kind, value_semantics=linearity
    )
    if preserve_active:
        existing = project.workspace
        if existing.data is None or dataset_identity(existing._original) != dataset_identity(data):
            raise ValueError("preserving analysis requires the exact preprocessing baseline")
        preserved = deepcopy(existing)
        catalog._branches[branch_id]["workspace"] = preserved
        catalog._branches[branch_id]["presentation"] = deepcopy(
            {
                "views": project.views,
                "saved_reports": project.saved_reports,
                "saved_token": project.saved_token,
                "report_token": project.report_token,
            }
        )
        from scMM.ion.annotation import migrate_lipid_version
        from scMM.util.lipid_annotation import annotation_store

        legacy = annotation_store(existing.data)
        if legacy["versions"]:
            catalog.registry["legacy_annotations"] = {
                row["id"]: migrate_lipid_version(row) for row in legacy["versions"]
            }
    state = catalog.export_state()
    DataViewCatalog.from_state(state)
    project.ion_state = state
    project.workspace = catalog.workspace
    if not preserve_active:
        project.saved_reports = {}
        project.views = {}
        project.saved_token = None
        project.report_token = None
    project.dirty = True
    return view, branch_id


def freeze_active_branch(project):
    """Freeze live active fields before reconstructing a transactional catalogue."""
    if project.ion_state is None:
        raise ValueError("measurement catalogue is not initialized")
    state = deepcopy(project.ion_state)
    if state["active_branch_id"] is None:
        state["project_presentation"] = {"views": deepcopy(project.views)}
        return state
    entry = state["branches"][state["active_branch_id"]]
    entry["workspace"] = deepcopy(vars(project.workspace))
    entry["presentation"] = deepcopy(
        {
            "saved_reports": project.saved_reports,
            "views": project.views,
            "saved_token": project.saved_token,
            "report_token": project.report_token,
        }
    )
    return state


def activate_view(project, view_id, *, branch_id=None, expected_catalog_revision):
    """Publish all active compatibility fields together after candidate validation."""
    frozen = freeze_active_branch(project)
    catalog = DataViewCatalog.from_state(frozen)
    matches = [key for key, entry in catalog._branches.items() if entry["view_id"] == view_id]
    if branch_id is None:
        if len(matches) != 1:
            raise ValueError("select an explicit analysis branch")
        branch_id = matches[0]
    if branch_id not in matches:
        raise ValueError("analysis branch belongs to another view")
    catalog.activate(branch_id, expected_revision=expected_catalog_revision)
    state = catalog.export_state()
    for key, entry in state["branches"].items():
        entry["presentation"] = deepcopy(frozen["branches"][key].get("presentation", {}))
    presentation = state["branches"][branch_id]["presentation"]
    project.ion_state = state
    project.workspace = catalog.workspace
    project.saved_reports = presentation.get("saved_reports", {})
    project.views = presentation.get("views", {})
    project.saved_token = presentation.get("saved_token")
    project.report_token = presentation.get("report_token")
    project.dirty = True


def add_source_view(
    project, data, *, root_id, level, source_features=None, grouping_id=None, quantification_id=None
):
    """Register an immutable derived source; incomplete L2 is never auto-filled."""
    import numpy as np

    state = freeze_active_branch(project)
    catalog = DataViewCatalog.from_state(state)
    if level not in {"L1", "L2"} or min(data.shape) < 1:
        raise ValueError("nonempty L1 or L2 source required")
    root = catalog._roots[root_id]
    features = list(data.var_names) if level == "L1" else list(source_features or [])
    if not set(features).issubset(set(root.data.var_names)) or not set(data.obs_names).issubset(
        set(root.data.obs_names)
    ):
        raise ValueError("derived source is outside measurement root")
    values = data.X.toarray() if hasattr(data.X, "toarray") else np.asarray(data.X)
    if np.isinf(values).any():
        raise ValueError("source contains infinite values")
    if level == "L2":
        available = data.layers["scmm_quantifiable"]
        mask = available.toarray() if hasattr(available, "toarray") else np.asarray(available)
        if mask.dtype.kind != "b" or not np.array_equal(~mask, np.isnan(values)):
            raise ValueError("source availability differs from missing measurements")
    elif not np.isfinite(values).all():
        raise ValueError("L1 feature source must be finite")
    view_id = uuid4().hex
    view = {
        "schema_version": 1,
        "id": view_id,
        "root_id": root_id,
        "root_identity": root.identity,
        "root_available": True,
        "level": level,
        "variable_kind": "feature" if level == "L1" else "empirical_compound",
        "cell_ids": list(data.obs_names),
        "feature_ids": features,
        "variable_ids": list(data.var_names),
        "source_identity": dataset_identity(data, allow_missing=True),
        "grouping_id": grouping_id,
        "quantification_id": quantification_id,
    }
    catalog._views[view_id] = view
    catalog.source_matrices[view_id] = data.copy()
    branch_id = None
    if np.isfinite(values).all():
        branch_id = uuid4().hex
        workspace = AnalysisWorkspace()
        workspace.replace(data, source=f"view:{view_id}")
        catalog._branches[branch_id] = {
            "view_id": view_id,
            "workspace": workspace,
            "presentation": {},
        }
    catalog.revision += 1
    exported = catalog.export_state()
    DataViewCatalog.from_state(exported)
    project.ion_state = exported
    project.dirty = True
    return deepcopy(view), branch_id


def materialize_analysis_branch(project, *, view_id, preview):
    from scMM.ion.representation import materialize_complete_availability

    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    view = catalog._views[view_id]
    source = catalog.source_matrices[view_id]
    selected = materialize_complete_availability(source, preview)
    workspace = AnalysisWorkspace()
    workspace.replace(selected, source=f"view:{view_id}")
    branch_id = uuid4().hex
    catalog._branches[branch_id] = {
        "view_id": view["id"],
        "workspace": workspace,
        "materialization": deepcopy(preview),
        "presentation": {},
    }
    catalog.revision += 1
    state = catalog.export_state()
    DataViewCatalog.from_state(state)
    project.ion_state = state
    project.dirty = True
    return branch_id


def replace_measurement(project, data, *, source, origin_kind):
    """Retain earlier roots/branches when a new approved measurement replaces current data."""
    if project.ion_state is None:
        project.workspace.replace(data, source=source)
        return
    catalog = DataViewCatalog.from_state(freeze_active_branch(project))
    semantic = value_states(data)["X"]["space"]
    catalog.add_measurement(
        data, source={"kind": source}, origin_kind=origin_kind, value_semantics=semantic
    )
    project.ion_state = catalog.export_state()
    project.workspace = catalog.workspace
    project.saved_reports = {}
    project.views = {}
    project.saved_token = None
    project.report_token = None
    project.dirty = True
