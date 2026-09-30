output "api_url" {
  description = "URL pública del Cloud Run service. /health y /ready cuelgan de acá."
  value       = google_cloud_run_v2_service.api.uri
}

output "project_id" {
  value = var.project_id
}

output "images_repository" {
  description = "Nombre completo del repositorio de Artifact Registry adonde el CD promueve la imagen por digest (ADR-0028)."
  value       = google_artifact_registry_repository.images.name
}
