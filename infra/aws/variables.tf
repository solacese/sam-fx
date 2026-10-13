variable "region" {
  description = "AWS region for the isolated FX demo."
  type        = string
  default     = "eu-south-1"
}

variable "name" {
  description = "Resource name prefix."
  type        = string
  default     = "sam-fx"
}

variable "owner" {
  description = "Owner tag used for cleanup and billing."
  type        = string
  default     = "raphael.caillon@solace.com"
}

variable "ttl" {
  description = "Human-readable maximum lifetime tag for the demo."
  type        = string
  default     = "7d"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version."
  type        = string
  default     = "1.35"
}

variable "node_instance_type" {
  description = "Two nodes provide Agent Mesh quick-start capacity with headroom."
  type        = string
  default     = "m7i.xlarge"
}

variable "node_count" {
  description = "Fixed demo node count."
  type        = number
  default     = 2
}

variable "cluster_public_access_cidrs" {
  description = "CIDRs allowed to access the EKS public API endpoint."
  type        = list(string)
}

variable "budget_limit_usd" {
  description = "Monthly budget notification threshold."
  type        = number
  default     = 400
}

variable "budget_alert_email" {
  description = "Email receiving the AWS budget notification."
  type        = string
  default     = "raphael.caillon@solace.com"
}

variable "hosted_zone_id" {
  description = "Public Route53 zone id for sol-se-emea.com."
  type        = string
}
