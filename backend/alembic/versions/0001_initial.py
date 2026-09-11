"""Initial FleetBeat schema

Baseline covering every entity in Sections 4 and 4a of the product spec:
organizations and settings, users/auth/audit, vehicles, drivers and the
shared driver-event stream, GPS device inventory, trips and persisted
position history, geofences and POIs, maintenance, fuel, routing, tasks,
compliance, incidents, alerts and the AI layer.

Revision ID: 0001_initial
Revises:
Create Date: 2026-09-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('organizations',
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('slug', sa.String(length=200), nullable=False),
    sa.Column('industry', sa.String(length=120), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('contact_name', sa.String(length=200), nullable=True),
    sa.Column('contact_email', sa.String(length=320), nullable=True),
    sa.Column('contact_phone', sa.String(length=50), nullable=True),
    sa.Column('logo_url', sa.String(length=500), nullable=True),
    sa.Column('primary_color', sa.String(length=9), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('plan', sa.String(length=50), nullable=False),
    sa.Column('subscription_status', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('slug')
    )
    op.create_index(op.f('ix_organizations_name'), 'organizations', ['name'], unique=False)
    op.create_index(op.f('ix_organizations_status'), 'organizations', ['status'], unique=False)
    op.create_table('alert_rules',
    sa.Column('rule_type', sa.String(length=40), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('parameters', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('notify_roles', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'rule_type', name='uq_alert_rule_per_org')
    )
    op.create_index(op.f('ix_alert_rules_organization_id'), 'alert_rules', ['organization_id'], unique=False)
    op.create_table('organization_settings',
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('distance_unit', sa.String(length=8), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('show_leaderboard_to_drivers', sa.Boolean(), nullable=False),
    sa.Column('driver_points_baseline', sa.Integer(), nullable=False),
    sa.Column('point_weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('maintenance_auto_book_enabled', sa.Boolean(), nullable=False),
    sa.Column('alert_thresholds', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('co2_emission_factors', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_organization_settings_organization_id'), 'organization_settings', ['organization_id'], unique=True)
    op.create_table('report_summaries',
    sa.Column('period_type', sa.String(length=16), nullable=False),
    sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
    sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
    sa.Column('summary_text', sa.Text(), nullable=False),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('generated_by', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_report_summaries_organization_id'), 'report_summaries', ['organization_id'], unique=False)
    op.create_table('users',
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('hashed_password', sa.String(length=255), nullable=True),
    sa.Column('role', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('must_change_password', sa.Boolean(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('failed_login_count', sa.Integer(), nullable=False),
    sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_users_email')
    )
    op.create_index('ix_users_org_role', 'users', ['organization_id', 'role'], unique=False)
    op.create_index(op.f('ix_users_organization_id'), 'users', ['organization_id'], unique=False)
    op.create_index(op.f('ix_users_role'), 'users', ['role'], unique=False)
    op.create_table('vehicles',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('make', sa.String(length=80), nullable=True),
    sa.Column('model', sa.String(length=80), nullable=True),
    sa.Column('year', sa.Integer(), nullable=True),
    sa.Column('vin', sa.String(length=32), nullable=True),
    sa.Column('license_plate', sa.String(length=32), nullable=False),
    sa.Column('vehicle_type', sa.String(length=32), nullable=False),
    sa.Column('fuel_type', sa.String(length=32), nullable=False),
    sa.Column('ownership', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('odometer_km', sa.Float(), nullable=False),
    sa.Column('battery_capacity_kwh', sa.Float(), nullable=True),
    sa.Column('battery_level_percent', sa.Float(), nullable=True),
    sa.Column('ev_range_km', sa.Float(), nullable=True),
    sa.Column('purchase_date', sa.Date(), nullable=True),
    sa.Column('purchase_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('residual_value', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('useful_life_years', sa.Integer(), nullable=True),
    sa.Column('replacement_recommended', sa.Boolean(), nullable=False),
    sa.Column('ev_transition_candidate', sa.Boolean(), nullable=False),
    sa.Column('last_latitude', sa.Float(), nullable=True),
    sa.Column('last_longitude', sa.Float(), nullable=True),
    sa.Column('last_heading', sa.Float(), nullable=True),
    sa.Column('last_speed_kph', sa.Float(), nullable=True),
    sa.Column('last_position_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stopped_since', sa.DateTime(timezone=True), nullable=True),
    sa.Column('primary_driver_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('organization_id', 'license_plate', name='uq_vehicle_plate_per_org')
    )
    op.create_index('ix_vehicles_org_status', 'vehicles', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_vehicles_organization_id'), 'vehicles', ['organization_id'], unique=False)
    op.create_index(op.f('ix_vehicles_primary_driver_id'), 'vehicles', ['primary_driver_id'], unique=False)
    op.create_index(op.f('ix_vehicles_vin'), 'vehicles', ['vin'], unique=False)
    op.create_table('weather_zones',
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('radius_m', sa.Float(), nullable=False),
    sa.Column('condition', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('expected_delay_minutes', sa.Integer(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_weather_zones_organization_id'), 'weather_zones', ['organization_id'], unique=False)
    op.create_table('activation_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('purpose', sa.String(length=32), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('issued_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['issued_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_activation_tokens_token_hash'), 'activation_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_activation_tokens_user_id'), 'activation_tokens', ['user_id'], unique=False)
    op.create_table('assistant_conversations',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assistant_conversations_organization_id'), 'assistant_conversations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_assistant_conversations_user_id'), 'assistant_conversations', ['user_id'], unique=False)
    op.create_table('audit_logs',
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('actor_email', sa.String(length=320), nullable=True),
    sa.Column('actor_role', sa.String(length=32), nullable=True),
    sa.Column('impersonator_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=48), nullable=False),
    sa.Column('entity_type', sa.String(length=64), nullable=True),
    sa.Column('entity_id', sa.Uuid(), nullable=True),
    sa.Column('summary', sa.String(length=400), nullable=True),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('request_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['impersonator_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_action'), 'audit_logs', ['action'], unique=False)
    op.create_index('ix_audit_logs_actor_time', 'audit_logs', ['actor_user_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_actor_user_id'), 'audit_logs', ['actor_user_id'], unique=False)
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'], unique=False)
    op.create_index('ix_audit_logs_entity', 'audit_logs', ['entity_type', 'entity_id'], unique=False)
    op.create_index('ix_audit_logs_org_time', 'audit_logs', ['organization_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_audit_logs_organization_id'), 'audit_logs', ['organization_id'], unique=False)
    op.create_table('devices',
    sa.Column('serial_number', sa.String(length=64), nullable=False),
    sa.Column('imei', sa.String(length=32), nullable=True),
    sa.Column('model', sa.String(length=120), nullable=True),
    sa.Column('firmware_version', sa.String(length=64), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('assigned_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_signal_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_devices_imei'), 'devices', ['imei'], unique=True)
    op.create_index(op.f('ix_devices_organization_id'), 'devices', ['organization_id'], unique=False)
    op.create_index(op.f('ix_devices_serial_number'), 'devices', ['serial_number'], unique=True)
    op.create_index(op.f('ix_devices_status'), 'devices', ['status'], unique=False)
    op.create_index(op.f('ix_devices_vehicle_id'), 'devices', ['vehicle_id'], unique=True)
    op.create_table('drivers',
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('full_name', sa.String(length=200), nullable=False),
    sa.Column('employee_number', sa.String(length=64), nullable=True),
    sa.Column('phone', sa.String(length=50), nullable=True),
    sa.Column('license_number', sa.String(length=64), nullable=True),
    sa.Column('license_class', sa.String(length=32), nullable=True),
    sa.Column('license_expiry', sa.Date(), nullable=True),
    sa.Column('employment_status', sa.String(length=32), nullable=False),
    sa.Column('hired_on', sa.Date(), nullable=True),
    sa.Column('assigned_vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('safety_score', sa.Float(), nullable=False),
    sa.Column('fatigue_risk_level', sa.String(length=16), nullable=False),
    sa.Column('fatigue_computed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('points_balance', sa.Integer(), nullable=False),
    sa.Column('points_month', sa.String(length=7), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['assigned_vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_drivers_assigned_vehicle_id'), 'drivers', ['assigned_vehicle_id'], unique=False)
    op.create_index(op.f('ix_drivers_license_expiry'), 'drivers', ['license_expiry'], unique=False)
    op.create_index('ix_drivers_org_status', 'drivers', ['organization_id', 'employment_status'], unique=False)
    op.create_index(op.f('ix_drivers_organization_id'), 'drivers', ['organization_id'], unique=False)
    op.create_index(op.f('ix_drivers_points_month'), 'drivers', ['points_month'], unique=False)
    op.create_index(op.f('ix_drivers_user_id'), 'drivers', ['user_id'], unique=True)
    op.create_table('geofences',
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('shape', sa.String(length=16), nullable=False),
    sa.Column('geometry', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('color', sa.String(length=9), nullable=False),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('vehicle_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_geofences_organization_id'), 'geofences', ['organization_id'], unique=False)
    op.create_table('known_devices',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('fingerprint', sa.String(length=128), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('last_ip', sa.String(length=64), nullable=True),
    sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'fingerprint', name='uq_known_device')
    )
    op.create_index(op.f('ix_known_devices_user_id'), 'known_devices', ['user_id'], unique=False)
    op.create_table('login_attempts',
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('successful', sa.Boolean(), nullable=False),
    sa.Column('ip_address', sa.String(length=64), nullable=True),
    sa.Column('user_agent', sa.String(length=500), nullable=True),
    sa.Column('device_fingerprint', sa.String(length=128), nullable=True),
    sa.Column('suspicious', sa.Boolean(), nullable=False),
    sa.Column('suspicion_reason', sa.String(length=200), nullable=True),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_attempts_device_fingerprint'), 'login_attempts', ['device_fingerprint'], unique=False)
    op.create_index('ix_login_attempts_email_time', 'login_attempts', ['email', 'attempted_at'], unique=False)
    op.create_index(op.f('ix_login_attempts_user_id'), 'login_attempts', ['user_id'], unique=False)
    op.create_table('maintenance_schedules',
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('component', sa.String(length=120), nullable=True),
    sa.Column('interval_type', sa.String(length=16), nullable=False),
    sa.Column('interval_km', sa.Float(), nullable=True),
    sa.Column('interval_days', sa.Integer(), nullable=True),
    sa.Column('last_service_odometer_km', sa.Float(), nullable=True),
    sa.Column('last_service_date', sa.Date(), nullable=True),
    sa.Column('next_due_odometer_km', sa.Float(), nullable=True),
    sa.Column('next_due_date', sa.Date(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_maintenance_schedules_next_due_date'), 'maintenance_schedules', ['next_due_date'], unique=False)
    op.create_index(op.f('ix_maintenance_schedules_organization_id'), 'maintenance_schedules', ['organization_id'], unique=False)
    op.create_index(op.f('ix_maintenance_schedules_vehicle_id'), 'maintenance_schedules', ['vehicle_id'], unique=False)
    op.create_table('points_of_interest',
    sa.Column('name', sa.String(length=160), nullable=False),
    sa.Column('category', sa.String(length=32), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('address', sa.String(length=400), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_points_of_interest_category'), 'points_of_interest', ['category'], unique=False)
    op.create_index(op.f('ix_points_of_interest_organization_id'), 'points_of_interest', ['organization_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('impersonated_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['impersonated_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_refresh_tokens_token_hash'), 'refresh_tokens', ['token_hash'], unique=True)
    op.create_index(op.f('ix_refresh_tokens_user_id'), 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('road_closures',
    sa.Column('label', sa.String(length=200), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('radius_m', sa.Float(), nullable=False),
    sa.Column('active_from', sa.DateTime(timezone=True), nullable=True),
    sa.Column('active_until', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_road_closures_organization_id'), 'road_closures', ['organization_id'], unique=False)
    op.create_table('alerts',
    sa.Column('rule_type', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('subject_type', sa.String(length=40), nullable=True),
    sa.Column('subject_id', sa.Uuid(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('acknowledged_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['acknowledged_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_alerts_dedupe', 'alerts', ['organization_id', 'dedupe_key'], unique=False)
    op.create_index(op.f('ix_alerts_driver_id'), 'alerts', ['driver_id'], unique=False)
    op.create_index('ix_alerts_org_status_time', 'alerts', ['organization_id', 'status', 'created_at'], unique=False)
    op.create_index(op.f('ix_alerts_organization_id'), 'alerts', ['organization_id'], unique=False)
    op.create_index(op.f('ix_alerts_rule_type'), 'alerts', ['rule_type'], unique=False)
    op.create_index(op.f('ix_alerts_status'), 'alerts', ['status'], unique=False)
    op.create_index(op.f('ix_alerts_vehicle_id'), 'alerts', ['vehicle_id'], unique=False)
    op.create_table('assistant_messages',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('intent', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('pending_action', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['assistant_conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_assistant_messages_conversation_id'), 'assistant_messages', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_assistant_messages_organization_id'), 'assistant_messages', ['organization_id'], unique=False)
    op.create_table('compliance_documents',
    sa.Column('document_type', sa.String(length=32), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('reference_number', sa.String(length=120), nullable=True),
    sa.Column('issuer', sa.String(length=200), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('issued_on', sa.Date(), nullable=True),
    sa.Column('expires_on', sa.Date(), nullable=True),
    sa.Column('cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('file_url', sa.String(length=500), nullable=True),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('uploaded_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_compliance_documents_driver_id'), 'compliance_documents', ['driver_id'], unique=False)
    op.create_index(op.f('ix_compliance_documents_expires_on'), 'compliance_documents', ['expires_on'], unique=False)
    op.create_index('ix_compliance_documents_org_expiry', 'compliance_documents', ['organization_id', 'expires_on'], unique=False)
    op.create_index(op.f('ix_compliance_documents_organization_id'), 'compliance_documents', ['organization_id'], unique=False)
    op.create_index(op.f('ix_compliance_documents_vehicle_id'), 'compliance_documents', ['vehicle_id'], unique=False)
    op.create_table('driver_badges',
    sa.Column('driver_id', sa.Uuid(), nullable=False),
    sa.Column('badge_code', sa.String(length=64), nullable=False),
    sa.Column('period_month', sa.String(length=7), nullable=False),
    sa.Column('awarded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('driver_id', 'badge_code', 'period_month', name='uq_driver_badge_period')
    )
    op.create_index(op.f('ix_driver_badges_driver_id'), 'driver_badges', ['driver_id'], unique=False)
    op.create_index(op.f('ix_driver_badges_organization_id'), 'driver_badges', ['organization_id'], unique=False)
    op.create_table('fuel_logs',
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('fuel_type', sa.String(length=24), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('unit', sa.String(length=8), nullable=False),
    sa.Column('unit_price', sa.Numeric(precision=12, scale=4), nullable=True),
    sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('odometer_km', sa.Float(), nullable=True),
    sa.Column('filled_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('location_name', sa.String(length=200), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('battery_level_after', sa.Float(), nullable=True),
    sa.Column('co2_kg', sa.Float(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_fuel_logs_driver_id'), 'fuel_logs', ['driver_id'], unique=False)
    op.create_index(op.f('ix_fuel_logs_filled_at'), 'fuel_logs', ['filled_at'], unique=False)
    op.create_index(op.f('ix_fuel_logs_organization_id'), 'fuel_logs', ['organization_id'], unique=False)
    op.create_index(op.f('ix_fuel_logs_vehicle_id'), 'fuel_logs', ['vehicle_id'], unique=False)
    op.create_index('ix_fuel_logs_vehicle_time', 'fuel_logs', ['vehicle_id', 'filled_at'], unique=False)
    op.create_table('geofence_events',
    sa.Column('geofence_id', sa.Uuid(), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('direction', sa.String(length=8), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['geofence_id'], ['geofences.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_geofence_events_geofence_id'), 'geofence_events', ['geofence_id'], unique=False)
    op.create_index('ix_geofence_events_org_time', 'geofence_events', ['organization_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_geofence_events_organization_id'), 'geofence_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_geofence_events_vehicle_id'), 'geofence_events', ['vehicle_id'], unique=False)
    op.create_table('routes',
    sa.Column('name', sa.String(length=200), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('origin_latitude', sa.Float(), nullable=False),
    sa.Column('origin_longitude', sa.Float(), nullable=False),
    sa.Column('destination_latitude', sa.Float(), nullable=False),
    sa.Column('destination_longitude', sa.Float(), nullable=False),
    sa.Column('distance_km', sa.Float(), nullable=True),
    sa.Column('duration_seconds', sa.Integer(), nullable=True),
    sa.Column('geometry_polyline', sa.Text(), nullable=True),
    sa.Column('planned_departure_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('eta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('replaced_route_id', sa.Uuid(), nullable=True),
    sa.Column('reroute_reason', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['replaced_route_id'], ['routes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_routes_driver_id'), 'routes', ['driver_id'], unique=False)
    op.create_index(op.f('ix_routes_organization_id'), 'routes', ['organization_id'], unique=False)
    op.create_index(op.f('ix_routes_task_id'), 'routes', ['task_id'], unique=False)
    op.create_index(op.f('ix_routes_vehicle_id'), 'routes', ['vehicle_id'], unique=False)
    op.create_table('trips',
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('start_latitude', sa.Float(), nullable=True),
    sa.Column('start_longitude', sa.Float(), nullable=True),
    sa.Column('end_latitude', sa.Float(), nullable=True),
    sa.Column('end_longitude', sa.Float(), nullable=True),
    sa.Column('distance_km', sa.Float(), nullable=False),
    sa.Column('duration_seconds', sa.Integer(), nullable=False),
    sa.Column('average_speed_kph', sa.Float(), nullable=False),
    sa.Column('max_speed_kph', sa.Float(), nullable=False),
    sa.Column('idle_seconds', sa.Integer(), nullable=False),
    sa.Column('start_odometer_km', sa.Float(), nullable=True),
    sa.Column('end_odometer_km', sa.Float(), nullable=True),
    sa.Column('estimated_fuel_litres', sa.Float(), nullable=True),
    sa.Column('estimated_co2_kg', sa.Float(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_trips_driver_id'), 'trips', ['driver_id'], unique=False)
    op.create_index('ix_trips_org_start', 'trips', ['organization_id', 'started_at'], unique=False)
    op.create_index(op.f('ix_trips_organization_id'), 'trips', ['organization_id'], unique=False)
    op.create_index(op.f('ix_trips_status'), 'trips', ['status'], unique=False)
    op.create_index(op.f('ix_trips_task_id'), 'trips', ['task_id'], unique=False)
    op.create_index(op.f('ix_trips_vehicle_id'), 'trips', ['vehicle_id'], unique=False)
    op.create_index('ix_trips_vehicle_start', 'trips', ['vehicle_id', 'started_at'], unique=False)
    op.create_table('work_orders',
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('schedule_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('odometer_km', sa.Float(), nullable=True),
    sa.Column('labour_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('parts_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('vendor', sa.String(length=200), nullable=True),
    sa.Column('created_by_copilot', sa.Boolean(), nullable=False),
    sa.Column('copilot_rationale', sa.Text(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['schedule_id'], ['maintenance_schedules.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_work_orders_org_status', 'work_orders', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_work_orders_organization_id'), 'work_orders', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_orders_vehicle_id'), 'work_orders', ['vehicle_id'], unique=False)
    op.create_table('driver_events',
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('trip_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(length=40), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('speed_kph', sa.Float(), nullable=True),
    sa.Column('magnitude', sa.Float(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('points_applied', sa.Boolean(), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_driver_events_driver_id'), 'driver_events', ['driver_id'], unique=False)
    op.create_index('ix_driver_events_driver_time', 'driver_events', ['driver_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_driver_events_event_type'), 'driver_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_driver_events_occurred_at'), 'driver_events', ['occurred_at'], unique=False)
    op.create_index('ix_driver_events_org_time', 'driver_events', ['organization_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_driver_events_organization_id'), 'driver_events', ['organization_id'], unique=False)
    op.create_index(op.f('ix_driver_events_points_applied'), 'driver_events', ['points_applied'], unique=False)
    op.create_index(op.f('ix_driver_events_trip_id'), 'driver_events', ['trip_id'], unique=False)
    op.create_index(op.f('ix_driver_events_vehicle_id'), 'driver_events', ['vehicle_id'], unique=False)
    op.create_table('position_samples',
    sa.Column('trip_id', sa.Uuid(), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('speed_kph', sa.Float(), nullable=False),
    sa.Column('heading', sa.Float(), nullable=False),
    sa.Column('altitude_m', sa.Float(), nullable=True),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('ignition_on', sa.Boolean(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('source', sa.String(length=32), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_position_samples_organization_id'), 'position_samples', ['organization_id'], unique=False)
    op.create_index(op.f('ix_position_samples_trip_id'), 'position_samples', ['trip_id'], unique=False)
    op.create_index('ix_position_samples_trip_time', 'position_samples', ['trip_id', 'recorded_at'], unique=False)
    op.create_index(op.f('ix_position_samples_vehicle_id'), 'position_samples', ['vehicle_id'], unique=False)
    op.create_index('ix_position_samples_vehicle_time', 'position_samples', ['vehicle_id', 'recorded_at'], unique=False)
    op.create_table('route_stops',
    sa.Column('route_id', sa.Uuid(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=200), nullable=True),
    sa.Column('latitude', sa.Float(), nullable=False),
    sa.Column('longitude', sa.Float(), nullable=False),
    sa.Column('planned_arrival_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('actual_arrival_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('poi_id', sa.Uuid(), nullable=True),
    sa.Column('metadata_json', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['poi_id'], ['points_of_interest.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_route_stops_organization_id'), 'route_stops', ['organization_id'], unique=False)
    op.create_index(op.f('ix_route_stops_route_id'), 'route_stops', ['route_id'], unique=False)
    op.create_index('ix_route_stops_route_seq', 'route_stops', ['route_id', 'sequence'], unique=False)
    op.create_table('service_records',
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('work_order_id', sa.Uuid(), nullable=True),
    sa.Column('performed_on', sa.Date(), nullable=False),
    sa.Column('odometer_km', sa.Float(), nullable=True),
    sa.Column('summary', sa.String(length=400), nullable=False),
    sa.Column('total_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_service_records_organization_id'), 'service_records', ['organization_id'], unique=False)
    op.create_index(op.f('ix_service_records_performed_on'), 'service_records', ['performed_on'], unique=False)
    op.create_index(op.f('ix_service_records_vehicle_id'), 'service_records', ['vehicle_id'], unique=False)
    op.create_table('tasks',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('task_type', sa.String(length=24), nullable=False),
    sa.Column('priority', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('destination_label', sa.String(length=300), nullable=True),
    sa.Column('destination_latitude', sa.Float(), nullable=False),
    sa.Column('destination_longitude', sa.Float(), nullable=False),
    sa.Column('waypoints', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('due_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('eta', sa.DateTime(timezone=True), nullable=True),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancellation_reason', sa.String(length=300), nullable=True),
    sa.Column('completion_note', sa.Text(), nullable=True),
    sa.Column('completion_photo_url', sa.String(length=500), nullable=True),
    sa.Column('route_id', sa.Uuid(), nullable=True),
    sa.Column('trip_id', sa.Uuid(), nullable=True),
    sa.Column('created_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['route_id'], ['routes.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_tasks_driver_id'), 'tasks', ['driver_id'], unique=False)
    op.create_index('ix_tasks_driver_status', 'tasks', ['driver_id', 'status'], unique=False)
    op.create_index('ix_tasks_org_status', 'tasks', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_tasks_organization_id'), 'tasks', ['organization_id'], unique=False)
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)
    op.create_index(op.f('ix_tasks_vehicle_id'), 'tasks', ['vehicle_id'], unique=False)
    op.create_table('work_order_parts',
    sa.Column('work_order_id', sa.Uuid(), nullable=False),
    sa.Column('part_number', sa.String(length=80), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('quantity', sa.Float(), nullable=False),
    sa.Column('unit_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_work_order_parts_organization_id'), 'work_order_parts', ['organization_id'], unique=False)
    op.create_index(op.f('ix_work_order_parts_work_order_id'), 'work_order_parts', ['work_order_id'], unique=False)
    op.create_table('incidents',
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('trip_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('work_order_id', sa.Uuid(), nullable=True),
    sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('latitude', sa.Float(), nullable=True),
    sa.Column('longitude', sa.Float(), nullable=True),
    sa.Column('location_label', sa.String(length=300), nullable=True),
    sa.Column('estimated_cost', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('reported_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reported_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['trip_id'], ['trips.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['work_order_id'], ['work_orders.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incidents_driver_id'), 'incidents', ['driver_id'], unique=False)
    op.create_index('ix_incidents_org_time', 'incidents', ['organization_id', 'occurred_at'], unique=False)
    op.create_index(op.f('ix_incidents_organization_id'), 'incidents', ['organization_id'], unique=False)
    op.create_index(op.f('ix_incidents_vehicle_id'), 'incidents', ['vehicle_id'], unique=False)
    op.create_table('points_ledger_entries',
    sa.Column('driver_id', sa.Uuid(), nullable=False),
    sa.Column('driver_event_id', sa.Uuid(), nullable=True),
    sa.Column('delta', sa.Integer(), nullable=False),
    sa.Column('balance_after', sa.Integer(), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=False),
    sa.Column('period_month', sa.String(length=7), nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_event_id'], ['driver_events.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_points_ledger_driver_time', 'points_ledger_entries', ['driver_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_points_ledger_entries_driver_id'), 'points_ledger_entries', ['driver_id'], unique=False)
    op.create_index(op.f('ix_points_ledger_entries_organization_id'), 'points_ledger_entries', ['organization_id'], unique=False)
    op.create_index(op.f('ix_points_ledger_entries_period_month'), 'points_ledger_entries', ['period_month'], unique=False)
    op.create_table('pre_trip_inspections',
    sa.Column('driver_id', sa.Uuid(), nullable=False),
    sa.Column('vehicle_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('items', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('passed', sa.Boolean(), nullable=False),
    sa.Column('odometer_km', sa.Float(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_pre_trip_inspections_driver_id'), 'pre_trip_inspections', ['driver_id'], unique=False)
    op.create_index(op.f('ix_pre_trip_inspections_organization_id'), 'pre_trip_inspections', ['organization_id'], unique=False)
    op.create_index(op.f('ix_pre_trip_inspections_vehicle_id'), 'pre_trip_inspections', ['vehicle_id'], unique=False)
    op.create_table('recommendations',
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=24), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('summary', sa.Text(), nullable=False),
    sa.Column('suggested_action', sa.Text(), nullable=True),
    sa.Column('estimated_benefit', sa.String(length=200), nullable=True),
    sa.Column('action_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('signals', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('vehicle_id', sa.Uuid(), nullable=True),
    sa.Column('driver_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('dedupe_key', sa.String(length=200), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('decided_by_user_id', sa.Uuid(), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['driver_id'], ['drivers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vehicle_id'], ['vehicles.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_recommendations_dedupe', 'recommendations', ['organization_id', 'dedupe_key'], unique=False)
    op.create_index(op.f('ix_recommendations_driver_id'), 'recommendations', ['driver_id'], unique=False)
    op.create_index(op.f('ix_recommendations_kind'), 'recommendations', ['kind'], unique=False)
    op.create_index('ix_recommendations_org_status', 'recommendations', ['organization_id', 'status'], unique=False)
    op.create_index(op.f('ix_recommendations_organization_id'), 'recommendations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_recommendations_vehicle_id'), 'recommendations', ['vehicle_id'], unique=False)
    op.create_table('incident_photos',
    sa.Column('incident_id', sa.Uuid(), nullable=False),
    sa.Column('file_url', sa.String(length=500), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=True),
    sa.Column('caption', sa.String(length=300), nullable=True),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('organization_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['incident_id'], ['incidents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_incident_photos_incident_id'), 'incident_photos', ['incident_id'], unique=False)
    op.create_index(op.f('ix_incident_photos_organization_id'), 'incident_photos', ['organization_id'], unique=False)
    op.create_foreign_key('fk_routes_task_id', 'routes', 'tasks', ['task_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_trips_task_id', 'trips', 'tasks', ['task_id'], ['id'], ondelete='SET NULL')
    op.create_foreign_key('fk_vehicles_primary_driver_id', 'vehicles', 'drivers', ['primary_driver_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_routes_x', 'routes', type_='foreignkey')
    op.drop_constraint('fk_trips_x', 'trips', type_='foreignkey')
    op.drop_constraint('fk_vehicles_x', 'vehicles', type_='foreignkey')
    op.drop_index(op.f('ix_incident_photos_incident_id'), table_name='incident_photos')
    op.drop_index(op.f('ix_incident_photos_organization_id'), table_name='incident_photos')
    op.drop_table('incident_photos')
    op.drop_index('ix_recommendations_dedupe', table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_driver_id'), table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_kind'), table_name='recommendations')
    op.drop_index('ix_recommendations_org_status', table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_organization_id'), table_name='recommendations')
    op.drop_index(op.f('ix_recommendations_vehicle_id'), table_name='recommendations')
    op.drop_table('recommendations')
    op.drop_index(op.f('ix_pre_trip_inspections_driver_id'), table_name='pre_trip_inspections')
    op.drop_index(op.f('ix_pre_trip_inspections_organization_id'), table_name='pre_trip_inspections')
    op.drop_index(op.f('ix_pre_trip_inspections_vehicle_id'), table_name='pre_trip_inspections')
    op.drop_table('pre_trip_inspections')
    op.drop_index('ix_points_ledger_driver_time', table_name='points_ledger_entries')
    op.drop_index(op.f('ix_points_ledger_entries_driver_id'), table_name='points_ledger_entries')
    op.drop_index(op.f('ix_points_ledger_entries_organization_id'), table_name='points_ledger_entries')
    op.drop_index(op.f('ix_points_ledger_entries_period_month'), table_name='points_ledger_entries')
    op.drop_table('points_ledger_entries')
    op.drop_index(op.f('ix_incidents_driver_id'), table_name='incidents')
    op.drop_index('ix_incidents_org_time', table_name='incidents')
    op.drop_index(op.f('ix_incidents_organization_id'), table_name='incidents')
    op.drop_index(op.f('ix_incidents_vehicle_id'), table_name='incidents')
    op.drop_table('incidents')
    op.drop_index(op.f('ix_work_order_parts_organization_id'), table_name='work_order_parts')
    op.drop_index(op.f('ix_work_order_parts_work_order_id'), table_name='work_order_parts')
    op.drop_table('work_order_parts')
    op.drop_index(op.f('ix_tasks_driver_id'), table_name='tasks')
    op.drop_index('ix_tasks_driver_status', table_name='tasks')
    op.drop_index('ix_tasks_org_status', table_name='tasks')
    op.drop_index(op.f('ix_tasks_organization_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_status'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_vehicle_id'), table_name='tasks')
    op.drop_table('tasks')
    op.drop_index(op.f('ix_service_records_organization_id'), table_name='service_records')
    op.drop_index(op.f('ix_service_records_performed_on'), table_name='service_records')
    op.drop_index(op.f('ix_service_records_vehicle_id'), table_name='service_records')
    op.drop_table('service_records')
    op.drop_index(op.f('ix_route_stops_organization_id'), table_name='route_stops')
    op.drop_index(op.f('ix_route_stops_route_id'), table_name='route_stops')
    op.drop_index('ix_route_stops_route_seq', table_name='route_stops')
    op.drop_table('route_stops')
    op.drop_index(op.f('ix_position_samples_organization_id'), table_name='position_samples')
    op.drop_index(op.f('ix_position_samples_trip_id'), table_name='position_samples')
    op.drop_index('ix_position_samples_trip_time', table_name='position_samples')
    op.drop_index(op.f('ix_position_samples_vehicle_id'), table_name='position_samples')
    op.drop_index('ix_position_samples_vehicle_time', table_name='position_samples')
    op.drop_table('position_samples')
    op.drop_index(op.f('ix_driver_events_driver_id'), table_name='driver_events')
    op.drop_index('ix_driver_events_driver_time', table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_event_type'), table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_occurred_at'), table_name='driver_events')
    op.drop_index('ix_driver_events_org_time', table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_organization_id'), table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_points_applied'), table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_trip_id'), table_name='driver_events')
    op.drop_index(op.f('ix_driver_events_vehicle_id'), table_name='driver_events')
    op.drop_table('driver_events')
    op.drop_index('ix_work_orders_org_status', table_name='work_orders')
    op.drop_index(op.f('ix_work_orders_organization_id'), table_name='work_orders')
    op.drop_index(op.f('ix_work_orders_vehicle_id'), table_name='work_orders')
    op.drop_table('work_orders')
    op.drop_index(op.f('ix_trips_driver_id'), table_name='trips')
    op.drop_index('ix_trips_org_start', table_name='trips')
    op.drop_index(op.f('ix_trips_organization_id'), table_name='trips')
    op.drop_index(op.f('ix_trips_status'), table_name='trips')
    op.drop_index(op.f('ix_trips_task_id'), table_name='trips')
    op.drop_index(op.f('ix_trips_vehicle_id'), table_name='trips')
    op.drop_index('ix_trips_vehicle_start', table_name='trips')
    op.drop_table('trips')
    op.drop_index(op.f('ix_routes_driver_id'), table_name='routes')
    op.drop_index(op.f('ix_routes_organization_id'), table_name='routes')
    op.drop_index(op.f('ix_routes_task_id'), table_name='routes')
    op.drop_index(op.f('ix_routes_vehicle_id'), table_name='routes')
    op.drop_table('routes')
    op.drop_index(op.f('ix_geofence_events_geofence_id'), table_name='geofence_events')
    op.drop_index('ix_geofence_events_org_time', table_name='geofence_events')
    op.drop_index(op.f('ix_geofence_events_organization_id'), table_name='geofence_events')
    op.drop_index(op.f('ix_geofence_events_vehicle_id'), table_name='geofence_events')
    op.drop_table('geofence_events')
    op.drop_index(op.f('ix_fuel_logs_driver_id'), table_name='fuel_logs')
    op.drop_index(op.f('ix_fuel_logs_filled_at'), table_name='fuel_logs')
    op.drop_index(op.f('ix_fuel_logs_organization_id'), table_name='fuel_logs')
    op.drop_index(op.f('ix_fuel_logs_vehicle_id'), table_name='fuel_logs')
    op.drop_index('ix_fuel_logs_vehicle_time', table_name='fuel_logs')
    op.drop_table('fuel_logs')
    op.drop_index(op.f('ix_driver_badges_driver_id'), table_name='driver_badges')
    op.drop_index(op.f('ix_driver_badges_organization_id'), table_name='driver_badges')
    op.drop_table('driver_badges')
    op.drop_index(op.f('ix_compliance_documents_driver_id'), table_name='compliance_documents')
    op.drop_index(op.f('ix_compliance_documents_expires_on'), table_name='compliance_documents')
    op.drop_index('ix_compliance_documents_org_expiry', table_name='compliance_documents')
    op.drop_index(op.f('ix_compliance_documents_organization_id'), table_name='compliance_documents')
    op.drop_index(op.f('ix_compliance_documents_vehicle_id'), table_name='compliance_documents')
    op.drop_table('compliance_documents')
    op.drop_index(op.f('ix_assistant_messages_conversation_id'), table_name='assistant_messages')
    op.drop_index(op.f('ix_assistant_messages_organization_id'), table_name='assistant_messages')
    op.drop_table('assistant_messages')
    op.drop_index('ix_alerts_dedupe', table_name='alerts')
    op.drop_index(op.f('ix_alerts_driver_id'), table_name='alerts')
    op.drop_index('ix_alerts_org_status_time', table_name='alerts')
    op.drop_index(op.f('ix_alerts_organization_id'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_rule_type'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_status'), table_name='alerts')
    op.drop_index(op.f('ix_alerts_vehicle_id'), table_name='alerts')
    op.drop_table('alerts')
    op.drop_index(op.f('ix_road_closures_organization_id'), table_name='road_closures')
    op.drop_table('road_closures')
    op.drop_index(op.f('ix_refresh_tokens_token_hash'), table_name='refresh_tokens')
    op.drop_index(op.f('ix_refresh_tokens_user_id'), table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index(op.f('ix_points_of_interest_category'), table_name='points_of_interest')
    op.drop_index(op.f('ix_points_of_interest_organization_id'), table_name='points_of_interest')
    op.drop_table('points_of_interest')
    op.drop_index(op.f('ix_maintenance_schedules_next_due_date'), table_name='maintenance_schedules')
    op.drop_index(op.f('ix_maintenance_schedules_organization_id'), table_name='maintenance_schedules')
    op.drop_index(op.f('ix_maintenance_schedules_vehicle_id'), table_name='maintenance_schedules')
    op.drop_table('maintenance_schedules')
    op.drop_index(op.f('ix_login_attempts_device_fingerprint'), table_name='login_attempts')
    op.drop_index('ix_login_attempts_email_time', table_name='login_attempts')
    op.drop_index(op.f('ix_login_attempts_user_id'), table_name='login_attempts')
    op.drop_table('login_attempts')
    op.drop_index(op.f('ix_known_devices_user_id'), table_name='known_devices')
    op.drop_table('known_devices')
    op.drop_index(op.f('ix_geofences_organization_id'), table_name='geofences')
    op.drop_table('geofences')
    op.drop_index(op.f('ix_drivers_assigned_vehicle_id'), table_name='drivers')
    op.drop_index(op.f('ix_drivers_license_expiry'), table_name='drivers')
    op.drop_index('ix_drivers_org_status', table_name='drivers')
    op.drop_index(op.f('ix_drivers_organization_id'), table_name='drivers')
    op.drop_index(op.f('ix_drivers_points_month'), table_name='drivers')
    op.drop_index(op.f('ix_drivers_user_id'), table_name='drivers')
    op.drop_table('drivers')
    op.drop_index(op.f('ix_devices_imei'), table_name='devices')
    op.drop_index(op.f('ix_devices_organization_id'), table_name='devices')
    op.drop_index(op.f('ix_devices_serial_number'), table_name='devices')
    op.drop_index(op.f('ix_devices_status'), table_name='devices')
    op.drop_index(op.f('ix_devices_vehicle_id'), table_name='devices')
    op.drop_table('devices')
    op.drop_index(op.f('ix_audit_logs_action'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_actor_time', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_actor_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index('ix_audit_logs_entity', table_name='audit_logs')
    op.drop_index('ix_audit_logs_org_time', table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_organization_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
    op.drop_index(op.f('ix_assistant_conversations_organization_id'), table_name='assistant_conversations')
    op.drop_index(op.f('ix_assistant_conversations_user_id'), table_name='assistant_conversations')
    op.drop_table('assistant_conversations')
    op.drop_index(op.f('ix_activation_tokens_token_hash'), table_name='activation_tokens')
    op.drop_index(op.f('ix_activation_tokens_user_id'), table_name='activation_tokens')
    op.drop_table('activation_tokens')
    op.drop_index(op.f('ix_weather_zones_organization_id'), table_name='weather_zones')
    op.drop_table('weather_zones')
    op.drop_index('ix_vehicles_org_status', table_name='vehicles')
    op.drop_index(op.f('ix_vehicles_organization_id'), table_name='vehicles')
    op.drop_index(op.f('ix_vehicles_primary_driver_id'), table_name='vehicles')
    op.drop_index(op.f('ix_vehicles_vin'), table_name='vehicles')
    op.drop_table('vehicles')
    op.drop_index('ix_users_org_role', table_name='users')
    op.drop_index(op.f('ix_users_organization_id'), table_name='users')
    op.drop_index(op.f('ix_users_role'), table_name='users')
    op.drop_table('users')
    op.drop_index(op.f('ix_report_summaries_organization_id'), table_name='report_summaries')
    op.drop_table('report_summaries')
    op.drop_index(op.f('ix_organization_settings_organization_id'), table_name='organization_settings')
    op.drop_table('organization_settings')
    op.drop_index(op.f('ix_alert_rules_organization_id'), table_name='alert_rules')
    op.drop_table('alert_rules')
    op.drop_index(op.f('ix_organizations_name'), table_name='organizations')
    op.drop_index(op.f('ix_organizations_status'), table_name='organizations')
    op.drop_table('organizations')
