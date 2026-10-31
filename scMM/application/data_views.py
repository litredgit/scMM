"""Internal immutable source catalogue; not connected to user-facing persistence yet."""

from copy import deepcopy
from uuid import uuid4

from scMM.ion.contracts import MeasurementRoot, validate_schema
from scMM.ion.identity import dataset_identity
from scMM.ion.semantics import unknown_state, value_states, write_value_states

from .workbench import AnalysisWorkspace


class DataViewCatalog:
    """Own roots and isolated analysis branches until complete project storage is available."""

    def __init__(self):
        self._roots = {}
        self._views = {}
        self._branches = {}
        self.active_branch_id = None
        self.revision = 0

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
        states["X"] = {**unknown_state(), "space": value_semantics}
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
        return self._branches[self.active_branch_id]["workspace"]

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
        states = value_states(selected)
        states["X"] = {**unknown_state(), "space": root.value_semantics}
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
        root = self._roots[view["root_id"]]
        root.validate()
        if root.identity != view["root_identity"]:
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
        return {
            "schema_version": 1,
            "roots": {
                key: {"metadata": root.metadata(), "data": root.data}
                for key, root in self._roots.items()
            },
            "views": deepcopy(self._views),
            "branches": {
                key: {"view_id": entry["view_id"], "workspace": deepcopy(vars(entry["workspace"]))}
                for key, entry in self._branches.items()
            },
            "active_branch_id": self.active_branch_id,
            "revision": self.revision,
        }

    @classmethod
    def from_state(cls, state):
        validate_schema(state)
        candidate = cls()
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
        for key, view in candidate._views.items():
            validate_schema(view)
            root = candidate._roots[view["root_id"]]
            if key != view["id"] or view["root_identity"] != root.identity:
                raise ValueError("view identity mismatch")
            if not set(view["cell_ids"]).issubset(set(root.data.obs_names)) or not set(
                view["feature_ids"]
            ).issubset(set(root.data.var_names)):
                raise ValueError("view axis outside measurement root")
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
            if (
                list(branch._original.obs_names) != view["cell_ids"]
                or list(branch._original.var_names) != view["feature_ids"]
                or not set(branch.data.obs_names).issubset(set(view["cell_ids"]))
                or not set(branch.data.var_names).issubset(set(view["feature_ids"]))
            ):
                raise ValueError("analysis branch axes differ from its source view")
            if any(
                item["workspace"].dataset_id == branch.dataset_id
                for item in candidate._branches.values()
            ):
                raise ValueError("analysis branches must have distinct dataset identities")
            candidate._branches[key] = {"view_id": entry["view_id"], "workspace": branch}
        if state["active_branch_id"] not in candidate._branches:
            raise ValueError("unknown active branch")
        if type(state["revision"]) is not int or state["revision"] < 0:
            raise ValueError("invalid catalogue revision")
        candidate.active_branch_id = state["active_branch_id"]
        candidate.revision = state["revision"]
        return candidate


def initialize_catalog(project, data, *, source, origin_kind, linearity):
    """Internal opt-in; ordinary extraction/import remains unchanged until S7."""
    if project.ion_state is not None:
        raise ValueError("measurement catalogue already initialized")
    catalog = DataViewCatalog()
    view, branch_id = catalog.add_measurement(
        data, source=source, origin_kind=origin_kind, value_semantics=linearity
    )
    state = catalog.export_state()
    project.ion_state = state
    project.workspace = catalog.workspace
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
