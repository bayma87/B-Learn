import hashlib
import json
import uuid
from datetime import datetime
from typing import Dict, Optional

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

# ==========================================
# 1. MODELOS DE DADOS (SCHEMAS)
# ==========================================

class Scope1Input(BaseModel):
    diesel_liters: float = Field(0.0, description="Consumo de combustível fóssil (litros)")
    gasoline_liters: float = Field(0.0, description="Consumo de gasolina (litros)")
    natural_gas_m3: float = Field(0.0, description="Gás natural envasado ou encanado (m³)")

class Scope2Input(BaseModel):
    electricity_kwh: float = Field(0.0, description="Energia elétrica adquirida da rede (kWh)")

class Scope3Input(BaseModel):
    business_flights_km: float = Field(0.0, description="Viagens aéreas a trabalho (km)")
    logistics_freight_tkm: float = Field(0.0, description="Frete terceirizado (tonelada.km)")

class ESGReportRequest(BaseModel):
    company_id: str = Field(..., example="PME-98765")
    period_start: datetime
    period_end: datetime
    scope_1: Scope1Input
    scope_2: Scope2Input
    scope_3: Scope3Input
    meta_data: Optional[Dict[str, str]] = Field(default={}, description="Ids de sensores IoT ou arquivos anexos")

class ScopeBreakdown(BaseModel):
    scope_1_tco2e: float
    scope_2_tco2e: float
    scope_3_tco2e: float
    total_tco2e: float

class AuditDossierResponse(BaseModel):
    dossier_id: str
    company_id: str
    generated_at: datetime
    standard: str = "GHG Protocol Corporate Accounting Standard"
    emissions: ScopeBreakdown
    audit_hash: str = Field(..., description="Assinatura digital/Hash SHA-256 para verificação em auditoria")
    status: str = "VALIDATED"


# ==========================================
# 2. MOTOR DE CÁLCULO DE EMISSÕES
# ==========================================

class CarbonEngine:
    """
    Fatores de emissão padronizados (kgCO2e por unidade).
    Em produção, esses fatores devem ser sincronizados com bases oficiais (ex: MCTI no Brasil).
    """
    FACTORS = {
        "diesel": 2.671,
        "gasoline": 2.272,
        "natural_gas": 1.980,
        "electricity": 0.085,
        "flight_km": 0.150,
        "freight_tkm": 0.105
    }

    @classmethod
    def calculate_scope_1(cls, s1_data: Scope1Input) -> float:
        emissions_kg = (
            (s1_data.diesel_liters * cls.FACTORS["diesel"]) +
            (s1_data.gasoline_liters * cls.FACTORS["gasoline"]) +
            (s1_data.natural_gas_m3 * cls.FACTORS["natural_gas"])
        )
        return round(emissions_kg / 1000, 4)

    @classmethod
    def calculate_scope_2(cls, s2_data: Scope2Input) -> float:
        emissions_kg = s2_data.electricity_kwh * cls.FACTORS["electricity"]
        return round(emissions_kg / 1000, 4)

    @classmethod
    def calculate_scope_3(cls, s3_data: Scope3Input) -> float:
        emissions_kg = (
            (s3_data.business_flights_km * cls.FACTORS["flight_km"]) +
            (s3_data.logistics_freight_tkm * cls.FACTORS["freight_tkm"])
        )
        return round(emissions_kg / 1000, 4)


# ==========================================
# 3. RASTREABILIDADE E AUDITORIA (INTEGRIDADE)
# ==========================================

class AuditTrail:
    @staticmethod
    def generate_sha256_signature(payload: dict) -> str:
        """Gera hash SHA-256 imutável para validação de auditoria legal/bancária."""
        encoded_data = json.dumps(payload, sort_keys=True, default=str).encode('utf-8')
        return hashlib.sha256(encoded_data).hexdigest()


# ==========================================
# 4. API FASTAPI (ENDPOINTS)
# ==========================================

app = FastAPI(
    title="História 4 - API de Dossiês de Auditoria e Certificação ESG",
    version="1.0.0",
    description="Emissão automática de dossiês formais de pegada de carbono (Escopos 1, 2 e 3) com assinatura de integridade."
)

# Simulador de armazenamento em memória
report_db: Dict[str, AuditDossierResponse] = {}


@app.post(
    "/api/v1/esg/reports/generate", 
    response_model=AuditDossierResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Gera dossiê auditável de emissões de carbono para bancos e auditores"
)
async def generate_esg_dossier(payload: ESGReportRequest):
    # 1. Cálculo de emissões por escopo
    s1_tco2e = CarbonEngine.calculate_scope_1(payload.scope_1)
    s2_tco2e = CarbonEngine.calculate_scope_2(payload.scope_2)
    s3_tco2e = CarbonEngine.calculate_scope_3(payload.scope_3)
    total_tco2e = round(s1_tco2e + s2_tco2e + s3_tco2e, 4)

    dossier_id = f"DOSSIER-{uuid.uuid4().hex[:8].upper()}"
    generated_at = datetime.utcnow()

    # 2. Assinatura e Rastreabilidade
    raw_audit_payload = {
        "dossier_id": dossier_id,
        "company_id": payload.company_id,
        "period": f"{payload.period_start} to {payload.period_end}",
        "metrics": {
            "scope_1": s1_tco2e,
            "scope_2": s2_tco2e,
            "scope_3": s3_tco2e,
            "total": total_tco2e
        },
        "raw_inputs": payload.dict()
    }
    
    audit_hash = AuditTrail.generate_sha256_signature(raw_audit_payload)

    # 3. Montagem do Dossiê Final
    dossier = AuditDossierResponse(
        dossier_id=dossier_id,
        company_id=payload.company_id,
        generated_at=generated_at,
        emissions=ScopeBreakdown(
            scope_1_tco2e=s1_tco2e,
            scope_2_tco2e=s2_tco2e,
            scope_3_tco2e=s3_tco2e,
            total_tco2e=total_tco2e
        ),
        audit_hash=audit_hash
    )

    # Persistência
    report_db[dossier_id] = dossier

    return dossier


@app.get(
    "/api/v1/esg/reports/verify/{dossier_id}",
    response_model=AuditDossierResponse,
    summary="Valida a autenticidade de um dossiê emitido"
)
async def verify_dossier(dossier_id: str):
    """Endpoint público para bancos e grandes clientes confirmarem a autenticidade do relatório."""
    if dossier_id not in report_db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Dossiê de auditoria não encontrado ou inválido."
        )
    return report_db[dossier_id]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)