# EIN Service Specification — COMET-RIOBAMBA

> SPEC PROPUESTA - NO IMPLEMENTADA.
> Este documento describe un servicio que aun no existe en codigo.
> El checklist de la seccion 11 esta todo en [ ]. Se planea construir
> en Fase 1 del plan de autosustentabilidad. NO confundir con
> documentacion de algo funcional.

> **Purpose:** Technical specification for the Energy Intelligence Node (EIN) as a paid verification service. This document describes endpoints, schemas, pricing, payment integration, and discovery. It is intended to be read alongside the code.

## 1. Overview

The EIN is a claim verification service for energy-related assertions. It accepts a natural-language claim, verifies it against the claims_tracker.json database (~29,400 entries, live and growing) and energy_intel.db (776 KB), and returns a structured verdict with confidence score, sources, and timestamps.

Key differentiator: Contextual verification, not raw data. The service answers "Is this claim real, fabricated, or outdated?" rather than "What is the current price of oil?"

## 2. Architecture

    Client (agent or human)
        |
    HTTP POST /verify-claim
        |
    [EIN Service]
        |- Load claim
        |- Query claims_tracker.json for matching claims
        |- Query energy_intel.db for corroborating evidence
        |- Compute confidence score (0.0 to 1.0)
        |- Generate verdict (verified / refuted / unverifiable / outdated)
        |- Return structured response
        |
    x402 payment layer (if via MoltsPay)
        |
    Client receives response + payment receipt

## 3. Endpoints

### 3.1 POST /verify-claim

Request body:

    {
      "claim": "Solid-state batteries have achieved 500 Wh/kg energy density in production.",
      "context": "optional - source document or conversation",
      "max_age_days": 365,
      "min_confidence": 0.5
    }

Response body:

    {
      "claim": "Solid-state batteries have achieved 500 Wh/kg energy density in production.",
      "verdict": "refuted",
      "confidence": 0.87,
      "sources": [
        {
          "source_type": "paper",
          "title": "Solid-State Battery Roadmap 2026",
          "date": "2026-03-15",
          "url": "https://doi.org/...",
          "stance": "contradicts"
        }
      ],
      "explanation": "Current production energy density for solid-state batteries is 350-400 Wh/kg. The 500 Wh/kg figure appears in laboratory settings, not production.",
      "processing_time_ms": 1240,
      "timestamp": "2026-09-18T21:00:00Z"
    }

Verdicts:

| Verdict | Meaning |
|---|---|
| verified | Claim is supported by >=2 independent Tier-1 sources |
| refuted | Claim is contradicted by >=1 Tier-1 source |
| unverifiable | No sufficient evidence found |
| outdated | Claim was true but is no longer current |

### 3.2 GET /health

Returns service status.

    {
      "status": "ok",
      "claims_loaded": 29389,
      "energy_intel_loaded": true,
      "uptime_seconds": 86400
    }

## 4. Pricing

| Tier | Price | Description |
|---|---|---|
| Standard | $0.01 per verification | Full verification with sources |
| Quick | $0.003 per verification | Verdict only (no sources) |
| Bulk | $0.005 per verification | >=100 verifications per batch |

Payment: USDC on Base, via x402 protocol. No API keys, no signup.

Comparison with competitors:
- Apify Claim Verifier: $8.00/1,000 = $0.008 per verification
- AgentOracle: $0.02 USDC per query
- Event Resolver: $0.003 per quick verification

## 5. Payment Integration (MoltsPay / x402)

### 5.1 Setup

    npm install moltspay@latest
    npx moltspay fund

### 5.2 x402 flow

    Client -> GET /verify-claim
    Server -> 402 Payment Required + payment details
    Client -> USDC payment signature (EIP-3009)
    Server -> Verify payment, forward to upstream API
    Server -> Return response + receipt

### 5.3 SDK integration (3 lines)

    from x402 import paywall

    @app.post("/verify-claim")
    @paywall(price_usdc=0.01)
    async def verify_claim(request):
        # ... verification logic
        return verdict

## 6. Discovery

### 6.1 Moltbook skills directory

Publish endpoint at: moltbook.com/skills/energy-verify

### 6.2 MCP server

Expose as MCP tool:

    {
      "name": "energy_verify_claim",
      "description": "Verify an energy-related claim against EIN database",
      "input_schema": {
        "type": "object",
        "properties": {
          "claim": {"type": "string"},
          "max_age_days": {"type": "integer", "default": 365}
        }
      }
    }

### 6.3 x402 marketplace

List on Polygon Agentic Services directory and Apify Store.

## 7. Rate Limits

| Limit | Value |
|---|---|
| Requests per minute | 100 |
| Requests per day (standard) | 10,000 |
| Max claim length | 1,000 characters |
| Max context length | 5,000 characters |

## 8. Error Handling

| HTTP Code | Meaning |
|---|---|
| 400 | Invalid claim format |
| 402 | Payment required (x402) |
| 429 | Rate limit exceeded |
| 500 | Internal error |

## 9. Configuration

All configuration in config/ein_service.json:

    {
      "port": 8080,
      "claims_tracker_path": "data/claims_tracker.json",
      "energy_intel_path": "data/energy_intel.db",
      "min_confidence_threshold": 0.5,
      "max_sources_returned": 5,
      "tier_1_sources": ["arxiv.org", "doi.org", "nrel.gov", "iea.org"],
      "tier_2_sources": ["reuters.com", "bloomberg.com"],
      "tier_3_sources": ["company_blog", "press_release"]
    }

## 10. Multi-domain generalization

The EIN is designed to be domain-configurable. The following components change per domain:

| Component | Energy (current) | Agents (future) |
|---|---|---|
| Claim types | energy_density, cost_per_kwh, efficiency | failure_mode, latency, rollback |
| Source trust tiers | Government = Tier 3, analyst = Tier 1 | Official docs = Tier 1, blog = Tier 3 |
| Scoring weights | Density, cost, efficiency | Reliability, observability, safety |
| Keyword mappings | battery, solar, hydrogen | agent, tool, memory |

The following components remain constant:
- Confidence formula
- KG extraction and validation
- Research pipeline
- Merging / dedup / similarity
- Storage backend

## 11. Implementation checklist

- [ ] Implement POST /verify-claim endpoint
- [ ] Integrate claims_tracker.json lookup
- [ ] Integrate energy_intel.db lookup
- [ ] Implement confidence scoring
- [ ] Implement verdict logic
- [ ] Add x402 payment layer (MoltsPay)
- [ ] Publish to Moltbook skills directory
- [ ] Publish as MCP server
- [ ] Add rate limiting
- [ ] Add tests (unit + integration)
- [ ] Document API with OpenAPI spec
- [ ] Deploy and monitor

---

*Document created: 2026-09-18.*
