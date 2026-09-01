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
