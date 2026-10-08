import cairosvg

FONT = "Helvetica, Arial, sans-serif"
DEEP = "#201F1D"
INK = "#46453F"
RULE = "#D3D1CB"

ARROW_DEFS = (
    '<defs><marker id="arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
    'markerHeight="7" orient="auto-start-reverse">'
    '<path d="M2 1L8 5L2 9" fill="none" stroke="%s" stroke-width="1.6" '
    'stroke-linecap="round" stroke-linejoin="round"/></marker></defs>' % INK
)

STYLES = {
    "frontend": dict(fill="#E7E6E2", stroke="#4A4D52", title="#201F1D", sub="#46453F"),
    "api": dict(fill="#E3EDEA", stroke="#3E7C74", title="#1F4A44", sub="#2F5F58"),
    "db": dict(fill="#E4EAF2", stroke="#3B5A82", title="#1F3A57", sub="#33506F"),
    "external": dict(fill="#F1DDD3", stroke="#8C2F2F", title="#5C1F1F", sub="#7A2A2A"),
}


def box(x, y, w, h, kind, title, lines=None, title_size=15):
    s = STYLES[kind]
    parts = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
        f'fill="{s["fill"]}" stroke="{s["stroke"]}" stroke-width="1.3"/>'
    ]
    cx = x + w / 2
    ty = y + 26
    parts.append(
        f'<text x="{cx}" y="{ty}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="{title_size}" font-weight="bold" fill="{s["title"]}">{title}</text>'
    )
    if lines:
        ly = ty + 22
        for line in lines:
            parts.append(
                f'<text x="{cx}" y="{ly}" text-anchor="middle" font-family="{FONT}" '
                f'font-size="12" fill="{s["sub"]}">{line}</text>'
            )
            ly += 18
    return "\n".join(parts)


def sub_lane(x, y, w, h, title, detail, color):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
        f'fill="#FFFFFF" stroke="{color}" stroke-width="0.9" stroke-dasharray="3 2"/>\n'
        f'<text x="{x+14}" y="{y+20}" font-family="{FONT}" font-size="12.5" '
        f'font-weight="bold" fill="{color}">{title}</text>\n'
        f'<text x="{x+14}" y="{y+37}" font-family="{FONT}" font-size="11" fill="{INK}">{detail}</text>'
    )


def actor(x, y, w, h, title):
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="24" '
        f'fill="#FFFFFF" stroke="{INK}" stroke-width="1.3"/>\n'
        f'<text x="{x+w/2}" y="{y+h/2+5}" text-anchor="middle" font-family="{FONT}" '
        f'font-size="14" font-weight="bold" fill="{DEEP}">{title}</text>'
    )


def arrow(x1, y1, x2, y2, label=None, dashed=False, lx=None, ly=None):
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    parts = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{INK}" '
        f'stroke-width="1.2"{dash} marker-end="url(#arrow)"/>'
    ]
    if label:
        tx = lx if lx is not None else (x1 + x2) / 2 + 10
        ty = ly if ly is not None else (y1 + y2) / 2
        parts.append(
            f'<text x="{tx}" y="{ty}" font-family="{FONT}" font-size="11.5" '
            f'font-style="italic" fill="{INK}">{label}</text>'
        )
    return "\n".join(parts)


def curve(path_d, label, lx, ly):
    return (
        f'<path d="{path_d}" fill="none" stroke="{INK}" stroke-width="1.2" '
        f'stroke-dasharray="6 4" marker-end="url(#arrow)"/>\n'
        f'<text x="{lx}" y="{ly}" font-family="{FONT}" font-size="11.5" '
        f'font-style="italic" fill="{INK}">{label}</text>'
    )


def legend(y0):
    return f'''
<line x1="160" y1="{y0}" x2="210" y2="{y0}" stroke="{INK}" stroke-width="1.2" marker-end="url(#arrow)"/>
<text x="220" y="{y0}" dominant-baseline="central" font-family="{FONT}" font-size="12.5" fill="{INK}">Appel HTTP synchrone (JSON)</text>

<line x1="160" y1="{y0+28}" x2="210" y2="{y0+28}" stroke="{INK}" stroke-width="1.2" stroke-dasharray="6 4" marker-end="url(#arrow)"/>
<text x="220" y="{y0+28}" dominant-baseline="central" font-family="{FONT}" font-size="12.5" fill="{INK}">Canal asynchrone (e-mail avec lien de décision)</text>

<rect x="160" y="{y0+42}" width="50" height="18" rx="4" fill="none" stroke="{RULE}" stroke-width="1.3" stroke-dasharray="5 3"/>
<text x="220" y="{y0+51}" dominant-baseline="central" font-family="{FONT}" font-size="12.5" fill="{INK}">Périmètre orchestré par docker-compose.yml</text>
'''


def build():
    b = []
    b.append(
        f'<rect x="130" y="105" width="500" height="520" rx="14" fill="#FAFAF8" '
        f'stroke="{RULE}" stroke-width="1.3" stroke-dasharray="7 4"/>'
    )
    b.append(
        f'<text x="150" y="128" font-family="{FONT}" font-size="12.5" font-weight="bold" '
        f'fill="{DEEP}">docker-compose.yml</text>'
    )

    # Actor
    b.append(actor(250, 45, 260, 50, "Employé / Manager / DRH (navigateur)"))
    b.append(arrow(380, 95, 380, 145, "HTTP :5173", lx=395, ly=124))

    # Frontend
    b.append(box(160, 145, 440, 90, "frontend",
                  "frontend — React 19 + TypeScript + Vite",
                  ["Port 5173 · pages/, components/ui, lib/api.ts",
                   "Page publique /decisions/:jeton (option B)"]))
    b.append(arrow(380, 235, 380, 265, "HTTP/JSON :8000 (CORS)", lx=395, ly=254))

    # API with internal lanes
    b.append(box(160, 265, 440, 220, "api", "api — FastAPI (Uvicorn), port 8000", title_size=15))
    b.append(sub_lane(180, 305, 400, 42, "Routeurs",
                       "conges · decisions · auth · types-conge · jours-feries · utilisateurs", "#3E7C74"))
    b.append(sub_lane(180, 352, 400, 42, "Services (logique métier)",
                       "routing_engine · verrou_rh · decision_tokens · webhooks · email_service", "#3E7C74"))
    b.append(sub_lane(180, 399, 400, 42, "Modèles SQLAlchemy",
                       "11 tables : utilisateurs, demandes, etapes_workflow, soldes_conges...", "#3E7C74"))
    b.append(arrow(380, 485, 380, 515, "asyncpg :5432", lx=395, ly=504))

    # DB
    b.append(box(210, 515, 340, 80, "db", "db — PostgreSQL 16",
                  ["Port 5432 · schéma versionné (Alembic)"]))

    # Resend (external)
    b.append(box(660, 340, 150, 80, "external", "Resend",
                  ["API transactionnelle", "(notification e-mail)"], title_size=14))
    b.append(arrow(600, 375, 660, 375, "HTTPS", lx=605, ly=368))
    b.append(curve("M735,340 C 735,180 560,55 512,68", "e-mail reçu, lien /decisions/:jeton", 545, 160))

    b.append(legend(670))

    total_h = 760
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="850" height="{total_h}" '
        f'viewBox="0 0 850 {total_h}">{ARROW_DEFS}' + "\n".join(b) + "</svg>"
    )


if __name__ == "__main__":
    svg = build()
    with open("/home/claude/work/plateforme-workflows/docs/architecture.svg", "w", encoding="utf-8") as f:
        f.write(svg)
    cairosvg.svg2png(
        url="/home/claude/work/plateforme-workflows/docs/architecture.svg",
        write_to="/home/claude/work/plateforme-workflows/docs/architecture.png",
        scale=2,
        background_color="white",
    )
    print("saved")
