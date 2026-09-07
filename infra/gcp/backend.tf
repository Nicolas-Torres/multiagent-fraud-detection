# Backend remoto (ADR-0022): el bucket de GCS ya existe -se creó a mano,
# ver docs/runbook_gcp_setup.md §3- porque el backend tiene que existir
# antes de que haya un Terraform que lo use. Nunca estado local, mismo
# motivo que infra/azure/backend.tf.
terraform {
  backend "gcs" {
    bucket = "fraud-detection-portafolio-tfstate"
    prefix = "terraform/state"
  }
}
