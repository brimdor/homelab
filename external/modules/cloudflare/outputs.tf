output "versa_access_audience" {
  description = "Cloudflare Access audience used by the Versa production application."
  value       = cloudflare_zero_trust_access_application.versa.aud
}

output "versa_canary_access_audience" {
  description = "Cloudflare Access audience used by the Versa canary application."
  value       = cloudflare_zero_trust_access_application.versa_canary.aud
}

output "pointguide_access_audience" {
  description = "Cloudflare Access audience used by the PointGuide production application."
  value       = cloudflare_zero_trust_access_application.pointguide.aud
}

output "pointguide_canary_access_audience" {
  description = "Cloudflare Access audience used by the PointGuide canary application."
  value       = cloudflare_zero_trust_access_application.pointguide_canary.aud
}
