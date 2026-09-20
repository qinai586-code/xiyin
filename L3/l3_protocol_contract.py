# -*- coding: utf-8 -*-

PROTOCOL_VERSION = "phase1.l3_contract.v1"
PHASE_SCOPE = "P1_PLACEHOLDER_ONLY"
APPROVED_CHAIN_ENTRY = "submit_to_chain(text, source)"

RUNTIME_ENABLED = False
WRITES_PERFORMED = False
SIDE_EFFECTS_ALLOWED = False
DIRECT_CORE_ACCESS_ALLOWED = False
DIRECT_MEMORY_COMMIT_ALLOWED = False
SERVICE_START_ALLOWED = False
PENDING_MODULE_BINDING_ALLOWED = False


def validate_l3_contract():
    return {
        "ok": True,
        "layer": "L3",
        "protocol_version": PROTOCOL_VERSION,
        "phase_scope": PHASE_SCOPE,
        "approved_chain_entry": APPROVED_CHAIN_ENTRY,
        "runtime_enabled": RUNTIME_ENABLED,
        "writes_performed": WRITES_PERFORMED,
        "side_effects_allowed": SIDE_EFFECTS_ALLOWED,
        "direct_core_access_allowed": DIRECT_CORE_ACCESS_ALLOWED,
        "direct_memory_commit_allowed": DIRECT_MEMORY_COMMIT_ALLOWED,
        "service_start_allowed": SERVICE_START_ALLOWED,
        "pending_module_binding_allowed": PENDING_MODULE_BINDING_ALLOWED,
    }
