"""Request identity context shared without pulling web dependencies into the domain."""

from contextvars import ContextVar

actor: ContextVar[dict | None] = ContextVar("scmm_actor", default=None)
