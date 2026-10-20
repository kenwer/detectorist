# /// script
# requires-python = ">=3.14"
# dependencies = ["onnx"]
# ///
"""Regenerate the tiny ONNX models in tests/data.

Run by hand after changing tests/tiny_models.py:

    uv run --script scripts/make_test_models.py

onnxruntime can load a model but not create one, and the onnx package is not
a project dependency, so it is declared inline above and installed into a
throwaway environment for this script only.
"""

import json
import sys
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import tiny_models  # noqa: E402


def build(path: Path, logits: list, class_names: dict, masks: list | None = None) -> None:
    """Write a model whose outputs are constants, shaped like an RF-DETR export."""
    size = tiny_models.INPUT_SIZE
    model_input = helper.make_tensor_value_info("input", TensorProto.FLOAT, [1, 3, size, size])

    constants = [("dets", tiny_models.BOXES), ("labels", logits)]
    if masks is not None:
        constants.append(("masks", masks))

    nodes, outputs = [], []
    for name, values in constants:
        batched = np.asarray(values, dtype=np.float32)[None]
        nodes.append(helper.make_node("Constant", [], [name], value=numpy_helper.from_array(batched, name + "_value")))
        outputs.append(helper.make_tensor_value_info(name, TensorProto.FLOAT, list(batched.shape)))

    graph = helper.make_graph(nodes, "tiny", [model_input], outputs)
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    # Pinned so a newer onnx package does not emit an IR version that the
    # project's onnxruntime cannot read yet.
    model.ir_version = 8
    model.metadata_props.add(key="names", value=repr(class_names))

    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def build_classifier(path: Path) -> None:
    """Write a classifier shaped like a species_export.py export, with a free batch size."""
    size = tiny_models.CLASSIFY_SIZE
    species = len(tiny_models.CLASSIFY_SPECIES)
    pixels = helper.make_tensor_value_info("pixels", TensorProto.FLOAT, ["batch", 3, size, size])
    probs = helper.make_tensor_value_info("probs", TensorProto.FLOAT, ["batch", species])

    weights = numpy_helper.from_array(np.asarray(tiny_models.CLASSIFY_WEIGHTS, dtype=np.float32), "weights")
    bias = numpy_helper.from_array(np.asarray(tiny_models.CLASSIFY_BIAS, dtype=np.float32), "bias")
    nodes = [
        helper.make_node("ReduceMean", ["pixels"], ["channel_means"], axes=[2, 3], keepdims=0),
        helper.make_node("MatMul", ["channel_means", "weights"], ["scores"]),
        helper.make_node("Add", ["scores", "bias"], ["logits"]),
        helper.make_node("Softmax", ["logits"], ["probs"], axis=1),
    ]

    graph = helper.make_graph(nodes, "tiny-classify", [pixels], [probs], initializer=[weights, bias])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = 8
    model.metadata_props.add(key="names", value=repr(tiny_models.CLASSIFY_SPECIES))
    model.metadata_props.add(key="classifier", value=json.dumps({
        "size": size,
        "margin": tiny_models.CLASSIFY_MARGIN,
        "fill": tiny_models.CLASSIFY_FILL,
        "input": "RGB 0..1 NCHW",
        "genera": tiny_models.CLASSIFY_GENERA,
        "families": tiny_models.CLASSIFY_FAMILIES,
        "genus_of": tiny_models.CLASSIFY_GENUS_OF,
        "family_of": tiny_models.CLASSIFY_FAMILY_OF,
    }))

    path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(path))
    print(f"wrote {path} ({path.stat().st_size} bytes)")


def main() -> None:
    build(tiny_models.DETECT_MODEL, tiny_models.DETECT_LOGITS, tiny_models.DETECT_CLASS_NAMES)
    build(tiny_models.SEG_MODEL, tiny_models.SEG_LOGITS, tiny_models.SEG_CLASS_NAMES, masks=tiny_models.mask_logits())
    build_classifier(tiny_models.CLASSIFY_MODEL)


if __name__ == "__main__":
    main()
