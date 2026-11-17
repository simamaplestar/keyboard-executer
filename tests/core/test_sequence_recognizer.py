import base64
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from keyboard_executor.core.ai.provider import AiAborted, ChatResult


def parse(text, ids={8}):
    from keyboard_executor.core.ai.sequence_recognizer import parse_sequence_readings
    return parse_sequence_readings(text, ids)


def test_ids_and_normalization():
    rows = parse('{"readings":[{"sample_id":8,"index":3,"char":"p"}]}')
    assert [(r.sample_id, r.index, r.char) for r in rows] == [(8, 3, "P")]


@pytest.mark.parametrize("rows", [[], [{"sample_id":9,"index":3,"char":"P"}],
    [{"sample_id":8,"index":True,"char":"P"}], [{"sample_id":8,"index":1,"char":"Ｐ"}],
    [{"sample_id":8,"index":1,"char":None}], [{"sample_id":8,"index":1,"char":"PP"}],
    [{"sample_id":8,"index":1,"char":"P","action":"click"}],
    [{"sample_id":8,"index":1,"char":"P"}]*2])
def test_invalid_or_foreign_readings(rows):
    with pytest.raises(ValueError): parse(json.dumps({"readings": rows}))


@pytest.mark.parametrize("raises", [False, True])
def test_request_sends_only_crop_and_cleans_files(raises):
    from keyboard_executor.core.ai.sequence_recognizer import SequenceRecognizer, SequenceSample
    paths = []
    def stream(messages, **kwargs):
        assert kwargs["tools"] == []
        image = messages[0]["images"][0]
        paths.append(Path(image["path"]))
        assert paths[0].read_bytes() == base64.b64decode(image["data"])
        assert image["name"] == "sample-8.png"
        if raises: raise RuntimeError("offline")
        return ChatResult('{"readings":[{"sample_id":8,"index":null,"char":null}]}')
    recognizer = SequenceRecognizer(SimpleNamespace(stream_chat=stream))
    sample = SequenceSample(8, np.zeros((20, 30, 3), np.uint8))
    if raises:
        with pytest.raises(RuntimeError): recognizer.recognize([sample], should_abort=lambda: False)
    else:
        assert recognizer.recognize([sample], should_abort=lambda: False)[0].index is None
    assert paths and not paths[0].exists()


def test_pre_cancel_does_not_call_provider():
    from keyboard_executor.core.ai.sequence_recognizer import SequenceRecognizer
    with pytest.raises(AiAborted):
        SequenceRecognizer(None).recognize([], should_abort=lambda: True)
