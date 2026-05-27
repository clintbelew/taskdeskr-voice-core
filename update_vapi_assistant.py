"""
update_vapi_assistant.py
========================
SINGLE SOURCE OF TRUTH SYNC SCRIPT

This is the ONLY script that should be used to update the Vapi assistant config.

Usage:
    python3 update_vapi_assistant.py

What it does:
    1. Reads el_jefe_config_baseline.json for all settings
    2. Reads el_jefe_system_prompt.txt for the system prompt
    3. Reads src/tools/definitions.py for tool definitions
    4. PATCHes the Vapi assistant with the combined config
    5. Confirms the phone number is pointing to the correct assistantId

Rules:
    - NEVER change model/voice/transcriber/firstMessage in the Vapi dashboard directly.
    - NEVER change the assistant-request inline response payload in webhooks.py.
    - ALWAYS update el_jefe_config_baseline.json or el_jefe_system_prompt.txt first.
    - THEN run this script to push the changes to Vapi.
"""

import os
import sys
import json
import requests

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BASELINE_FILE = os.path.join(BASE_DIR, "el_jefe_config_baseline.json")
PROMPT_FILE   = os.path.join(BASE_DIR, "el_jefe_system_prompt.txt")

sys.path.insert(0, BASE_DIR)
from src.tools.definitions import TOOL_DEFINITIONS

# ─── Credentials ──────────────────────────────────────────────────────────────
VAPI_KEY  = os.environ.get("VAPI_API_KEY", "491e868b-7a79-4356-91c4-7630678ff6f9")
ASST_ID   = "32535107-c49c-4aa7-b9e1-c7ec3184d313"
PHONE_ID  = "32ff4b53-6ffc-4f4f-8b85-cb14201d7eb5"
HEADERS   = {"Authorization": f"Bearer {VAPI_KEY}", "Content-Type": "application/json"}

# ─── Load config ──────────────────────────────────────────────────────────────
with open(BASELINE_FILE) as f:
    cfg = json.load(f)

with open(PROMPT_FILE) as f:
    system_prompt = f.read()

print(f"Baseline loaded: {BASELINE_FILE}")
print(f"System prompt: {len(system_prompt):,} chars")
print(f"Tools: {len(TOOL_DEFINITIONS)}")

# ─── Build payload ────────────────────────────────────────────────────────────
asst_cfg = cfg["assistant"]
model_cfg = cfg["model"]
voice_cfg = cfg["voice"]
trans_cfg = cfg["transcriber"]
server_cfg = cfg["server"]

payload = {
    "name": asst_cfg["name"],
    "firstMessage": asst_cfg["firstMessage"],
    "silenceTimeoutSeconds": asst_cfg["silenceTimeoutSeconds"],
    "responseDelaySeconds": asst_cfg["responseDelaySeconds"],
    "numWordsToInterruptAssistant": asst_cfg["numWordsToInterruptAssistant"],
    "model": {
        "provider": model_cfg["provider"],
        "model": model_cfg["model"],
        "systemPrompt": system_prompt,
        "temperature": model_cfg["temperature"],
        "tools": TOOL_DEFINITIONS,
    },
    "voice": {
        "provider": voice_cfg["provider"],
        "voiceId": voice_cfg["voiceId"],
        "model": voice_cfg["model"],
        "stability": voice_cfg["stability"],
        "similarityBoost": voice_cfg["similarityBoost"],
        "optimizeStreamingLatency": voice_cfg["optimizeStreamingLatency"],
    },
    "transcriber": {
        "provider": trans_cfg["provider"],
        "model": trans_cfg["model"],
        "language": trans_cfg["language"],
        "endpointing": trans_cfg["endpointing"],
    },
    "server": {
        "url": server_cfg["url"],
        "timeoutSeconds": server_cfg["timeoutSeconds"],
    },
}

# ─── Push to Vapi ─────────────────────────────────────────────────────────────
print(f"\nUpdating Vapi assistant {ASST_ID}...")
r = requests.patch(
    f"https://api.vapi.ai/assistant/{ASST_ID}",
    headers=HEADERS,
    json=payload,
    timeout=30,
)
if r.status_code != 200:
    print(f"ERROR {r.status_code}: {r.text[:500]}")
    sys.exit(1)

d = r.json()
print(f"  ✓ name:     {d.get('name')}")
print(f"  ✓ model:    {d.get('model',{}).get('model')}")
print(f"  ✓ voiceId:  {d.get('voice',{}).get('voiceId')}")
print(f"  ✓ language: {d.get('transcriber',{}).get('language')}")
print(f"  ✓ tools:    {len(d.get('model',{}).get('tools',[]))}")

# ─── Confirm phone number points to this assistant ────────────────────────────
print(f"\nVerifying phone number {PHONE_ID}...")
rp = requests.get(f"https://api.vapi.ai/phone-number/{PHONE_ID}", headers=HEADERS, timeout=15)
phone = rp.json()
current_asst = phone.get("assistantId")

if current_asst != ASST_ID:
    print(f"  Phone assistantId mismatch ({current_asst}). Fixing...")
    rp2 = requests.patch(
        f"https://api.vapi.ai/phone-number/{PHONE_ID}",
        headers=HEADERS,
        json={"assistantId": ASST_ID, "server": {"url": server_cfg["url"], "timeoutSeconds": server_cfg["timeoutSeconds"]}},
        timeout=15,
    )
    if rp2.status_code == 200:
        print(f"  ✓ Phone now points to {ASST_ID}")
    else:
        print(f"  ERROR fixing phone: {rp2.text[:200]}")
else:
    print(f"  ✓ Phone correctly points to {ASST_ID}")

print("\n✅ Vapi assistant is in sync with el_jefe_config_baseline.json")
print("   Test a call to verify.")
