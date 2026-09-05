"""
Core Data Registry and Offline Fallbacks for Ledger402.
Calibrated for Port of Singapore (SGSIN) Congestion & Supply Chain Analysis.
"""

PROVIDERS_REGISTRY = {
    "public_port_stats": {
        "price_drops": 0,
        "freshness_hours": 72,
        "quality_score": 0.62,
        "endpoint": "/api/b2b/public-stats",
        "description": "Maritime and Port Authority of Singapore (MPA) Public Aggregate",
        "license": "Open Data Commons - PDDL (Free Open Access)",
        "payload": {
            "port_code": "SGSIN",
            "facility_name": "Port of Singapore (PSA Multi-Terminal)",
            "timestamp": "2026-09-02T08:00:00Z",
            "data_vintage": "72_HOURS_STALE",
            "metrics": {
                "berth_occupancy_ratio": 0.68,
                "average_wait_hours": 18.2,
                "vessel_queue_count": 24,
                "schedule_reliability_pct": 56.4
            },
            "signals_provided": ["berth_occupancy", "wait_hours", "vessel_queue"],
            "analyst_note": "Lagging monthly averages mask localized yard and berth bottlenecks."
        }
    },
    "satellite_logistics_paid": {
        "price_drops": 1200,
        "freshness_hours": 3,
        "quality_score": 0.93,
        "endpoint": "/api/b2b/satellite-logistics",
        "description": "Synthetic Aperture Radar (SAR) & AIS Optical Yard Telemetry",
        "license": "ODRL; AI_INFERENCE_COMMERCIAL_USE; NO_REDISTRIBUTION",
        "payload": {
            "port_code": "SGSIN",
            "observation_window_utc": "2026-09-05T03:00:00Z",
            "metrics": {
                "anchored_vessels_count": 52,
                "container_yard_utilization_ratio": 0.89,
                "container_density_index": 0.94,
                "truck_turnaround_hours": 4.8,
                "anchorage_hotspots": ["Eastern Anchorage (AEW)", "Western Petroleum (APW)"],
                "backlog_teu_estimated": 450000
            },
            "signals_provided": ["yard_utilization", "anchored_vessels", "container_density", "truck_activity"],
            "analyst_note": "Critical yard saturation. Stack density is slowing gantry operations."
        }
    },
    "terminal_telemetry_paid": {
        "price_drops": 600,
        "freshness_hours": 6,
        "quality_score": 0.81,
        "endpoint": "/api/b2b/terminal-telemetry",
        "description": "Port Gate Optical Character & Intermodal Gantry Sensor Feeds",
        "license": "ODRL; AI_INFERENCE_COMMERCIAL_USE; EPHEMERAL_24H",
        "payload": {
            "port_code": "SGSIN",
            "terminal_ids": ["Pasir Panjang Terminal 4/5", "Tuas Mega Port Phase 1"],
            "observation_window_utc": "2026-09-05T06:00:00Z",
            "metrics": {
                "gate_dwell_hours": 41.5,
                "rail_and_intermodal_dwell_pct": 0.92,
                "crane_moves_per_hour": 21.4,
                "inland_truck_queue_length_meters": 1380,
                "import_dwell_days": 9.2
            },
            "signals_provided": ["gate_turnaround", "rail_dwell"],
            "analyst_note": "Severe gate queues and dwell expansion. Evacuation rates lagging arrivals."
        }
    }
}

# Verified on XRPL Testnet
OFFLINE_REPLAY_SETTLEMENTS = {
    "satellite_logistics_paid": {
        "tx_hash": "F6A2FF74D92356F611764407BCF657EDE5A0E4DF1C5B2B69D3DD8F5ADF974028",
        "ledger_index": 20493969,
        "amount_drops": 1200,
        "result": "tesSUCCESS"
    },
    "terminal_telemetry_paid": {
        "tx_hash": "46221A684146CADA8569BC2583A2D8A9CD3108597C84070A4AF107C4C7436CA0",
        "ledger_index": 20493983,
        "amount_drops": 600,
        "result": "tesSUCCESS"
    },
    "canonical_target_92": {
        "tx_1": "4FFC8C44B097400153A69554636577847E6F02B44AB8E7B30DC82AFE6E856BC8",
        "tx_2": "7E73C0F85A1602096B35022AB22C1C846AAE3C054BEFFB08EB7740B669DBF609",
        "total_spent_drops": 1800,
        "composite_sha256_audit_anchor": "9cf1e4a3b841de6254bb21f37e81d4b684062f627bb309e20cb646730dc5a549"
    }
}
