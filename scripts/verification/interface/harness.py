import os
from playwright.sync_api import sync_playwright
PWD="MotDePasseVerif123!"; SUF=os.environ["UI_SUFFIXE"]
EMP=f"verif-employe-{SUF}@example.com"; DRH=f"verif-drh-{SUF}@example.com"; MGR=f"verif-manager-{SUF}@example.com"
BASE=os.environ.get("UI_BASE","http://localhost:3000")

def login(page, email):
    page.goto(f"{BASE}/login"); page.wait_for_selector("input[type=email], input[name=email], #email")
    page.fill("input[type=email], input[name=email], #email", email)
    page.fill("input[type=password]", PWD)
    page.click("button[type=submit]")
    page.wait_for_url("**/mes-demandes", timeout=30000)
