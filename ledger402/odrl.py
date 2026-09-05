"""Machine-readable usage rights (ODRL) attached to paid responses.

The deliverable spec's Unit Economics table contrasts "manual legal contract review" with
"machine-readable ODRL header metadata". This is that half of the trade: when an agent
pays for data it also receives the terms under which it may use it, in a form it can
enforce without a human reading a contract.

The terms are synthetic, like the data. The point being demonstrated is the shape of the
exchange: settlement and licence arrive together, in the same HTTP response.
"""

from __future__ import annotations

from typing import Any

ODRL_CONTEXT = "http://www.w3.org/ns/odrl.jsonld"

# Header carrying a compact form of the policy, so a client can read the terms without
# parsing the body.
ODRL_HEADER = "X-ODRL-Policy"


def agreement(
    *,
    provider_id: str,
    dataset_id: str,
    price_drops: int,
    retention: str = "P30D",
    purpose: str = "internalAnalysis",
) -> dict[str, Any]:
    """Build the ODRL Agreement granted on successful payment."""
    return {
        "@context": ODRL_CONTEXT,
        "@type": "Agreement",
        "uid": f"urn:ledger402:agreement:{provider_id}",
        "assigner": f"urn:ledger402:provider:{provider_id}",
        "target": f"urn:ledger402:dataset:{dataset_id}",
        "permission": [
            {
                "target": f"urn:ledger402:dataset:{dataset_id}",
                "action": "use",
                "constraint": [
                    {
                        "leftOperand": "purpose",
                        "operator": "eq",
                        "rightOperand": purpose,
                    },
                    {
                        "leftOperand": "elapsedTime",
                        "operator": "lteq",
                        "rightOperand": retention,
                    },
                ],
            },
            {
                "target": f"urn:ledger402:dataset:{dataset_id}",
                "action": "derive",
                "constraint": [
                    {
                        "leftOperand": "purpose",
                        "operator": "eq",
                        "rightOperand": "commercialDerivative",
                    }
                ],
                "duty": [
                    {
                        "action": "attribute",
                        "constraint": [
                            {
                                "leftOperand": "attributedParty",
                                "operator": "eq",
                                "rightOperand": f"urn:ledger402:provider:{provider_id}",
                            }
                        ],
                    }
                ],
            },
        ],
        "prohibition": [
            {
                "target": f"urn:ledger402:dataset:{dataset_id}",
                "action": "distribute",
            },
            {
                "target": f"urn:ledger402:dataset:{dataset_id}",
                "action": "aggregate",
            },
        ],
        # Not part of the ODRL vocabulary; records what was paid for this grant so the
        # licence and the on-ledger settlement can be reconciled.
        "ledger402:settlement": {
            "price_drops": price_drops,
            "asset": "XRP",
            "network": "xrpl:1",
            "protocol": "x402",
        },
        "synthetic": True,
    }


def compact(policy: dict[str, Any]) -> str:
    """One-line policy summary for the response header."""
    permissions = ",".join(
        str(p.get("action")) for p in policy.get("permission") or [] if p.get("action")
    )
    prohibitions = ",".join(
        str(p.get("action")) for p in policy.get("prohibition") or [] if p.get("action")
    )
    return f"uid={policy.get('uid')}; permit={permissions}; prohibit={prohibitions}"
