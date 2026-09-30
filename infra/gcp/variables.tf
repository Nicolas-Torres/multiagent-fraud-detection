variable "project_id" {
  type    = string
  default = "fraud-detection-portafolio"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "image_repository" {
  description = "Referencia de la imagen tal como CI la publica en GHCR (sin el host ghcr.io, sin tag) — p. ej. nicolas-torres/multiagent-fraud-detection. Es también su ruta dentro del repositorio `images` de Artifact Registry, adonde deploy-gcp.yml la promueve por digest (ADR-0028)."
  type        = string
  default     = "nicolas-torres/multiagent-fraud-detection"
}

variable "image_tag" {
  description = "Tag sha-<7> (ADR-0008). Fase 4-equivalente (deploy-gcp.yml) la actualiza en cada deploy con `gcloud run services update --image`, sin volver a correr apply — mismo criterio que infra/azure."
  type        = string
  default     = "sha-149bbfd"
}

variable "deployer_service_account" {
  description = "Cuenta de servicio que usa deploy-gcp.yml por Workload Identity Federation (creada a mano en el bootstrap, docs/runbook_gcp_setup.md). Recibe permiso de escritura sólo sobre el repositorio `images` (ADR-0028)."
  type        = string
  default     = "github-actions-deployer@fraud-detection-portafolio.iam.gserviceaccount.com"
}

variable "database_url" {
  description = "Connection string de Neon — el mismo valor que usa Azure (ADR-0021/0022: base neutral, sin cambios)."
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
}

variable "gemini_api_key" {
  type      = string
  sensitive = true
}

variable "langsmith_api_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "langsmith_tracing" {
  type    = bool
  default = true
}

variable "langsmith_project" {
  type    = string
  default = "fraud-detection"
}

variable "fetch_intel_cron" {
  description = "Cadencia del Job fetch-intel, UTC. Semanal, lunes 06:00 (ADR-0026): diaria costaba ~USD 33/mes sin cambiar ninguna decisión de la demo, cuyas transacciones tienen fecha fija. Igual en Azure y GCP."
  type        = string
  default     = "0 6 * * 1"
}
