<p align="center">
  <a href="https://github.com/kids-first/kf-update-dbgap-consent/blob/master/LICENSE"><img src="https://img.shields.io/github/license/kids-first/kf-update-dbgap-consent.svg?style=for-the-badge"></a>
  <a href="https://circleci.com/gh/kids-first/kf-update-dbgap-consent"><img src="https://img.shields.io/circleci/project/github/kids-first/kf-update-dbgap-consent.svg?style=for-the-badge"></a>
  <a href="https://github.com/psf/black"><img src="https://img.shields.io/badge/code%20style-black ----line--length 80-000000.svg?style=for-the-badge"></a>
</p>

# Kids First dbGaP sample consent status processor

## Purpose

Gets sample consent codes for a study from dbGaP (`https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/GetSampleStatus.cgi?study_id=<STUDY_PHS_ID>&rettype=xml`) and apply the appropriate access control settings as described below to related dataservice biospecimens and their descendants.

---

## Running the Tool

`dbgapconsent SD_12345678 --server https://kf-api-dataservice.kidsfirstdrc.org --db_url postgresql://{USER_NAME}:{PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DBNAME} --dry_run`

See `python main.py --help` for details.

### Match dbGaP to Dataservice Aliquot IDs

The `--match_aliquot` flag will match dbGaP `submitted_sample_id` to `external_aliquot_id` in the dataservice. By default, (without the flag), matched on `external_sample_id`.

`dbgapconsent SD_12345678 --server https://kf-api-dataservice.kidsfirstdrc.org --db_url postgresql://{USER_NAME}:{PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DBNAME} --dry_run --match_aliquot`

---

## ACL Definitions

* study_phs: (e.g. "phs001138")
* consent_acl: f"/programs/{study_phs}.c{consent_code}" (consent_code for the specimen) 
* default_acl: set([{consent_acl} from visible biospecimens which contribute to the genomic file])
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
field set to **True** should get the `{default_acl}`.

* The `default_acl` is the unique set of the `consent_acl` from the visible
specimens in the study which contribute to the genomic_file.

* The `consent_acl` is composed of the study phs ID and the
reported sample consent code of the sample, prepended with the dbgap
prefix "/programs" (e.g. "/programs/phs001138.c1")

* All other genomic files in the dataservice should get `{empty_acl}`
indicating no access.


