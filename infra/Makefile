.PHONY: help validate deploy deploy-prod deploy-dev rollback rollback-prod rollback-dev logs status

help:
	@echo "AirSense MX — CloudFormation Commands"
	@echo "======================================"
	@echo ""
	@echo "Validación:"
	@echo "  make validate              Validar template CloudFormation"
	@echo ""
	@echo "Deploy:"
	@echo "  make deploy ENV=prod       Deploy a prod (default: dev)"
	@echo "  make deploy-prod           Deploy a producción"
	@echo "  make deploy-dev            Deploy a desarrollo"
	@echo ""
	@echo "Rollback:"
	@echo "  make rollback ENV=prod     Rollback (default: dev)"
	@echo "  make rollback-prod         Rollback de producción"
	@echo "  make rollback-dev          Rollback de desarrollo"
	@echo ""
	@echo "Monitoreo:"
	@echo "  make status ENV=prod       Ver estado del stack"
	@echo "  make logs                  Ver logs Streamlit (tail -f)"
	@echo "  make events ENV=prod       Ver eventos del stack"
	@echo ""

validate:
	@echo "Validando CloudFormation template..."
	aws cloudformation validate-template \
		--template-body file://infra/core.yaml \
		--region us-east-1
	@echo "✓ Template válido"

deploy: ENV=dev
deploy:
	@echo "Desplegando a $(ENV)..."
	./infra/deploy.sh $(ENV) us-east-1

deploy-prod:
	$(MAKE) deploy ENV=prod

deploy-dev:
	$(MAKE) deploy ENV=dev

rollback: ENV=dev
rollback:
	./infra/rollback.sh $(ENV) us-east-1

rollback-prod:
	$(MAKE) rollback ENV=prod

rollback-dev:
	$(MAKE) rollback ENV=dev

status: ENV=dev
status:
	@aws cloudformation describe-stacks \
		--stack-name airsense-mx-$(ENV) \
		--query 'Stacks[0].[StackName,StackStatus,LastUpdatedTime]' \
		--output table

logs:
	aws logs tail /airsense-mx/streamlit --follow

events: ENV=dev
events:
	aws cloudformation describe-stack-events \
		--stack-name airsense-mx-$(ENV) \
		--query 'StackEvents[].{Time:Timestamp,Type:ResourceType,Status:ResourceStatus,Reason:ResourceStatusReason}' \
		--output table

describe: ENV=dev
describe:
	aws cloudformation describe-stacks \
		--stack-name airsense-mx-$(ENV)

delete: ENV=dev
delete:
	@echo "⚠️  Esto eliminará el stack airsense-mx-$(ENV)"
	@read -p "¿Estás seguro? (sí/no): " confirm && \
	if [ "$$confirm" = "sí" ] || [ "$$confirm" = "yes" ]; then \
		aws cloudformation delete-stack --stack-name airsense-mx-$(ENV); \
		echo "✓ Stack marcado para eliminación"; \
	else \
		echo "Cancelado"; \
	fi
