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

