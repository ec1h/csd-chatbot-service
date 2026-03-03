"""
Configuration settings for the CSD Chatbot
Centralized configuration management with validation
"""
import os
from typing import Optional
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables
load_dotenv()

# Base directory
SCRIPT_DIR = Path(__file__).parent.parent.parent
REFINED_DATA_DIR = SCRIPT_DIR / "data" / "refined data" / "files"

# Database Configuration
POSTGRES_URI: Optional[str] = os.getenv("POSTGRES_URI")
if not POSTGRES_URI:
    raise RuntimeError("Missing POSTGRES_URI environment variable")

WATER_TABLE = os.getenv("WATER_TABLE", "joburg_water")
ELECTRIC_TABLE = os.getenv("ELECTRIC_TABLE", "city_power")
MERGED_TABLE = os.getenv("MERGED_TABLE", "merged_call_types")

# Azure OpenAI Configuration
AZURE_OPENAI_API_KEY: Optional[str] = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_API_VERSION: Optional[str] = os.getenv("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_ENDPOINT: Optional[str] = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT: Optional[str] = os.getenv("AZURE_OPENAI_DEPLOYMENT")

if not all([AZURE_OPENAI_API_KEY, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT]):
    raise RuntimeError("Missing one or more required Azure OpenAI environment variables (AZURE_OPENAI_*)")

# Application Settings
SHOW_BACK_HINT = os.getenv("SHOW_BACK_HINT", "false").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Security Settings
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
MAX_MESSAGE_LENGTH = int(os.getenv("MAX_MESSAGE_LENGTH", "2000"))
ENABLE_RATE_LIMITING = os.getenv("ENABLE_RATE_LIMITING", "true").lower() == "true"

# Department to Intent Bucket Mapping
DEPARTMENT_TO_INTENT = {
    "water": "water",
    "electricity": "electricity",
    "power": "electricity",
    "roads": "roads",
    "jra": "roads",
    "waste": "waste",
    "refuse": "waste",
    "pikitup": "waste",
    "fire": "emergency",
    "ems": "emergency",
    "emergency": "emergency",
    "metro bus": "transport",
    "metrobus": "transport",
    "rea vaya": "transport",
    "reavaya": "transport",
    "environmental": "environmental",
    "health": "environmental",
    "revenue": "revenue",
    "accounts": "revenue",
    "complaints": "complaints",
}
