output "versa_access_audience" {
  description = "Cloudflare Access audience used by the Versa production application."
  value       = module.cloudflare.versa_access_audience
}

output "versa_canary_access_audience" {
  description = "Cloudflare Access audience used by the Versa canary application."
  value       = module.cloudflare.versa_canary_access_audience
}
