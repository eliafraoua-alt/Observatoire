# ─── Observatoire RPDF — Infrastructure AWS ──────────────────────────────────
# ECS Fargate + ALB + S3 + CloudWatch + Secrets Manager
# terraform init && terraform plan && terraform apply

terraform {
  required_version = ">= 1.8"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.50" }
  }
  backend "s3" {
    bucket = "rpdf-terraform-state"
    region = "eu-west-3"
  }
}

variable "aws_account_id" {}
variable "ecr_registry"   {}
variable "image_tag"      { default = "latest" }

provider "aws" { region = "eu-west-3" }

locals {
  name = "rpdf-observatoire"
  tags = { Project = "Observatoire RPDF", ManagedBy = "Terraform" }
}

# ── VPC ──────────────────────────────────────────────────────────────────────
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.8"
  name    = "${local.name}-vpc"
  cidr    = "10.0.0.0/16"
  azs             = ["eu-west-3a", "eu-west-3b"]
  private_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
  public_subnets  = ["10.0.101.0/24", "10.0.102.0/24"]
  enable_nat_gateway = true
  single_nat_gateway = true
  tags = local.tags
}

# ── ECS Cluster ───────────────────────────────────────────────────────────────
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting { name = "containerInsights"; value = "enabled" }
  tags = local.tags
}

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name       = aws_ecs_cluster.main.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# ── S3 — Data Lake ────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "datalake" {
  bucket = "rpdf-observatoire-datalake"
  tags   = local.tags
}

resource "aws_s3_bucket_versioning" "datalake" {
  bucket = aws_s3_bucket.datalake.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_lifecycle_configuration" "datalake" {
  bucket = aws_s3_bucket.datalake.id
  rule {
    id     = "archive-old-parquet"
    status = "Enabled"
    transition { days = 90; storage_class = "STANDARD_IA" }
    transition { days = 365; storage_class = "GLACIER" }
    filter {}
  }
}

# ── EFS — DuckDB persistant ───────────────────────────────────────────────────
resource "aws_efs_file_system" "duckdb" {
  encrypted        = true
  performance_mode = "generalPurpose"
  tags             = merge(local.tags, { Name = "${local.name}-duckdb" })
}

resource "aws_efs_mount_target" "duckdb" {
  count           = 2
  file_system_id  = aws_efs_file_system.duckdb.id
  subnet_id       = module.vpc.private_subnets[count.index]
  security_groups = [aws_security_group.efs.id]
}

# ── Security Groups ────────────────────────────────────────────────────────────
resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = module.vpc.vpc_id
  ingress { from_port = 80;  to_port = 80;  protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }
  ingress { from_port = 443; to_port = 443; protocol = "tcp"; cidr_blocks = ["0.0.0.0/0"] }
  egress  { from_port = 0;   to_port = 0;   protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }
  tags = local.tags
}

resource "aws_security_group" "ecs" {
  name   = "${local.name}-ecs"
  vpc_id = module.vpc.vpc_id
  ingress { from_port = 8000; to_port = 8501; protocol = "tcp"; security_groups = [aws_security_group.alb.id] }
  egress  { from_port = 0;    to_port = 0;    protocol = "-1";  cidr_blocks = ["0.0.0.0/0"] }
  tags = local.tags
}

resource "aws_security_group" "efs" {
  name   = "${local.name}-efs"
  vpc_id = module.vpc.vpc_id
  ingress { from_port = 2049; to_port = 2049; protocol = "tcp"; security_groups = [aws_security_group.ecs.id] }
  tags = local.tags
}

# ── ALB ───────────────────────────────────────────────────────────────────────
resource "aws_lb" "main" {
  name               = "${local.name}-alb"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = module.vpc.public_subnets
  tags               = local.tags
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = module.vpc.vpc_id
  target_type = "ip"
  health_check { path = "/health"; matcher = "200" }
}

resource "aws_lb_target_group" "dashboard" {
  name        = "${local.name}-dash"
  port        = 8501
  protocol    = "HTTP"
  vpc_id      = module.vpc.vpc_id
  target_type = "ip"
  health_check { path = "/_stcore/health"; matcher = "200" }
}

# ── IAM Task Role ─────────────────────────────────────────────────────────────
resource "aws_iam_role" "ecs_task" {
  name = "${local.name}-ecs-task"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow"; Principal = { Service = "ecs-tasks.amazonaws.com" }; Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "ecs_task" {
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow"; Action = ["s3:GetObject","s3:PutObject","s3:ListBucket"]; Resource = ["${aws_s3_bucket.datalake.arn}","${aws_s3_bucket.datalake.arn}/*"] },
      { Effect = "Allow"; Action = ["secretsmanager:GetSecretValue"]; Resource = "arn:aws:secretsmanager:eu-west-3:${var.aws_account_id}:secret:rpdf/*" },
      { Effect = "Allow"; Action = ["logs:CreateLogStream","logs:PutLogEvents"]; Resource = "*" },
      { Effect = "Allow"; Action = ["elasticfilesystem:ClientMount","elasticfilesystem:ClientWrite"]; Resource = aws_efs_file_system.duckdb.arn },
    ]
  })
}

# ── CloudWatch Log Groups ──────────────────────────────────────────────────────
resource "aws_cloudwatch_log_group" "api"       { name = "/ecs/rpdf-api";       retention_in_days = 30; tags = local.tags }
resource "aws_cloudwatch_log_group" "dashboard"  { name = "/ecs/rpdf-dashboard"; retention_in_days = 30; tags = local.tags }

# ── ECS Task Definition — API ────────────────────────────────────────────────
resource "aws_ecs_task_definition" "api" {
  family                   = "rpdf-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_task.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  volume {
    name = "duckdb-efs"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.duckdb.id
      root_directory     = "/"
      transit_encryption = "ENABLED"
    }
  }

  container_definitions = jsonencode([{
    name  = "api"
    image = "${var.ecr_registry}/rpdf-api:${var.image_tag}"
    portMappings = [{ containerPort = 8000; protocol = "tcp" }]
    environment = [
      { name = "DUCKDB_PATH"; value = "/data/warehouse.duckdb" },
    ]
    secrets = [
      { name = "INSEE_TOKEN";              valueFrom = "arn:aws:secretsmanager:eu-west-3:${var.aws_account_id}:secret:rpdf/insee-token" },
      { name = "FRANCE_TRAVAIL_CLIENT_ID"; valueFrom = "arn:aws:secretsmanager:eu-west-3:${var.aws_account_id}:secret:rpdf/ft-client-id" },
      { name = "FRANCE_TRAVAIL_SECRET";    valueFrom = "arn:aws:secretsmanager:eu-west-3:${var.aws_account_id}:secret:rpdf/ft-secret" },
    ]
    mountPoints = [{ sourceVolume = "duckdb-efs"; containerPath = "/data"; readOnly = false }]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { "awslogs-group" = "/ecs/rpdf-api"; "awslogs-region" = "eu-west-3"; "awslogs-stream-prefix" = "ecs" }
    }
    healthCheck = { command = ["CMD-SHELL","curl -f http://localhost:8000/health || exit 1"]; interval = 30; timeout = 5; retries = 3 }
  }])
  tags = local.tags
}

# ── ECS Service — API ────────────────────────────────────────────────────────
resource "aws_ecs_service" "api" {
  name            = "rpdf-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.ecs.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  deployment_circuit_breaker { enable = true; rollback = true }
  tags = local.tags
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "alb_dns" {
  description = "DNS de l'ALB (à pointer dans Route 53)"
  value       = aws_lb.main.dns_name
}

output "datalake_bucket" {
  description = "Bucket S3 Data Lake"
  value       = aws_s3_bucket.datalake.bucket
}

output "ecs_cluster" {
  description = "Nom du cluster ECS"
  value       = aws_ecs_cluster.main.name
}
