import json
from urllib.parse import parse_qs

import pytest
from d3b_utils.requests_retry import Session

from kf_update_dbgap_consent.sample_status import ConsentProcessor

host = "http://localhost:5000"


def mock_dbgap(mocker):
    def sample_file(request, context):
        accession = parse_qs(request.query)["study_id"][0]
        with open(f"tests/data/{accession}.xml") as f:
            return f.read()

    mocker.get(
        "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetSampleStatus.cgi",
        text=sample_file,
    )


def load_data():
    with open("tests/data/phs999999_dataservice.json") as f:
        data = json.load(f)
    study_id = list(data["studies"].keys())[0]
    with open("tests/data/phs999999_patches.json") as f:
        expected_patches = json.load(f)
    return study_id, data, expected_patches


def clear_study(study_id):
    Session().delete(f"{host}/studies/{study_id}")


def populate_dataservice(data):
    for endpoint, entities in data.items():
        for k, v in entities.items():
            v["kf_id"] = k
            v["visible"] = True
            resp = Session().post(f"{host}/{endpoint}/", json=v)
            if resp.status_code not in {200, 201}:
                raise Exception(resp.json())


def compare(patches, expected):
    assert patches == expected
    for endpoint, entities in expected.items():
        assert entities == patches[endpoint]
        for kfid, p in entities.items():
            assert p == patches[endpoint][kfid]
            for k, v in p.items():
                assert v == patches[endpoint][kfid][k]


def test_sample_status(requests_mock):
    requests_mock._real_http = True
    mock_dbgap(requests_mock)

    study_id, data, expected_patches = load_data()

    # No study should raise a study not found exception
    clear_study(study_id)
    with pytest.raises(Exception) as e:
        ConsentProcessor(host).get_patches_for_study(study_id)
    assert f"{study_id} not found" in str(e.value)

    populate_dataservice(data)

    # Everything exists: patches should come back as expected
    patches, alerts = ConsentProcessor(host).get_patches_for_study(study_id)
    assert not alerts
    compare(patches, expected_patches)

    # A visible GF has controlled_access set to null
    Session().patch(
        f"{host}/genomic-files/GF_22222222", json={"controlled_access": None}
    )
    patches, alerts = ConsentProcessor(host).get_patches_for_study(study_id)
    assert alerts == [
        "ALERT: GF GF_22222222 is visible but has controlled_access set to null"
        " instead of True/False."
    ]

    # A hidden GF with controlled_access set to null gets empty acl
    Session().patch(
        f"{host}/genomic-files/GF_22222222", json={"visible": False}
    )
    patches, alerts = ConsentProcessor(host).get_patches_for_study(study_id)
    assert patches["genomic-files"]["GF_22222222"]["authz"] == []

    # A biospecimen is missing: patches should be absent relevant parts + alert
    Session().delete(f"{host}/biospecimens/BS_22222222")
    patches, alerts = ConsentProcessor(host).get_patches_for_study(study_id)
    new_expected_patches = {
        endpoint: {
            k: v for k, v in entities.items() if not k.endswith("22222222")
        }
        for endpoint, entities in expected_patches.items()
    }
    compare(patches, new_expected_patches)
    assert (
        data["biospecimens"]["BS_22222222"]["external_sample_id"] in alerts[0]
    )

    # An extra biospecimen: it should be hidden
    Session().post(
        f"{host}/biospecimens",
        json={
            "participant_id": "PT_11111111",
            "external_sample_id": "test_sample_4",
            "sequencing_center_id": "SC_11111111",
            "analyte_type": "DNA",
            "kf_id": "BS_44444444",
            "consent_type": "LOL",
            "dbgap_consent_code": "phs999999.c1",
        },
    )
    patches, alerts = ConsentProcessor(host).get_patches_for_study(study_id)
    new_expected_patches["biospecimens"]["BS_44444444"] = {
        "visible": False,
        "visibility_reason": "Consent Hold",
        "visibility_comment": "Sample is not registered in dbGaP",
        "consent_type": None,
        "dbgap_consent_code": None,
    }
    compare(patches, new_expected_patches)
