import { DefinirMotDePasseForm } from "@/components/definir-mot-de-passe-form";

export default async function ActiverComptePage({
  params,
}: {
  params: Promise<{ jeton: string }>;
}) {
  const { jeton } = await params;
  return <DefinirMotDePasseForm mode="invitation" jeton={jeton} />;
}
