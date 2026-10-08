import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { SignaturePad } from "./signature-pad";

/**
 * jsdom ne dessine pas : on remplace le contexte 2D par un enregistreur et on pilote la geometrie du canvas.
 * Ce qui compte ici, c'est la CONVERSION pointeur -> coordonnees internes (360 x 140), la regle qui s'est
 * revelee fausse sur telephone : un canvas affiche a 180 px de large doit ramener un clic a x=90 sur 180 en x=180 interne.
 */
const appels: Array<[string, number, number]> = [];
const ctx = {
  beginPath: () => {},
  moveTo: (x: number, y: number) => appels.push(["moveTo", x, y]),
  lineTo: (x: number, y: number) => appels.push(["lineTo", x, y]),
  stroke: () => {},
  clearRect: () => {},
  lineWidth: 0,
  lineCap: "",
  strokeStyle: "",
};

function pointeur(canvas: HTMLElement, type: string, clientX: number, clientY: number) {
  act(() => {
    canvas.dispatchEvent(new MouseEvent(type, { bubbles: true, clientX, clientY }));
  });
}

function afficherA(canvas: HTMLElement, largeur: number, hauteur: number, gauche = 10, haut = 20) {
  canvas.getBoundingClientRect = () =>
    ({ left: gauche, top: haut, width: largeur, height: hauteur, right: gauche + largeur, bottom: haut + hauteur, x: gauche, y: haut, toJSON: () => ({}) }) as DOMRect;
}

describe("SignaturePad", () => {
  beforeEach(() => {
    appels.length = 0;
    Object.defineProperty(window, "devicePixelRatio", { value: 1, configurable: true });
    HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx) as unknown as typeof HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/png;base64,QUJD");
  });

  it("taille normale : les coordonnees du pointeur sont celles du canvas", () => {
    render(<SignaturePad onChange={() => {}} />);
    const canvas = screen.getByLabelText("Zone de signature");
    afficherA(canvas, 360, 140);
    pointeur(canvas, "pointerdown", 10 + 100, 20 + 50);
    pointeur(canvas, "pointermove", 10 + 200, 20 + 100);
    expect(appels).toEqual([["moveTo", 100, 50], ["lineTo", 200, 100]]);
  });

  it("ecran etroit (canvas affiche a la moitie) : les coordonnees sont ramenees a l'echelle interne", () => {
    render(<SignaturePad onChange={() => {}} />);
    const canvas = screen.getByLabelText("Zone de signature");
    afficherA(canvas, 180, 70);                       // moitie de 360 x 140
    pointeur(canvas, "pointerdown", 10 + 90, 20 + 35);   // milieu de la zone affichee
    pointeur(canvas, "pointermove", 10 + 180, 20 + 70);  // coin bas droit affiche
    expect(appels).toEqual([["moveTo", 180, 70], ["lineTo", 360, 140]]);   // milieu et coin bas droit INTERNES
  });

  it("transmet le PNG sans prefixe a la fin du trace, et Effacer remet a zero", () => {
    const onChange = vi.fn();
    render(<SignaturePad onChange={onChange} />);
    const canvas = screen.getByLabelText("Zone de signature");
    afficherA(canvas, 360, 140);
    expect((screen.getByRole("button", { name: "Effacer" }) as HTMLButtonElement).disabled).toBe(true);
    pointeur(canvas, "pointerdown", 20, 40);
    pointeur(canvas, "pointermove", 80, 90);
    pointeur(canvas, "pointerup", 80, 90);
    expect(onChange).toHaveBeenLastCalledWith("QUJD");
    expect(screen.queryByText("Signature enregistrée.")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Effacer" }));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.queryByText("Tracez votre signature ci-dessus.")).not.toBeNull();
  });

  it.each([[1, 360, 140], [2, 720, 280], [3, 1080, 420], [5, 1080, 420]])(
    "ecran de densite %s : resolution interne %s x %s (bornee a 3x), meme zone affichee",
    (densite, largeur, hauteur) => {
      Object.defineProperty(window, "devicePixelRatio", { value: densite, configurable: true });
      render(<SignaturePad onChange={() => {}} />);
      const canvas = screen.getByLabelText("Zone de signature") as HTMLCanvasElement;
      expect([canvas.width, canvas.height]).toEqual([largeur, hauteur]);
    },
  );

  it("ecran 2x : le pointeur est converti en pixels internes et le trait garde son epaisseur apparente", () => {
    Object.defineProperty(window, "devicePixelRatio", { value: 2, configurable: true });
    render(<SignaturePad onChange={() => {}} />);
    const canvas = screen.getByLabelText("Zone de signature");
    afficherA(canvas, 360, 140);                         // affichage inchange : 360 x 140 px CSS
    pointeur(canvas, "pointerdown", 10 + 100, 20 + 50);
    pointeur(canvas, "pointermove", 10 + 180, 20 + 70);
    expect(appels).toEqual([["moveTo", 200, 100], ["lineTo", 360, 140]]);
    expect(ctx.lineWidth).toBe(4);                       // 2 px CSS x 2
  });

  it("densite invalide (0, NaN) : retombe sur 1x", () => {
    Object.defineProperty(window, "devicePixelRatio", { value: 0, configurable: true });
    render(<SignaturePad onChange={() => {}} />);
    const canvas = screen.getByLabelText("Zone de signature") as HTMLCanvasElement;
    expect([canvas.width, canvas.height]).toEqual([360, 140]);
  });

  it("sans appui, un deplacement ne dessine rien", () => {
    render(<SignaturePad onChange={() => {}} />);
    const canvas = screen.getByLabelText("Zone de signature");
    afficherA(canvas, 360, 140);
    pointeur(canvas, "pointermove", 50, 50);
    expect(appels).toEqual([]);
  });
});
