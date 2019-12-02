"""
ACL Definitions

study_kfid: (e.g. "SD_12345678")
study_phs: (e.g. "phs001138")
root_phs_acl: f"{study_phs}.c999"    (This gives root access to the study)
consent_acl: f"{study_phs}.c{code}"  (Not c999 which is a reserved admin code)
default_acl: [study_kfid, root_phs_acl]

ACL Rules

* The tool should discover and use the latest version of the study’s sample
  status file that has status "released". (If phs1.v1.p2 is marked as released
  and phs1.v2.p1 exists and is not yet marked released, use phs1.v1.p2)

* The Study entity in the dataservice should have its version set to the
  version found in the used sample status file.

* For all samples in the sample status file which are not found in the
  dataservice, return or display an alert.

* Dataservice biospecimens whose samples are found in the sample status file
  with status "Loaded" should have their consent_type dbgap_consent_code fields
  set as indicated in the file.

* All other dataservice biospecimens should be hidden in the dataservice and
  their "consent_type" and "dbgap_consent_code" fields should be set to null.

    * If a biospecimen is hidden in the dataservice, its descendants (genomic
      files, read groups, etc) should also be hidden.

* All genomic files in the dataservice should get {default_acl}.

* Each reported custom consent code should be added to each genomic file with
  contribution from any biospecimen(s) in the study with the reported sample
  external ID by adding the {consent_acl} in addition to the default IF AND
  ONLY IF the genomic file and its contributing biospecimen(s) are all visible
  in the dataservice, with the following exception:

    * Until indexd supports "and" composition rules, if a genomic file has
      multiple contributing specimens with non-identical access control codes,
      that genomic file should get {default_acl}. Return or display an alert
      for each such case.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from d3b_utils.requests_retry import Session

from kf_utils.dataservice.descendants import find_descendants_by_kfids
from kf_utils.dataservice.scrape import yield_entities, yield_kfids
from kf_utils.dbgap.release import get_latest_sample_status


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

    def get_patches_for_study(self, study_id, dbgap_status="released"):
        print("Looking up dbGaP accession ID")
        study_phs, study_version = self.get_accession(study_id)
        print(f"Found accession ID: {study_phs}")
        default_acl = {study_id, f"{study_phs}.c999"}
        alerts = []
        patches = defaultdict(dict)

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
                self.db_url, "studies", [study_id], False, kfids_only=False,
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
                        (
                            "genomic-files",
                            {"study_id": study_id, "visible": False},
                        ),
                    ]
                }
                for f in as_completed(futures):
                    storage[futures[f]] = f.result()
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

        """
        Rule: For all samples in the sample status file which are not found in
        the dataservice, return or display an alert.
        """
        specimen_extids = set(
            bs["external_sample_id"] for bs in storage["biospecimens"].values()
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
            sample = dbgap_samples.get(bs["external_sample_id"], {})
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
                }
                hidden_specimens[kfid] = bs

        """
        Rule: Each reported custom consent code should be added to each genomic
        file that has contribution from any biospecimen(s) in the study with
        the reported sample external ID by adding the {consent_acl} in addition
        to the {default_acl} IF AND ONLY IF the genomic file and its
        contributing biospecimen(s) are all visible in the dataservice, ...
        """
        for gfid, bsids in gfids_bsids.items():
            all_biospecimens_visible = all(
                [k not in hidden_specimens for k in bsids]
            )
            biospecimen_codes = set(
                patches["biospecimens"][k].get("dbgap_consent_code")
                for k in bsids
            )
            if (gfid not in hidden_genomic_files) and all_biospecimens_visible:
                """
                Rule: ...with the following exception: Until indexd supports
                "and" composition rules, if a genomic file has multiple
                contributing specimens with non-identical access control codes,
                that genomic file should get {default_acl}. Return or display
                an alert for each such case.
                """
                all_biospecimens_same_code = len(biospecimen_codes) == 1
                if all_biospecimens_same_code:
                    patches["genomic-files"][gfid] = {
                        "acl": sorted(default_acl | biospecimen_codes)
                    }
                else:
                    alerts.append(
                        f"ALERT: GF {gfid} has inconsistent sample access"
                        f" codes {biospecimen_codes}"
                    )
                    print(alerts[-1])
                    patches["genomic-files"][gfid] = {
                        "acl": sorted(default_acl)
                    }
            else:
                patches["genomic-files"][gfid] = {"acl": sorted(default_acl)}

        """
        Rule: If a biospecimen is hidden in the dataservice, its descendants
        should also be hidden.
        """
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
                p = patches.setdefault(endpoint, dict()).setdefault(k, dict())
                p["visible"] = False
                if endpoint == "genomic-files":
                    p["acl"] = sorted(default_acl)
        print()

        # remove known unneeded patches

        def cmp(a, b):
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
                        and (cmp(storage[endpoint][kfid][k], v))
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

        return patches, alerts
