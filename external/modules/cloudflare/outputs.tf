output "versa_access_audience" {
  description = "Cloudflare Access audience used by the Versa production application."
  value       = cloudflare_zero_trust_access_application.versa.aud
}

output "versa_canary_access_audience" {
  description = "Cloudflare Access audience used by the Versa canary application."
  value       = cloudflare_zero_trust_access_application.versa_canary.aud
}
