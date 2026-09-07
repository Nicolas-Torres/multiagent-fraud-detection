output "api_fqdn" {
  description = "URL pública de la Container App. /health y /ready cuelgan de acá."
  value       = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "resource_group_name" {
  value = data.azurerm_resource_group.main.name
}

output "container_app_environment_id" {
  value = azurerm_container_app_environment.main.id
}
