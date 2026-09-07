# El resource group se creó a mano (docs/runbook_azure_setup.md §2) — se lo
# referencia como `data`, no como `resource`: Terraform no lo crea ni lo
# destruye, sólo lee su nombre/ubicación para el resto de los recursos.
data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-fraud-detection"
  location            = data.azurerm_resource_group.main.location
  resource_group_name = data.azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-fraud-detection"
  location                   = data.azurerm_resource_group.main.location
  resource_group_name        = data.azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
}

# Los secrets y el registro de GHCR se repiten igual en la Container App y
# en los tres Jobs -misma imagen, mismos insumos-, así que se arman una
# sola vez acá y se referencian desde cada recurso con `dynamic`.
#
# LangSmith es opcional (ADR-0013: sin clave, o con LANGSMITH_TRACING=false,
# el sistema funciona igual sin trazar). Azure Container Apps rechaza un
# secret con `value = ""` ("value or keyVaultUrl and identity should be
# provided"), así que ese par secret/env sólo se arma cuando hay una clave
# real — de lo contrario ni siquiera se declara.
locals {
  container_secrets = concat(
    [
      { name = "ghcr-token", value = var.ghcr_token },
      { name = "database-url", value = var.database_url },
      { name = "anthropic-api-key", value = var.anthropic_api_key },
      { name = "gemini-api-key", value = var.gemini_api_key },
    ],
    var.langsmith_api_key == "" ? [] : [
      { name = "langsmith-api-key", value = var.langsmith_api_key },
    ],
  )

  container_env = concat(
    [
      { name = "DATABASE_URL", secret_name = "database-url" },
      { name = "ANTHROPIC_API_KEY", secret_name = "anthropic-api-key" },
      { name = "GEMINI_API_KEY", secret_name = "gemini-api-key" },
    ],
    var.langsmith_api_key == "" ? [] : [
      { name = "LANGSMITH_API_KEY", secret_name = "langsmith-api-key" },
    ],
  )

  container_env_plain = [
    { name = "LANGSMITH_TRACING", value = tostring(var.langsmith_tracing) },
    { name = "LANGSMITH_PROJECT", value = var.langsmith_project },
    { name = "ENVIRONMENT", value = "production" },
  ]
}

# --- Modo servir: la Container App, siempre activa ------------------------

resource "azurerm_container_app" "api" {
  name                         = "ca-fraud-detection-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = data.azurerm_resource_group.main.name
  revision_mode                = "Single"

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  registry {
    server               = "ghcr.io"
    username             = var.ghcr_username
    password_secret_name = "ghcr-token"
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    # ADR-0021: nunca en cero — el costo fijo es a propósito, para que
    # nadie encuentre el sistema dormido (requisito de 24/7).
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "api"
      image  = var.image
      cpu    = 0.25
      memory = "0.5Gi"

      dynamic "env" {
        for_each = local.container_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
      dynamic "env" {
        for_each = local.container_env_plain
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/health"
        port      = 8000
      }
      readiness_probe {
        transport = "HTTP"
        path      = "/ready"
        port      = 8000
      }
    }
  }

  # `var.image` sólo fija el punto de partida. A partir de acá, Fase 4
  # actualiza la imagen en cada deploy con `az containerapp update --image`,
  # sin volver a correr `apply` -el camino caliente de cada push no debería
  # depender de Terraform-. Efecto colateral a tener presente: un `apply`
  # posterior por un motivo distinto (subir memoria, agregar un secret)
  # VUELVE a fijar la imagen al valor de `var.image` en ese momento, así que
  # hay que actualizar esa variable antes de re-aplicar, o se revierte el
  # despliegue en curso sin querer.
}

# --- Los tres modos batch: Container Apps Jobs -----------------------------

resource "azurerm_container_app_job" "migrate" {
  name                         = "caj-fraud-detection-migrate"
  location                     = data.azurerm_resource_group.main.location
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = 300
  # ADR-0009: nunca reintentar una migración fallida -un reintento
  # automático puede solaparse con la corrida que sigue esperando el lock.
  replica_retry_limit = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  registry {
    server               = "ghcr.io"
    username             = var.ghcr_username
    password_secret_name = "ghcr-token"
  }

  template {
    container {
      name    = "migrate"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["alembic", "upgrade", "head"]

      dynamic "env" {
        for_each = local.container_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
      dynamic "env" {
        for_each = local.container_env_plain
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }
}

resource "azurerm_container_app_job" "seed" {
  name                         = "caj-fraud-detection-seed"
  location                     = data.azurerm_resource_group.main.location
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = 600
  # ADR-0010: el seed es idempotente -un reintento no duplica ni rompe
  # nada, a diferencia de la migración.
  replica_retry_limit = 1

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  registry {
    server               = "ghcr.io"
    username             = var.ghcr_username
    password_secret_name = "ghcr-token"
  }

  template {
    container {
      name    = "seed"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "scripts/seed.py"]

      dynamic "env" {
        for_each = local.container_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
      dynamic "env" {
        for_each = local.container_env_plain
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }
}

resource "azurerm_container_app_job" "fetch_intel" {
  name                         = "caj-fraud-detection-fetch-intel"
  location                     = data.azurerm_resource_group.main.location
  resource_group_name          = data.azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id

  replica_timeout_in_seconds = 900
  replica_retry_limit        = 1

  schedule_trigger_config {
    cron_expression          = var.fetch_intel_cron
    parallelism              = 1
    replica_completion_count = 1
  }

  dynamic "secret" {
    for_each = local.container_secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  registry {
    server               = "ghcr.io"
    username             = var.ghcr_username
    password_secret_name = "ghcr-token"
  }

  template {
    container {
      name    = "fetch-intel"
      image   = var.image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "scripts/fetch_threat_intel.py"]

      dynamic "env" {
        for_each = local.container_env
        content {
          name        = env.value.name
          secret_name = env.value.secret_name
        }
      }
      dynamic "env" {
        for_each = local.container_env_plain
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }
}
