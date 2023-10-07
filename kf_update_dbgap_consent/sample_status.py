"""
## ACL Definitions

* study_phs: (e.g. "phs001138")
* consent_acl: f"/programs/{study_phs}.c{consent_code}" (consent_code for the specimen)
* default_acl: unique([{consent_acl} from visible biospecimens which contribute to the genomic file])
* open_acl: ["/open"]

## ACL Rules

* The tool should discover and use the latest version of the study’s sample
  status file that has status "released". (e.g. if phsXXX.*v1.p2* is marked as
  released and phsXXX.*v2.p1* exists and is not yet marked released, use
  phsXXX.*v1.p2*)

* The Study entity in the dataservice should have its version set to the
  version found in the used sample status file.

* For all samples in the sample status file which are not found in the
  dataservice, **return or display an alert**.

* Dataservice biospecimens whose samples are found in the sample status file
  with status "Loaded" should have their `consent_type` and
  `dbgap_consent_code` fields set as indicated in the file.

* All other dataservice biospecimens should be hidden in the dataservice and
  their `consent_type` and `dbgap_consent_code` fields should be set to `null`.

* If a biospecimen is hidden in the dataservice, its descendants (genomic
  files, read groups, etc) should also be hidden.

* All visible genomic files in the dataservice with their
  controlled_access field set to **null** should **return or display a QC
  failure alert**.

* All visible genomic files in the dataservice with their `controlled_access`
field set to **False** should get `{open_acl}`.

* All visible genomic files in the dataservice with their `controlled_access`
field set to **True** should get the `{default_acl}`. If the genomic file
previously had an ACL containing the study KF ID, this will be replaced with
the `{default_acl}` containing the PHS ID.

* The `default_acl` is the unique set of the `consent_acl` from the visible
specimens in the study which contribute to the genomic_file.

* The `consent_acl` is composed of the study phs ID and the
reported sample consent code of the sample, prepended with the dbgap
prefix "/programs" (e.g. "/programs/phs001138.c1")

* All other genomic files in the dataservice should get `{empty_acl}`
indicating no access.


"""
from pprint import pprint
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from d3b_utils.requests_retry import Session

from kf_utils.dataservice.descendants import find_descendants_by_kfids
from kf_utils.dataservice.scrape import yield_entities
from kf_utils.dbgap.release import get_latest_sample_status


def is_localhost(url):
    hosts = {"localhost", "127.0.0.1"}
    return any(hostname in url for hostname in hosts)


class ConsentProcessor:
    def __init__(self, api_url, db_url=None):
        self.api_url = api_url
        self.db_url = db_url

    def _link(self, e, field):
        return e["_links"][field].rsplit("/", 1)[1]

    def get_accession(self, study_id):
        resp = Session().get(f"{self.api_url}/studies/{study_id}")
        if resp.status_code != 200:
            raise Exception(f"Study {study_id} not found in dataservice")
        study = resp.json()["results"]

        if study.get("data_access_authority", "").lower() == "dbgap":
            return study["external_id"], study["version"]
        else:
            raise Exception(
                f"data_access_authority for study {study_id} is not 'dbGaP'"
            )

    def get_patches_for_study(
        self, study_id, dbgap_status="released", match_aliquot=False
    ):
        if match_aliquot:
            match_entity = "external_aliquot_id"
        else:
            match_entity = "external_sample_id"
        print("Looking up dbGaP accession ID")
        study_phs, study_version = self.get_accession(study_id)
        print(f"Found accession ID: {study_phs}")
        open_acl = {"/open"}
        empty_acl = set()
        default_acl = [study_id]
        alerts = []
        patches = defaultdict(lambda: defaultdict(dict))

        """
        Rule: The tool should discover and use the latest version of the
        study’s sample status file that has status "released".
        """
        released_accession, study = get_latest_sample_status(
            study_phs, dbgap_status
        )
        released_version = released_accession.split(".", 1)[1]

        """
        Rule: The Study entity in the dataservice should have its version set to
        the version found in the used sample status file
        """
        if study_version != released_version:
            patches["studies"][study_id] = {"version": released_version}

        dbgap_samples = {
            s["@submitted_sample_id"]: s for s in study["SampleList"]["Sample"]
        }

        storage = defaultdict(dict)
        gfids_bsids = defaultdict(set)

        if self.db_url:
            print("Querying the database...")
            storage = find_descendants_by_kfids(
                self.db_url,
                "studies",
                [study_id],
                False,
                kfids_only=False,
            )
            for e in storage["biospecimen-genomic-files"].values():
                bsid = e["biospecimen_id"]
                gfid = e["genomic_file_id"]
                gfids_bsids[gfid].add(bsid)
        else:
            print("Scraping the dataservice...")
            with ThreadPoolExecutor() as tpex:

                def entities_dict(endpoint, filt):
                    return {
                        e["kf_id"]: e
                        for e in yield_entities(
                            self.api_url, endpoint, filt, True
                        )
                    }

                futures = {
                    tpex.submit(entities_dict, endpoint, filt): endpoint
                    for endpoint, filt in [
                        ("biospecimens", {"study_id": study_id}),
                        ("biospecimen-genomic-files", {"study_id": study_id}),
                        ("genomic-files", {"study_id": study_id}),
                    ]
                }
                for f in as_completed(futures):
                    storage[futures[f]].update(f.result())
            print()
            for e in storage["biospecimen-genomic-files"].values():
                bsid = self._link(e, "biospecimen")
                gfid = self._link(e, "genomic_file")
                gfids_bsids[gfid].add(bsid)

        hidden_specimens = {
            k: e for k, e in storage["biospecimens"].items() if not e["visible"]
        }
        hidden_genomic_files = set(
            k for k, e in storage["genomic-files"].items() if not e["visible"]
        )
        print("**************")
        for entity, entities in storage.items():
            print(f"*** {entity} count: {len(entities)}")

        """
        Rule: For all samples in the sample status file which are not found in
        the dataservice, return or display an alert.
        """
        specimen_extids = set(
            bs[match_entity] for bs in storage["biospecimens"].values()
        )
        for extid, s in dbgap_samples.items():
            if (s["@dbgap_status"] == "Loaded") and (
                extid not in specimen_extids
            ):
                alerts.append(
                    f"ALERT: sample {extid} from dbGaP not found in dataservice"
                )
                print(alerts[-1])

        """
        Rule: Biospecimens whose samples are found in the sample status file
        with status "Loaded" should have their consent_type dbgap_consent_code
        fields set as indicated in the file.

        All other biospecimens should be hidden in the dataservice and their
        "consent_type" and "dbgap_consent_code" fields should be set to null.
        """
        for kfid, bs in storage["biospecimens"].items():
            sample = dbgap_samples.get(bs[match_entity], {})
            if sample.get("@dbgap_status") == "Loaded":
                patches["biospecimens"][kfid] = {
                    "consent_type": sample["@consent_short_name"],
                    "dbgap_consent_code": f"{study_phs}.c{sample['@consent_code']}",
                }
            else:
                patches["biospecimens"][kfid] = {
                    "consent_type": None,
                    "dbgap_consent_code": None,
                    "visible": False,
                    "visibility_reason": "Consent Hold",
                    "visibility_comment": "Sample is not registered in dbGaP",
                }
                hidden_specimens[kfid] = bs

        """
        Rule: If a biospecimen is hidden in the dataservice, its descendants
        should also be hidden.
        """
        if hidden_specimens:
            descendants_of_hidden_specimens = find_descendants_by_kfids(
                self.db_url or self.api_url,
                "biospecimens",
                list(hidden_specimens.keys()),
                ignore_gfs_with_hidden_external_contribs=False,
                kfids_only=False,
            )
            descendants_of_hidden_specimens["biospecimens"] = hidden_specimens
            for endpoint, entities in descendants_of_hidden_specimens.items():
                for k, e in entities.items():
                    storage[endpoint][k] = e
                    patches[endpoint][k]["visible"] = False
                    patches[endpoint][k]["visibility_reason"] = "Consent Hold"
                    patches[endpoint][k][
                        "visibility_comment"
                    ] = "Sample is not registered in dbGaP"
                    if endpoint == "genomic-files":
                        hidden_genomic_files.add(k)

        print()

        # ACLs
        for gfid, bsids in gfids_bsids.items():
            all_biospecimens_visible = all(
                [k not in hidden_specimens for k in bsids]
            )
            gf_visible = gfid not in hidden_genomic_files
            controlled_access = storage["genomic-files"][gfid][
                "controlled_access"
            ]
            # GenomicFile visible = True and
            # all contributing Biospecimen visible = True
            if gf_visible and all_biospecimens_visible:
                if controlled_access == None:
                    """
                    Rule: All visible genomic files in the dataservice with
                    their controlled_access field set to **null** should
                    **return or display a QC failure alert**.
                    """
                    alerts.append(
                        f"ALERT: GF {gfid} is visible but has controlled_access"
                        " set to null instead of True/False."
                    )
                    print(alerts[-1])
                elif controlled_access == False:
                    """
                    Rule: All visible genomic files in the dataservice with
                    their `controlled_access` field set to **False** should get
                    `{open_acl}`.
                    """
                    patches["genomic-files"][gfid].update(
                        {"authz": sorted(open_acl)}
                    )
                elif controlled_access == True:
                    """
                    Rule: All visible genomic files in the dataservice with
                    their `controlled_access` field set to **True** should get
                    the `{default_acl}`.

                    * The `default_acl` is the unique set of the `consent_acl`
                    from the visible specimens in the study which contribute to
                    the genomic_file.

                    * The `consent_acl` is composed of the study phs ID and the
                    reported consent code of the sample, prepended with the
                    dbgap prefix "/programs" (e.g. "/programs/phs001138.c1")
                    """
                    biospecimen_codes = set(
                        patches["biospecimens"][k].get("dbgap_consent_code")
                        for k in bsids
                    )
                    patches["genomic-files"][gfid].update(
                        {
                            "authz": sorted(
                                [
                                    f"/programs/{code}"
                                    for code in biospecimen_codes
                                ]
                            )
                        }
                    )
            # GenomicFile visible = False OR one of contributing Biospecimen
            # visible=False
            else:
                """
                Rule: All other genomic files in the dataservice should get
                `{empty_acl}` indicating no access.
                """
                patches["genomic-files"][gfid].update(
                    {"authz": sorted(empty_acl)}
                )

        # remove known unneeded patches
        def cmp(a, b, field_name):
            # Values get filtered out if they are equal to what
            # is already in dataservice.
            # This matters for the authz field bc it will always
            # be equal to [] since local dataservice is not connected to
            # indexd. Therefore when we try to patch a GF with
            # authz = [], this will get filtered out and
            # tests will fail
            # So when testing with localhost we force a patch with authz
            if field_name == "authz" and is_localhost(self.api_url):
                return False

            if isinstance(a, list) and isinstance(b, list):
                return sorted(a) == sorted(b)
            else:
                return a == b

        patches = {
            endpoint: {
                kfid: {
                    k: v
                    for k, v in patch.items()
                    if not (
                        (endpoint in storage)
                        and (kfid in storage[endpoint])
                        and (k in storage[endpoint][kfid])
                        and cmp(storage[endpoint][kfid][k], v, k)
                    )
                }
                for kfid, patch in ep_patches.items()
            }
            for endpoint, ep_patches in patches.items()
        }
        patches = {
            endpoint: {k: v for k, v in ep_patches.items() if v}
            for endpoint, ep_patches in patches.items()
        }
        patches = {k: v for k, v in patches.items() if v}

        # from pprint import pprint
        # breakpoint()

        return patches, alerts
