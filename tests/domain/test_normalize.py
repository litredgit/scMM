import numpy as np
import pytest

from scMM.util.normalize import normalize


def test_quantile_ties_are_equal_and_invariant_under_cell_permutation():
    data = np.array([[0.0, 0.0, 6.0], [2.0, 4.0, 8.0], [0.0, 0.0, 0.0]])
    result = normalize(data, "quantile")
    np.testing.assert_allclose(result, [[1.5, 1.5, 7], [1, 2, 7], [0, 0, 0]])
    order = [2, 0, 1]
    np.testing.assert_allclose(normalize(data[order], "quantile")[np.argsort(order)], result)
    np.testing.assert_array_equal(normalize(np.zeros((3, 2)), "quantile"), 0)


def test_pqn_sparse_detection_reference_and_counts():
    from scMM.util.normalize import pqn_with_counts

    values = np.array([[2, 0, 0], [0, 6, 0], [0, 0, 8], [4, 0, 0], [0, 0, 0]])
    output, counts = pqn_with_counts(values, {"reference": "median"})
    np.testing.assert_allclose(output, [[3, 0, 0], [0, 6, 0], [0, 0, 8], [3, 0, 0], [0, 0, 0]])
    np.testing.assert_array_equal(counts, [1, 1, 1, 1, 0])
    with pytest.raises(ValueError, match="共同检出"):
        pqn_with_counts(values, {"reference": [1, 0, 0]})


@pytest.mark.parametrize("method", ["pqn", "log"])
def test_abundance_transforms_reject_negative_input_and_keep_zero(method):
    with pytest.raises(ValueError, match="非负"):
        normalize([[1, -0.1]], method)
    assert normalize([[0, 1]], method)[0, 0] == 0


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
