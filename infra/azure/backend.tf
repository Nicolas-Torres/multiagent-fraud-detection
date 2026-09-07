# Backend remoto (ADR-0021): el Storage Account y el contenedor ya existen
# —se crearon a mano, ver docs/runbook_azure_setup.md §3— porque el backend
# tiene que existir antes de que haya un Terraform que lo use. Nunca estado
# local: no sobrevive un cambio de máquina y el CD no podría leerlo.
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-fraud-detection"
    storage_account_name = "stfrauddetecttf"
    container_name       = "tfstate"
    key                  = "fraud-detection.tfstate"
  }
}
