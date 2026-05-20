# EKS cluster — Wm runs 100% K8s on AWS
# Highlights: managed node groups, IRSA, cluster autoscaler-ready, CloudWatch logs

terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "wm-tfstate"
    key            = "eks/terraform.tfstate"
    region         = "us-west-2"
    encrypt        = true
    dynamodb_table = "tfstate-locks"
  }
}

provider "aws" {
  region = var.region
}

variable "region"       { default = "us-west-2" }
variable "cluster_name" { default = "wm-prod" }
variable "k8s_version"  { default = "1.30" }

# VPC data (assumes VPC/subnets exist; typical in a mature org)
data "aws_vpc" "main" { tags = { Name = "wm-vpc" } }
data "aws_subnets" "private" {
  filter {
    name   = "tag:Tier"
    values = ["Private"]
  }
}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = var.k8s_version
  vpc_id          = data.aws_vpc.main.id
  subnet_ids      = data.aws_subnets.private.ids

  # Disable public API endpoint — all kubectl access through bastion / VPN
  cluster_endpoint_public_access  = false
  cluster_endpoint_private_access = true

  # Audit + API logs → CloudWatch (required for compliance visibility)
  cluster_enabled_log_types = ["audit", "api", "authenticator"]

  eks_managed_node_groups = {
    general = {
      instance_types = ["m6g.large"]   # Graviton2 — best perf/$ for arm64 workloads
      min_size       = 2
      max_size       = 10
      desired_size   = 3
      disk_size      = 50
      labels         = { role = "general" }
    }
  }

  # IRSA: pods get AWS IAM via service account — no static credentials anywhere
  enable_irsa = true

  tags = {
    Environment = "production"
    Team        = "sre"
    ManagedBy   = "terraform"
  }
}

# Output for kubeconfig
output "cluster_endpoint"              { value = module.eks.cluster_endpoint }
output "cluster_certificate_authority" { value = module.eks.cluster_certificate_authority_data }
output "oidc_provider_arn"             { value = module.eks.oidc_provider_arn }
