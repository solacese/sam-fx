output "cluster_name" { value = module.eks.cluster_name }
output "region" { value = var.region }
output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "certificate_arn" { value = aws_acm_certificate_validation.demo.certificate_arn }
output "hosted_zone_id" { value = var.hosted_zone_id }
output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.region} --name ${module.eks.cluster_name}"
}
