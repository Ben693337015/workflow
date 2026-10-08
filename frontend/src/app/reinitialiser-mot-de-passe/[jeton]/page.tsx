import { DefinirMotDePasseForm } from "@/components/definir-mot-de-passe-form";

export default async function ReinitialiserMotDePassePage({
  params,
}: {
  params: Promise<{ jeton: string }>;
}) {
  const { jeton } = await params;
  return <DefinirMotDePasseForm mode="reinitialisation" jeton={jeton} />;
}
