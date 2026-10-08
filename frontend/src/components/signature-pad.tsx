"use client";

import * as React from "react";
import { Button } from "@/components/ui/button";

/**
 * Capture d'une signature a l'ecran (section 8 du CDC technique : role
 * Signataire, "capturer une signature a l'ecran, ou refuser"). Trace au
 * doigt ou a la souris (Pointer Events, tactile et souris avec le meme
 * code), exporte en PNG base64 - la valeur attendue par le backend
 * (DecisionRequest.signature_image_base64).
 *
 * `onChange` recoit la chaine base64 SANS le prefixe "data:image/png;base64,"
 * (le backend decode du base64 brut), ou null tant que rien n'est trace.
 */
/** Taille d'affichage (px CSS) de la zone de signature. */
const LARGEUR = 360;
const HAUTEUR = 140;
const RATIO_MAX = 3;

/** Densite de pixels de l'ecran (2 sur un iPhone ou un ecran Retina), bornee pour garder un PNG leger. */
function ratioEcran(): number {
  const ratio = typeof window !== "undefined" ? window.devicePixelRatio : 1;
  return Math.min(RATIO_MAX, Math.max(1, Number.isFinite(ratio) && ratio ? ratio : 1));
}

export function SignaturePad({ onChange }: { onChange: (base64: string | null) => void }) {
  const canvasRef = React.useRef<HTMLCanvasElement>(null);
  const enTrace = React.useRef(false);
  const ratio = React.useRef(1);
  const [vide, setVide] = React.useState(true);

  // Resolution INTERNE proportionnelle a la densite de l'ecran : sur un ecran 2x, le canvas compte 720 x 280 pixels
  // pour la meme zone de 360 x 140 px CSS. Sans cela le navigateur agrandit une image de 360 px (trait flou, bords en
  // escalier) et le PNG envoye au bon de commande est plus grossier.
  React.useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    ratio.current = ratioEcran();
    canvas.width = Math.round(LARGEUR * ratio.current);
    canvas.height = Math.round(HAUTEUR * ratio.current);
  }, []);

  function contexte() {
    const ctx = canvasRef.current?.getContext("2d");
    if (ctx) {
      ctx.lineWidth = 2 * ratio.current;        // meme epaisseur APPARENTE (2 px CSS) quelle que soit la densite
      ctx.lineCap = "round";
      ctx.strokeStyle = "#101425";
    }
    return ctx ?? null;
  }

  /**
   * Position du pointeur en coordonnees INTERNES du canvas. Sur un ecran etroit le canvas est affiche plus petit
   * que ses 360 x 140 px (CSS `w-full`) : sans cette mise a l'echelle, le trait se dessinait decale et ecrase
   * vers le coin haut-gauche, et la moitie droite de la signature etait perdue (constate au test navigateur a 390 px).
   */
  function position(e: React.PointerEvent<HTMLCanvasElement>) {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const echelleX = rect.width > 0 ? canvas.width / rect.width : 1;
    const echelleY = rect.height > 0 ? canvas.height / rect.height : 1;
    return { x: (e.clientX - rect.left) * echelleX, y: (e.clientY - rect.top) * echelleY };
  }

  function debut(e: React.PointerEvent<HTMLCanvasElement>) {
    const ctx = contexte();
    if (!ctx) return;
    enTrace.current = true;
    const { x, y } = position(e);
    ctx.beginPath();
    ctx.moveTo(x, y);
    e.currentTarget.setPointerCapture?.(e.pointerId);
  }

  function trace(e: React.PointerEvent<HTMLCanvasElement>) {
    if (!enTrace.current) return;
    const ctx = contexte();
    if (!ctx) return;
    const { x, y } = position(e);
    ctx.lineTo(x, y);
    ctx.stroke();
  }

  function fin() {
    if (!enTrace.current) return;
    enTrace.current = false;
    const canvas = canvasRef.current;
    if (!canvas) return;
    setVide(false);
    onChange(canvas.toDataURL("image/png").replace(/^data:image\/png;base64,/, ""));
  }

  function effacer() {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (canvas && ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
    setVide(true);
    onChange(null);
  }

  return (
    <div className="flex flex-col gap-2">
      <canvas
        ref={canvasRef}
        width={LARGEUR}
        height={HAUTEUR}
        aria-label="Zone de signature"
        onPointerDown={debut}
        onPointerMove={trace}
        onPointerUp={fin}
        onPointerLeave={fin}
        className="w-full max-w-[360px] touch-none rounded-lg border border-line-strong bg-white"
      />
      <div className="flex items-center justify-between text-[12px] text-ink-dim">
        <span>{vide ? "Tracez votre signature ci-dessus." : "Signature enregistrée."}</span>
        <Button type="button" variant="ghost" onClick={effacer} disabled={vide}>
          Effacer
        </Button>
      </div>
    </div>
  );
}
