# =============================================================================
# Cloudflare Zero Trust Access — Citadel (Production ONLY)
# =============================================================================
# Configured 2026-05-15. Google OAuth restricts access to authorized emails.
# WARNING: citadel-canary.eaglepass.io is NOT protected — internal-only.
# ------------------------------------------------------------------------------

# Identity provider pre-configured at account level:
# Google OAuth ID: facd56ad-71fa-4cf3-98a0-ac986681b252

resource "cloudflare_zero_trust_access_application" "citadel" {
  account_id               = var.cloudflare_account_id
  name                     = "Citadel"
  domain                   = "citadel.eaglepass.io"
  type                     = "self_hosted"
  session_duration         = "24h"
  allowed_idps             = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible     = true
}

resource "cloudflare_zero_trust_access_policy" "citadel_allow" {
  account_id     = var.cloudflare_account_id
  application_id = cloudflare_zero_trust_access_application.citadel.id
  name           = "Citadel Access"
  decision       = "allow"
  precedence     = 1
  session_duration = "24h"

  include {
    email {
      email = "chrisnelsonx@gmail.com"
    }
    email {
      email = "kaleb.bays@gmail.com"
    }
  }
}

# =============================================================================
# Cloudflare Zero Trust Access — Citadel Canary
# =============================================================================
# Restricts canary to the same authorized emails.
# ------------------------------------------------------------------------------

resource "cloudflare_zero_trust_access_application" "citadel_canary" {
  account_id                = var.cloudflare_account_id
  name                      = "Citadel Canary"
  domain                    = "citadel-canary.eaglepass.io"
  type                      = "self_hosted"
  session_duration          = "24h"
  allowed_idps              = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible      = true
}

resource "cloudflare_zero_trust_access_policy" "citadel_canary_allow" {
  account_id       = var.cloudflare_account_id
  application_id   = cloudflare_zero_trust_access_application.citadel_canary.id
  name             = "Citadel Canary Allow"
  decision         = "allow"
  precedence       = 1
  session_duration = "24h"

  include {
    email {
      email = "chrisnelsonx@gmail.com"
    }
    email {
      email = "kaleb.bays@gmail.com"
    }
  }
}
