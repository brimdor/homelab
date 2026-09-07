output "versa_access_audience" {
  description = "Cloudflare Access audience used by the Versa production application."
  value       = module.cloudflare.versa_access_audience
}

output "versa_canary_access_audience" {
  description = "Cloudflare Access audience used by the Versa canary application."
  value       = module.cloudflare.versa_canary_access_audience
}

output "pointguide_access_audience" {
  description = "Cloudflare Access audience used by the PointGuide production application."
  value       = module.cloudflare.pointguide_access_audience
}

output "pointguide_canary_access_audience" {
  description = "Cloudflare Access audience used by the PointGuide canary application."
  value       = module.cloudflare.pointguide_canary_access_audience
}
