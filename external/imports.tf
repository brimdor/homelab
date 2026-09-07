# Versa Access resources were created through the Cloudflare API because the
# pre-existing Cloudflare module still contains provider-v4 resources while it
# declares provider v5. These import blocks ensure the resources are adopted
# rather than recreated once that broader module migration is completed.
import {
  to = module.cloudflare.cloudflare_zero_trust_access_application.versa
  id = "accounts/${var.cloudflare_account_id}/f6f2690c-1b53-4b5f-a453-9f13cbf28976"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_policy.versa_allow_google
  id = "${var.cloudflare_account_id}/13699fda-4487-421b-8875-c8eda15ca89c"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_application.versa_canary
  id = "accounts/${var.cloudflare_account_id}/36947bbd-fabe-4491-8b3a-09169799b198"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_policy.versa_canary_owner
  id = "${var.cloudflare_account_id}/d564444b-9b5e-439c-a4e5-1f0cf97648d7"
}

# PointGuide Access resources follow the same API-bootstrap-and-adopt path as
# Versa while the broader provider-v5 migration remains incomplete.
import {
  to = module.cloudflare.cloudflare_zero_trust_access_application.pointguide
  id = "accounts/${var.cloudflare_account_id}/dbb92eeb-ceb2-49ae-a497-a4a82a71c633"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_policy.pointguide_allow_google
  id = "${var.cloudflare_account_id}/70f82692-4d74-462e-bf1e-1db0292f8b87"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_application.pointguide_canary
  id = "accounts/${var.cloudflare_account_id}/60224322-5e72-4f0b-97d8-bacad17f7ed8"
}

import {
  to = module.cloudflare.cloudflare_zero_trust_access_policy.pointguide_canary_owner
  id = "${var.cloudflare_account_id}/95be941a-e716-462e-a111-0ff093b95f81"
}
