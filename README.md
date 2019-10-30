# Kids First dbGaP sample consent status processor

## ACL Definitions

* study_kfid: (e.g. "SD_12345678")
* study_phs: (e.g. "phs001138")
* root_phs_acl: f"{study_phs}.c999" (This gives root access to the study)
* consent_acl: f"{study_phs}.c{code}" (Not c999 which is a reserved admin code)
* default_acl: [study_kfid, root_phs_acl]

## ACL Rules

* The tool should discover and use the latest version of the study’s sample
  status file that has status "released". (e.g. if phsXXX.*v1.p2* is marked as
  released and phsXXX.*v2.p1* exists and is not yet marked released, use
  phsXXX.*v1.p2*)

* The Study entity in the dataservice should have its version set to the
  version found in the used sample status file.

* For all samples in the sample status file which are not found in the
  dataservice, return or display an alert.

* Dataservice biospecimens whose samples are found in the sample status file
  with status "Loaded" should have their consent_type dbgap_consent_code fields
  set as indicated in the file.

* All other dataservice biospecimens should be hidden in the dataservice and
  their `"consent_type"` and `"dbgap_consent_code"` fields should be set to
  `null`.

    * If a biospecimen is hidden in the dataservice, its descendants (genomic
      files, read groups, etc) should also be hidden.

* All genomic files in the dataservice should get `{default_acl}`.

* Each reported custom consent code should be added to each genomic file with
  contribution from any biospecimen(s) in the study with the reported sample
  external ID by adding the `{consent_acl}` in addition to the default **IF AND
  ONLY IF** the genomic file and its contributing biospecimen(s) are all
  visible in the dataservice, **with the following exception:**

    * Until indexd supports "and" composition rules, if a genomic file has
      multiple contributing specimens with non-identical access control codes,
      that genomic file should get `{default_acl}`. **Return or display an
      alert for each such case.**
