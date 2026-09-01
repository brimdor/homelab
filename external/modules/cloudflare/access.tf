# =============================================================================
# Cloudflare Zero Trust Access — Citadel (Production ONLY)
# =============================================================================
# Configured 2026-05-15. Google OAuth restricts access to authorized emails.
# WARNING: citadel-canary.eaglepass.io is NOT protected — internal-only.
# ------------------------------------------------------------------------------

# Identity provider pre-configured at account level:
# Google OAuth ID: facd56ad-71fa-4cf3-98a0-ac986681b252

resource "cloudflare_zero_trust_access_application" "citadel" {
  account_id                = var.cloudflare_account_id
  name                      = "Citadel"
  domain                    = "citadel.eaglepass.io"
  type                      = "self_hosted"
  session_duration          = "24h"
  allowed_idps              = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible      = true
}

resource "cloudflare_zero_trust_access_policy" "citadel_allow" {
  account_id       = var.cloudflare_account_id
  application_id   = cloudflare_zero_trust_access_application.citadel.id
  name             = "Citadel Access"
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

# =============================================================================
# Cloudflare Zero Trust Access — Arc Tracker
# =============================================================================

resource "cloudflare_zero_trust_access_application" "arc_tracker" {
  account_id                = var.cloudflare_account_id
  name                      = "Arc Tracker"
  domain                    = "arc.eaglepass.io"
  type                      = "self_hosted"
  session_duration          = "24h"
  allowed_idps              = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible      = true
}

resource "cloudflare_zero_trust_access_policy" "arc_tracker_allow" {
  account_id       = var.cloudflare_account_id
  application_id   = cloudflare_zero_trust_access_application.arc_tracker.id
  name             = "Arc Tracker Allow"
  decision         = "allow"
  precedence       = 1
  session_duration = "24h"

  include {
    email {
      email = "chrisnelsonx@gmail.com"
    }
  }
}

# =============================================================================
# Cloudflare Zero Trust Access — Versa
# =============================================================================
# The production marketing page remains public. Cloudflare Access protects the
# application surface, while Versa keeps newly authenticated accounts pending
# until an administrator approves them.
# ------------------------------------------------------------------------------

resource "cloudflare_zero_trust_access_application" "versa" {
  account_id                = var.cloudflare_account_id
  name                      = "Versa"
  domain                    = "versa.eaglepass.io/app*"
  type                      = "self_hosted"
  session_duration          = "24h"
  allowed_idps              = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible      = true
  policies = [{
    id         = cloudflare_zero_trust_access_policy.versa_allow_google.id
    precedence = 1
  }]
}

resource "cloudflare_zero_trust_access_policy" "versa_allow_google" {
  account_id       = var.cloudflare_account_id
  name             = "Versa Google Sign-In"
  decision         = "allow"
  session_duration = "24h"
  include          = [{ everyone = {} }]
}

resource "cloudflare_zero_trust_access_application" "versa_canary" {
  account_id                = var.cloudflare_account_id
  name                      = "Versa Canary"
  domain                    = "versa-canary.eaglepass.io"
  type                      = "self_hosted"
  session_duration          = "24h"
  allowed_idps              = ["facd56ad-71fa-4cf3-98a0-ac986681b252"]
  auto_redirect_to_identity = true
  app_launcher_visible      = false
  policies = [{
    id         = cloudflare_zero_trust_access_policy.versa_canary_owner.id
    precedence = 1
  }]
}

resource "cloudflare_zero_trust_access_policy" "versa_canary_owner" {
  account_id       = var.cloudflare_account_id
  name             = "Versa Canary Owner"
  decision         = "allow"
  session_duration = "24h"
  include          = [{ email = { email = "chrisnelsonx@gmail.com" } }]
}
