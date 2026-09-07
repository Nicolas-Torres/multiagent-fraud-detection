# --- Identidad de runtime ---------------------------------------------
# Distinta del Service Account que usa GitHub Actions (github-actions-deployer,
# creado a mano en el bootstrap, ver docs/runbook_gcp_setup.md §4-5): ese
# despliega recursos, este es el que los recursos usan para correr — nunca
# el mismo, principio de mínimo privilegio.
resource "google_service_account" "runtime" {
  account_id   = "fraud-detection-runtime"
  display_name = "Cloud Run runtime (fraud-detection)"
}

# --- Los cinco secrets de runtime, mismos valores que Azure -------------
# LangSmith es opcional (ADR-0013) y Secret Manager, igual que Azure
# Container Apps, no acepta un secret sin contenido real — mismo fix que
# infra/azure/main.tf: el par no se declara si no hay clave.
#
# `for_each` no puede iterar un mapa cuyos *valores* son sensibles —
# Terraform lo rechaza en `validate` porque las claves quedarían
# expuestas como parte del identificador del recurso en el state. Por
# eso `secret_ids` (las claves, no sensibles) vive separado de
# `secret_values` (los valores, sí sensibles) — el `for_each` sólo mira
# el primero, el segundo se indexa recién dentro del recurso.
# `nonsensitive()` es seguro acá: sólo declara que *si* LangSmith está
# configurado no es en sí un secreto, la clave real sigue marcada
# sensible en `secret_values`.
locals {
  secret_ids = compact([
    "ghcr-token",
    "database-url",
    "anthropic-api-key",
    "gemini-api-key",
    nonsensitive(var.langsmith_api_key == "") ? "" : "langsmith-api-key",
  ])

  secret_values = {
    "ghcr-token"        = var.ghcr_token
    "database-url"      = var.database_url
    "anthropic-api-key" = var.anthropic_api_key
    "gemini-api-key"    = var.gemini_api_key
    "langsmith-api-key" = var.langsmith_api_key
  }

  # env vars que sí van directo (no son secretas)
  env_plain = [
    { name = "LANGSMITH_TRACING", value = tostring(var.langsmith_tracing) },
    { name = "LANGSMITH_PROJECT", value = var.langsmith_project },
    { name = "ENVIRONMENT", value = "production" },
  ]

  # mapeo secret_id -> nombre de variable de entorno que la app espera
  secret_env_names = {
    "database-url"      = "DATABASE_URL"
    "anthropic-api-key" = "ANTHROPIC_API_KEY"
    "gemini-api-key"    = "GEMINI_API_KEY"
    "langsmith-api-key" = "LANGSMITH_API_KEY"
  }
  # sólo los que la app consume como env var (ghcr-token es sólo para el
  # espejo de Artifact Registry, la app nunca lo ve)
  app_secret_ids = [for id in local.secret_ids : id if id != "ghcr-token"]

  full_image = "${var.region}-docker.pkg.dev/${var.project_id}/ghcr-mirror/${var.image_repository}:${var.image_tag}"
}

resource "google_secret_manager_secret" "this" {
  for_each  = toset(local.secret_ids)
  secret_id = each.key
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "this" {
  for_each    = toset(local.secret_ids)
  secret      = google_secret_manager_secret.this[each.key].id
  secret_data = local.secret_values[each.key]
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each  = toset(local.app_secret_ids)
  secret_id = google_secret_manager_secret.this[each.key].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Espejo de Artifact Registry hacia GHCR ------------------------------
# Cloud Run no puede pull-ear un registro externo directo (a diferencia de
# Azure Container Apps, que sí toma credenciales de un registry cualquiera)
# — un remote repository de Artifact Registry actúa de proxy autenticado
# hacia GHCR (ADR-0022 §Alternativas descartadas). Sigue apuntando a GHCR
# como fuente real, no una copia manual: la imagen real la sigue publicando
# sólo el job `build` de ci.yml (ADR-0008).
resource "google_artifact_registry_repository" "ghcr_mirror" {
  location      = var.region
  repository_id = "ghcr-mirror"
  format        = "DOCKER"
  mode          = "REMOTE_REPOSITORY"

  remote_repository_config {
    description                 = "Espejo de solo lectura hacia ghcr.io (ADR-0022)"
    disable_upstream_validation = true

    docker_repository {
      custom_repository {
        uri = "https://ghcr.io"
      }
    }

    upstream_credentials {
      username_password_credentials {
        username                = var.ghcr_username
        password_secret_version = google_secret_manager_secret_version.this["ghcr-token"].name
      }
    }
  }
}

resource "google_artifact_registry_repository_iam_member" "runtime_pull" {
  location   = google_artifact_registry_repository.ghcr_mirror.location
  repository = google_artifact_registry_repository.ghcr_mirror.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

# --- Modo servir: el Cloud Run service, escala a cero (ADR-0022) --------
resource "google_cloud_run_v2_service" "api" {
  name     = "fraud-detection-api"
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    scaling {
      # A propósito, a diferencia del min_replicas=1 de Azure: esta es la
      # demo secundaria de aprendizaje, no la enlazada en el README — un
      # cold-start ocasional es aceptable a cambio de no duplicar el costo
      # fijo mensual (ADR-0022).
      min_instance_count = 0
      max_instance_count = 1
    }

    service_account = google_service_account.runtime.email

    containers {
      name  = "api"
      image = local.full_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      dynamic "env" {
        for_each = local.app_secret_ids
        content {
          name = local.secret_env_names[env.value]
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.this[env.value].secret_id
              version = "latest"
            }
          }
        }
      }
      dynamic "env" {
        for_each = local.env_plain
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      # Startup: no sirve tráfico hasta que /ready confirme que Postgres
      # responde — mismo rol que el readiness_probe de Azure.
      startup_probe {
        http_get {
          path = "/ready"
          port = 8000
        }
        initial_delay_seconds = 0
        period_seconds        = 3
        timeout_seconds       = 3
        failure_threshold     = 10
      }
      # Liveness: el proceso responde, sin tocar la base — mismo rol que
      # el liveness_probe de Azure.
      liveness_probe {
        http_get {
          path = "/health"
          port = 8000
        }
        period_seconds    = 10
        timeout_seconds   = 3
        failure_threshold = 3
      }
    }
  }

  depends_on = [google_artifact_registry_repository_iam_member.runtime_pull]

  # `image` sólo fija el punto de partida (var.image_tag por defecto).
  # deploy-gcp.yml lo actualiza en cada push con
  # `gcloud run services update --image`, sin volver a correr `apply` —
  # mismo criterio que infra/azure/main.tf.
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  location = google_cloud_run_v2_service.api.location
  name     = google_cloud_run_v2_service.api.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Los tres modos batch: Cloud Run Jobs --------------------------------

resource "google_cloud_run_v2_job" "migrate" {
  name     = "fraud-detection-migrate"
  location = var.region

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.runtime.email
      timeout         = "300s"
      # ADR-0009: nunca reintentar una migración fallida sola.
      max_retries = 0

      containers {
        name    = "migrate"
        image   = local.full_image
        command = ["alembic", "upgrade", "head"]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        dynamic "env" {
          for_each = local.app_secret_ids
          content {
            name = local.secret_env_names[env.value]
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
        dynamic "env" {
          for_each = local.env_plain
          content {
            name  = env.value.name
            value = env.value.value
          }
        }
      }
    }
  }

  depends_on = [google_artifact_registry_repository_iam_member.runtime_pull]
}

resource "google_cloud_run_v2_job" "seed" {
  name     = "fraud-detection-seed"
  location = var.region

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.runtime.email
      timeout         = "600s"
      # ADR-0010: el seed es idempotente, un reintento no rompe nada.
      max_retries = 1

      containers {
        name    = "seed"
        image   = local.full_image
        command = ["python", "scripts/seed.py"]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        dynamic "env" {
          for_each = local.app_secret_ids
          content {
            name = local.secret_env_names[env.value]
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
        dynamic "env" {
          for_each = local.env_plain
          content {
            name  = env.value.name
            value = env.value.value
          }
        }
      }
    }
  }

  depends_on = [google_artifact_registry_repository_iam_member.runtime_pull]
}

resource "google_cloud_run_v2_job" "fetch_intel" {
  name     = "fraud-detection-fetch-intel"
  location = var.region

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.runtime.email
      timeout         = "900s"
      max_retries     = 1

      containers {
        name    = "fetch-intel"
        image   = local.full_image
        command = ["python", "scripts/fetch_threat_intel.py"]

        resources {
          limits = { cpu = "1", memory = "512Mi" }
        }

        dynamic "env" {
          for_each = local.app_secret_ids
          content {
            name = local.secret_env_names[env.value]
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.this[env.value].secret_id
                version = "latest"
              }
            }
          }
        }
        dynamic "env" {
          for_each = local.env_plain
          content {
            name  = env.value.name
            value = env.value.value
          }
        }
      }
    }
  }

  depends_on = [google_artifact_registry_repository_iam_member.runtime_pull]
}

# --- Cron de fetch-intel: Cloud Scheduler --------------------------------
# GCP no tiene un trigger de cron nativo en el recurso Job (a diferencia de
# Azure Container Apps Jobs, que sí lo tiene) — hace falta Cloud Scheduler
# invocando la Admin API del Job por HTTP. Identidad propia y acotada, no
# la de runtime ni la de GitHub Actions: sólo necesita permiso para
# disparar este Job puntual.
resource "google_service_account" "scheduler_invoker" {
  account_id   = "fraud-detection-scheduler"
  display_name = "Cloud Scheduler -> fetch-intel Job invoker"
}

resource "google_cloud_run_v2_job_iam_member" "scheduler_can_run" {
  location = google_cloud_run_v2_job.fetch_intel.location
  name     = google_cloud_run_v2_job.fetch_intel.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler_invoker.email}"
}

resource "google_cloud_scheduler_job" "fetch_intel" {
  name      = "fraud-detection-fetch-intel-cron"
  schedule  = var.fetch_intel_cron
  time_zone = "UTC"

  http_target {
    http_method = "POST"
    uri         = "https://cloudrun.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.fetch_intel.name}:run"

    oidc_token {
      service_account_email = google_service_account.scheduler_invoker.email
      audience              = "https://cloudrun.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.fetch_intel.name}"
    }
  }
}
