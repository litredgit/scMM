import numpy as np
import pytest

from scMM.util.normalize import normalize


def test_quantile_ties_are_equal_and_invariant_under_cell_permutation():
    data = np.array([[0.0, 1.0], [0.0, 4.0], [0.0, 9.0]])
    result = normalize(data, "quantile")
    np.testing.assert_allclose(result, [[7 / 3, 0.5], [7 / 3, 2], [7 / 3, 4.5]])
    order = [2, 0, 1]
    np.testing.assert_allclose(normalize(data[order], "quantile")[np.argsort(order)], result)
    np.testing.assert_array_equal(normalize(np.zeros((3, 2)), "quantile"), 0)


def test_pqn_numpy_reference_is_supported_without_mutation():
    reference = np.array([0.0, 2.0, 4.0])
    original = reference.copy()
    result = normalize(
        np.array([[0.0, 2.0, 4.0], [0.0, 4.0, 8.0]]), "pqn", {"reference": reference}
    )
    np.testing.assert_array_equal(reference, original)
    np.testing.assert_allclose(result, [[0.0, 2.0, 4.0], [0.0, 2.0, 4.0]])


def test_total_normalization_preserves_zero_rows() -> None:
    data = np.array([[1.0, 3.0], [0.0, 0.0]])

    result = normalize(data, "total", {"scale": 100.0})

    np.testing.assert_allclose(result, [[25.0, 75.0], [0.0, 0.0]])


def test_max_normalization_does_not_divide_by_zero() -> None:
    data = np.array([[0.0, 0.0], [2.0, 4.0]])

    result = normalize(data, "max")

    assert np.isfinite(result).all()
    np.testing.assert_allclose(result, [[0.0, 0.0], [0.5, 1.0]])


def test_pqn_rejects_reference_with_wrong_shape() -> None:
    with pytest.raises(ValueError, match="one value per feature"):
        normalize(np.ones((2, 3)), "pqn", {"reference": [1.0, 2.0]})


def test_normalize_validates_method_and_options() -> None:
    with pytest.raises(ValueError, match="Unknown normalization method"):
        normalize(np.ones((2, 2)), "missing")
    with pytest.raises(TypeError, match="mapping"):
        normalize(np.ones((2, 2)), norm_kwargs=[])  # type: ignore[arg-type]
