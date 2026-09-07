variable "resource_group_name" {
  type    = string
  default = "rg-fraud-detection"
}

variable "location" {
  type    = string
  default = "eastus2"
}

variable "image" {
  description = "Referencia completa a la imagen en GHCR (con tag o digest). Fase 4 la actualiza en cada deploy sin volver a correr apply — este valor es sólo el punto de partida."
  type        = string
  default     = "ghcr.io/nicolas-torres/multiagent-fraud-detection:sha-b642e85"
}

variable "ghcr_username" {
  description = "Usuario de GitHub para autenticar el pull desde GHCR (el registry es privado, contrato §1.5)."
  type        = string
}

variable "ghcr_token" {
  description = "Personal Access Token de GitHub con permiso read:packages — nunca el GITHUB_TOKEN de un workflow, ese vive sólo en CI."
  type        = string
  sensitive   = true
}

variable "database_url" {
  description = "Connection string de Neon (Postgres + pgvector). Se aprovisiona aparte, no es un recurso de este módulo — ver ADR-0021."
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
  description = "Cadencia del Job fetch-intel, UTC. Diario a las 06:00 de arranque — se ajusta con evidencia real de qué tan seguido cambia el snapshot."
  type        = string
  default     = "0 6 * * *"
}
