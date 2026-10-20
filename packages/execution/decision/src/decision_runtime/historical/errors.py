"""Historical codec refusal only; no retired runtime errors or execution."""
class ContractError(ValueError):
    code = 'contract_invalid'
