"""Versioned module exchange requests; uploaded paths never address server files."""

from typing import Literal

from pydantic import Field

from .schemas import RevisionRequest

ModuleName = Literal["extraction", "annotation", "statistics"]
ExchangeFormat = Literal["package", "h5ad", "matrix_csv", "feature_csv"]


class ExchangeImport(RevisionRequest):
    format: ExchangeFormat
    filename: str = Field(default="upload", min_length=1, max_length=255)
    file_base64: str = Field(default="", max_length=280_000_000)
    matrix_csv: str = Field(default="", max_length=100_000_000)
    observations_csv: str = Field(default="", max_length=20_000_000)
    features_csv: str = Field(default="", max_length=20_000_000)
    orientation: Literal["observations_rows", "observations_columns"] = "observations_rows"
    observation_kind: Literal["cell", "sample"] = "cell"
