output "api_url" {
  description = "URL pública del Cloud Run service. /health y /ready cuelgan de acá."
  value       = google_cloud_run_v2_service.api.uri
}

output "project_id" {
  value = var.project_id
}

output "ghcr_mirror_repository" {
  description = "Nombre completo del espejo de Artifact Registry, para referenciar la imagen en el CD."
  value       = google_artifact_registry_repository.ghcr_mirror.name
}
