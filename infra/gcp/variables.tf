variable "project_id" {
  type    = string
  default = "fraud-detection-portafolio"
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "image_repository" {
  description = "Referencia de la imagen tal como CI la publica en GHCR (sin el host ghcr.io, sin tag) — p. ej. nicolas-torres/multiagent-fraud-detection. Cloud Run no puede pull-earla directo: pasa por el espejo de Artifact Registry (ver artifact_registry.tf)."
  type        = string
  default     = "nicolas-torres/multiagent-fraud-detection"
}

variable "image_tag" {
  description = "Tag sha-<7> (ADR-0008). Fase 4-equivalente (deploy-gcp.yml) la actualiza en cada deploy con `gcloud run services update --image`, sin volver a correr apply — mismo criterio que infra/azure."
  type        = string
  default     = "sha-149bbfd"
}

variable "ghcr_username" {
  description = "Usuario de GitHub para el espejo de Artifact Registry hacia GHCR (el registry es privado, contrato §1.5)."
  type        = string
}

variable "ghcr_token" {
  description = "Personal Access Token de GitHub con permiso read:packages — igual que ghcr_token en infra/azure, nunca el GITHUB_TOKEN de un workflow."
  type        = string
  sensitive   = true
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
  description = "Cadencia del Job fetch-intel, UTC. Mismo valor que Azure de arranque."
  type        = string
  default     = "0 6 * * *"
}
